# Changelog

## 26.08.5

- Added saving generated study decks to PDF, HTML, AnkiWeb import text, or Quizlet import text, including concepts in subdecks and the selected study modes.
- Added percentage and completed-card progress during question generation for saved decks.
- Added chapter-number and PDF page-range selection before concept extraction, with reading budgets applied only to the selected units.
- Fixed chapter-heading recognition and removed the first-500-heading detection cutoff. Long books are classified in batches, and omitted headings or failed later batches no longer silently discard the remaining chapters.
- Replaced Focus Session native dropdowns with stable in-page menus and added custom goals of 1–100 cards and timers of 0–120 minutes (0 is untimed).
- Added a compact AI account-credit indicator. OpenRouter account balances are displayed when permissions allow; OpenAI accounts provide a billing link because no supported prepaid-balance endpoint is documented.

## 26.08.4

- Fixed Windows PowerShell aborting on an expected missing release instead of creating it before uploading the MSI.
- Fixed update checks using the original fork's release feed instead of `mando1967/ankigpt`, and added support for `ankigpt-v` version tags. Previously installed versions require a manual MSI update to receive this fix.
- Aligned CI and local MSI asset names so uploading the same version replaces its asset instead of creating a second differently named installer.
- Fixed local MSI uploads attaching new versions to an older release. The uploader now selects the installer matching `.version`, uses its own `ankigpt-v` release tag, and creates missing releases with version-specific changelog notes and a pushed source commit.

## 26.08.3

- Added a bundled beginner-friendly How To guide with annotated screenshots, accessible from a built-in bookmark and shown when the browser first opens in a profile session.
- Added the Khan Academy bookmark, protected built-in bookmarks from deletion, and required confirmation before deleting user bookmarks.
- Made bookmark selection load the page immediately.
- Blocked automatic popup windows while preserving user-initiated links to new tabs.
- Added filtering for known ad services and common in-page banners and overlays, with a remembered per-site option to allow ads.
- Fixed Windows build configuration failing on inaccessible generated Python caches such as `qt/.pytest_cache`; the source scanner now skips these directories.

## 26.08.2

### Study and course creation

- Added hierarchical course generation with category, subcategory, and deck organization, including book chapter and section review.
- Added web URL sources and scoped concept generation.
- Added mixed study sessions combining typed answers, multiple-choice, true-or-false, and fill-in-the-blank questions.
- Improved deck selection, accordion navigation, answer layout, and grouped concept/card browsing.
- Added focus sessions with card goals, timers, breaks, and session recaps.
- Added local background audio, generated white/pink/brown noise, and browser tabs with study bookmarks.

### Fixes and developer tools

- Fixed AI inquiry and visual-generation result fields conflicting with Qt's dialog result method.
- Corrected translation argument types and background progress callbacks during course generation.
- Improved Windows installer upload options and PowerShell argument handling.
- Added curl upload progress, transfer speed, connection timings, and confirmation of the uploaded asset size.
- Updated regression tests, screenshots, the Study Hub guide, profile storage/backup guidance, and Windows test-environment documentation.

The Windows MSI includes the latest application updates. The release source archives include the current application source, fixes, and upload tooling.
