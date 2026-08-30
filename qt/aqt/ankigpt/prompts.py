# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Pure prompt/schema building for AnkiGPT. No Qt, no collection access.

Everything here is deterministic and unit-testable. The LLM client only sees
(system, user, schema) triples produced by the build_* functions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from anki import scheduler_pb2
from anki.cards import Card
from aqt.ankigpt.retrieve import Passage, preview

Mode = Literal["self", "typed", "mcq"]
MODES: tuple[Mode, ...] = ("self", "typed", "mcq")

# Markers that let FakeLLMClient (and humans reading logs) find structured
# parts of a prompt.
CHUNK_MARKER = "=== DOCUMENT TEXT ==="
CANDIDATES_MARKER = "=== CANDIDATE CONCEPTS (JSON) ==="
RECENT_MARKER = "=== RECENTLY ASKED (avoid repeating) ==="
PASSAGES_MARKER = "=== RETRIEVED PASSAGES ==="
CANDIDATE_SECTIONS_MARKER = "=== CANDIDATE SECTIONS ==="
SECTIONS_MARKER = "=== SECTIONS ==="
WANT_RE = re.compile(r"Return (?:at most|exactly) (\d+) concepts")

# ---------------------------------------------------------------------------
# Mastery
# ---------------------------------------------------------------------------

MasteryLevel = Literal[
    "new", "learning", "relearning", "developing", "solid", "mastered", "expert"
]

_LEVEL_ORDER: list[MasteryLevel] = [
    "new",
    "learning",
    "relearning",
    "developing",
    "solid",
    "mastered",
    "expert",
]

_LEVEL_STYLE: dict[MasteryLevel, str] = {
    "new": "The learner has never studied this. Ask a basic recall question that "
    "checks the core definition or idea in the summary.",
    "learning": "The learner saw this recently and is still learning it. Ask a "
    "straightforward recall question, optionally with a light cue.",
    "relearning": "The learner forgot this recently. Ask a focused recall question "
    "that targets the essential point they are most likely to have missed.",
    "developing": "The learner remembers the basics. Ask them to explain the idea "
    "in their own words or to explain why it works.",
    "solid": "The learner knows this well. Ask them to apply the concept to a "
    "concrete scenario, or to compare/contrast it with a related idea.",
    "mastered": "The learner has strong retention. Ask a transfer question: a novel "
    "problem, an edge case, or a subtle misconception to untangle.",
    "expert": "The learner has very strong retention. Ask them to critique the "
    "concept: its limitations, trade-offs, or when it fails to apply.",
}


@dataclass(frozen=True)
class MasteryInfo:
    level: MasteryLevel
    stability_days: float | None = None
    difficulty: float | None = None
    reps: int = 0
    lapses: int = 0
    ivl_days: int = 0

    def style_hint(self) -> str:
        return _LEVEL_STYLE[self.level]


def _level_from_days(days: float) -> MasteryLevel:
    if days < 7:
        return "developing"
    if days < 30:
        return "solid"
    if days < 120:
        return "mastered"
    return "expert"


def _demote(level: MasteryLevel) -> MasteryLevel:
    idx = _LEVEL_ORDER.index(level)
    return _LEVEL_ORDER[max(idx - 1, _LEVEL_ORDER.index("developing"))]


def mastery_from_state(
    state: scheduler_pb2.SchedulingState | None, card: Card | None
) -> MasteryInfo:
    """Derive a mastery level from the scheduler's current state for a card.

    Falls back to the card's own fields (ivl/reps/lapses) when the state is
    missing or is a filtered-preview state.
    """
    reps = card.reps if card else 0
    lapses = card.lapses if card else 0
    ivl = card.ivl if card else 0

    normal: scheduler_pb2.SchedulingState.Normal | None = None
    if state is not None:
        kind = state.WhichOneof("kind")
        if kind == "normal":
            normal = state.normal
        elif kind == "filtered":
            if state.filtered.WhichOneof("kind") == "rescheduling":
                normal = state.filtered.rescheduling.original_state

    if normal is None:
        if reps == 0:
            return MasteryInfo("new", reps=reps, lapses=lapses, ivl_days=ivl)
        level = _level_from_days(max(ivl, 0))
        if lapses >= 3:
            level = _demote(level)
        return MasteryInfo(level, reps=reps, lapses=lapses, ivl_days=ivl)

    nkind = normal.WhichOneof("kind")
    if nkind == "new" or nkind is None:
        return MasteryInfo("new", reps=reps, lapses=lapses, ivl_days=ivl)
    if nkind == "learning":
        return MasteryInfo("learning", reps=reps, lapses=lapses, ivl_days=ivl)

    review = normal.review if nkind == "review" else normal.relearning.review
    stability: float | None = None
    difficulty: float | None = None
    if review.HasField("memory_state"):
        stability = review.memory_state.stability
        difficulty = review.memory_state.difficulty
    review_lapses = max(review.lapses, lapses)

    if nkind == "relearning":
        return MasteryInfo(
            "relearning", stability, difficulty, reps, review_lapses, ivl
        )

    days = stability if stability is not None else float(review.scheduled_days or ivl)
    level = _level_from_days(days)
    if review_lapses >= 3 or (difficulty is not None and difficulty >= 8):
        level = _demote(level)
    return MasteryInfo(level, stability, difficulty, reps, review_lapses, ivl)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ConceptCandidate:
    title: str
    summary: str
    key_points: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "key_points": list(self.key_points),
            "sources": list(self.sources),
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> ConceptCandidate:
        sources = d.get("sources")
        if sources is None:
            excerpt = d.get("source_excerpt", "")
            sources = [excerpt] if excerpt else []
        return ConceptCandidate(
            title=str(d.get("title", "")).strip(),
            summary=str(d.get("summary", "")).strip(),
            key_points=[
                str(p).strip() for p in d.get("key_points", []) if str(p).strip()
            ],
            sources=[str(s).strip() for s in sources if str(s).strip()],
        )


@dataclass
class QuestionRequest:
    title: str
    summary: str
    key_points: list[str]
    sources: list[str]
    context: str
    mastery: MasteryInfo
    mode: Mode
    recent_questions: list[str] = field(default_factory=list)
    passages: list[Passage] = field(default_factory=list)
    lookup_candidates: list[Passage] = field(default_factory=list)


@dataclass
class GeneratedQuestion:
    question: str
    model_answer: str
    key_points: list[str]
    mode: Mode
    options: list[str] = field(default_factory=list)
    correct_index: int = -1
    explanation: str = ""
    source_refs: list[int] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "question": self.question,
                "model_answer": self.model_answer,
                "key_points": self.key_points,
                "mode": self.mode,
                "options": self.options,
                "correct_index": self.correct_index,
                "explanation": self.explanation,
                "source_refs": self.source_refs,
            }
        )

    @staticmethod
    def from_json(text: str) -> GeneratedQuestion:
        d = json.loads(text)
        return GeneratedQuestion(
            question=d["question"],
            model_answer=d.get("model_answer", ""),
            key_points=list(d.get("key_points", [])),
            mode=d.get("mode", "self"),
            options=list(d.get("options", [])),
            correct_index=int(d.get("correct_index", -1)),
            explanation=d.get("explanation", ""),
            source_refs=[int(r) for r in d.get("source_refs", [])],
        )


@dataclass
class GradeRequest:
    title: str
    question: str
    model_answer: str
    key_points: list[str]
    user_answer: str
    mastery: MasteryInfo


@dataclass
class GradeResult:
    score: int
    ease: int
    feedback: str
    missed_points: list[str] = field(default_factory=list)


class PromptError(ValueError):
    """The LLM returned something that doesn't fit the request."""


@dataclass
class InquiryResult:
    answer: str
    revised_title: str = ""
    revised_summary: str = ""
    revised_key_points: list[str] = field(default_factory=list)
    source_refs: list[int] = field(default_factory=list)
    visual_recommended: bool = False
    visual_description: str = ""
    visual_placement: str = "answer"


@dataclass
class GeneratedVisual:
    svg: str
    alt_text: str
    placement: str
    rationale: str


# ---------------------------------------------------------------------------
# JSON schemas (OpenAI strict mode: every property required, no extras)
# ---------------------------------------------------------------------------


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties.keys()),
        "additionalProperties": False,
    }


def _str_list() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


QUESTION_SCHEMA = _obj(
    {
        "question": {"type": "string"},
        "model_answer": {"type": "string"},
        "key_points": _str_list(),
        "options": _str_list(),
        "correct_index": {"type": "integer"},
        "explanation": {"type": "string"},
        "source_refs": {"type": "array", "items": {"type": "integer"}},
        "visual_recommended": {"type": "boolean"},
        "visual_description": {"type": "string"},
        "visual_placement": {
            "type": "string",
            "enum": ["question", "answer", "both"],
        },
    }
)

LOOKUP_SCHEMA = _obj(
    {
        "sections": {"type": "array", "items": {"type": "integer"}},
        "rationale": {"type": "string"},
    }
)

GRADE_SCHEMA = _obj(
    {
        "score": {"type": "integer"},
        "ease": {"type": "integer"},
        "feedback": {"type": "string"},
        "missed_points": _str_list(),
    }
)

EXTRACT_SCHEMA = _obj(
    {
        "concepts": {
            "type": "array",
            "items": _obj(
                {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "key_points": _str_list(),
                    "source_excerpt": {"type": "string"},
                }
            ),
        }
    }
)

PLAN_SCHEMA = _obj(
    {
        "sections": {
            "type": "array",
            "items": _obj(
                {"index": {"type": "integer"}, "priority": {"type": "integer"}}
            ),
        },
        "rationale": {"type": "string"},
    }
)

GAP_SCHEMA = _obj(
    {
        "sections": {"type": "array", "items": {"type": "integer"}},
        "rationale": {"type": "string"},
    }
)

MERGE_SCHEMA = _obj(
    {
        "concepts": {
            "type": "array",
            "items": _obj(
                {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "key_points": _str_list(),
                    "sources": _str_list(),
                }
            ),
        }
    }
)

INQUIRY_SCHEMA = _obj(
    {
        "answer": {"type": "string"},
        "revised_title": {"type": "string"},
        "revised_summary": {"type": "string"},
        "revised_key_points": _str_list(),
        "source_refs": {"type": "array", "items": {"type": "integer"}},
    }
)

VISUAL_SCHEMA = _obj(
    {
        "svg": {"type": "string"},
        "alt_text": {"type": "string"},
        "placement": {"type": "string", "enum": ["question", "answer", "both"]},
        "rationale": {"type": "string"},
    }
)

# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_QUESTION_SYSTEM = """You are a tutor generating one study question for spaced-repetition review.
You are given a concept (title, summary, key points, and verbatim source excerpts from the learner's course material), the learner's current mastery of it, and questions they were asked recently.

Rules:
- Ground every factual premise and the expected answer in the supplied concept or retrieved passages. Never introduce outside facts, names, examples, formulas, or assumptions.
- Ask exactly ONE question. It must be directly relevant to the course context and answerable from the supplied material alone.
- If the requested difficulty would require unsupported facts, ask a simpler grounded question instead.
- Treat the course context as a hard relevance constraint, including its priority topics, exclusions, learner level, and question style.
- Do not repeat or trivially rephrase any recently asked question. Vary the angle.
- Match the requested difficulty style.
- "model_answer": a concise reference answer (2-5 sentences).
- "key_points": 2-5 short items a good answer must include.
- If retrieved passages are given, prefer material from them for applied and transfer questions, and list the numbers of the passages you actually relied on in "source_refs" (empty if none).
- Use plain text (no markdown headings). Short inline HTML like <b>, <i>, <code> is allowed.
"""

_MODE_INSTRUCTIONS: dict[Mode, str] = {
    "self": 'Set "options" to an empty list and "correct_index" to -1. Leave "explanation" empty.',
    "typed": 'The learner will type a free-text answer. Set "options" to an empty list and "correct_index" to -1. Leave "explanation" empty.',
    "mcq": 'Produce a multiple-choice question: "options" must contain exactly 4 answer choices (plain text, no letter prefixes), exactly one correct. "correct_index" is the 0-based index of the correct option. Distractors must be plausible and reflect real misconceptions; make them harder as mastery increases. "explanation" briefly explains why the correct option is right and the others are wrong.',
}


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "(none)"


def format_passages(passages: list[Passage]) -> str:
    if not passages:
        return "(none)"
    return "\n\n".join(
        f'[{i}] ({p.label()})\n"""{p.text}"""' for i, p in enumerate(passages, start=1)
    )


def build_question_prompt(req: QuestionRequest) -> tuple[str, str]:
    sources = "\n\n".join(f'"""{s}"""' for s in req.sources) or "(no excerpts)"
    recent = _bullets(req.recent_questions)
    user = f"""CONCEPT TITLE: {req.title}

SUMMARY:
{req.summary}

KEY POINTS:
{_bullets(req.key_points)}

SOURCE EXCERPTS:
{sources}

COURSE CONTEXT: {req.context or "(none given)"}

{PASSAGES_MARKER}
{format_passages(req.passages)}

LEARNER MASTERY: {req.mastery.level}
DIFFICULTY STYLE: {req.mastery.style_hint()}

QUESTION FORMAT: {req.mode}
{_MODE_INSTRUCTIONS[req.mode]}

{RECENT_MARKER}
{recent}
"""
    return _QUESTION_SYSTEM, user


_LOOKUP_SYSTEM = """You are preparing to write an advanced study question about a concept, and may read more of the learner's course material first.
You see the concept, the passages already retrieved, and candidate sections (title, position, preview). Pick at most 2 candidate sections whose full text would let you ask a better applied, transfer or critique question — for example a worked example, an edge case, a contrast with a related idea. Pick none if the retrieved passages already suffice.
"""


def build_lookup_prompt(req: QuestionRequest) -> tuple[str, str]:
    lines = []
    for i, c in enumerate(req.lookup_candidates, start=1):
        lines.append(f"[{i}] ({c.label()}, {len(c.text):,} chars): {preview(c.text)}")
    user = f"""CONCEPT: {req.title}
SUMMARY: {req.summary}
LEARNER MASTERY: {req.mastery.level} — {req.mastery.style_hint()}

{PASSAGES_MARKER}
{format_passages(req.passages)}

{CANDIDATE_SECTIONS_MARKER}
{chr(10).join(lines) or "(none)"}
"""
    return _LOOKUP_SYSTEM, user


def parse_lookup(data: dict[str, Any], count: int) -> list[int]:
    """1-based candidate numbers chosen by the model, validated, at most 2."""
    out: list[int] = []
    for item in data.get("sections", []):
        try:
            n = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= count and n not in out:
            out.append(n)
    return out[:2]


def parse_question(data: dict[str, Any], mode: Mode) -> GeneratedQuestion:
    question = str(data.get("question", "")).strip()
    if not question:
        raise PromptError("empty question")
    options = [str(o).strip() for o in data.get("options", [])]
    correct = int(data.get("correct_index", -1))
    if mode == "mcq":
        if len(options) != 4 or any(not o for o in options):
            raise PromptError("multiple choice needs exactly 4 options")
        if not 0 <= correct < 4:
            raise PromptError("correct_index out of range")
    else:
        options = []
        correct = -1
    refs: list[int] = []
    for item in data.get("source_refs", []):
        try:
            refs.append(int(item))
        except (TypeError, ValueError):
            continue
    return GeneratedQuestion(
        question=question,
        model_answer=str(data.get("model_answer", "")).strip(),
        key_points=[
            str(p).strip() for p in data.get("key_points", []) if str(p).strip()
        ],
        mode=mode,
        options=options,
        correct_index=correct,
        explanation=str(data.get("explanation", "")).strip(),
        source_refs=refs,
    )


_GRADE_SYSTEM = """You grade a learner's free-text answer to a study question for spaced repetition.
Compare the answer against the model answer and key points. Be fair: accept different wording, partial credit for partially correct answers, and do not penalize brevity if the substance is right. Penalize factual errors.

Output:
- "score": 0-100.
- "ease": the spaced-repetition rating. 1 = Again (wrong or missing the core idea), 2 = Hard (partially right, important gaps), 3 = Good (essentially correct), 4 = Easy (complete, precise, effortless).
- "feedback": 1-3 sentences addressed to the learner. Plain text; <b>/<i> allowed.
- "missed_points": key points the answer failed to cover (empty if none).
"""


def build_grade_prompt(req: GradeRequest) -> tuple[str, str]:
    user = f"""CONCEPT: {req.title}
LEARNER MASTERY: {req.mastery.level}

QUESTION:
{req.question}

MODEL ANSWER:
{req.model_answer}

KEY POINTS:
{_bullets(req.key_points)}

LEARNER'S ANSWER:
\"\"\"{req.user_answer}\"\"\"
"""
    return _GRADE_SYSTEM, user


def parse_grade(data: dict[str, Any]) -> GradeResult:
    score = max(0, min(100, int(data.get("score", 0))))
    ease = int(data.get("ease", 0))
    if ease not in (1, 2, 3, 4):
        ease = 1 if score < 40 else 2 if score < 65 else 3 if score < 90 else 4
    return GradeResult(
        score=score,
        ease=ease,
        feedback=str(data.get("feedback", "")).strip(),
        missed_points=[
            str(p).strip() for p in data.get("missed_points", []) if str(p).strip()
        ],
    )


_EXTRACT_SYSTEM = """You extract study concepts from course material for spaced-repetition review.
A concept is a single, self-contained idea worth remembering: a definition, a mechanism, a theorem, a distinction, a procedure, a cause-effect relationship.

First classify the supplied text. Study material teaches or explains reusable subject
knowledge. Scaffolding includes directions, grading rules, rubrics, due dates, learning
platform text, navigation, answer-entry instructions, and other administrative content.
Assessment material includes quiz/exam questions, answer choices, point values, attempt
history, and solution keys. Extract concepts only from study material and from assessment
material that contains enough explanation or a worked solution to support the concept.

For each concept:
- "title": short, specific (3-10 words).
- "summary": 2-4 sentences that fully explain the concept as the material presents it.
- "key_points": 2-5 essential facts a learner must know.
- "source_excerpt": a verbatim quote (up to ~500 characters) from the text that best supports the concept.

Quality rules:
- Treat HTML/XML tags, escaped markup, CSS, JavaScript, Markdown control syntax, template syntax, and similar machine or presentation content as document scaffolding, not subject matter. Use only the human-readable meaning they contain. Never create a concept about the markup itself or copy markup into a concept field.
- Return plain text only in every concept field. Do not emit tags, HTML entities used as markup, Markdown formatting, code fences, style rules, scripts, or template artifacts. Preserve meaningful mathematical and scientific notation as plain text.
- Prefer concepts that match the learner's instructions. Skip scaffolding, boilerplate, administrative text, and trivia. Do not duplicate concepts.
- Never make a concept about document directions or quiz mechanics (for example "select two answers," "show your work," a point value, or a submission deadline).
- When a quiz problem includes a supported principle or an explained solution, extract that reusable principle in clean instructional language. Do not copy the question format, question number, answer choices, blanks, commands to the student, or grading language into the title, summary, or key points.
- A bare question is not evidence for its answer. If the text asks something but does not supply enough teaching content, an answer, or a worked solution, skip it rather than answering from memory.
- Treat text with broken reading order, isolated glyphs, replacement characters, mangled formulas, or incoherent fragments as unreadable. Do not repair or interpret corrupted PDF extraction from outside knowledge; skip it.
- The learner's course, level, priority topics, and exclusions are hard relevance constraints. Every factual statement must be explicitly supported by legible supplied text.
- Return fewer concepts than requested whenever the material does not support enough distinct, useful, self-contained concepts. Quality is more important than count.
"""


def build_extract_prompt(
    chunk: str,
    instructions: str,
    want: int,
    doc_name: str,
    outline: str = "",
    sampled: bool = False,
) -> tuple[str, str]:
    structure = ""
    if outline:
        structure = (
            "\nDOCUMENT OUTLINE (headings found across the whole document, with "
            f"approximate position):\n{outline}\n"
        )
    note = ""
    if sampled:
        note = (
            "\nNOTE: the document is large, so only selected sections of it are "
            "provided; '[...]' marks skipped material. Use the outline for context and "
            "extract only concepts that the excerpt actually explains.\n"
        )
    user = f"""LEARNER'S INSTRUCTIONS: {instructions or "(none given)"}
DOCUMENT: {doc_name}
Return at most {want} concepts.
{structure}{note}
{CHUNK_MARKER}
{chunk}
"""
    return _EXTRACT_SYSTEM, user


_PLAN_SYSTEM = """You plan how to read a long document for spaced-repetition concept extraction under a strict reading budget.
You see a skim of the document: one line per section with its index, position, length and the first words. You cannot read more than the budget allows, so choose the sections most likely to contain the ideas worth remembering, given the learner's instructions.

Rules:
- Return the sections to read as {"index", "priority"} with priority 5 (must read) down to 1 (nice to have). Omit sections that should not be read.
- Prefer substantive teaching material: definitions, mechanisms, methods, worked examples, explained solutions, and key results.
- Deprioritize directions, rubrics, schedules, navigation, answer-entry instructions, question-only exercise lists, answer choices without explanations, references, indexes, and visibly corrupted text extraction.
- Aim for a set whose total length is around the budget; include more sections than fit so lower priorities can be dropped.
- Spread choices across the document when the instructions do not single out a part.
"""


def build_plan_prompt(
    skim: str,
    instructions: str,
    doc_name: str,
    total_chars: int,
    budget_chars: int,
    section_count: int,
) -> tuple[str, str]:
    user = f"""LEARNER'S INSTRUCTIONS: {instructions or "(none given)"}
DOCUMENT: {doc_name} ({total_chars:,} characters, {section_count} sections)
READING BUDGET: about {budget_chars:,} characters in total.

{SECTIONS_MARKER}
{skim}
"""
    return _PLAN_SYSTEM, user


def parse_plan(data: dict[str, Any]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for item in data.get("sections", []):
        try:
            index = int(item.get("index"))
            priority = int(item.get("priority", 1))
        except (TypeError, ValueError, AttributeError):
            continue
        out.append((index, max(1, min(5, priority))))
    return out


_GAP_SYSTEM = """You check whether important material was skipped while reading a long document under a budget.
You see the titles of concepts already extracted, and a skim of the sections that were NOT read. Pick the unread sections most likely to contain important, well-explained concepts that are missing, if any. Do not select administrative material, question-only assessments, answer choices without explanations, or corrupted text. It is fine to pick none.
"""


def build_gap_prompt(
    unread_skim: str,
    extracted_titles: list[str],
    instructions: str,
    doc_name: str,
    remaining_chars: int,
    max_sections: int,
) -> tuple[str, str]:
    user = f"""LEARNER'S INSTRUCTIONS: {instructions or "(none given)"}
DOCUMENT: {doc_name}
REMAINING BUDGET: about {remaining_chars:,} characters. Pick at most {max_sections} sections (by index), or none.

CONCEPTS ALREADY EXTRACTED:
{_bullets(extracted_titles)}

{SECTIONS_MARKER}
{unread_skim}
"""
    return _GAP_SYSTEM, user


def parse_gaps(data: dict[str, Any]) -> list[int]:
    out: list[int] = []
    for item in data.get("sections", []):
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


_MERGE_SYSTEM = """You curate a list of study concepts extracted from course material.
You receive candidate concepts (possibly overlapping, from different parts of the documents) and must produce a final, deduplicated, well-ordered list.

- Merge near-duplicates into one concept, combining their key points and keeping up to 3 of the best source excerpts in "sources".
- Act as a strict quality gate, not merely a summarizer. Delete candidates about instructions, rubrics, quiz mechanics, question numbers, answer choices, point values, deadlines, document structure, or other non-subject scaffolding.
- Convert a useful assessment-derived candidate into a clean, reusable subject concept only when its supplied summary, key points, and source excerpts contain enough evidence. Remove all question formatting and commands to the student. Otherwise delete it.
- Delete candidates whose excerpts are garbled, fragmentary, in broken reading order, or do not support every factual claim. Never fill gaps from outside knowledge.
- Delete vague labels, incomplete thoughts, trivial facts, and candidates that would not produce a worthwhile spaced-repetition question.
- Rank by importance to the learner's instructions; drop weak material even when doing so leaves fewer than the requested count.
- Order the final list in a sensible learning sequence (foundational ideas first).
- Keep titles specific and independent of their source document; keep summaries 2-4 clear instructional sentences.
- Treat markup inherited from candidates as document scaffolding. Keep only its supported human-readable meaning, and return plain text in titles, summaries, key points, and source excerpts—never HTML/XML tags, escaped markup, Markdown formatting, code fences, CSS, JavaScript, or template artifacts.
- Treat the learner's stated course, priorities, and exclusions as hard constraints. Drop off-topic candidates even if that means returning fewer than requested.
- Preserve source support. Do not add facts that are absent from the candidate summaries, key points, and excerpts.
"""


def build_merge_prompt(
    candidates: list[ConceptCandidate], instructions: str, target: int
) -> tuple[str, str]:
    payload = json.dumps([c.to_dict() for c in candidates], ensure_ascii=False)
    user = f"""LEARNER'S INSTRUCTIONS: {instructions or "(none given)"}
Return at most {target} concepts. Return fewer whenever candidates fail the quality rules.

{CANDIDATES_MARKER}
{payload}
"""
    return _MERGE_SYSTEM, user


def parse_concepts(data: dict[str, Any]) -> list[ConceptCandidate]:
    out: list[ConceptCandidate] = []
    for item in data.get("concepts", []):
        c = ConceptCandidate.from_dict(item)
        if c.title and c.summary:
            out.append(c)
    return out


_INQUIRY_SYSTEM = """You are a source-grounded learning assistant embedded in a spaced-repetition application.
Answer the learner's request using the supplied concept and course excerpts. Clearly say when the material does not support a claim; never fill gaps from memory. Explain in clear instructional language and do not reveal or solve an active assessment unless the supplied material itself contains the solution.

When MODE is STUDY, answer the question and leave every revised_* field empty.
When MODE is EDIT, also propose a cleaner, self-contained concept in revised_title, revised_summary, and revised_key_points. Preserve supported meaning, remove quiz/document scaffolding, and do not invent facts. The learner must explicitly apply your proposal.
List only the 1-based SOURCE EXCERPT numbers actually used in source_refs.
Recommend a visual only when spatial structure, a process, comparison, chart, or diagram would materially improve comprehension. Describe an instructional visual precisely and choose whether it belongs on the question, answer, or both sides. Do not recommend decorative imagery.
"""


def build_inquiry_prompt(
    *,
    mode: str,
    question: str,
    title: str,
    summary: str,
    key_points: list[str],
    context: str = "",
    sources: list[str] | None = None,
) -> tuple[str, str]:
    rendered_sources = "\n\n".join(
        f'[{i}] """{source}"""'
        for i, source in enumerate(sources or [], start=1)
    ) or "(none)"
    user = f"""MODE: {mode.upper()}
LEARNER REQUEST: {question}

CONCEPT TITLE: {title}
SUMMARY: {summary}
KEY POINTS:
{_bullets(key_points)}
COURSE CONTEXT: {context or "(none)"}

SOURCE EXCERPTS:
{rendered_sources}
"""
    return _INQUIRY_SYSTEM, user


def parse_inquiry(data: dict[str, Any]) -> InquiryResult:
    answer = str(data.get("answer", "")).strip()
    if not answer:
        raise PromptError("empty inquiry answer")
    refs: list[int] = []
    for value in data.get("source_refs", []):
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in refs:
            refs.append(number)
    return InquiryResult(
        answer=answer,
        revised_title=str(data.get("revised_title", "")).strip(),
        revised_summary=str(data.get("revised_summary", "")).strip(),
        revised_key_points=[
            str(point).strip()
            for point in data.get("revised_key_points", [])
            if str(point).strip()
        ],
        source_refs=refs,
        visual_recommended=bool(data.get("visual_recommended", False)),
        visual_description=str(data.get("visual_description", "")).strip(),
        visual_placement=(
            str(data.get("visual_placement", "answer"))
            if str(data.get("visual_placement", "answer"))
            in {"question", "answer", "both"}
            else "answer"
        ),
    )


_VISUAL_SYSTEM = """You design one concise instructional SVG for a spaced-repetition concept.
The visual must teach, not decorate. Choose the representation that best reduces cognitive load: a labeled process, relationship diagram, comparison, timeline, plot, hierarchy, free-body diagram, or other appropriate schematic. If the concept is not inherently visual, make a restrained concept map rather than inventing a scene.

Rules:
- Use only facts explicitly present in the concept and course context. Never add plausible domain details.
- Focus on one learning objective and omit ornamental elements, backgrounds, logos, and clip art.
- Use a 16:9 viewBox of 0 0 960 540, generous spacing, high contrast, and readable text at least 22px.
- Keep labels brief. Prefer arrows, grouping, alignment, and color coding over paragraphs.
- Do not reveal the answer on the question side; choose answer placement when labels or relationships would give it away.
- Return standalone SVG using only svg, g, rect, circle, ellipse, line, polyline, polygon, path, text, tspan, and marker elements.
- Do not use scripts, CSS, foreignObject, images, links, external resources, animation, filters, masks, or event handlers.
- Include a clear alt-text description and a one-sentence rationale.
"""


def build_visual_prompt(
    *, title: str, summary: str, key_points: list[str], context: str = "", request: str = ""
) -> tuple[str, str]:
    return _VISUAL_SYSTEM, f"""CONCEPT: {title}
SUMMARY: {summary}
KEY POINTS:
{_bullets(key_points)}
COURSE CONTEXT: {context or "(none)"}
LEARNER'S VISUAL REQUEST: {request or "Choose the most instructionally useful visual."}
"""


def parse_visual(data: dict[str, Any]) -> GeneratedVisual:
    svg = str(data.get("svg", "")).strip()
    alt = str(data.get("alt_text", "")).strip()
    if not svg or not alt:
        raise PromptError("visual response is incomplete")
    placement = str(data.get("placement", "answer"))
    if placement not in {"question", "answer", "both"}:
        placement = "answer"
    return GeneratedVisual(svg, alt, placement, str(data.get("rationale", "")).strip())
