### AnkiGPT: LLM-generated questions over scheduled concepts.

## Menus
ankigpt-menu = AnkiGPT
ankigpt-menu-create-deck = Create Concept Deck from Documents...
ankigpt-menu-deck-settings = Concept Deck Settings...

## Create concept deck dialog
ankigpt-create-deck-title = Create Concept Deck
ankigpt-documents = Documents
ankigpt-add-files = Add Files...
ankigpt-remove-file = Remove
ankigpt-deck-name = Deck
ankigpt-instructions = Instructions
ankigpt-instructions-placeholder = Describe the course or what to focus on, e.g. "Intro to Microeconomics, weeks 1-6. Focus on definitions and the causal mechanisms behind each model."
ankigpt-target-count = Number of concepts
ankigpt-grading-mode = Grading mode
ankigpt-mode-self = Self-grade
ankigpt-mode-typed = Typed answer, graded by AI
ankigpt-mode-mcq = Multiple choice
ankigpt-mode-mix = Random mix
ankigpt-extract = Extract Concepts
ankigpt-extracting = Extracting concepts...
ankigpt-extracting-chunk = Extracting concepts ({ $current } of { $total })...
ankigpt-merging = Merging and ranking concepts...
ankigpt-reading-files = Reading documents...
ankigpt-back = Back
ankigpt-create-notes =
    { $count ->
        [one] Create { $count } Note
       *[other] Create { $count } Notes
    }
ankigpt-created-notes =
    { $count ->
        [one] { $count } concept added to "{ $deck }".
       *[other] { $count } concepts added to "{ $deck }".
    }
ankigpt-no-files = Please add at least one document.
ankigpt-no-deck-name = Please enter a deck name.
ankigpt-nothing-selected = Select at least one concept.
ankigpt-no-concepts-found = No concepts could be extracted from these documents.
ankigpt-extraction-failed = Concept extraction failed: { $error }
ankigpt-unsupported-file = Unsupported file type: { $name }
ankigpt-column-title = Title
ankigpt-column-summary = Summary
ankigpt-column-key-points = Key points
ankigpt-file-filter = Documents (*.pdf *.txt *.md *.docx)

## Preferences
ankigpt-preferences-group = AnkiGPT (OpenAI-compatible API)
ankigpt-api-key = API key
ankigpt-base-url = Base URL
ankigpt-model = Model
ankigpt-timeout = Timeout (seconds)
ankigpt-no-api-key = No AnkiGPT API key is configured. Add one in Preferences > Third Party Services.

## Deck settings
ankigpt-deck-settings-title = Concept Deck Settings: { $deck }
ankigpt-deck-context = Context given to the AI when generating questions
ankigpt-auto-submit = Automatically submit the AI's suggested grade
ankigpt-auto-submit-delay = Auto-submit delay (seconds)
ankigpt-not-concept-deck = This deck has no AnkiGPT concept notes. Create one with Tools > AnkiGPT.

## Review
ankigpt-generating = Generating question...
ankigpt-grading = Grading your answer...
ankigpt-generation-failed = AnkiGPT could not generate a question: { $error }
ankigpt-grading-failed = AnkiGPT could not grade the answer: { $error }
ankigpt-suggested-grade = Suggested grade
ankigpt-your-answer = Your answer
ankigpt-model-answer = Model answer
ankigpt-key-points = Key points
ankigpt-missed-points = What was missing
ankigpt-no-answer-given = No answer was given.
ankigpt-correct = Correct
ankigpt-incorrect = Incorrect
ankigpt-score = Score: { $score }/100
ankigpt-type-answer-hint = Type your answer, then press Enter (Shift+Enter for a new line).

## Limits
ankigpt-max-chars = Max characters read per document
ankigpt-max-chars-tooltip = Hard cap on how much of each document is sent to the AI (roughly 4 characters per token). Text beyond this is ignored.
ankigpt-sampled-files = Large documents were read selectively to stay within { $limit } characters each (change in Preferences > Third Party Services):
    { $files }
ankigpt-sampled-file = { $name }: read { $read } of { $sections } sections ({ $percent }% of { $total } characters)
ankigpt-planning = Planning what to read ({ $current } of { $total } documents)...
ankigpt-gap-check = Checking for skipped sections...

## Prominence
ankigpt-create-deck-button = AI Concept Deck
ankigpt-concept-settings-button = Concept Settings
ankigpt-overview-badge = AI concept deck: questions are generated for each concept when it comes up
ankigpt-generated-question = AI-generated question
ankigpt-mastery-label = mastery: { $level }

## Extraction progress
ankigpt-progress-title = Extracting concepts
ankigpt-progress-reading = Reading documents
ankigpt-progress-planning = Planning what to read
ankigpt-progress-extracting = Extracting concepts
ankigpt-progress-gap = Checking for skipped sections
ankigpt-progress-merging = Merging and ranking
ankigpt-progress-done = Done
ankigpt-progress-cancelled = Cancelled
ankigpt-progress-failed = Failed
ankigpt-progress-candidates = { $count } candidate concepts found so far
ankigpt-progress-elapsed = Elapsed: { $seconds }s
ankigpt-cancel = Cancel
ankigpt-continue = Continue

## Source concept, badges, help
ankigpt-concept-label = Concept: { $title }
ankigpt-from-your-notes = From your notes: { $title }
ankigpt-deck-badge = AI
ankigpt-menu-help = AnkiGPT Guide...
ankigpt-help-title = AnkiGPT Guide

## Sources
ankigpt-sources-button = Sources
ankigpt-sources-title = AnkiGPT Sources
ankigpt-open-original = Open Original File
ankigpt-next-highlight = Next Highlight
ankigpt-original-missing = The original file is no longer at its recorded location.
ankigpt-no-sources = No source documents are stored for this deck. Documents are kept when a concept deck is created from files.
ankigpt-source-info = { $chars } characters, { $sections } sections{ $pages }
ankigpt-open-in-source = Open in source
ankigpt-passages-title = Passages retrieved from your documents for this question (starred = used by the AI)
ankigpt-deep-lookup = Let the AI read more of the source documents for well-known concepts (one extra request)
ankigpt-deep-lookup-tooltip = For concepts at "solid" mastery or above, the AI may pull in up to two more sections of your documents before writing an applied or transfer question.
