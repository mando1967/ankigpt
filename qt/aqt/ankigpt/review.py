# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Reviewer integration: replaces a concept card's rendered question/answer
with an LLM-generated question, and grades typed / multiple-choice answers.

The Reviewer calls exactly three methods (intercept_question,
intercept_answer, suggested_ease); everything else is done via gui_hooks so
the diff against upstream reviewer.py stays tiny.

Threading rule: all collection/note access happens on the main thread when a
request is built; background ops only talk to the LLM client.
"""

from __future__ import annotations

import html
import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, Literal, cast

from anki import scheduler_pb2
from anki.cards import Card, CardId
from anki.notes import NoteId
from anki.scheduler.v3 import Scheduler as V3Scheduler
from anki.template import TemplateRenderOutput
from aqt import gui_hooks
from aqt.ankigpt import concepts, prompts
from aqt.ankigpt.llm import FakeLLMClient, LLMClient, make_client
from aqt.ankigpt.prompts import (
    GeneratedQuestion,
    GradeRequest,
    GradeResult,
    MasteryInfo,
    Mode,
    QuestionRequest,
)
from aqt.ankigpt.settings import MODE_MIX, DeckSettings, deck_settings, llm_config
from aqt.ankigpt.store import Store
from aqt.operations import QueryOp
from aqt.qt import QTimer
from aqt.theme import theme_manager
from aqt.utils import showWarning, tr

if TYPE_CHECKING:
    from aqt.reviewer import Reviewer

Ease = Literal[1, 2, 3, 4]
AsyncRunner = Callable[
    [Callable[[], Any], Callable[[Any], None], Callable[[Exception], None]], None
]

PREFETCH_AHEAD = 2
GENERATE_ATTEMPTS = 2
JS_CHOOSE_PREFIX = "ankigpt:choose:"


@dataclass
class ActiveQuestion:
    card_id: CardId
    note_id: NoteId
    note_mod: int
    title: str
    mode: Mode
    question: GeneratedQuestion
    mastery: MasteryInfo
    settings: DeckSettings
    render_output: TemplateRenderOutput
    history_id: int | None = None
    user_answer: str | None = None
    choice: int | None = None
    grade: GradeResult | None = None
    graded: bool = False
    grading: bool = False


class ConceptReviewController:
    def __init__(
        self,
        reviewer: Reviewer,
        *,
        store_provider: Callable[[], Store] | None = None,
        run_async: AsyncRunner | None = None,
    ) -> None:
        self.reviewer = reviewer
        self.mw = reviewer.mw
        self.store_provider = store_provider or _default_store
        self.run_async = run_async or self._run_query_op
        self._current: ActiveQuestion | None = None
        self._inflight: dict[CardId, int] = {}
        self._prefetching: set[CardId] = set()
        self._serial = 0
        self._auto_timer: QTimer | None = None
        self._register_hooks()

    # ------------------------------------------------------------------
    # Public API used by Reviewer
    # ------------------------------------------------------------------

    def intercept_question(self) -> bool:
        """Called first thing in Reviewer._showQuestion.

        Returns True when the reviewer must stop: either a question is being
        generated asynchronously (and _showQuestion will be re-invoked), or an
        error was shown and the reviewer is leaving.
        """
        r = self.reviewer
        card = r.card
        if card is None or not self._is_concept(card):
            return False
        cur = self._current
        if cur is not None and cur.card_id == card.id:
            # second pass, or a redraw after card.load() dropped our output
            card.set_render_output(cur.render_output)
            return False
        self._cancel_auto_submit()
        if card.id in self._inflight:
            self._take_over(card)
            return True

        config = llm_config(self.mw.pm)
        if not config.configured:
            self._fail(tr.ankigpt_no_api_key())
            return True

        note = card.note()
        state = self._current_state()
        store = self.store_provider()
        if cached := store.get_cached(card.id, note.mod):
            store.drop_cached(card.id)
            self._activate(card, cached.question, cached.question.mode, state)
            card.start_timer()
            return False

        mode, _settings = self._pick_mode(card)
        req = self._build_request(card, mode, state)
        client = make_client(config)
        self._serial += 1
        token = self._serial
        self._inflight[card.id] = token
        self._take_over(card)

        def success(question: GeneratedQuestion) -> None:
            self._inflight.pop(card.id, None)
            if not self._still_current(card, token):
                # user moved on; keep the work for next time
                store.put_cached(
                    card.id, note.id, note.mod, req.mastery.level, question
                )
                return
            if card.note().mod != note.mod:
                # note edited while generating: start over with fresh fields
                r._showQuestion()
                return
            self._activate(card, question, mode, state)
            card.start_timer()
            r._showQuestion()

        def failure(exc: Exception) -> None:
            self._inflight.pop(card.id, None)
            if not self._still_current(card, token):
                return
            self._fail(tr.ankigpt_generation_failed(error=str(exc)))

        self.run_async(lambda: self._generate(client, req), success, failure)
        return True

    def intercept_answer(self) -> bool:
        """Called at the top of Reviewer._showAnswer.

        Returns True while a typed answer is being graded asynchronously;
        _showAnswer is re-invoked when grading completes.
        """
        r = self.reviewer
        card = r.card
        cur = self._current
        if cur is None or card is None or cur.card_id != card.id:
            return False
        card.set_render_output(cur.render_output)
        if cur.graded or cur.mode == "self":
            return False
        if cur.grading:
            return True

        if cur.mode == "mcq":
            self._grade_choice(cur)
            return False

        answer = (r.typedAnswer or "").strip()
        if not answer:
            cur.grade = GradeResult(0, 1, tr.ankigpt_no_answer_given(), [])
            self._finish_grading(cur)
            return False

        cur.user_answer = answer
        cur.grading = True
        elapsed_ms = card.time_taken(capped=False)
        self._show_grading_banner()
        config = llm_config(self.mw.pm)
        client = make_client(config)
        req = GradeRequest(
            title=cur.title,
            question=cur.question.question,
            model_answer=cur.question.model_answer,
            key_points=cur.question.key_points,
            user_answer=answer,
            mastery=cur.mastery,
        )
        token = cur

        def restore_timer() -> None:
            card.timer_started = time.time() - elapsed_ms / 1000

        def success(grade: GradeResult) -> None:
            if self._current is not token:
                return
            cur.grade = grade
            self._finish_grading(cur)
            restore_timer()
            r._showAnswer()

        def failure(exc: Exception) -> None:
            if self._current is not token:
                return
            cur.grade = None
            self._finish_grading(cur)
            restore_timer()
            showWarning(tr.ankigpt_grading_failed(error=str(exc)), parent=self.mw)
            r._showAnswer()

        self.run_async(lambda: self._grade(client, req), success, failure)
        return True

    def suggested_ease(self) -> Ease | None:
        cur = self._current
        card = self.reviewer.card
        if cur is None or card is None or cur.card_id != card.id:
            return None
        if not cur.graded or cur.grade is None:
            return None
        ease = cur.grade.ease
        if ease in (1, 2, 3, 4):
            return cast(Ease, ease)
        return None

    # ------------------------------------------------------------------
    # Question lifecycle
    # ------------------------------------------------------------------

    def _is_concept(self, card: Card) -> bool:
        try:
            return concepts.is_concept_card(self.mw.col, card)
        except Exception:
            return False

    def _current_state(self) -> scheduler_pb2.SchedulingState | None:
        v3 = getattr(self.reviewer, "_v3", None)
        if v3 is None:
            return None
        try:
            return v3.states.current
        except AttributeError:
            return None

    def _pick_mode(self, card: Card) -> tuple[Mode, DeckSettings]:
        settings = deck_settings(self.mw.col, card.current_deck_id())
        mode = settings.mode
        if mode == MODE_MIX:
            mode = random.choice(prompts.MODES)
        if mode not in prompts.MODES:
            mode = "self"
        return cast(Mode, mode), settings

    def _build_request(
        self, card: Card, mode: Mode, state: scheduler_pb2.SchedulingState | None
    ) -> QuestionRequest:
        note = card.note()
        settings = deck_settings(self.mw.col, card.current_deck_id())
        context = settings.context or concepts.field_to_text(
            note[concepts.FIELD_CONTEXT]
        )
        return QuestionRequest(
            title=concepts.field_to_text(note[concepts.FIELD_TITLE]),
            summary=concepts.field_to_text(note[concepts.FIELD_SUMMARY]),
            key_points=concepts.field_to_lines(note[concepts.FIELD_KEY_POINTS]),
            sources=concepts.field_to_lines(note[concepts.FIELD_SOURCES]),
            context=context,
            mastery=prompts.mastery_from_state(state, card),
            mode=mode,
            recent_questions=self.store_provider().recent_questions(note.id),
        )

    @staticmethod
    def _generate(
        client: LLMClient | FakeLLMClient, req: QuestionRequest
    ) -> GeneratedQuestion:
        system, user = prompts.build_question_prompt(req)
        last: Exception | None = None
        for _ in range(GENERATE_ATTEMPTS):
            data = client.complete_json(
                system, user, "generate_question", prompts.QUESTION_SCHEMA
            )
            try:
                return prompts.parse_question(data, req.mode)
            except prompts.PromptError as exc:
                last = exc
        assert last is not None
        raise last

    @staticmethod
    def _grade(client: LLMClient | FakeLLMClient, req: GradeRequest) -> GradeResult:
        system, user = prompts.build_grade_prompt(req)
        data = client.complete_json(system, user, "grade_answer", prompts.GRADE_SCHEMA)
        return prompts.parse_grade(data)

    def _activate(
        self,
        card: Card,
        question: GeneratedQuestion,
        mode: Mode,
        state: scheduler_pb2.SchedulingState | None,
    ) -> None:
        note = card.note()
        _mode, settings = self._pick_mode(card)
        mastery = prompts.mastery_from_state(state, card)
        base = card.render_output()
        cur = ActiveQuestion(
            card_id=card.id,
            note_id=note.id,
            note_mod=note.mod,
            title=concepts.field_to_text(note[concepts.FIELD_TITLE]),
            mode=mode,
            question=question,
            mastery=mastery,
            settings=settings,
            render_output=TemplateRenderOutput(
                question_text=render_question_html(question, mode, mastery),
                answer_text="",
                question_av_tags=[],
                answer_av_tags=[],
                css=base.css,
            ),
        )
        cur.render_output.answer_text = render_answer_html(cur)
        card.set_render_output(cur.render_output)
        client_model = llm_config(self.mw.pm).model
        try:
            cur.history_id = self.store_provider().log_question(
                note.id, card.id, mode, mastery.level, question, client_model
            )
        except Exception:
            cur.history_id = None
        self._current = cur

    def _take_over(self, card: Card) -> None:
        """Park the reviewer while a question is generated for `card`."""
        r = self.reviewer
        r.state = "transition"
        r._clear_auto_advance_timers()
        text = tr.ankigpt_generating()
        body = (
            f'<div class="ankigpt-banner ankigpt-generating">{html.escape(text)}</div>'
        )
        bodyclass = theme_manager.body_classes_for_card_ord(card.ord)
        r.web.eval(f"_showQuestion({json.dumps(body)}, '', '{bodyclass}');")
        middle = f'<span class="stattxt">{html.escape(text)}</span>'
        r.bottom.web.eval(f"showQuestion({json.dumps(middle)}, 0);")

    def _still_current(self, card: Card, token: int) -> bool:
        r = self.reviewer
        return (
            self.mw.state == "review"
            and r.card is not None
            and r.card.id == card.id
            and self._serial == token
        )

    def _fail(self, message: str) -> None:
        r = self.reviewer
        r.state = "transition"
        self._current = None

        def go() -> None:
            showWarning(message, parent=self.mw)
            if self.mw.state == "review":
                self.mw.moveToState("overview")

        self.mw.progress.single_shot(10, go, False)

    # ------------------------------------------------------------------
    # Grading
    # ------------------------------------------------------------------

    def _grade_choice(self, cur: ActiveQuestion) -> None:
        q = cur.question
        if cur.choice is None:
            cur.grade = GradeResult(0, 1, tr.ankigpt_no_answer_given(), [])
        elif cur.choice == q.correct_index:
            cur.grade = GradeResult(100, 3, q.explanation, [])
        else:
            cur.grade = GradeResult(0, 1, q.explanation, [])
        self._finish_grading(cur)

    def _finish_grading(self, cur: ActiveQuestion) -> None:
        cur.grading = False
        cur.graded = True
        cur.render_output.answer_text = render_answer_html(cur)
        card = self.reviewer.card
        if card is not None and card.id == cur.card_id:
            card.set_render_output(cur.render_output)

    def _show_grading_banner(self) -> None:
        text = json.dumps(tr.ankigpt_grading())
        self.reviewer.web.eval(
            "(function(){"
            "var t=document.getElementById('typeans');if(t){t.disabled=true;}"
            "var qa=document.getElementById('qa');"
            "if(qa&&!document.getElementById('ankigpt-grading')){"
            "var b=document.createElement('div');b.id='ankigpt-grading';"
            f"b.className='ankigpt-banner';b.textContent={text};qa.appendChild(b);}}"
            "})();"
        )

    def _choose(self, index: int) -> None:
        cur = self._current
        r = self.reviewer
        if cur is None or cur.mode != "mcq" or cur.choice is not None:
            return
        if r.state != "question" or r.card is None or r.card.id != cur.card_id:
            return
        if not 0 <= index < len(cur.question.options):
            return
        cur.choice = index
        r._showAnswer()

    # ------------------------------------------------------------------
    # Prefetch
    # ------------------------------------------------------------------

    def _prefetch(self) -> None:
        cur = self._current
        if cur is None:
            return
        config = llm_config(self.mw.pm)
        if not config.configured:
            return
        sched = self.mw.col.sched
        if not isinstance(sched, V3Scheduler):
            return
        try:
            queued = sched.get_queued_cards(fetch_limit=1 + PREFETCH_AHEAD)
        except Exception:
            return
        store = self.store_provider()
        for qc in queued.cards:
            cid = CardId(qc.card.id)
            if cid == cur.card_id or cid in self._prefetching or cid in self._inflight:
                continue
            card = Card(self.mw.col, backend_card=qc.card)
            if not self._is_concept(card):
                continue
            note = card.note()
            if store.get_cached(cid, note.mod):
                continue
            mode, _settings = self._pick_mode(card)
            req = self._build_request(card, mode, qc.states.current)
            client = make_client(config)
            self._prefetching.add(cid)
            self.run_async(
                partial(self._generate, client, req),
                partial(self._on_prefetched, cid, note.id, note.mod, req.mastery.level),
                partial(self._on_prefetch_failed, cid),
            )

    def _on_prefetched(
        self,
        cid: CardId,
        nid: NoteId,
        note_mod: int,
        mastery: str,
        question: GeneratedQuestion,
    ) -> None:
        self._prefetching.discard(cid)
        try:
            self.store_provider().put_cached(cid, nid, note_mod, mastery, question)
        except Exception:
            pass

    def _on_prefetch_failed(self, cid: CardId, _exc: Exception) -> None:
        self._prefetching.discard(cid)

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    def _register_hooks(self) -> None:
        gui_hooks.reviewer_did_show_question.append(self._on_show_question)
        gui_hooks.reviewer_did_show_answer.append(self._on_show_answer)
        gui_hooks.reviewer_did_answer_card.append(self._on_answer_card)
        gui_hooks.reviewer_will_init_answer_buttons.append(self._on_init_buttons)
        gui_hooks.reviewer_will_end.append(self._on_reviewer_end)
        gui_hooks.webview_did_receive_js_message.append(self._on_js_message)
        gui_hooks.state_shortcuts_will_change.append(self._on_state_shortcuts)

    def unregister_hooks(self) -> None:
        gui_hooks.reviewer_did_show_question.remove(self._on_show_question)
        gui_hooks.reviewer_did_show_answer.remove(self._on_show_answer)
        gui_hooks.reviewer_did_answer_card.remove(self._on_answer_card)
        gui_hooks.reviewer_will_init_answer_buttons.remove(self._on_init_buttons)
        gui_hooks.reviewer_will_end.remove(self._on_reviewer_end)
        gui_hooks.webview_did_receive_js_message.remove(self._on_js_message)
        gui_hooks.state_shortcuts_will_change.remove(self._on_state_shortcuts)

    def _on_show_question(self, card: Card) -> None:
        cur = self._current
        if cur is None or cur.card_id != card.id:
            return
        self._prefetch()

    def _on_show_answer(self, card: Card) -> None:
        cur = self._current
        if cur is None or cur.card_id != card.id or not cur.graded or not cur.grade:
            return
        if not cur.settings.auto_submit:
            return
        ease = cur.grade.ease
        r = self.reviewer

        def fire() -> None:
            self._auto_timer = None
            if r.state != "answer" or r.card is None or r.card.id != cur.card_id:
                return
            if self._current is not cur:
                return
            r._answerCard(cast(Ease, ease))

        self._cancel_auto_submit()
        self._auto_timer = self.mw.progress.timer(
            max(200, cur.settings.auto_submit_delay_ms), fire, False, parent=self.mw
        )

    def _cancel_auto_submit(self) -> None:
        if self._auto_timer is not None:
            self._auto_timer.stop()
            self._auto_timer.deleteLater()
            self._auto_timer = None

    def _on_answer_card(self, reviewer: Reviewer, card: Card, ease: int) -> None:
        self._cancel_auto_submit()
        cur = self._current
        if cur is None or cur.card_id != card.id:
            return
        self._current = None
        if cur.history_id is None:
            return
        try:
            store = self.store_provider()
            store.finish_question(
                cur.history_id,
                user_answer=cur.user_answer
                if cur.user_answer is not None
                else (
                    cur.question.options[cur.choice]
                    if cur.choice is not None and cur.question.options
                    else None
                ),
                score=cur.grade.score if cur.grade else None,
                suggested_ease=cur.grade.ease if cur.grade else None,
                final_ease=ease,
                feedback=cur.grade.feedback if cur.grade else None,
            )
            store.prune(cur.note_id)
        except Exception:
            pass

    def _on_init_buttons(
        self,
        buttons: tuple[tuple[int, str], ...],
        reviewer: Reviewer,
        card: Card,
    ) -> tuple[tuple[int, str], ...]:
        if reviewer is not self.reviewer:
            return buttons
        suggested = self.suggested_ease()
        if suggested is None:
            return buttons
        return tuple(
            (ease, f"<b>&#9733; {label}</b>" if ease == suggested else label)
            for ease, label in buttons
        )

    def _on_reviewer_end(self) -> None:
        self._cancel_auto_submit()
        self._current = None

    def _on_js_message(
        self, handled: tuple[bool, Any], message: str, context: Any
    ) -> tuple[bool, Any]:
        if context is not self.reviewer or not message.startswith(JS_CHOOSE_PREFIX):
            return handled
        try:
            index = int(message[len(JS_CHOOSE_PREFIX) :])
        except ValueError:
            return (True, None)
        self._choose(index)
        return (True, None)

    def _on_state_shortcuts(
        self, state: str, shortcuts: list[tuple[str, Callable]]
    ) -> None:
        if state != "review":
            return
        for ease in (1, 2, 3, 4):
            key = self.mw.pm.get_answer_key(ease) or str(ease)
            shortcuts.append((key, partial(self._on_digit, ease)))

    def _on_digit(self, ease: int) -> None:
        r = self.reviewer
        cur = self._current
        if (
            r.state == "question"
            and cur is not None
            and cur.mode == "mcq"
            and cur.choice is None
            and r.card is not None
            and r.card.id == cur.card_id
        ):
            self._choose(ease - 1)
            return
        r._answerCard(cast(Ease, ease))

    # ------------------------------------------------------------------
    # Async plumbing
    # ------------------------------------------------------------------

    def _run_query_op(
        self,
        op: Callable[[], Any],
        success: Callable[[Any], None],
        failure: Callable[[Exception], None],
    ) -> None:
        QueryOp(parent=self.mw, op=lambda _col: op(), success=success).failure(
            failure
        ).without_collection().run_in_background()


def _default_store() -> Store:
    from aqt.ankigpt import get_store

    return get_store()


# ----------------------------------------------------------------------
# HTML rendering
# ----------------------------------------------------------------------

_ALLOWED_TAGS = ("b", "i", "em", "strong", "code", "br", "sub", "sup", "u")


def sanitize(text: str) -> str:
    """Escape LLM text, re-allowing a small set of inline tags."""
    out = html.escape(text, quote=False)
    for tag in _ALLOWED_TAGS:
        out = out.replace(f"&lt;{tag}&gt;", f"<{tag}>").replace(
            f"&lt;/{tag}&gt;", f"</{tag}>"
        )
    out = out.replace("&lt;br/&gt;", "<br>").replace("&lt;br /&gt;", "<br>")
    return out.replace("\n", "<br>")


def _question_block(question: GeneratedQuestion) -> str:
    return f'<div class="ankigpt-question">{sanitize(question.question)}</div>'


def _option_list(question: GeneratedQuestion, chosen: int | None, reveal: bool) -> str:
    items = []
    for i, opt in enumerate(question.options):
        label = f"{i + 1}. {sanitize(opt)}"
        if reveal:
            cls = ""
            if i == question.correct_index:
                cls = "ankigpt-option-correct"
            elif i == chosen:
                cls = "ankigpt-option-wrong"
            items.append(
                f'<li><button type="button" class="{cls}" disabled>{label}</button></li>'
            )
        else:
            items.append(
                f'<li><button type="button" onclick="pycmd(\'{JS_CHOOSE_PREFIX}{i}\')">'
                f"{label}</button></li>"
            )
    return f'<ul class="ankigpt-options">{"".join(items)}</ul>'


def _mode_name(mode: Mode) -> str:
    return {
        "self": tr.ankigpt_mode_self(),
        "typed": tr.ankigpt_mode_typed(),
        "mcq": tr.ankigpt_mode_mcq(),
    }.get(mode, mode)


def _header(mode: Mode, mastery: MasteryInfo | None) -> str:
    bits = [tr.ankigpt_generated_question(), _mode_name(mode)]
    if mastery is not None:
        bits.append(tr.ankigpt_mastery_label(level=mastery.level))
    return f'<div class="ankigpt-header">{" &middot; ".join(html.escape(b) for b in bits)}</div>'


def render_question_html(
    question: GeneratedQuestion, mode: Mode, mastery: MasteryInfo | None = None
) -> str:
    parts = [_header(mode, mastery), _question_block(question)]
    if mode == "typed":
        parts.append(
            '<textarea id="typeans" rows="4" onkeydown="'
            "if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();pycmd('ans');}"
            '"></textarea>'
            f'<div class="ankigpt-banner">{html.escape(tr.ankigpt_type_answer_hint())}</div>'
        )
    elif mode == "mcq":
        parts.append(_option_list(question, None, reveal=False))
    return "\n".join(parts)


def _ease_label(ease: int) -> str:
    return {
        1: tr.studying_again(),
        2: tr.studying_hard(),
        3: tr.studying_good(),
        4: tr.studying_easy(),
    }.get(ease, str(ease))


def _points_block(title: str, points: list[str]) -> str:
    if not points:
        return ""
    items = "".join(f"<li>{sanitize(p)}</li>" for p in points)
    return f'<div class="ankigpt-keypoints"><b>{html.escape(title)}</b><ul>{items}</ul></div>'


def render_answer_html(cur: ActiveQuestion) -> str:
    q = cur.question
    parts = [_header(cur.mode, cur.mastery), _question_block(q)]
    if cur.mode == "mcq":
        parts.append(_option_list(q, cur.choice, reveal=cur.graded))
    parts.append("<hr id=answer>")

    if cur.mode == "typed" and cur.user_answer:
        parts.append(
            f'<div class="ankigpt-user-answer"><b>{html.escape(tr.ankigpt_your_answer())}</b>'
            f"<br>{html.escape(cur.user_answer)}</div>"
        )

    if cur.graded and cur.grade is not None:
        g = cur.grade
        bits = []
        if cur.mode == "mcq":
            verdict = tr.ankigpt_correct() if g.score >= 100 else tr.ankigpt_incorrect()
            bits.append(f'<span class="ankigpt-score">{html.escape(verdict)}</span>')
        else:
            bits.append(
                f'<span class="ankigpt-score">{html.escape(tr.ankigpt_score(score=str(g.score)))}</span>'
            )
        bits.append(
            f"{html.escape(tr.ankigpt_suggested_grade())}: <b>{html.escape(_ease_label(g.ease))}</b>"
        )
        feedback = f"<br>{sanitize(g.feedback)}" if g.feedback else ""
        parts.append(
            f'<div class="ankigpt-feedback">{" &middot; ".join(bits)}{feedback}'
            f"{_points_block(tr.ankigpt_missed_points(), g.missed_points)}</div>"
        )

    if q.model_answer:
        parts.append(
            f'<div class="ankigpt-model-answer"><b>{html.escape(tr.ankigpt_model_answer())}</b>'
            f"<br>{sanitize(q.model_answer)}</div>"
        )
    parts.append(_points_block(tr.ankigpt_key_points(), q.key_points))
    return "\n".join(parts)


__all__ = [
    "ActiveQuestion",
    "ConceptReviewController",
    "render_answer_html",
    "render_question_html",
    "sanitize",
]
