# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

from types import SimpleNamespace

from aqt.ankigpt.study_hub import render_study_hub


def node(name: str, deck_id: int, new: int = 0, review: int = 0):
    return SimpleNamespace(
        name=name,
        deck_id=deck_id,
        new_count=new,
        learn_count=0,
        review_count=review,
        children=[],
    )


def test_hub_renders_decks_actions_and_escapes_names() -> None:
    first = node("Statics <Moments>", 10, review=4)
    second = node("Thermodynamics", 11)
    root = SimpleNamespace(children=[first, second])

    page = render_study_hub(root, "12 cards studied today")

    assert "Good to see you" in page
    assert "Statics &lt;Moments&gt;" in page
    assert "pycmd('ankigpt:route:course:10')" in page
    assert "pycmd('open:" not in page
    assert "4 due" in page
    assert "Up to date" in page
    assert "12 cards studied today" in page
    assert "Advanced Anki Tools" not in page
    assert "Exit" in page and "ankigpt:exit" in page


def test_shell_routes_stay_in_the_new_interface() -> None:
    root = SimpleNamespace(children=[node("Statics", 10, review=4)])

    records = [(100, "Moment of Force", "Turning effect of a force.", ["M = Fd"])]
    concepts = render_study_hub(root, "Today", "concepts", records)
    editor = render_study_hub(root, "Today", "concept:100", records)
    progress = render_study_hub(root, "Today", "progress")
    settings = render_study_hub(
        root,
        "Today",
        "settings",
        settings={
            "provider": "openai",
            "configured": True,
            "model": "gpt-test",
            "base_url": "https://example.test/v1",
            "timeout": 45,
            "max_chars": 120000,
        },
        notice="Connected successfully.",
    )
    system = render_study_hub(root, "Today", "system")
    course = render_study_hub(root, "Today", "course:10")
    notes = [
        {
            "id": 200,
            "deck": "Statics",
            "notetype": "Basic",
            "preview": "What is a moment?",
            "fields": [("Front", "What is a moment?"), ("Back", "Force × distance")],
        }
    ]
    library = render_study_hub(root, "Today", "library", notes=notes)
    editor_note = render_study_hub(root, "Today", "note:200", notes=notes)
    add_card = render_study_hub(root, "Today", "add", notes=notes)

    assert "Your concepts" in concepts and "ankigpt:route:concepts" in concepts
    assert "Moment of Force" in concepts
    assert "Edit concept" in editor and "ankigpt:save-concept" in editor
    assert "Improve with AI" in editor and "ankigpt:assist-concept" in editor
    visual_editor = render_study_hub(
        root,
        "Today",
        "concept:100",
        [(100, "Moment", "Turning effect.", ["M = Fd"], "moment.png", "Force and lever arm", "answer")],
    )
    assert "Visual aid" in visual_editor and 'src="moment.png"' in visual_editor
    assert "ankigpt:attach-visual" in visual_editor
    assert "Generate AI visual" in visual_editor and "ankigpt:generate-visual" in visual_editor
    assert "Image description" in visual_editor and "Screen readers" in visual_editor
    assert "Your progress" in progress and "Ready to review" in progress
    assert "Settings" in settings and "AI connection" in settings
    assert "gpt-test" in settings and "https://example.test/v1" in settings
    assert "ankigpt:save-settings" in settings
    assert "Connected successfully." in settings
    assert "Data and synchronization" in system
    assert "ankigpt:system:sync" in system and "ankigpt:system:check-db" in system
    assert "ankigpt:system:import" in system and "ankigpt:system:export" in system
    assert "Statics" in course and "Start studying" in course
    assert "ankigpt:study:10" in course
    assert "ankigpt:course-sources:10" in course
    assert "Delete course" in course
    assert "ankigpt:delete-course:10" in course
    assert "Card Library" in library and "What is a moment?" in library
    assert "ankigpt:route:note:200" in library
    assert "Edit note" in editor_note and "ankigpt:save-note" in editor_note
    assert "Add a study card" in add_card and "ankigpt:add-card" in add_card
    assert "ankigpt:advanced" not in concepts + progress + settings
