# M6e dev set: the 120 CLEAN predictions wrong in substance, classified by hand (2026-10-30)

Source: `scripts/m6_gate.py --set history_dev --dump --law ...` on the 32 laws involved (var/m6e_dev_laws_dump.jsonl), read case by case against R_after's new notes and, where a heading or wording was in doubt, the enrolled bill. The dev set may be inspected; test and sealed are not.

Each case is one law and one Code section (title U.S.C. section).

| Class | Cases |
| --- | --- |
| real: wrong occurrence or position (and, period, sentence, placement) | 6 |
| real: quotation marks (nested quotes, closing quote kept) | 5 |
| real: new text lost or misplaced (table row, chapeau, clause, heading target, ';') | 5 |
| real: instruction for this section not applied (resolver/attribution) | 4 |
| real: 'wherever appearing' not fanned out, or applied twice | 2 |
| real: CLEAN though matched across a footnote marker | 1 |
| whitespace only (designation spacing, space before punctuation) | 12 |
| oracle: delayed effective date (OLRC 'Amendment of ...' note) | 36 |
| oracle: another law's amendment executed in the same window | 10 |
| editorial: heading style, case, OLRC-supplied heading or catchline | 9 |
| editorial: Act reference translated to a Code citation | 8 |
| editorial: enactment date set in (comma added, or phrase the detector lacks) | 7 |
| oracle: OLRC text departs from the literal instruction, no note | 7 |
| editorial: 'Repealed'/'Omitted'/'Renumbered' placeholder | 3 |
| editorial: footnote markers or bracketed references | 3 |
| editorial: executed 'to reflect the probable intent of Congress' (OLRC note) | 2 |

## real: wrong occurrence or position (and, period, sentence, placement) (6)

- 113-66 10 U.S.C. 1501
- 114-94 23 U.S.C. 607
- 114-94 42 U.S.C. 1437a
- 115-254 42 U.S.C. 5170a
- 116-136 2 U.S.C. 2062
- 116-136 39 U.S.C. 3210

## real: quotation marks (nested quotes, closing quote kept) (5)

- 113-66 10 U.S.C. 1044e
- 113-291 10 U.S.C. 1044e
- 114-153 18 U.S.C. 1839
- 116-315 38 U.S.C. 547
- 117-263 10 U.S.C. 525

## real: new text lost or misplaced (table row, chapeau, clause, heading target, ';') (5)

- 113-67 22 U.S.C. 4071e
- 113-76 20 U.S.C. 954
- 113-76 8 U.S.C. 1101
- 114-255 42 U.S.C. 290bb–41
- 116-260 33 U.S.C. 467

## real: instruction for this section not applied (resolver/attribution) (4)

- 114-255 21 U.S.C. 355–1
- 115-254 49 U.S.C. 46102
- 115-254 49 U.S.C. 46105
- 116-315 38 U.S.C. 1562

## real: 'wherever appearing' not fanned out, or applied twice (2)

- 114-144 42 U.S.C. 3030s–1
- 115-254 49 U.S.C. 46111

## real: CLEAN though matched across a footnote marker (1)

- 117-103 34 U.S.C. 21711

## whitespace only (designation spacing, space before punctuation) (12)

- 113-67 5 U.S.C. 8423
- 113-76 5 U.S.C. 3111
- 113-255 5 U.S.C. 8477
- 114-94 23 U.S.C. 103
- 114-94 12 U.S.C. 5110
- 114-255 42 U.S.C. 290aa–5
- 114-315 38 U.S.C. 7423
- 115-271 18 U.S.C. 220
- 116-260 49 U.S.C. 60125
- 116-260 49 U.S.C. 44735
- 116-315 38 U.S.C. 1714
- 117-263 14 U.S.C. 4902

## oracle: delayed effective date (OLRC 'Amendment of ...' note) (36)

- 113-67 49 U.S.C. 44940
- 113-67 41 U.S.C. 4304
- 113-255 5 U.S.C. 8438
- 113-255 5 U.S.C. 8439
- 114-94 49 U.S.C. 30165
- 114-198 42 U.S.C. 1395iii
- 114-255 42 U.S.C. 1396d
- 114-255 42 U.S.C. 1395w–28
- 114-287 40 U.S.C. 571
- 115-84 5 U.S.C. 8432b
- 115-182 38 U.S.C. 1703
- 115-182 38 U.S.C. 1712
- 115-182 38 U.S.C. 1712A
- 115-182 38 U.S.C. 2303
- 115-254 15 U.S.C. 4721
- 116-113 19 U.S.C. 3602
- 116-113 19 U.S.C. 1304
- 116-113 19 U.S.C. 4374
- 116-113 19 U.S.C. 1677
- 116-113 28 U.S.C. 2201
- 116-113 28 U.S.C. 2643
- 116-136 11 U.S.C. 1182
- 116-136 11 U.S.C. 101
- 116-136 11 U.S.C. 1325
- 116-260 15 U.S.C. 1070
- 116-260 20 U.S.C. 1087a
- 116-260 20 U.S.C. 1087e
- 116-260 11 U.S.C. 507
- 116-315 38 U.S.C. 2304
- 116-315 38 U.S.C. 2307
- 116-315 38 U.S.C. 113
- 117-11 21 U.S.C. 321
- 117-81 10 U.S.C. 844
- 117-81 10 U.S.C. 867
- 117-81 5 U.S.C. 7511
- 117-263 10 U.S.C. 2861

## oracle: another law's amendment executed in the same window (10)

- 117-81 10 U.S.C. 139
- 117-81 10 U.S.C. 2583
- 117-81 10 U.S.C. 1746a
- 117-81 10 U.S.C. 2380c
- 117-81 10 U.S.C. 239c
- 117-81 10 U.S.C. 483
- 117-81 10 U.S.C. 171a
- 117-81 10 U.S.C. 3221
- 117-81 10 U.S.C. 4375
- 117-81 10 U.S.C. 1734

## editorial: heading style, case, OLRC-supplied heading or catchline (9)

- 113-23 16 U.S.C. 823a
- 113-291 10 U.S.C. 1407a
- 114-70 8 U.S.C. 1201
- 115-256 22 U.S.C. 2507c
- 115-270 33 U.S.C. 610
- 115-271 42 U.S.C. 247b–15
- 116-260 15 U.S.C. 1062
- 117-81 32 U.S.C. 329
- 117-263 33 U.S.C. 701r

## editorial: Act reference translated to a Code citation (8)

- 113-235 29 U.S.C. 1132
- 114-255 42 U.S.C. 290bb–2
- 114-255 42 U.S.C. 290bb–7
- 115-271 42 U.S.C. 294i
- 116-260 42 U.S.C. 13317
- 116-260 42 U.S.C. 300jj
- 117-103 15 U.S.C. 77ppp
- 117-263 6 U.S.C. 1501

## editorial: enactment date set in (comma added, or phrase the detector lacks) (7)

- 113-40 42 U.S.C. 17022
- 115-254 6 U.S.C. 941
- 116-136 12 U.S.C. 1795f
- 116-260 42 U.S.C. 16273
- 116-260 42 U.S.C. 294c
- 116-260 42 U.S.C. 1395bb
- 117-263 43 U.S.C. 390b

## oracle: OLRC text departs from the literal instruction, no note (7)

- 113-291 10 U.S.C. 1129a
- 114-55 49 U.S.C. 41742
- 114-94 23 U.S.C. 120
- 116-260 42 U.S.C. 8287a
- 117-81 10 U.S.C. 2714
- 117-81 10 U.S.C. 2715
- 117-263 10 U.S.C. 4025

## editorial: 'Repealed'/'Omitted'/'Renumbered' placeholder (3)

- 113-76 2 U.S.C. 1907
- 117-81 22 U.S.C. 2349aa–7
- 117-103 42 U.S.C. 300hh–11

## editorial: footnote markers or bracketed references (3)

- 113-291 10 U.S.C. 429
- 116-7 36 U.S.C. 70907
- 116-260 42 U.S.C. 5905

## editorial: executed 'to reflect the probable intent of Congress' (OLRC note) (2)

- 117-81 10 U.S.C. 231a
- 117-263 37 U.S.C. 402b
