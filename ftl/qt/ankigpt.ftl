### AnkiGPT: LLM-generated questions over scheduled concepts.

## Menus
ankigpt-menu = AnkiGPT
ankigpt-menu-create-deck = Create Concept Deck from Documents...
ankigpt-menu-deck-settings = Concept Deck Settings...

## Create concept deck dialog
ankigpt-create-deck-title = Create AI Course
ankigpt-step-materials = STEP 1 OF 3  ·  MATERIALS & GOALS
ankigpt-create-course = Create your course
ankigpt-create-course-subtitle = Choose the material and tell AnkiGPT what matters. Clear guidance produces more relevant concepts and questions.
ankigpt-course-details = Course Goals
ankigpt-step-concepts = STEP 2 OF 3  ·  REVIEW CONCEPTS
ankigpt-review-concepts = Review what the AI found
ankigpt-review-concepts-subtitle = Keep only useful, on-target concepts. You can edit titles, summaries, and key points before creating the course.
ankigpt-documents = Documents
ankigpt-study-materials = Study Materials
ankigpt-study-materials-intro = Add course files, a folder, or a web URL. Folders are searched recursively, including locally synchronized OneDrive folders. You can also drag files or folders here.
ankigpt-book-source = This source is a book
ankigpt-book-source-tooltip = Detect chapters and sections, review the structure, and create a separate deck for each selected unit.
ankigpt-nonbook-organization = Multiple sources
ankigpt-nonbook-combined = One combined deck
ankigpt-nonbook-per-document = One deck per document
ankigpt-drop-sources = Drop files or folders here
ankigpt-add-files = Add Files...
ankigpt-add-folder = Add Folder...
ankigpt-add-url = Add URL...
ankigpt-add-url-tooltip = If the expected webpage content is missing or blocked, print the page to PDF in your browser and add the PDF with Add Files.
ankigpt-source-url = Web page or document URL
ankigpt-url-failed = Could not add URL: { $error }
ankigpt-remove-file = Remove
ankigpt-clear-files = Clear
ankigpt-no-study-materials = No study materials selected yet.
ankigpt-study-material-summary =
    { $count ->
        [one] { $count } document selected ({ $size })
       *[other] { $count } documents selected ({ $size })
    }
ankigpt-sources-skipped = Skipped { $unsupported } unsupported and { $missing } missing files.
ankigpt-deck-name = Course or category
ankigpt-subcategory = Subcategory
ankigpt-subcategory-placeholder = Required, e.g. Cars or Week 1
ankigpt-book-title-placeholder = Book title (automatically suggested from the source)
ankigpt-subject = Learning subject
ankigpt-subject-placeholder = e.g. Engineering Statics
ankigpt-learning-level = Learning level
ankigpt-level-introductory = Introductory
ankigpt-level-intermediate = Intermediate
ankigpt-level-advanced = Advanced
ankigpt-focus-topics = Focus topics
ankigpt-focus-placeholder = e.g. moments, equilibrium, free-body diagrams
ankigpt-exclusions = Exclude or de-emphasize
ankigpt-exclusions-placeholder = e.g. syllabus dates, biographies, optional appendices
ankigpt-question-style = Question style
ankigpt-style-balanced = Balanced understanding
ankigpt-style-core-knowledge = Core knowledge and definitions
ankigpt-style-applied = Applied problems
ankigpt-style-exam = Exam preparation
ankigpt-additional-guidance = Additional guidance
ankigpt-additional-guidance-placeholder = Anything else the AI should know about this course or your goals
ankigpt-instructions = Instructions
ankigpt-instructions-placeholder = Describe the course or what to focus on, e.g. "Intro to Microeconomics, weeks 1-6. Focus on definitions and the causal mechanisms behind each model."
ankigpt-target-count = Number of concepts
ankigpt-book-deck-granularity = Create decks
ankigpt-book-choose-granularity = Select chapter or section decks...
ankigpt-book-per-chapter = One per chapter
ankigpt-book-per-section = One per section within each chapter
ankigpt-book-choose-granularity-warning = Choose whether to create one deck per chapter or one deck per section.
ankigpt-book-concept-count = Concepts per deck
ankigpt-book-count-automatic = Automatic — based on chapter or section size
ankigpt-book-count-fixed = Fixed — use Number of concepts
ankigpt-grading-mode = Grading mode
ankigpt-mode-self = Self-grade
ankigpt-mode-typed = Typed answer, graded by AI
ankigpt-mode-mcq = Multiple choice
ankigpt-mode-true-false = True or False
ankigpt-mode-fill-blank = Fill in the blank
ankigpt-mode-mix = Random mix
ankigpt-study-modes = Study modes
ankigpt-choose-study-mode = Select at least one study mode.
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
ankigpt-no-deck-name = Please enter a course or category name.
ankigpt-no-subcategory = Please enter a subcategory name.
ankigpt-no-book-title = Please enter or confirm the book title.
ankigpt-nothing-selected = Select at least one concept.
ankigpt-no-concepts-found = No concepts could be extracted from these documents.
ankigpt-extraction-failed = Concept extraction failed: { $error }
ankigpt-unsupported-file = Unsupported file type: { $name }
ankigpt-column-title = Title
ankigpt-column-deck = Destination deck
ankigpt-column-summary = Summary
ankigpt-column-key-points = Key points
ankigpt-file-filter = Documents (*.pdf *.txt *.md *.docx)

## Book structure review
ankigpt-step-book-structure = STEP 2 OF 4  ·  BOOK STRUCTURE
ankigpt-review-book-structure = Review chapters and sections
ankigpt-review-book-structure-subtitle = Rename detected entries, uncheck material to exclude it, or merge and split entries before concept generation.
ankigpt-book-structure-title = Chapter or section
ankigpt-book-structure-size = Characters
ankigpt-book-structure-concepts = Automatic concepts
ankigpt-book-structure-confidence = Confidence
ankigpt-book-structure-preview = Beginning: { $beginning }
    Ending: { $ending }
ankigpt-book-structure-fallback = AI outline classification was unavailable, so locally detected headings are shown for review.
ankigpt-book-merge = Merge Selected
ankigpt-book-split = Split Selected
ankigpt-book-merge-selection = Select two or more adjacent chapters or sections at the same level.
ankigpt-book-split-selection = Select one chapter or section without children that contains enough text to split.
ankigpt-book-one-source = Book generation accepts exactly one source.
ankigpt-book-no-structure = No usable chapter or section structure was found.
ankigpt-book-nothing-selected = Include at least one chapter or section.
ankigpt-book-extracting-unit = Generating { $name } ({ $current } of { $total })...
ankigpt-book-active-unit = { $name } ({ $current } of { $total })
ankigpt-book-retrying-unit = No concepts returned for { $name }; retrying with focused book-unit guidance...
ankigpt-units-without-concepts = { $count } selected units returned no concepts and will be omitted:
    { $names }
ankigpt-created-book-decks = Created { $count } decks containing { $concepts } concepts.
ankigpt-created-document-decks = Created { $count } document decks containing { $concepts } concepts.
ankigpt-document-extracting-unit = Generating from { $name } ({ $current } of { $total })...
ankigpt-untitled-document = Untitled document

## Preferences
ankigpt-preferences-group = Connect Your AI
ankigpt-provider = AI service
ankigpt-api-key = API key
ankigpt-api-key-saved = Saved securely. Enter a new key to replace it.
ankigpt-show-key = Show
ankigpt-remove-key = Remove
ankigpt-api-key-removed = Saved API key removed.
ankigpt-api-key-help = How do I get this?
ankigpt-test-connection = Test Connection
ankigpt-testing-connection = Testing connection...
ankigpt-connection-failed-title = Connection failed
ankigpt-api-key-stored-securely = API key saved in your operating system's secure credential store.
ankigpt-secure-storage-failed = The API key was not saved because secure credential storage is unavailable: { $error }. You can set OPENAI_API_KEY in your environment instead.
ankigpt-advanced = Advanced
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
ankigpt-check-answer = Check Answer

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
ankigpt-source-viewer-subtitle = See the exact course material behind this question. Referenced passages are highlighted for transparency.
ankigpt-source-documents = COURSE SOURCES
ankigpt-open-original = Open Original File
ankigpt-next-highlight = Next Highlight
ankigpt-original-missing = The original file is no longer at its recorded location.
ankigpt-no-sources = No source documents are stored for this deck. Documents are kept when a concept deck is created from files.
ankigpt-source-info = { $chars } characters, { $sections } sections{ $pages }
ankigpt-open-in-source = Open in source
ankigpt-passages-title = Passages retrieved from your documents for this question (starred = used by the AI)
ankigpt-deep-lookup = Let the AI read more of the source documents for well-known concepts (one extra request)
ankigpt-deep-lookup-tooltip = For concepts at "solid" mastery or above, the AI may pull in up to two more sections of your documents before writing an applied or transfer question.
