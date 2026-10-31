# M6e: the dev 2 set's false cleans (2026-10-31)

Dev 2 is the former test set (280 laws), opened for inspection by Espen's decision of 2026-10-31. Measured at c9ef141
(after literal marks, the "not yet executed" rule and the reproducibility fixes): **49 of 1,385 CLEAN predictions wrong
in substance (3.54%)**, down from 115 of 1,444 at 5d2d585. Source: `scripts/m6_gate.py --set history_test --dump`
(var/m6e_test_dump.jsonl). Each case was read against R_after, OLRC's new notes and the enrolled text. Case numbers
follow the dump.

## Summary

| Class | Cases | What was done |
| --- | --- | --- |
| Parser | 9 | Fixed, each with a test (below) |
| Engine | 2 | Fixed, each with a test |
| Comparison (an OLRC convention the checker can verify) | 11 | Fixed, each with a test |
| OLRC departs from the law's text, or R_after is garbled | 11 | Not fixed: hand-label candidates for Espen, each to be checked against the enrolled text first |
| OLRC editorial work not yet checkable | 3 | Left counted as wrong; M8a's Act text can settle them |
| Open (not yet explained) | 13 | Left counted as wrong |
| **Total** | **49** | |

Three fixes made on the way are not among the 49: they came from the first look at Pub. L. 116-283 and were in the measured code already (37 U.S.C. 1005, a heading "amended to read" replacing the whole section; 10 U.S.C. 628a and 14502a, a space inside "<term>promotion board </term>"), and one dev case (15 U.S.C. 1062, a supplied heading on a unit the law replaces whole).

## Fixed

| # | Law | Section | Cause | Fix |
| --- | --- | --- | --- | --- |
| 11 | 114-289 | 54 U.S.C. 311103 | "Subsection (b) and subsection (d) of section 311103 ... are amended": read as the whole section | parser: two scopes |
| 14 | 114-328 | 10 U.S.C. 8081 | § 502(oo) read under (z)(3), a table-of-contents edit: after (z) the segmenter expected "(zz)", not "(aa)" | parser: (aa) follows (z) |
| 16 | 114-328 | 10 U.S.C. 1079 | § 1081(c)(6) amends § 1079(a) of the FY2016 NDAA; an "Effective as of ..., and as if included therein as enacted," clause hid the Act, so title 10 was taken from context | parser |
| 18 | 114-328 | 5 U.S.C. 5524a | "The heading of such section is amended" had no target | parser |
| 26 | 116-158 | 50 U.S.C. 3955 | "Paragraph (2) of such subsection is amended" had no target | parser |
| 43 | 117-151 | 11 U.S.C. 1182 | a two-year sunset ("Effective on the date that is 2 years after ...—") executed at once | parser: such lead-ins delay their items |
| 47 | 119-21 | 16 U.S.C. 3841 | "clauses (i) through (v)" read as the letters i to v: only (i) and (v) replaced | parser: a roman range |
| 48 | 119-37 | 38 U.S.C. 3737 | "Section (d)(1) of such section is amending by inserting": dropped | parser: applied by intent, WARN with the slip named |
| 8 | 114-92 | 10 U.S.C. 130h | quoted words in a header lost their marks | parser (text rendering) |
| 17 | 114-328 | 10 U.S.C. 2228 | "through the period" stopped at "122 Stat." | engine |
| 20 | 114-328 | 10 U.S.C. 930 | OLRC's "Transfer and Amendment of Section" note (effective on a date the President sets) was not read as a delayed amendment | comparison: pending |
| 28 | 116-189 | 36 U.S.C. 220506 | inserting “‘Parapan American’,” lost its marks and comma (read as a quoted block) | engine |
| 4 | 113-121 | 33 U.S.C. 2263 | "the date of enactment of this clause": "clause" missing from the date rule | comparison |
| 7, 15, 25 | 114-92, 114-328, 116-94 | 10 U.S.C. 652, 5 U.S.C. 7511, 23 U.S.C. 125 | a "Repealed" placeholder in square brackets | comparison |
| 10, 34 | 114-190, 117-7 | 5 U.S.C. 8415, 2 U.S.C. 901a | "7⁄10" for "7/10", "½" for "1/2" | comparison: fractions are their digits |
| 3, 21, 22, 39 | 113-79, 115-123, 115-407, 117-58 | 7 U.S.C. 3195, 4 U.S.C. 7, 38 U.S.C. 2021, 49 U.S.C. 119 | an Act reference set in the Code citation the law itself prints ("section 8(o)(19) of the ... Act of 1937 (42 U.S.C. 1437f(o)(19))" → "section 1437f(o)(19) of title 42") | comparison: accepted only for the law's own citation |

## Not fixed

**OLRC departs from the law's text, or R_after is garbled (hand-label candidates, to be checked one by one):**
- #1 7 U.S.C. 7284: the law's "(7 U.S.C. 8702 et seq.)" printed as "[7 U.S.C. 8701 et seq.]".
- #19 54 U.S.C. 308704: paragraph (a)(2) "Applicability" gone at R_after; Pub. L. 114-328 § 3507 does not strike it and the note does not mention it.
- #23 33 U.S.C. 4001a: "1998,1" (a footnote after a comma).
- #27 23 U.S.C. 403: "$26,560,000’" (a stray mark at R_after).
- #29 38 U.S.C. 1720J: "requiremen.ts".
- #32 5 U.S.C. 2302: "orI13(B)".
- #35, #41 18 U.S.C. 3014: "2021.12\" (two laws, the same garbled text).
- #37 49 U.S.C. 6701: "“Secretary”’".
- #38 49 U.S.C. 22406: "appropriations.1".
- #49 42 U.S.C. 247b-13: "such $4,250,000" (the struck "such" left in).
- (dev) 38 U.S.C. 547: OLRC drops the law's stray closing mark (literal marks, Espen 2026-10-31).

**OLRC editorial work not yet checkable:**
- #2 16 U.S.C. 2003: "and tribal" inserted "each place it appears" in subsection (b); OLRC also inserted it in the subsection's heading, which is almost certainly OLRC's own (title 16 is not positive law). Whether the Act has that heading is a question for M8a's Act text.
- #12, #13 33 U.S.C. 1383, 2908: OLRC dropped "of this section" after an internal reference. Counted once here as one convention to confirm.

**Open:**
- #24 38 U.S.C. 3683 (not yet examined beyond its first difference, a space after a heading's dash).
- #5 21 U.S.C. 822 ("(e)(1)" set as subsection (e) with a paragraph heading), #6 16 U.S.C. 1826b (two Act sections with one Code parenthetical), #9 20 U.S.C. 6332 ("sections 1124 and 1124A" without the Act named), #36 23 U.S.C. 164 (two divisions amend the same text; order of execution), #40 42 U.S.C. 6325 ("the first proviso of the matter under the heading ..."), #42 11 U.S.C. 101, #44–#46 42 U.S.C. 1395w-116, 1395w-132 and 7 U.S.C. 2012 (an Act's own section numbers inside the Code, and R_after's run-together headings).
- 116-283's remaining (#30, #31, #33): 10 U.S.C. 146 (OLRC keeps the law's ‘Office’ single), 10 U.S.C. 9084 (an empty section at R_after), 14 U.S.C. 561 (a detached footnote marker).

The next measurement (tuning, dev and dev 2 at the fixed code) is recorded in `records/milestones.md`.
