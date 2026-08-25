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
ankigpt-truncated-files = Only the first { $limit } characters of these documents were used (change the limit in Preferences > Third Party Services):
    { $files }
