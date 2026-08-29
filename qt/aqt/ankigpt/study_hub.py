# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Modern Study Hub rendered inside Anki's existing deck-browser webview."""

from __future__ import annotations

import html
from collections.abc import Iterable
from typing import Any


def _all_decks(nodes: Iterable[Any]) -> list[Any]:
    decks: list[Any] = []
    for node in nodes:
        decks.append(node)
        decks.extend(_all_decks(node.children))
    return decks


def render_study_hub(
    root: Any,
    studied_today: str,
    route: str = "home",
    concepts: list[tuple[int, str, str, list[str]]] | None = None,
    notes: list[dict[str, Any]] | None = None,
    settings: dict[str, Any] | None = None,
    notice: str = "",
) -> str:
    decks = _all_decks(root.children)
    first_due = next(
        (
            deck
            for deck in decks
            if deck.new_count + deck.learn_count + deck.review_count > 0
        ),
        decks[0] if decks else None,
    )
    continue_action = (
        f"pycmd('ankigpt:route:course:{int(first_due.deck_id)}')"
        if first_due
        else "pycmd('ankigpt')"
    )
    rows = "".join(_deck_row(deck) for deck in decks)
    if not rows:
        rows = """<tr><td colspan="5" class="hub-empty">
        No courses yet. Create your first AI course from your materials.
        </td></tr>"""

    main = _route_content(
        route,
        decks,
        rows,
        studied_today,
        continue_action,
        concepts or [],
        notes or [],
        settings or {},
        notice,
    )
    return f"""
<tr><td colspan="9" class="ankigpt-hub-cell">
<style>{_CSS}</style>
<div class="ankigpt-hub">
  <aside class="hub-nav">
    <div class="hub-brand"><span class="hub-mark">A</span> AnkiGPT</div>
    <button class="nav-item {_active(route, "home")}" onclick="pycmd('ankigpt:route:home')">⌂ <span>Home</span></button>
    <button class="nav-item" onclick="pycmd('ankigpt')">＋ <span>Create Course</span></button>
    <button class="nav-item" onclick="{continue_action}">▷ <span>Study</span></button>
    <button class="nav-item {_active(route, "concepts")}" onclick="pycmd('ankigpt:route:concepts')">▣ <span>Concepts</span></button>
    <button class="nav-item {_active(route, "library")}" onclick="pycmd('ankigpt:route:library')">▤ <span>Card Library</span></button>
    <button class="nav-item {_active(route, "progress")}" onclick="pycmd('ankigpt:route:progress')">⌁ <span>Progress</span></button>
    <div class="nav-spacer"></div>
    <button class="nav-item {_active(route, "system")}" onclick="pycmd('ankigpt:route:system')">↻ <span>Data & Sync</span></button>
    <button class="nav-item {_active(route, "settings")}" onclick="pycmd('ankigpt:route:settings')">⚙ <span>Settings</span></button>
  </aside>
  {main}
</div>
</td></tr>
"""


def _active(route: str, expected: str) -> str:
    return "active" if route == expected else ""


def _route_content(
    route: str,
    decks: list[Any],
    rows: str,
    studied_today: str,
    continue_action: str,
    concepts: list[tuple[int, str, str, list[str]]],
    notes: list[dict[str, Any]],
    settings: dict[str, Any],
    notice: str,
) -> str:
    if route == "add":
        deck_options = "".join(
            f'<option value="{int(deck.deck_id)}">{html.escape(deck.name)}</option>'
            for deck in decks
        )
        return f"""<main class="hub-main"><button class="text-back" onclick="pycmd('ankigpt:route:library')">← Card library</button>
        <div class="page-head"><div class="hub-eyebrow">NEW CARD</div><h1>Add a study card</h1><p>Create a standard front-and-back card in any course.</p></div>
        <section class="content-card concept-form"><label>Course<select id="new-card-deck">{deck_options}</select></label>
        <label>Front<textarea id="new-card-front" rows="6"></textarea></label><label>Back<textarea id="new-card-back" rows="7"></textarea></label>
        <div class="form-actions"><button class="hub-secondary" onclick="pycmd('ankigpt:route:library')">Cancel</button>
        <button class="hub-primary" onclick="ankigptAddCard()">Add card</button></div></section>
        <script>function ankigptAddCard(){{const p={{deck_id:document.getElementById('new-card-deck').value,front:document.getElementById('new-card-front').value,back:document.getElementById('new-card-back').value}};pycmd('ankigpt:add-card:'+encodeURIComponent(JSON.stringify(p)));}}</script></main>"""
    if route.startswith("note:"):
        try:
            note_id = int(route.split(":", 1)[1])
        except ValueError:
            note_id = 0
        note = next((item for item in notes if item["id"] == note_id), None)
        if note:
            fields = "".join(
                f'<label>{html.escape(name)}<textarea class="note-field" data-name="{html.escape(name, quote=True)}" rows="5">{html.escape(value)}</textarea></label>'
                for name, value in note["fields"]
            )
            return f"""<main class="hub-main"><button class="text-back" onclick="pycmd('ankigpt:route:library')">← Card library</button>
            <div class="page-head"><div class="hub-eyebrow">CARD EDITOR</div><h1>Edit note</h1><p>{html.escape(note["deck"])} · {html.escape(note["notetype"])}</p></div>
            <section class="content-card concept-form">{fields}<div class="form-actions"><button class="hub-secondary" onclick="pycmd('ankigpt:route:library')">Cancel</button>
            <button class="hub-primary" onclick="ankigptSaveNote()">Save changes</button></div></section>
            <script>function ankigptSaveNote(){{const f={{}};document.querySelectorAll('.note-field').forEach(e=>f[e.dataset.name]=e.value);pycmd('ankigpt:save-note:'+encodeURIComponent(JSON.stringify({{nid:{note_id},fields:f}})));}}</script></main>"""
    if route == "library":
        note_rows = (
            "".join(
                f"""<button class="library-row" onclick="pycmd('ankigpt:route:note:{item["id"]}')"><span><strong>{html.escape(item["preview"])}</strong><small>{html.escape(item["deck"])} · {html.escape(item["notetype"])}</small></span><b>›</b></button>"""
                for item in notes
            )
            or '<div class="empty-card">No cards yet.</div>'
        )
        return f"""<main class="hub-main"><div class="page-head page-head-actions"><div><div class="hub-eyebrow">CARD LIBRARY</div><h1>Browse and edit</h1><p>Manage every note without leaving the AnkiGPT workspace.</p></div>
        <button class="hub-primary" onclick="pycmd('ankigpt:route:add')">＋ Add card</button></div>
        <section class="content-card"><div class="search-shell">⌕ <span>Browse {len(notes)} notes</span></div><div class="library-list">{note_rows}</div></section></main>"""
    if route.startswith("course:"):
        try:
            deck_id = int(route.split(":", 1)[1])
        except ValueError:
            deck_id = 0
        deck = next((item for item in decks if int(item.deck_id) == deck_id), None)
        if deck:
            total = deck.new_count + deck.learn_count + deck.review_count
            return f"""<main class="hub-main"><button class="text-back" onclick="pycmd('ankigpt:route:home')">← All courses</button>
            <section class="course-hero"><div><div class="hub-eyebrow">COURSE</div><h1>{html.escape(deck.name)}</h1>
            <p>{total} cards are ready across new, learning, and review queues.</p>
            <div class="hero-actions"><button class="hub-primary" onclick="pycmd('ankigpt:study:{deck_id}')">▷ Start studying</button>
            <button class="hub-secondary" onclick="pycmd('ankigpt:course-sources:{deck_id}')">View sources</button></div></div>
            <div class="course-total"><strong>{total}</strong><span>ready today</span></div></section>
            <div class="metric-grid course-metrics"><div class="metric blue"><span>New</span><strong>{deck.new_count}</strong></div>
            <div class="metric amber"><span>Learning</span><strong>{deck.learn_count}</strong></div>
            <div class="metric green"><span>Review</span><strong>{deck.review_count}</strong></div>
            <div class="metric"><span>Status</span><strong>{"Ready" if total else "Done"}</strong></div></div>
            <section class="content-card"><div class="section-heading"><div><div class="hub-eyebrow">NEXT STEP</div><h2>Keep the momentum</h2></div></div>
            <p>Study with source-aware answers, or inspect and refine the concepts generated for this course.</p>
            <div class="hero-actions"><button class="hub-secondary" onclick="pycmd('ankigpt:route:concepts')">Browse concepts</button>
            <button class="hub-secondary" onclick="pycmd('ankigpt:course-sources:{deck_id}')">Open source library</button></div></section></main>"""
    if route.startswith("concept:"):
        try:
            note_id = int(route.split(":", 1)[1])
        except ValueError:
            note_id = 0
        concept = next((item for item in concepts if item[0] == note_id), None)
        if concept:
            nid, title, summary, points = concept
            points_text = "\n".join(points)
            return f"""<main class="hub-main"><button class="text-back" onclick="pycmd('ankigpt:route:concepts')">← All concepts</button>
            <div class="page-head"><div class="hub-eyebrow">CONCEPT EDITOR</div><h1>Edit concept</h1>
            <p>Refine the material used to generate future study questions.</p></div>
            <section class="content-card concept-form"><label>Title<input id="concept-title" value="{html.escape(title, quote=True)}"></label>
            <label>Description<textarea id="concept-summary" rows="6">{html.escape(summary)}</textarea></label>
            <label>Key points <small>One per line</small><textarea id="concept-points" rows="7">{html.escape(points_text)}</textarea></label>
            <div class="form-actions"><button class="hub-secondary" onclick="pycmd('ankigpt:route:concepts')">Cancel</button>
            <button class="hub-primary" onclick="(function(){{const p={{nid:{nid},title:document.getElementById('concept-title').value,summary:document.getElementById('concept-summary').value,points:document.getElementById('concept-points').value}};pycmd('ankigpt:save-concept:'+encodeURIComponent(JSON.stringify(p)))}})()">Save changes</button></div></section></main>"""
    if route == "concepts":
        cards = (
            "".join(
                f"""<button class="course-tile" onclick="pycmd('ankigpt:route:concept:{nid}')">
            <span class="course-icon">◇</span><span><strong>{html.escape(title)}</strong>
            <small>{html.escape(summary[:110])}</small></span><b>›</b></button>"""
                for nid, title, summary, _points in concepts
            )
            or '<div class="empty-card">Create a course to begin building concepts.</div>'
        )
        return f"""<main class="hub-main"><div class="page-head"><div class="hub-eyebrow">KNOWLEDGE LIBRARY</div>
        <h1>Your concepts</h1><p>Browse concepts by course and continue refining what you want to learn.</p></div>
        <div class="content-card"><div class="search-shell">⌕ <span>Search concepts and courses</span></div>
        <div class="course-grid">{cards}</div></div></main>"""
    if route == "progress":
        new = sum(deck.new_count for deck in decks)
        learning = sum(deck.learn_count for deck in decks)
        review = sum(deck.review_count for deck in decks)
        return f"""<main class="hub-main"><div class="page-head"><div class="hub-eyebrow">LEARNING INSIGHTS</div>
        <h1>Your progress</h1><p>A clear view of today's workload across all your courses.</p></div>
        <div class="metric-grid"><div class="metric"><span>Courses</span><strong>{len(decks)}</strong></div>
        <div class="metric blue"><span>New</span><strong>{new}</strong></div>
        <div class="metric amber"><span>Learning</span><strong>{learning}</strong></div>
        <div class="metric green"><span>Ready to review</span><strong>{review}</strong></div></div>
        <div class="content-card progress-card"><h2>Today</h2><p>{html.escape(studied_today)}</p>
        <div class="progress-track"><i style="width:{min(100, review + learning)}%"></i></div></div></main>"""
    if route == "settings":
        provider = str(settings.get("provider", "openai"))
        openai_selected = "selected" if provider == "openai" else ""
        compatible_selected = "selected" if provider != "openai" else ""
        configured = (
            "Connected credential saved"
            if settings.get("configured")
            else "API key required"
        )
        notice_html = (
            f'<div class="shell-notice">{html.escape(notice)}</div>' if notice else ""
        )
        return f"""<main class="hub-main"><div class="page-head"><div class="hub-eyebrow">PERSONALIZE</div>
        <h1>Settings</h1><p>Configure AnkiGPT without leaving the new application shell.</p></div>
        {notice_html}<div class="settings-grid"><section class="content-card concept-form"><h2>AI connection</h2><p>{configured}</p>
        <label>Provider<select id="setting-provider"><option value="openai" {openai_selected}>OpenAI</option><option value="openai-compatible" {compatible_selected}>Other / OpenAI-compatible</option></select></label>
        <label>API key<input id="setting-key" type="password" placeholder="Leave blank to keep the saved key" autocomplete="off"></label>
        <label>Model<input id="setting-model" value="{html.escape(str(settings.get("model", "")), quote=True)}"></label>
        <label>Base URL<input id="setting-base-url" value="{html.escape(str(settings.get("base_url", "")), quote=True)}"></label>
        <div class="settings-inline"><label>Timeout (seconds)<input id="setting-timeout" type="number" min="5" max="600" value="{int(settings.get("timeout", 60))}"></label>
        <label>Characters per document<input id="setting-max-chars" type="number" min="10000" max="5000000" step="10000" value="{int(settings.get("max_chars", 150000))}"></label></div>
        <div class="form-actions"><button class="hub-secondary" onclick="pycmd('ankigpt:test-settings')">Test connection</button>
        <button class="hub-primary" onclick="ankigptSaveSettings()">Save settings</button></div></section>
        <section class="content-card"><h2>Study preferences</h2><p>Question types, hints, solutions, and keyboard behavior.</p>
        <div class="setting-row"><span>Adaptive difficulty</span><b>On</b></div><div class="setting-row"><span>Source citations</span><b>On</b></div></section></div>
        <script>function ankigptSaveSettings(){{const p={{provider:document.getElementById('setting-provider').value,key:document.getElementById('setting-key').value,model:document.getElementById('setting-model').value,base_url:document.getElementById('setting-base-url').value,timeout:document.getElementById('setting-timeout').value,max_chars:document.getElementById('setting-max-chars').value}};pycmd('ankigpt:save-settings:'+encodeURIComponent(JSON.stringify(p)));}}</script></main>"""
    if route == "system":
        return """<main class="hub-main"><div class="page-head"><div class="hub-eyebrow">DATA & RELIABILITY</div>
        <h1>Data and synchronization</h1><p>Keep your learning data safe, synchronized, and healthy.</p></div>
        <div class="operation-grid">
        <button class="operation-card" onclick="pycmd('ankigpt:system:sync')"><span>↻</span><strong>Sync now</strong><small>Synchronize collections and media</small></button>
        <button class="operation-card" onclick="pycmd('ankigpt:system:backup')"><span>⬡</span><strong>Create backup</strong><small>Save a local recovery point</small></button>
        <button class="operation-card" onclick="pycmd('ankigpt:system:switch-profile')"><span>♙</span><strong>Switch profile</strong><small>Open another learning space</small></button>
        <button class="operation-card" onclick="pycmd('ankigpt:system:check-db')"><span>✓</span><strong>Check database</strong><small>Verify collection integrity</small></button>
        <button class="operation-card" onclick="pycmd('ankigpt:system:check-media')"><span>▧</span><strong>Check media</strong><small>Find missing or unused files</small></button>
        <button class="operation-card" onclick="pycmd('ankigpt:system:import')"><span>⇩</span><strong>Import collection</strong><small>Bring cards or course packages into this profile</small></button>
        <button class="operation-card" onclick="pycmd('ankigpt:system:export')"><span>⇧</span><strong>Export collection</strong><small>Create a portable deck or collection package</small></button>
        </div></main>"""
    return f"""<main class="hub-main">
    <section class="hub-hero">
      <div>
        <div class="hub-eyebrow">YOUR LEARNING SPACE</div>
        <h1>Good to see you.</h1>
        <p>Turn your course materials into lasting understanding.</p>
        <div class="hero-actions">
          <button class="hub-primary" onclick="pycmd('ankigpt')">Create a New Course</button>
          <button class="hub-secondary" onclick="{continue_action}">Continue Studying</button>
        </div>
      </div>
      <svg class="hub-art" viewBox="0 0 420 190" aria-hidden="true">
        <defs><linearGradient id="sky" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#dcecff"/><stop offset="1" stop-color="#f3f8ff"/></linearGradient></defs>
        <rect width="420" height="190" rx="18" fill="url(#sky)"/>
        <path d="M0 145L90 75l45 42 72-91 93 102 48-48 72 65v45H0z" fill="#a8cff4"/>
        <path d="M75 145l60-71 35 45 39-50 57 76z" fill="#f8fbff" opacity=".9"/>
        <path d="M0 155c80-27 143-12 214-2 76 11 133-28 206-10v47H0z" fill="#9bc69a"/>
        <path d="M0 170c88-18 157 8 234 2 70-6 128-28 186-14v32H0z" fill="#528b68"/>
      </svg>
    </section>
    <section class="hub-section">
      <div class="section-heading">
        <div><div class="hub-eyebrow">COURSES</div><h2>Your decks</h2></div>
        <div class="today">{html.escape(studied_today)}</div>
      </div>
      <div class="deck-card"><table class="hub-table">
        <thead><tr><th>Deck</th><th>New</th><th>Learning</th><th>Review</th><th>Status</th></tr></thead>
        <tbody>{rows}</tbody>
      </table></div>
    </section>
  </main>"""


def _deck_row(deck: Any) -> str:
    due = deck.new_count + deck.learn_count + deck.review_count
    status = f"{due} due" if due else "Up to date"
    status_class = "due" if due else "ready"
    return f"""<tr onclick="pycmd('ankigpt:route:course:{int(deck.deck_id)}')">
      <td><strong>{html.escape(deck.name)}</strong></td>
      <td>{deck.new_count}</td><td>{deck.learn_count}</td><td>{deck.review_count}</td>
      <td><span class="status {status_class}"><i></i>{status}</span></td>
    </tr>"""


_CSS = """
body { background:#eef3f9 !important; color:#14213d; }
center > table { width:100%; max-width:none; }
.ankigpt-hub-cell { padding:0 !important; }
.ankigpt-hub { display:grid; grid-template-columns:210px 1fr; width:min(1180px, calc(100vw - 34px)); min-height:650px; margin:16px auto; background:#fff; border:1px solid #dce3ec; border-radius:16px; overflow:hidden; box-shadow:0 14px 38px rgba(31,54,92,.13); text-align:left; font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
.hub-nav { display:flex; flex-direction:column; gap:7px; padding:25px 16px; background:#f7f9fc; border-right:1px solid #e3e8ef; }
.hub-brand { display:flex; align-items:center; gap:10px; margin:0 7px 22px; font-size:19px; font-weight:750; color:#12265d; }
.hub-mark { display:grid; place-items:center; width:31px; height:31px; border-radius:9px; color:#fff; background:linear-gradient(135deg,#2367e8,#6a8dff); }
.nav-item { display:flex; align-items:center; gap:11px; width:100%; padding:10px 12px; border:0; border-radius:9px; background:transparent; color:#36435c; font-weight:600; text-align:left; cursor:pointer; }
.nav-item:hover { background:#e9eef8; }.nav-item.active { color:#fff; background:#2367e8; box-shadow:0 5px 13px rgba(35,103,232,.24); }.nav-spacer { flex:1; }
.hub-main { padding:30px; min-width:0; }.hub-hero { display:grid; grid-template-columns:1.1fr .9fr; gap:24px; align-items:center; padding:30px; border-radius:15px; background:linear-gradient(120deg,#f8fbff,#edf4ff); overflow:hidden; }
.hub-eyebrow { color:#2367e8; font-size:11px; font-weight:800; letter-spacing:.1em; }.hub-hero h1 { margin:7px 0 4px; font-size:32px; line-height:1.15; color:#10204d; }.hub-hero p { margin:0 0 22px; color:#5e6b82; font-size:15px; }
.hero-actions { display:flex; gap:10px; flex-wrap:wrap; }.hub-primary,.hub-secondary { padding:11px 18px; border-radius:8px; font-weight:700; cursor:pointer; }.hub-primary { color:#fff; background:#2367e8; border:1px solid #2367e8; }.hub-primary:hover { background:#1955c6; }.hub-secondary { color:#24406d; background:#fff; border:1px solid #cfd9e8; }.hub-art { width:100%; max-height:190px; }
.hub-section { margin-top:28px; }.section-heading { display:flex; align-items:end; justify-content:space-between; margin-bottom:11px; }.section-heading h2 { margin:4px 0 0; font-size:22px; color:#15234a; }.today { color:#718096; font-size:12px; }
.deck-card { overflow:hidden; border:1px solid #e0e6ee; border-radius:11px; }.hub-table { width:100%; border-collapse:collapse; }.hub-table th { padding:11px 14px; color:#718096; background:#f7f9fc; font-size:11px; text-transform:uppercase; letter-spacing:.05em; }.hub-table td { padding:13px 14px; border-top:1px solid #edf0f4; }.hub-table tbody tr { cursor:pointer; }.hub-table tbody tr:hover { background:#f4f7ff; }.hub-table th:not(:first-child),.hub-table td:not(:first-child) { text-align:center; }
.status { display:inline-flex; align-items:center; gap:6px; white-space:nowrap; font-size:12px; font-weight:650; }.status i { width:7px; height:7px; border-radius:50%; background:#22a06b; }.status.due i { background:#e69228; }.hub-empty { padding:35px !important; color:#718096; text-align:center !important; }
.page-head { margin:6px 0 24px; }.page-head h1 { margin:7px 0 5px; color:#10204d; font-size:30px; }.page-head p,.content-card p { color:#667085; }.content-card { padding:22px; background:#fff; border:1px solid #e0e6ee; border-radius:12px; box-shadow:0 5px 18px rgba(31,54,92,.05); }.search-shell { padding:12px 14px; margin-bottom:18px; color:#8a94a6; background:#f7f9fc; border:1px solid #e0e6ee; border-radius:9px; }.course-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }.course-tile { display:grid; grid-template-columns:38px 1fr auto; align-items:center; gap:10px; padding:14px; text-align:left; color:#243557; background:#fff; border:1px solid #e1e6ee; border-radius:10px; cursor:pointer; }.course-tile:hover { border-color:#7da3ef; background:#f7f9ff; }.course-tile small { display:block; margin-top:3px; color:#7b879b; }.course-icon { display:grid; place-items:center; width:34px; height:34px; color:#2367e8; background:#eaf0ff; border-radius:9px; }.empty-card { color:#718096; padding:30px; text-align:center; }.metric-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:18px; }.metric { padding:18px; background:#fff; border:1px solid #e0e6ee; border-top:3px solid #8d99ae; border-radius:11px; }.metric.blue{border-top-color:#2367e8}.metric.amber{border-top-color:#e69228}.metric.green{border-top-color:#22a06b}.metric span { display:block; color:#718096; font-size:12px; }.metric strong { display:block; margin-top:7px; color:#17274e; font-size:27px; }.progress-card h2,.settings-grid h2 { margin-top:0; }.progress-track { height:9px; overflow:hidden; margin-top:18px; background:#e9edf3; border-radius:9px; }.progress-track i { display:block; height:100%; background:linear-gradient(90deg,#2367e8,#67a2ff); border-radius:9px; }.settings-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }.setting-row { display:flex; justify-content:space-between; padding:13px 0; border-top:1px solid #edf0f4; }.setting-row b { color:#22a06b; }
.migration-note { display:inline-block; padding:10px 12px; color:#4e5f7d; background:#f2f5fa; border-radius:8px; font-size:12px; }
.text-back { padding:7px 0; color:#3157d5; background:transparent; border:0; font-weight:650; cursor:pointer; }.concept-form { max-width:780px; }.concept-form label { display:block; margin-bottom:17px; color:#34435f; font-size:12px; font-weight:700; }.concept-form label small { color:#8490a4; font-weight:400; }.concept-form input,.concept-form textarea { display:block; box-sizing:border-box; width:100%; margin-top:7px; padding:11px 12px; color:#1e2c48; background:#fbfcfe; border:1px solid #d5dce7; border-radius:8px; font:inherit; font-size:14px; resize:vertical; }.concept-form input:focus,.concept-form textarea:focus { outline:2px solid #b9cbfa; border-color:#5c7fdb; }.form-actions { display:flex; justify-content:flex-end; gap:10px; padding-top:5px; }
.concept-form select { display:block; box-sizing:border-box; width:100%; margin-top:7px; padding:10px 12px; color:#1e2c48; background:#fbfcfe; border:1px solid #d5dce7; border-radius:8px; }.settings-inline { display:grid; grid-template-columns:1fr 1fr; gap:12px; }.shell-notice { margin-bottom:16px; padding:12px 14px; color:#265c42; background:#eaf7ef; border:1px solid #bfe3cd; border-radius:9px; }
.operation-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:13px; }.operation-card { display:grid; grid-template-columns:42px 1fr; grid-template-rows:auto auto; column-gap:13px; padding:18px; color:#263653; background:white; border:1px solid #dfe6ef; border-radius:11px; text-align:left; cursor:pointer; }.operation-card:hover { border-color:#7da3ef; background:#f8faff; }.operation-card>span { grid-row:1/3; display:grid; place-items:center; width:39px; height:39px; color:#2367e8; background:#eaf0ff; border-radius:10px; font-size:19px; }.operation-card strong { font-size:14px; }.operation-card small { margin-top:4px; color:#768399; }
.course-hero { display:flex; align-items:center; justify-content:space-between; gap:24px; margin-bottom:18px; padding:30px; color:#fff; background:linear-gradient(125deg,#173a8f,#3478ee); border-radius:15px; }.course-hero .hub-eyebrow,.course-hero p { color:#dce8ff; }.course-hero h1 { margin:7px 0; font-size:31px; }.course-hero .hub-secondary { color:#173a8f; }.course-total { display:flex; flex-direction:column; align-items:center; min-width:125px; padding:20px; background:rgba(255,255,255,.13); border:1px solid rgba(255,255,255,.24); border-radius:13px; }.course-total strong { font-size:38px; }.course-total span { color:#dce8ff; font-size:12px; }.course-metrics { grid-template-columns:repeat(4,minmax(0,1fr)); }
.page-head-actions { display:flex; align-items:center; justify-content:space-between; gap:20px; }.library-list { display:flex; flex-direction:column; gap:8px; }.library-row { display:flex; align-items:center; justify-content:space-between; width:100%; padding:14px 16px; color:#243557; background:#fff; border:1px solid #e2e7ef; border-radius:9px; text-align:left; cursor:pointer; }.library-row:hover { border-color:#7da3ef; background:#f7f9ff; }.library-row strong { display:block; max-width:670px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.library-row small { display:block; margin-top:4px; color:#7b879b; }
@media(max-width:760px){.ankigpt-hub{grid-template-columns:64px}.hub-nav{padding:20px 9px}.hub-brand{margin:0 auto 18px}.hub-brand:not(.hub-mark),.nav-item span{display:none}.nav-item{justify-content:center}.hub-main{padding:18px}.hub-hero{grid-template-columns:1fr}.hub-art{display:none}.hub-table th:nth-child(3),.hub-table td:nth-child(3){display:none}}
"""
