# 3 Draft parser

The parser turns a draft into a list of typed instructions (the IR) using a small grammar, and anything it cannot match is carried forward as UNPARSED rather than dropped. It is the hardest component because unpublished drafts arrive as Word files with inconsistent formatting.

## Stages

1. **Ingest.** .docx through python-docx, keeping style, indent level, numbering label and run formatting per paragraph; also .txt, .md, pasted text and published bill XML (which skips the grammar). Tracked changes: accept all by default, with a flag to reject all or to report them.
2. **Normalize.** Straight and curly quotes, the double-grave and double-apostrophe quote convention, en and em dashes, section symbols, non-breaking spaces and U.S.C. variants. Keep an offset map back to the original text.
3. **Segment.** Detect Division, Title, Subtitle, Chapter and SEC. headings; enumerators (a), (1), (A), (i), (I); and quoted blocks by indent and opening quote. Build a tree.
4. **Classify** each node as AMENDATORY, FREESTANDING, STRUCTURAL or TABLE-OF-CONTENTS.
5. **Parse** amendatory nodes with the grammar below, keeping a scope stack so that (1) in subsection (a)— (A) by striking... inherits its targets.
6. **Emit** IR JSON, with every source span accounted for.

## Grammar (start with these 15, add only by the promotion rule in tab 9)

| ID | Shape (capitals are placeholders) | IR op |
| --- | --- | --- |
| P1 | Section N of title T, United States Code, is amended— | OPEN\_SCOPE |
| P2 | by striking 'A' and inserting 'B' | STRIKE\_INSERT |
| P3 | by striking 'A' | STRIKE |
| P4 | by inserting 'B' after (or before) 'A' | INSERT\_AFTER, INSERT\_BEFORE |
| P5 | by adding at the end the following: | ADD\_END |
| P6 | by inserting after subsection (c) the following: | ADD\_UNIT\_AFTER |
| P7 | by striking subsection (b) and inserting the following: | REPLACE\_UNIT |
| P8 | by redesignating paragraphs (2) through (5) as (3) through (6) | REDESIGNATE |
| P9 | Section N is repealed | REPEAL |
| P10 | The heading for section N is amended... | AMEND\_HEADING |
| P11 | The table of sections for chapter C is amended... | CONFORM\_TOC |
| P12 | each place it appears; in each of subsections (a) and (b) | modifier: occurrence or multi-scope |
| P13 | by striking 'A' and all that follows through 'B' | STRIKE\_THROUGH |
| P14 | Section N of the NAMED ACT (Public Law X) is amended— | OPEN\_SCOPE, kind act |
| P15 | Short title, definitions, authorizations, effective dates, rules of construction, sunsets | FREESTANDING, typed |

Each pattern ships with at least five positive and three negative examples taken from enacted law text, stored in tests/parse/patterns/.

## IR schema (pydantic)

| Field | Meaning |
| --- | --- |
| id | Stable id, e.g. sec2.a.1.A |
| bill\_loc | Path of the bill section and subsection |
| source\_text and span | Exact original text and character offsets |
| target | kind (usc, act, cfr, unknown), cite\_raw, cite\_norm, scope path |
| op | One of the ops above, plus UNPARSED |
| find, replace, new\_text | Quoted strings exactly as drafted, after normalization |
| occurrence | first, each or nth |
| confidence | 0 to 1; below the threshold the item goes to the fallback queue |
| shape\_hash | Hash of the instruction with quotes and cites replaced by placeholders; powers pattern promotion |
| flags and reason | Why something is UNPARSED or low confidence |

## Word-specific hazards

Manual numbering typed as text, smart quotes, tracked changes and comments, footnotes, tables inside quoted text, and soft line breaks that split an instruction in two. Each gets a named test file.

## Done when

On the oracle corpus the number of instructions in the source equals the number in the IR plus the number of UNPARSED items, and deterministic coverage is measured and logged.
