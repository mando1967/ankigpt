# AnkiGPT

AnkiGPT is a fork of [Anki](https://apps.ankiweb.net) in which the unit of
study is a **concept** rather than a fixed card. Anki's FSRS scheduler decides
which concepts are due; when one comes up, a question is generated on the fly
by an OpenAI-compatible LLM from the concept's summary and source excerpts,
adapted to how well you already know it. Concept decks are built by uploading
course documents (PDF, DOCX, Markdown, text) plus a short prompt.

Everything else in Anki (normal decks, sync, browser, stats) is unchanged.

## Using it

1. Build and run as described in [Development](./docs/development.md)
   (`just run`).
2. Preferences > Third Party Services: enter your API key. The base URL and
   model are editable, so any OpenAI-compatible endpoint works.
3. Tools > AnkiGPT > Create Concept Deck from Documents...: add files, write
   instructions (course name, what to focus on), pick a grading mode, extract,
   review the proposed concepts, and create the deck.
4. Study the deck. Grading modes (per deck, Tools > AnkiGPT > Concept Deck
   Settings...):
   - **Self-grade**: the usual Again/Hard/Good/Easy buttons.
   - **Typed answer**: type an answer, the LLM grades it and pre-selects a
     button; Enter/Space accepts, 1-4 overrides. Optional auto-submit.
   - **Multiple choice**: four options, auto-graded (click or press 1-4).
   - **Random mix** of the three.

Recently asked questions per concept are kept in `ankigpt.sqlite` next to your
profile so new questions do not repeat them. If no API key is set or the API
fails, reviewing a concept deck stops with an error.

Set `ANKIGPT_FAKE_LLM=1` to run without network (deterministic fake answers),
e.g. `ANKIGPT_FAKE_LLM=1 just run -b /tmp/ankigpt-base`. An end-to-end check
that boots the app offscreen lives in `tools/ankigpt_smoke.py`.

## Where the code lives

- `qt/aqt/ankigpt/` - all AnkiGPT code (`review.py` is the reviewer
  integration; `generate_dialog.py` + `extract.py` build decks;
  `store.py` is the sidecar database).
- `ftl/qt/ankigpt.ftl` - UI strings.
- Upstream files touched: `qt/aqt/reviewer.py` (four hook lines),
  `qt/aqt/main.py`, `qt/aqt/preferences.py`, `qt/pyproject.toml`/`uv.lock`.
- Tests: `qt/tests/test_ankigpt_*.py`.

---

# Anki

[![Build Status](https://github.com/ankitects/anki/actions/workflows/ci.yml/badge.svg)](https://github.com/ankitects/anki/actions/workflows/ci.yml)
[![Documentation](https://img.shields.io/badge/docs-dev--docs.ankiweb.net-blue)](https://dev-docs.ankiweb.net)

This repo contains the source code for the computer version of
[Anki](https://apps.ankiweb.net).

## About

Anki is a spaced repetition program. Please see the [website](https://apps.ankiweb.net) to learn more.

## Getting Started

### Contributing

Want to contribute to Anki? Check out the [Contribution Guidelines](./docs/contributing.md).

For more information on building and developing, please see [Development](./docs/development.md).

#### Contributors

The following people have contributed to Anki: [CONTRIBUTORS](./CONTRIBUTORS)

### Anki Betas

If you'd like to try development builds of Anki but don't feel comfortable
building the code, please see [Anki betas](https://betas.ankiweb.net/).

## License

Anki's license: [LICENSE](./LICENSE)
