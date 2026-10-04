# Selecting book chapters and PDF pages

When creating a course from a book, enable **Book source**. On the book
structure review screen, choose **Chapter numbers**, enter a range such as
`10-18` or `3, 7-9`, then select **Apply range**. Review the checked chapters
before continuing. The application stops if any requested chapter number is
missing; it never silently substitutes earlier chapters.

If chapter detection is incomplete, choose **PDF page positions** and enter
the pages to extract. These are the PDF's 1-based page positions, not the
page numbers printed on the pages. Applying the range displays the selected
page groups in the review tree. Clear the range and apply it to restore the
chapter list.

Selection happens before concept extraction and before the reading budget
is applied. In chapter mode, each selected chapter has its own configured
reading budget (150,000 characters by default). In section mode, each
selected section has its own budget. In page mode, each contiguous page
range has one budget. Earlier and unselected pages are excluded from the
text and outline used for concept extraction.

**Focus Topics** and **Additional Guidance** guide concept generation within
the selected source; they do not replace the range selector. A selected unit
larger than its reading budget may still be sampled. Review coverage and any
empty-unit notifications after extraction.
