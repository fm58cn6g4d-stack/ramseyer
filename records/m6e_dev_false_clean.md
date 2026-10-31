# M6e dev set: the 120 CLEAN predictions wrong in substance, classified by hand (2026-10-30)

Source: `scripts/m6_gate.py --set history_dev --dump --law ...` on the 32 laws involved (var/m6e_dev_laws_dump.jsonl). Each case was read against R_after's new notes, and each one first classed as ours was then checked against the enrolled bill text: six of those turned out to be OLRC departing from the literal instruction (#2, #11, #24, #29, #46, #77), one is unclear (#110). The dev set may be inspected; test and sealed are not.

Each case is one law and one Code section (title U.S.C. section); #n is its line in the dump.

| Class | Cases | What changed |
| --- | --- | --- |
| real: instruction for this section not applied (target not parsed) | 5 | "in each of sections A, B(c), and C" takes the title in context (#49, #50); "Such subsection is further amended" (#84); a Code parenthetical with no space before it (#31); an unapplied "each place it appears" strike naming no target keeps sections holding the words from CLEAN (#28) |
| real: quotation marks (apostrophe in a nested quotation, repeated closing marks) | 4 | a plural possessive inside a nested quotation (#3, #16); an unmatched closing mark on any block line dropped, and an inserted em dash takes no space (#89, #113) |
| real: new text lost or misplaced (table, lead-in text, heading) | 3 | a bill table kept as a marker, the instruction WARN (#5); lead-in text before units added at the end (#8); "in the section heading" edits the section's own heading (#34) |
| real: wrong place (sentence named, unit level) | 3 | "The second sentence of ..." heads and "the period at the end of the first sentence" (#26, #68); a unit added at the end of a unit of its own level follows its siblings, WARN (#67) |
| real: the same edit applied twice | 1 | an edit identical to one already applied to the section is CONFLICT (#45) |
| whitespace only (designation spacing, space before punctuation) | 12 | oracle/editorial.py |
| oracle: delayed effective date (OLRC 'Amendment of ...' note) | 36 | pending when R_after has a note headed "Amendment of ..." citing the law (matches exactly these 36) |
| oracle: OLRC text departs from the literal instruction, no note | 13 | none: counted as wrong; proposed as hand labels for Espen (tests/oracle/labels.json is tier 3) |
| oracle: another law's amendment executed in the same window | 10 | not graded ("ungradable") when R_after's amendment notes credit another law that R_before's did not |
| editorial: heading style, case, OLRC-supplied heading or catchline | 9 | oracle/editorial.py |
| editorial: Act reference translated to a Code citation | 8 | oracle/editorial.py |
| editorial: enactment date set in (comma added, or phrase the detector lacks) | 7 | oracle/editorial.py |
| editorial: 'Repealed'/'Omitted'/'Renumbered' placeholder | 3 | oracle/editorial.py |
| editorial: footnote markers or bracketed references | 3 | oracle/editorial.py |
| editorial: executed 'to reflect the probable intent of Congress' (OLRC note) | 2 | oracle/editorial.py |
| unclear: OLRC left a footnoted period our match crossed | 1 | - |

Totals: real 16, whitespace only 12, oracle 59, editorial 32, unclear 1.

## real: instruction for this section not applied (target not parsed) (5)

- #28 114-144 42 U.S.C. 3030s–1
- #31 114-255 21 U.S.C. 355–1
- #49 115-254 49 U.S.C. 46102
- #50 115-254 49 U.S.C. 46105
- #84 116-315 38 U.S.C. 1562

## real: quotation marks (apostrophe in a nested quotation, repeated closing marks) (4)

- #3 113-66 10 U.S.C. 1044e
- #16 113-291 10 U.S.C. 1044e
- #89 116-315 38 U.S.C. 547
- #113 117-263 10 U.S.C. 525

## real: new text lost or misplaced (table, lead-in text, heading) (3)

- #5 113-67 22 U.S.C. 4071e
- #8 113-76 20 U.S.C. 954
- #34 114-255 42 U.S.C. 290bb–41

## real: wrong place (sentence named, unit level) (3)

- #26 114-94 42 U.S.C. 1437a
- #67 116-136 2 U.S.C. 2062
- #68 116-136 39 U.S.C. 3210

## real: the same edit applied twice (1)

- #45 115-254 49 U.S.C. 46111

## whitespace only (designation spacing, space before punctuation) (12)

- #4 113-67 5 U.S.C. 8423
- #10 113-76 5 U.S.C. 3111
- #15 113-255 5 U.S.C. 8477
- #23 114-94 23 U.S.C. 103
- #27 114-94 12 U.S.C. 5110
- #33 114-255 42 U.S.C. 290aa–5
- #39 114-315 38 U.S.C. 7423
- #55 115-271 18 U.S.C. 220
- #71 116-260 49 U.S.C. 60125
- #72 116-260 49 U.S.C. 44735
- #88 116-315 38 U.S.C. 1714
- #119 117-263 14 U.S.C. 4902

## oracle: delayed effective date (OLRC 'Amendment of ...' note) (36)

- #6 113-67 49 U.S.C. 44940
- #7 113-67 41 U.S.C. 4304
- #13 113-255 5 U.S.C. 8438
- #14 113-255 5 U.S.C. 8439
- #25 114-94 49 U.S.C. 30165
- #30 114-198 42 U.S.C. 1395iii
- #36 114-255 42 U.S.C. 1396d
- #37 114-255 42 U.S.C. 1395w–28
- #38 114-287 40 U.S.C. 571
- #40 115-84 5 U.S.C. 8432b
- #41 115-182 38 U.S.C. 1703
- #42 115-182 38 U.S.C. 1712
- #43 115-182 38 U.S.C. 1712A
- #44 115-182 38 U.S.C. 2303
- #47 115-254 15 U.S.C. 4721
- #57 116-113 19 U.S.C. 3602
- #58 116-113 19 U.S.C. 1304
- #59 116-113 19 U.S.C. 4374
- #60 116-113 19 U.S.C. 1677
- #61 116-113 28 U.S.C. 2201
- #62 116-113 28 U.S.C. 2643
- #63 116-136 11 U.S.C. 1182
- #64 116-136 11 U.S.C. 101
- #65 116-136 11 U.S.C. 1325
- #70 116-260 15 U.S.C. 1070
- #81 116-260 20 U.S.C. 1087a
- #82 116-260 20 U.S.C. 1087e
- #83 116-260 11 U.S.C. 507
- #85 116-315 38 U.S.C. 2304
- #86 116-315 38 U.S.C. 2307
- #87 116-315 38 U.S.C. 113
- #90 117-11 21 U.S.C. 321
- #96 117-81 10 U.S.C. 844
- #97 117-81 10 U.S.C. 867
- #103 117-81 5 U.S.C. 7511
- #112 117-263 10 U.S.C. 2861

## oracle: OLRC text departs from the literal instruction, no note (13)

- #2 113-66 10 U.S.C. 1501
- #11 113-76 8 U.S.C. 1101
- #17 113-291 10 U.S.C. 1129a
- #20 114-55 49 U.S.C. 41742
- #22 114-94 23 U.S.C. 120
- #24 114-94 23 U.S.C. 607
- #29 114-153 18 U.S.C. 1839
- #46 115-254 42 U.S.C. 5170a
- #73 116-260 42 U.S.C. 8287a
- #77 116-260 33 U.S.C. 467
- #92 117-81 10 U.S.C. 2714
- #93 117-81 10 U.S.C. 2715
- #115 117-263 10 U.S.C. 4025

## oracle: another law's amendment executed in the same window (10)

- #91 117-81 10 U.S.C. 139
- #94 117-81 10 U.S.C. 2583
- #98 117-81 10 U.S.C. 1746a
- #99 117-81 10 U.S.C. 2380c
- #100 117-81 10 U.S.C. 239c
- #102 117-81 10 U.S.C. 483
- #104 117-81 10 U.S.C. 171a
- #105 117-81 10 U.S.C. 3221
- #106 117-81 10 U.S.C. 4375
- #107 117-81 10 U.S.C. 1734

## editorial: heading style, case, OLRC-supplied heading or catchline (9)

- #0 113-23 16 U.S.C. 823a
- #18 113-291 10 U.S.C. 1407a
- #21 114-70 8 U.S.C. 1201
- #51 115-256 22 U.S.C. 2507c
- #52 115-270 33 U.S.C. 610
- #54 115-271 42 U.S.C. 247b–15
- #69 116-260 15 U.S.C. 1062
- #95 117-81 32 U.S.C. 329
- #117 117-263 33 U.S.C. 701r

## editorial: Act reference translated to a Code citation (8)

- #12 113-235 29 U.S.C. 1132
- #32 114-255 42 U.S.C. 290bb–2
- #35 114-255 42 U.S.C. 290bb–7
- #53 115-271 42 U.S.C. 294i
- #75 116-260 42 U.S.C. 13317
- #79 116-260 42 U.S.C. 300jj
- #111 117-103 15 U.S.C. 77ppp
- #116 117-263 6 U.S.C. 1501

## editorial: enactment date set in (comma added, or phrase the detector lacks) (7)

- #1 113-40 42 U.S.C. 17022
- #48 115-254 6 U.S.C. 941
- #66 116-136 12 U.S.C. 1795f
- #74 116-260 42 U.S.C. 16273
- #78 116-260 42 U.S.C. 294c
- #80 116-260 42 U.S.C. 1395bb
- #118 117-263 43 U.S.C. 390b

## editorial: 'Repealed'/'Omitted'/'Renumbered' placeholder (3)

- #9 113-76 2 U.S.C. 1907
- #108 117-81 22 U.S.C. 2349aa–7
- #109 117-103 42 U.S.C. 300hh–11

## editorial: footnote markers or bracketed references (3)

- #19 113-291 10 U.S.C. 429
- #56 116-7 36 U.S.C. 70907
- #76 116-260 42 U.S.C. 5905

## editorial: executed 'to reflect the probable intent of Congress' (OLRC note) (2)

- #101 117-81 10 U.S.C. 231a
- #114 117-263 37 U.S.C. 402b

## unclear: OLRC left a footnoted period our match crossed (1)

- #110 117-103 34 U.S.C. 21711
## Hand labels proposed (PR #9), after review

After the third dev run, 13 of the remaining false cleans are OLRC's text departing from the enacted law, checked against the enrolled bill (labels in `tests/oracle/labels.json`, tier 3):

| Law | Section | Evidence |
| --- | --- | --- |
| 113-66 | 10 U.S.C. 1501 | § 581(a)(1)–(3) strikes "and" in (B), ends (C) with "; and", adds (D); R_after has (D) but (B) and (C) unchanged |
| 113-291 | 10 U.S.C. 1129a | the new section's number printed "§§ 1129a." |
| 113-291 | 10 U.S.C. 429 | R_after drops a comma OLRC had footnoted "So in original" at R_before, with its footnote; the law does not touch it |
| 114-55 | 49 U.S.C. 41742 | § 107 strikes "and $93,000,000 for fiscal year 2015"; R_after keeps the "and" |
| 114-94 | 23 U.S.C. 120 | OLRC's own note: § 1408(a)(1) inserted "or project delivery" after "or contracting"; R_after's text lacks it |
| 114-94 | 23 U.S.C. 607 | R_before ends "to carry out this chapter" with no period; § 2001(f) substitutes words only; R_after adds a period |
| 115-254 | 42 U.S.C. 5170a | the enrolled § 1206(a)(3) ends par. (5) "compliance; and"; R_after drops "and" |
| 116-260 | 42 U.S.C. 8287a | the law and OLRC's note read "maintenance expenses"; R_after "maintenance expense." |
| 116-260 | 33 U.S.C. 467 | R_after holds cl. (iii) of par. (4)(A) twice |
| 116-260 | 42 U.S.C. 16273 | R_after reads "180 days December 27, 2020,": "after" dropped |
| 117-81 | 10 U.S.C. 2714 | the enrolled § 341(a) ends § 2714 "nonfluorinated carbon atoms." and writes its catchline in sentence case; R_after adds a closing mark and title case |
| 117-81 | 10 U.S.C. 2715 | R_after reads "section:the" |
| 117-263 | 10 U.S.C. 4025 | the enrolled § 844(1)(A) inserts “that—” then “(1) have”; R_after reads "that—”" with a closing mark the text does not have |

Not labelled, on review (session_01UQzgBt7HmNwxNAYBzGkbux):
- 38 U.S.C. 119 (Pub. L. 116-171): the law's own text has the stray "”." and OLRC keeps it ("So in original. The quotation marks and second period probably should not appear", GovInfo 2023). Our rule that drops an unmatched closing mark on a block line removed it: ours. OLRC is not consistent here (it drops such a mark in 38 U.S.C. 547, Pub. L. 116-315 § 7002), so the rule's policy (keep the law's literal marks, or drop them) is an open question for a follow-up.
- 18 U.S.C. 1839 (Pub. L. 114-153): OLRC keeps the law's inner single quotation marks with a "So in original" footnote; our engine sets them as double. Counted as ours.
- 8 U.S.C. 1101 (#11, an OLRC-added ";") is no longer a false clean in the third run (no CLEAN prediction there now), so it needs no label.
