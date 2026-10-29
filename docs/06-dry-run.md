# 5 Dry-run engine

The engine applies every instruction to a working copy of the real section text, in bill order, and reports for each one whether it worked cleanly and, if not, exactly why. It is deterministic and never edits the stored statute.

## Semantics

- One working copy per target section: an ordered tree of units addressed by path, such as (a)(2)(B)
- Instructions apply in bill order and statefully, so a later instruction sees earlier edits to the same section
- The same input and release point always give the same output

## Rules by operation

| Op | Rule | Typical failure |
| --- | --- | --- |
| STRIKE\_INSERT, STRIKE | Find the quoted text within scope: exact, then quote and whitespace normalized, then case-insensitive. Fuzzy hits are reported, never applied | Text not found; found more than once without each |
| INSERT\_AFTER, INSERT\_BEFORE | The anchor text must be unique within scope | Anchor missing or ambiguous |
| ADD\_END | Append to the unit and check the previous item's trailing punctuation or conjunction | Dangling and or or, wrong terminal punctuation (warning) |
| ADD\_UNIT\_AFTER, REPLACE\_UNIT | Check label collisions and ordering | Label already exists |
| REDESIGNATE | Apply the label map, then use the refs table to find references to old labels in the same section and across the Code | Broken references |
| REPEAL, strike unit | Check inbound references | Orphaned citations |
| AMEND\_HEADING, CONFORM\_TOC | Heading and table-of-sections text must match | Heading mismatch |
| STRIKE\_THROUGH | Both endpoints found, in order | End before start |

## Result statuses

| Status | Meaning |
| --- | --- |
| CLEAN | Applied exactly as drafted |
| WARN | Applied, with an advisory such as punctuation or a conjunction |
| AMBIGUOUS | More than one possible match, or only a fuzzy match |
| NOT\_FOUND | Quoted text is absent from the target |
| TARGET\_MISSING | Target is repealed, omitted, transferred or unknown |
| STALE\_BASELINE | The quoted text matches a prior release point but not the current one, so the draft was written against older law |
| CONFLICT | Two instructions touch the same span |
| UNPARSED | Carried over from the parser |

STALE\_BASELINE is likely the check committee staff will value most. It needs the stored prior release points from tab 1.

## Output per instruction

Status, before span, after span, match count, 200 characters of surrounding evidence, release point, and the instruction's source span.

## Performance and tests

- Batch by section and cache section trees
- Property tests: applying and then reversing an edit reproduces the original; mutating a quote produces NOT\_FOUND
- The oracle test in tab 11 is the main acceptance gate

## Failure categories and the Act-text cross-check (added Oct 29, 2026)

Every non-CLEAN result also says why the amendment could not be carried out, and each instruction is checked against the Act's own text as well as the Code.

**Four reasons (M6d).** These are the House Comparative Print Suite's notification categories:

1. an error in drafting (typo, wrong citation);
2. an error in the current-law data;
3. an error in the system (an unsupported instruction);
4. the amendment has already been executed into current law.

The fourth is new to ramseyer. Today a struck text that is gone, with the inserted text already present, is reported NOT\_FOUND. Add an ALREADY\_EXECUTED status and test it on oracle laws whose before release point already carries the change.

**Act text in Code notes (M6e).** 583 of about 3,400 tuning instructions (17%) amend Act text quoted in a note (363) or uncodified text (220), and are NOT\_EXECUTED today. Dry-run the 363 note cases against the note's quoted text and grade them against the next release's note. M8a covers uncodified Acts that have a compilation.

**GPO as a second reader (M6e).** For enacted laws, GPO's USLM tags each amending verb (`amendingAction`) and each Code citation (`ref`). Compare that reading with ramseyer's parse instruction by instruction; a disagreement lowers CLEAN to WARN. The tagging is verb-level only and has known errors, so it is a witness, not an answer key.

**Act and Code cross-check (M8a).** Run each instruction against both sources and compare where it lands:

| Quote found in the Act | Quote found in the Code | Reading |
| --- | --- | --- |
| Yes, same effect | Yes, same effect | Strongest result ramseyer can give |
| Yes | No | OLRC's editorial form differs from the Act; report both |
| No | No | Drafting error or a stale draft |
| No | Yes | Compilation out of date or the draft targets Code form; report with both currency dates |
