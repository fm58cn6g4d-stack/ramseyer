# Milestone results

## M0: Environment and network test (2026-10-27)

**Gate** (from `docs/00-build-plan.md`): one OLRC title, one Congress.gov bill text and one
govinfo bulk file download from the build environment; results logged.

**Run:** `.venv/bin/python scripts/probe_sources.py` in the Claude Code cloud sandbox
(Python 3.11.17, SQLite 3.45.1 with FTS5). Full table in `var/probe.md` (gitignored).

| Source | Result | Measured |
| --- | --- | --- |
| OLRC release point page | PASS | Release point 119-134 (October 20, 2026) matches the pin; 58 per-title XML links |
| OLRC per-title XML | PASS | Title 4 zip, 48,796 bytes; `<uscDoc identifier="/us/usc/t4">`, `Online@119-134`; 47 section identifiers, all well-formed |
| OLRC all-titles zip | PASS (HEAD) | 108,691,570 bytes, last-modified 2026-10-23 |
| OLRC classification tables | PASS | 119th 2nd session: 647 rows, 47 public laws (119-70 to 119-134). The 1st session table also parses: 3,049 rows |
| Congress.gov API | PASS (2026-10-28) | 6 text versions for 119 hr 1. It was BLOCKED on 2026-10-27 until a key was added |
| Congress.gov bill text | PASS | `BILLS-119hr1enr.xml`, 1,754,658 bytes, root `<bill>`; the URL now comes from the API |
| govinfo bulk data | PASS | `BILLS/119/1/hr` lists 8,042 XML files; `PLAW/119/public` lists 132; one bill XML downloaded |

**Gate status:** PASS, with all 7 probes passing as of 2026-10-28 after the API key went into `.env`.

Unit tests: 10 passed (`pytest -q`), all offline.

## M1: Data layer (2026-10-28) — gate PASS, with open items carried to M2

**Gate** (from `docs/00-build-plan.md`): all titles for one release point indexed; 100 random
sections round-trip cite, section and text with no nulls. Plus the invariants in `docs/02-data-layer.md`.

**Run:** `.venv/bin/ramseyer sync` (3.3 min) then `.venv/bin/python scripts/m1_gate.py` (about 30 s); output in `var/m1_gate.md`.

| Check | Result | Measured |
| --- | --- | --- |
| Every node has non-null id, kind and path | PASS | 783,392 nodes, 0 violations |
| Section count and numbers per title match OLRC's XHTML edition | PASS | 58 titles, 0 differ |
| 100 random sections round-trip cite → node → text (seed 20261028) | PASS | 100 exact, 0 failed |
| Sampled text equals the XHTML statute field (ignoring whitespace and quote style) | PASS | 86 equal, 0 differ; 14 are repealed or omitted, with no statute field |
| All sections round-trip cite → node | PASS | 60,509 sections; 0 failed; 15 correctly ambiguous (duplicate numbers in the Code); 46 by identifier only |
| Every ref resolves or has dst_raw and a reason | PASS | 1,311,664 refs, 0 unexplained; 307,154 Code refs resolved |
| Query results carry the release point | PASS | 119-134 |

Index size: **1.57 GB** (SQLite with FTS5). Rows: 783k nodes, 1.31M refs, 253k notes,
155k source credits, 11k definitions (9,709 with a resolved scope).

**Follow-up (2026-10-28, same milestone):** a comparison of every section's text against the XHTML edition found two bugs, both now fixed:
- **Tables:** some tables put `<tfoot>` before `<tbody>` in the source (38 U.S.C. 1311). The text was
  in source order, so footnotes came before rows. Tables now read in display order: header, body, footer.
- **Status notes:** a subunit whose content is an OLRC note such as "[Repealed.]" (12 U.S.C. 1464(g)) now has
  that status (107 subunits); the note stays out of `text_plain`.

`ramseyer sync` now cross-checks every section against the XHTML edition and stores each difference
in `edition_diffs`, so later stages can warn when the two OLRC editions disagree on a section:

| Result at 119-134 | Sections |
| --- | --- |
| Equal (ignoring whitespace and quote style) | 52,845 |
| Rendering only (fractions, blank-line length, Unicode composition, dot leaders, formula layout) | 398 |
| **Content difference** | **81** |
| No statute field in XHTML (repealed, omitted, transferred) | 7,149 |
| Duplicate section numbers, not paired | 36 |

Content differences include real gaps in the XML. **19 U.S.C. 2702(b)'s list of eligible countries
appears in the XHTML but nowhere in the title 19 XML**, and 21 U.S.C. 812(e) lacks the "Schedule IV" label.
Others are XML artifacts: "Medicare+ÐChoice" (13 sections), a double-escaped `&quot;` in 10 U.S.C. 6284,
and footnote markers present in only one edition. The index keeps the XML as its single source of text
(rule 3) and flags these sections; it never substitutes XHTML text.

## M2: Free statute server (2026-10-28) — gate PASS

**Gate** (from `docs/00-build-plan.md` and `docs/03-free-statute-server.md`): resolve_cite, get_section,
cited_by and search work over MCP and match uscode.house.gov on 50 spot checks; cited_by equals the
inverted refs table.

**Built:** `ramseyer.statute.StatuteService`, with 11 tools: resolve_cite, get_section (operative, plain or
xml; as_of), get_pincite, cross_refs, cited_by, definitions, neighbors, search (FTS5 BM25), changes,
coverage, act_to_code. Thin wrappers expose them as an MCP server over stdio (`ramseyer serve-mcp`,
MCP SDK 2.3) and as a CLI (`ramseyer statute <tool> k=v`). Sample client configs are in `README.md`.

**Run:** `.venv/bin/python scripts/m2_gate.py` (52 s with a cold page cache); output in `var/m2_gate.md`.

| Check | Result | Measured |
| --- | --- | --- |
| Tools work over MCP (stdio client spawns `ramseyer serve-mcp`) | PASS | 11 tools listed; 7 calls, each with release point 119-134; the deliberate bad cite returns a structured not_found |
| 50 spot checks against uscode.house.gov (seed 20261028) | PASS | Headings 50/50 equal; text 25 equal, 25 rendering-only, 0 content; every page stamped "through Public Law 119-134" |
| cited_by equals the inverted refs table | PASS | 600 comparisons over 300 cited sections (text only, and with notes); 0 mismatches |
| Every response carries the release point; only documented error codes | PASS | 14 calls; codes seen: ambiguous, not_found, out_of_range |

All 25 rendering-only differences are the same thing: the website puts a word joiner (U+2060) before
every em dash.

Behaviors worth knowing:
- **Ranges:** a cite inside a published range resolves to the range unit and says so ("2 U.S.C. 1002"
  matches "within range /us/usc/t2/s1001...1004", status repealed).
- **Never a guess:** a duplicate section number returns `ambiguous` with both node ids, never one of them.
  A missing subunit says the section exists but the unit does not.
- **Edition warning:** get_section adds a `warning` when the section is among the 81 that the XML and
  XHTML editions disagree on in content (M1 follow-up).
- **Ref context:** refs inside tables of contents are now `context='toc'` (they were miscounted as text),
  so cited_by returns citing sections, not ToC lines.
- **act_to_code:** uses source credits only (layer 1) and says it is unvalidated until M5.

Unit tests: 21 passed, offline. They include a synthetic two-release-point index for `changes`,
ranges, ambiguity, definitions scope and act_to_code.

## M3: Oracle corpus and comparison harness (2026-10-28) — gate PASS

**Gate** (from `docs/00-build-plan.md` and `docs/12-testing.md`): 20 enacted laws with before and after
release points and enrolled-bill text, plus the comparison harness.

**Corpus** (`tests/oracle/corpus.json`, references and hashes only; text cached under `var/`): 20
public laws of the 119th Congress, 1,302 targeted sections in 22 release points. The selection rule
is in the manifest. The largest laws are 119-60 (NDAA for FY2026, 1,020 sections in 29 titles),
119-75 (Consolidated Appropriations Act, 2026, 94), 119-101 (21st Century ROAD to Housing Act, 88) and
119-103 (Continuing Appropriations and Extensions Act, 2027, 36). Sixteen smaller laws have 1 to 18 sections each.
No law shares a release-point window with another corpus law that touches the same section.

**Deviation from the plan:** the plan asks for laws mostly amending titles 49, 23 and 45. OLRC now publishes
prior release points only back to 119-73not60 (January 2026). None of them changes title 45, and the
title 49/23 changes in that window come from 119-60 only. The corpus therefore spreads across 34 titles.
It can grow once older release points are reachable.

**Set aside as hard cases:** 119-84 and 119-87 (FISA sunset extensions) amend § 403(b) of Pub. L. 110-261,
which is Act text held in a note under 50 U.S.C. 1881. OLRC classifies them to nine sections each, but no
section text or source credit changes. They are recorded in `hard_cases`, to come back for notes and Act text (M5/M6).

**Harness** (`ramseyer.oracle.harness`): a predictor returns, per law, a status and the predicted
`text_plain` for each section. The harness compares the prediction with the section at R_after
(whitespace and quote style ignored), and reports match, mismatch, missed, extra and unexpected_change. It
also reports the tab-11 metrics: false-clean rate, deterministic coverage and model tokens, with mismatches split
by stage (parser, resolver, engine, editorial, unclassified; manual labels in `tests/oracle/labels.json`).

**Run:** `.venv/bin/python scripts/m3_gate.py` (23 s); output in `var/m3_gate.md`.

| Check | Result | Measured |
| --- | --- | --- |
| 20 laws with enrolled text and before/after release points | PASS | 20 laws; enrolled XML hashes match; every law's titles loaded at both release points |
| Every law changes classified section text | PASS | 1,215 of 1,302 targeted sections change; 1,063 of 1,205 present at R_after cite the law in their source credit |
| Harness self-test with known predictors | PASS | oracle: match 1.0, false-clean 0; identity (no-op): mismatches = 1,215 = changed sections; one-word mutation: 1,120/1,120 caught; half predicted: 648 missed, 20 extra, WARN never counted as clean |
| Baseline stored for CI | PASS | `tests/oracle/baseline.json`: the no-op predictor's match rate is 0.0668; any pipeline must beat it |

Found along the way:
- **Repeals:** OLRC removes some repealed sections entirely at the next release point instead of leaving a
  "Repealed" stub (87 NDAA repeals, plus two transfers). The harness treats "absent at R_after" as the
  correct prediction for those.
- **Intermittent 403:** uscode.house.gov intermittently answers 403 during runs of downloads. The fetcher
  retries 403, 429 and 5xx with backoff (5, 15, 45 s).
- **Slow release-point drop:** dropping a release point was quadratic. SQLite checked foreign keys per
  deleted node against unindexed `source_credits.section_id` and `definitions.section_id`. Fixed with
  indexes and foreign-key checks off during the drop: 2 h+ down to seconds.
- **Size and time:** the oracle index (22 partial release points) is 7.1 GB under `var/oracle/`, and
  a clean build takes about 15 minutes.

## M4: Parser and IR, pasted text (2026-10-28) — gate PASS

**Gate** (from `docs/00-build-plan.md` and `docs/04-draft-parser.md`): on the corpus, the number of
instructions in the source equals the number in the IR plus UNPARSED; deterministic coverage is measured
and logged.

**Built** (`ramseyer.parse`):
- **Normalization** keeps an offset map back to the original text.
- **Segmentation** builds a tree of divisions, titles, sections and enumerated units. Quoted blocks attach
  to the unit that introduces them. Ambiguous enumerators (`(i)`, `(I)`) are settled by reading ahead to
  the next enumerator that follows on from an open unit. Table-of-contents headings are kept out of the structure.
- **Classification** marks units AMENDATORY, FREESTANDING (with a type), STRUCTURAL or TABLE_OF_CONTENTS.
- **Grammar:** patterns P1–P15 with a scope stack, so that "(1) in subsection (b)—(A) by striking …"
  inherits target and path. Multi-scope instructions ("in subsections (a) and (b)") fan out to one
  instruction per scope.
- **IR:** a pydantic model with the fields in tab 3, plus `through`, `unit` and `redesignate`.
- **Accounting:** every instruction the parser cannot match becomes UNPARSED, with its source text and a reason.
- **CLI:** `ramseyer parse draft.txt --out ir.json`.

**How the gate is measured honestly:** the parser reads only plain text rendered from each enrolled bill's XML,
as a staffer would paste it. The "count in" comes from the XML markup itself (`xmltext.xml_counts`): its
quote and unit boundaries come from `<quote>`, `<quoted-block>` and the structural elements, not from text. Both
counts use the same rule for where an instruction starts, so they agree only if the parser's segmentation and
quote detection agree with the markup at every bill location.

**Run:** `.venv/bin/python scripts/m4_gate.py` (10 s); output in `var/m4_gate.md`, residue in `var/m4_residue.jsonl`.

| Check | Result | Measured |
| --- | --- | --- |
| Instructions in = IR + UNPARSED on the corpus | PASS | 3,088 in; 2,933 IR + 155 UNPARSED; 0 per-location mismatches |
| Deterministic coverage measured and logged | PASS | **0.902** (2,785 of 3,088 parsed at confidence ≥ 0.8; 148 low-confidence, 155 UNPARSED). The tab-11 target is 0.85 |

Instructions by op: STRIKE_INSERT 1,199; ADD_END 435; INSERT_AFTER 222; STRIKE 212; REDESIGNATE 191;
ADD_UNIT_AFTER 157; UNPARSED 155; REPLACE_UNIT 109; STRIKE_UNIT 97; AMEND_HEADING 69; STRIKE_THROUGH 68;
CONFORM_TOC 58; REPEAL 50; INSERT_BEFORE and ADD_UNIT_BEFORE the rest.

**Pattern fixtures:** `tests/parse/patterns/P1.json`–`P15.json` hold 6 positive and 3–4 negative examples
for each pattern, taken from the corpus enrolled text by regexes independent of the grammar
(`scripts/harvest_patterns.py`). 150 fixture tests pass. Writing them caught two parser bugs (heading
insertions not marked AMEND_HEADING; a replacement quote starting on the next line), now fixed. They also
exposed five harvest regexes that had mislabeled correct parses, now corrected.

**Segmentation bugs found by the accounting check and fixed:** enumerators longer than three letters
(`(viii)`); a block closed by `”and` with no space; a real title heading straight after the table of contents;
`(i)` opening a clause versus continuing `(h)`, and the reverse case for `(I)` after `(H)`.

**Residue** (what the model fallback in M11 would see, and the input for promotion by recurrence):
- **Largest shape:** appropriations project-table edits ("striking recipient “…” and inserting “…”", 25 in 119-75).
- **Other shapes:** `transferring` and `moving` instructions; block insertions anchored on a punctuation description
  ("inserting a comma after “…”"); and redesignation lists qualified with "as so amended".

**Notes for M5/M6:**
- **Freestanding laws:** 119-88, 119-116 and 119-133 contain no amendatory instructions. Their Code
  changes are freestanding sections that OLRC places in the Code, so the dry-run needs a classification
  path for them, not an amendment path.
- **Targets (measured):** of 3,088 instructions, 1,419 (46%) target an Act section, usually with a
  parenthetical U.S.C. cite (the resolver's Act-to-Code job); 1,038 (34%) target a Code section directly;
  23 target a public law by number. For 608 (20%) the parser recognized no target (kind `unknown`),
  e.g. enacting clauses it did not read as a target, or heads naming the target in a form outside P1/P14.
  Those reach the resolver as UNKNOWN; the resolver milestone (M5) must measure and reduce them.

## M5: Resolver and Act-to-Code (2026-10-28) — gate PASS

**Gate** (from `docs/00-build-plan.md` and `docs/05-resolver.md`): zero silent mis-resolutions on 50 Act-section
references drawn from the oracle corpus, checked against the next release point.

**Built** (`ramseyer.resolve`):
- **Code targets:** a section and unit, a chapter or subchapter chain, or a whole title resolves to its node.
  Duplicate section numbers, missing units and repealed sections are reported, never guessed.
- **Act targets:** the Act is identified from the drafted public law, the OLRC Popular Name table, or both.
  Its Code location then comes from three layers, which are cross-checked:
  1. Source credits from the Code itself: each section's enacting credit names the Act and the Act section.
     For Acts cited by date and chapter, the section is read from the credit text, because the link omits it.
  2. OLRC classification tables.
  3. Act text set out in notes ("…, provided that:"), giving NOTE locations. A note on a chapter heading
     is cited as "note prec. <first section>", as OLRC does.
- **The drafted parenthetical is a second witness.** When it agrees, the result is `verified`. When it
  disagrees, the result is UNKNOWN with both candidates. When it is the only evidence, the result is
  flagged "unverified: parenthetical only".
- **Outcomes:** CODIFIED, NOTE, SPLIT, UNCODIFIED and UNKNOWN, each with evidence, flags and a reason.
  Positive-law status is stamped on every result.
- **Wiring:** the statute server's `act_to_code` tool now uses the resolver, and `ramseyer resolve "<target as drafted>"` runs it from the command line.

**Decision (mine, recorded):** layer 1 ignores positive-law titles. There, a section's first credit names the
law that inserted it (10 U.S.C. 1791 credits Pub. L. 104-106 § 568), not an Act section codified there. Using
it would silently send references to those laws into title 10.

**Ground truth:** OLRC's classification table row whose law section matches the instruction's bill location
names the Code section, or note, that the amendment changed. When the table and a resolution disagree only on
section text versus note at the same section, the oracle settles it: did the section text or its notes
change between the law's release points? A resolution is silently wrong when it claims a location the truth
contradicts without being flagged.

**Run:** `.venv/bin/python scripts/m5_gate.py` (about 60 s, including 32 s to build the Act-to-Code index); output in `var/m5_gate.md`.

| Check | Result | Measured |
| --- | --- | --- |
| Zero silent mis-resolutions on 50 Act-section references (seed 20261028) | PASS | 40 correct, **0 silent wrong**, 1 wrong but flagged, 3 UNCODIFIED, 6 UNKNOWN |
| Resolved sections show the law at the next release point | PASS | 34/34: text changed 32; 2 amendments set out as pending-effective-date notes |
| All checkable Act references in the corpus (measurement) | PASS | 988 checkable (1,287 Act references): 831 correct, **0 silent wrong**, 3 wrong but flagged, 5 SPLIT, 39 UNCODIFIED, 110 UNKNOWN |

Outcomes over all 2,933 parsed corpus instructions: Act targets CODIFIED 1,041, NOTE 314, UNCODIFIED 195, UNKNOWN 168,
SPLIT 5; Code targets CODIFIED 1,131, UNKNOWN 7; public-law targets NOTE 15, UNCODIFIED 5; unknown targets 52.

**The three flagged wrong answers are all real hard cases, caught:**
- **Atomic Energy Defense Act:** 119-60 § 3111 repealed the Act's title 50 sections and re-enacted them in title 10,
  while §§ 3114–3115 of the same bill amend them at their old citations ("50 U.S.C. 2661"). This is the "amendments
  to text another section of the same bill amends" case. The resolver lands on a repealed section and flags it.
- **Intelligence Authorization Act for FY1985 § 601:** credits and notes point to different places. Flagged.

**Parser improvements made for M5:** the M4 gate is unchanged, at 3,088 = 2,933 + 155 and coverage 0.902.
- **Target recognition:** instructions with no recognized target dropped from 580 to 52.
- **Header fix:** "In general.—" headers were not split from the unit text, because headers beginning "In " were refused.
- **New target forms:** Act names with commas, quoted nicknames and fiscal-year qualifiers; Act-level titles
  ("Title II of the National Housing Act"); "such section", "Subsection (d) of such section" and "such title"
  across sibling units (each bill section remembers the last target); "Section 2(6) (16 U.S.C. 973(6))" with
  the Act implied.

**Found along the way:**
- **Delayed effective dates:** OLRC does not execute amendments with a delayed effective date. It sets them out
  in an "Amendment of Section" note (e.g. 119-60 § 535(b)(4) under 50 U.S.C. 3811, effective one year after
  enactment). The M6 dry-run oracle must accept "pending" as an outcome.
- **Note versus section:** the classification table sometimes lists a section where the amended text is
  actually the Act text in its note (NDAA FY2019 § 1792 under 50 U.S.C. 4531). The oracle settles these.
- **Index fix:** the main index lacked the new `source_credits(section_id)` index (the database predates it).
  Opening the Indexer applies the schema, so this is fixed in place.

## M6: Dry-run engine (2026-10-28)

**Built:** `src/ramseyer/dryrun/engine.py` applies parsed instructions, in bill order, to a working copy of
each section's USLM XML at the law's R_before release point. Text edits run on a linear view of the scope's
text mapped back to the XML text nodes. New units are built as USLM elements from the quoted block.
`src/ramseyer/dryrun/predict.py` runs parse, resolve and dry-run for a bill, one prediction per Code section
reached, including new sections. Every instruction gets a status: CLEAN, WARN, AMBIGUOUS, NOT_FOUND,
TARGET_MISSING, CONFLICT or UNPARSED, and the section takes the worst.

**Run:** `.venv/bin/python scripts/m6_gate.py` (about 3 minutes). Output goes to `var/m6_gate.md`,
`var/m6_report.json` and `var/m6_traces.jsonl` (per-instruction traces). The baseline is
`tests/oracle/m6_baseline.json`.

| Check | Result | Measured |
| --- | --- | --- |
| Predicted text matches the next release point (measured) | PASS | 1,295 targets: 515 matched, 357 mismatched, 423 missed (match rate 0.398; 515 of 872 predicted targets). 7 pending-effective-date, 1 extra, 1 unexpected change |
| False-clean rate under 1% (substantive) | PASS | **0 of 369** CLEAN predictions differ from R_after in substance |
| False-clean rate, raw (measured) | — | **43 of 369 (11.7%)** CLEAN predictions differ from R_after in some way. All 43 are OLRC editorial changes: 37 found by the detector, 6 labelled by hand after checking the enrolled text |

**Calibration of the false-clean gate (decision for Espen to confirm):**
- **Target:** docs/12-testing.md says targets are starting points to calibrate after the first measurement. It also classifies an "editorial change by OLRC that is not in the law" as its own mismatch class.
- **Gate:** it therefore tests the substantive rate, and the raw rate is reported beside it.
- **What the detector ignores:** footnote markers, the letter case of headings, and an enactment date set in place of "the date of the enactment of this Act". It compares footnote-stripped XML text and accepts no other difference.
- **The six labelled cases:** `tests/oracle/labels.json` lists them, each checked against the enrolled XML.
  - **10 U.S.C. 139a:** R_after reads "section section 3221", an OLRC slip.
  - **46 U.S.C. 7307–7309:** OLRC printed "18 months" with a "So in original. Probably should be '18 months''" footnote. The enrolled bill strikes "3 years" and leaves the apostrophe.
  - **46 U.S.C. 70001:** OLRC set a SAFE Port Act provision into the section as subsection (l). Its text is not in Pub. L. 119-60.
  - **37 U.S.C. 204(h)(1):** OLRC inserted after "regular component" where the law says "reserve component".
- **Caveat:** these figures are measured on the corpus the engine was tuned on. The real-draft trial in M11 is the independent check.

**First run versus now:**

| Run | Matched | Missed | False-clean |
| --- | --- | --- | --- |
| First run | 229 of 612 predicted | 683 | 41% |
| Now | 515 of 872 predicted | 423 | 0 substantive, 11.7% raw |

**Mismatches by stage:**

| Stage | Count | Notes |
| --- | --- | --- |
| Engine | 231 | All non-CLEAN: WARN, NOT_FOUND, TARGET_MISSING or CONFLICT, each reported with its reason |
| Editorial | 75 | |
| Parser | 35 | |
| Resolver | 16 | |

**What made predictions right, and what keeps a CLEAN honest.**

*Engine: Code conventions verified on the corpus:*
- **Matching:**
  - Matches are word-bounded: "term" is not found inside "determines".
  - Spacing at edit boundaries follows the Code: one space around inserted words, and a strike leaves no double space or space before punctuation.
- **Footnotes:** a footnote attached to replaced words goes with them.
- **Bracketed cites:** OLRC's bracketed "[42 U.S.C. … et seq.]" after an Act name goes when the name is struck.
- **Inserted unit headings follow the amended unit's existing style:**
  - **".—":** 15 U.S.C. 2625(b) keeps ".—" though title 15 is not positive law.
  - **Case:** positive-law subsection headings are title-cased, measured on titles 10, 14 and 46. "With", "From" and "Under" are capitalized; "of", "and", "for", "on", "in", "or", "the", "by", "as", "a", "at" and "to" are not. After a hyphen the case is left as drafted.
  - **Below the subsection:** headings print in sentence case, e.g. "Senior leader of the coast guard". 13,463 of 13,524 words are lowercase.
- **New sections:**
  - A quoted Code section is set in Code form: "§ 4145. Program for the enhancement …".
  - "SEC." in USC-style blocks and chapter tables of sections are handled.
  - An Act section replaced in full keeps its Code number.
- **Inserted text:**
  - "‘…’" becomes "“…”", and apostrophes inside nested quotes stay.
  - A stray space before a comma in the bill is removed. The bill's "rifle , or" is printed "rifle, or".

*Parser gaps found by the dry run, all now covered, with the M4 accounting still exact:*

| Gap | Effect before the fix |
| --- | --- |
| "by amending paragraph (3) to read as follows" | 57 instructions were invisible to both the parser and the independent counter, which shared the op-start rule |
| "by repealing subsection (e)" | Not read as an instruction |
| "(15) In section 1749—" | Capital "In" was not read as a section scope |
| "The following sections of title 10 are amended by striking …: (1) Section 2130a(a)(1) …; (2) …" | Not applied to the listed sections; now one instruction per listed provision |
| "Sections 351(a), 352(a), 353(a), and 353(b) of such title" | Not split into separate targets |
| "Subsections (g)(1) and (h)(1) of section 204" | Scope lost |
| "in subsections (a)(1), (b), and (h)(1)" | Split into wrong units; now chain-aware |
| "Chapter 2003 of such title", "Such chapter 908" | No target found; title targets are now remembered across sibling units |
| "paragraph (2) of subsection (b)" in replacements | Parent unit dropped |
| "clauses (i) through (iii)" | (ii) was skipped |
| "in the section heading, by adding at the end …" | Not read as a heading edit; the P10 fixture had it as a negative example, now moved to positive |
| Unit headers up to 32 words | Longer headers were not recognized |

M4 gate now: 3,146 instructions = 2,982 + 164 UNPARSED, coverage 0.901. The count was 3,088 before the "amending … to read" and "repealing" fixes.

*Kept out of CLEAN on purpose:*

| Situation | Status | Why |
| --- | --- | --- |
| A text edit that adds an enumerated unit or heading | WARN | The Code restructures it |
| Inserted text in a non-positive-law title that still refers to the Act ("section 102", "subtitle A", "this title") | WARN | OLRC converts these to Code form, which needs the Act-to-Code map |
| A repealed section or unit | WARN | Set out as a "[Repealed …]" stub |
| Instructions the parser left partly unread | WARN | |
| Instructions governed by a delayed effective date | WARN, not applied | OLRC sets them out in a note. 46 corpus instructions are flagged by `parse/effective.py` |
| More than 10 sections enacted by one instruction | WARN | A restatement, such as 119-60 § 3111 (Atomic Energy Defense Act into 10 U.S.C. 6101 ff.). OLRC carried the bill's other amendments to the old provisions into the new ones |

**Still missed (423):**

Measured by classification-table row type:

| Cause | Count |
| --- | --- |
| Repealed sections the predictor does not emit | 148 |
| New sections not yet built | 128 |
| Chapter tables of sections ("prec" rows) | 120 |
| Section transfers ("tr" rows) | 23 |
| "amd gen" rows | 4 |

These are the next things to raise the match rate. They do not affect the false-clean rate, because a section with no prediction is never CLEAN.

**Harness:** the M3 self-test expectation for the "partial" predictor now excludes pending-effective-date targets, which are outside the target count. M3 passes again.

## M6b: Held-out check and coverage (in progress, 2026-10-28)

**Plan change:** made 2026-10-28 with Espen's go-ahead. Changed in the live Build Plan doc (overview rev 10,
Testing tab rev 2) and mirrored in `docs/`:
- **New milestone:** M6b, the held-out check.
- **M6 gate reworded:** substantive false-clean is gated, and the raw rate is reported beside it.
- **Order:** M8 (comparative print) moves ahead of M7 (Word ingestion), which waits for real drafts.

**Held-out set:**
- **Files:** `scripts/build_heldout.py` writes `tests/oracle/heldout.json` and builds `var/oracle/heldout.sqlite`. Selection is shared with the tuning corpus through `src/ramseyer/oracle/candidates.py`; the tuning manifest is reproduced byte for byte.
- **Contents:** every eligible law not in the tuning corpus, which is 10 laws with 10 target sections (titles 15, 16, 29, 30, 34 and 42).
  - **Set aside:** 119-84 and 119-87, which amend Act text kept in notes.
  - **Small by necessity:** OLRC publishes no USLM snapshot before 119-73not60 (January 2026). The other laws in the window either touch one or two sections or were already used for tuning.
- **Gate:** `scripts/m6_gate.py --heldout` writes `var/m6b_gate.md`, `var/m6b_report.json` and `var/m6b_traces.jsonl`.

| Set | Targets | Matched | Mismatched | Missed | CLEAN | Substantive false-clean |
| --- | --- | --- | --- | --- | --- | --- |
| Held-out, first run | 10 | 1 | 2 | 7 | 0 | — |
| Held-out, now | 10 | 2 | 2 (1 editorial only) | 6 | 0 | 0 of 0 |
| Tuning corpus, now | 1,295 | 528 | 361 | 406 | 370 (28.6% of targets) | 0 of 370; raw 43 (11.6%) |

**What the held-out laws exposed**, all fixed and re-measured on both sets:
- **One false-clean (30 U.S.C. 191(d)(3)):** "striking 'transfer—' and all that follows through 'the Fund'" crossed subparagraphs and left the emptied units behind, printing "Fund .". Swallowed units are now merged into the replacement, and the result is WARN.
- **A word-boundary bug:** the linear view joins a heading and its text with no space ("UseOf"), so a match at the start of the text was refused. Edges of the matched range now count as boundaries. CONFLICTs on the tuning corpus fell from 41 to 22.
- **Parser:** "Marine Mammal Protection Act Of 1972" (capital "Of"); "inserting after section 36 (16 U.S.C. 823g) the following".
- **Redesignation:**
  - **Below the named unit:** units are now found when they sit under it (WARN).
  - **Inline enumerators:** enumerators set inline in running text, e.g. "means (A) … (i) … (ii)" in 29 U.S.C. 1002(18), are redesignated in the text (WARN).
- **Act-to-Code references in inserted text:** "section 407(d)(6)" of ERISA is printed "section 1107(d)(6) of this title". The engine now translates bare "section N" references through the resolver. When the resolver has only one witness (source credits), the result stays WARN with the translation named.
- **Tuning corpus, list-form repeals:** "The following provisions of title 10 … are hereby repealed: (1) Chapter 345. (2) Section 3070. …" now fans out, and a repealed chapter predicts each of its sections (WARN). Items naming no single provision (a whole Act, "Sections 3116 and 3141 of …") become their own UNKNOWN instructions with their text. M4 now stands at 3,146 = 2,990 + 156 UNPARSED.
- **M5 gate:** it now uses the harness's pending-note test. One sampled amendment (119-75 § 6101, effective in 3 years) was otherwise counted as "unchanged".

**What held-out shows that tuning did not:**
- **Few confident answers:** on unseen laws the engine produced no CLEAN at all. Every applied change carried a reason to doubt it: a delayed date, an Act reference, a structural edit or a cross-unit strike. That is the intended behaviour, but it means little is confident.
- **Unpredictable placements (4 of 10 held-out targets):** the Code's editors placed free-standing bill sections as new Code sections (34 U.S.C. 51101, 15 U.S.C. 45g, 16 U.S.C. 430h-15, 29 U.S.C. 570). No instruction in the bill places them, so no tool can predict the section number.
- **New Act sections (2 targets, 16 U.S.C. 823h and 42 U.S.C. 915):** these get Code numbers the editors assign. Next-number conventions could predict them only as WARN.

**Left unpredicted on purpose:** chapter "prec" rows (tables of sections). 46 of the 120 such sections also changed text, through edits the engine does not attribute. Predicting "unchanged" would create false CLEANs.

**Decisions (Espen, 2026-10-28):** widen the held-out set with GovInfo's annual editions; the confident-answer
target is **35% of held-out targets**, with substantive false-clean under 1%.

### GovInfo held-out set (2026-10-29)

**Source and conversion:**
- **Editions:** GovInfo's 2023 edition (current through 2024-01-03) and 2024 edition (current through 2025-01-06), one XHTML granule per section, fetched with the api.data.gov key.
- **Converter:** `src/ramseyer/data/xhtml_uslm.py` turns OLRC's XHTML into USLM, and the standard indexer loads it as release points `usc-2023` and `usc-2024` in `var/oracle/govinfo.sqlite`.
  - **Measured:** on the current release (119-134), 57,660 of 58,696 sections (98.2%) convert with text and unit paths equal to the USLM index (`scripts/xhtml_check.py`).
  - **Conventions found:** recorded in `records/verify-first.md`.
- **Laws:** 118th-Congress laws enacted between the two editions' dates (per title), using the sections each law alone changed in that window. That gives 92 laws and 1,312 targets (`tests/oracle/heldout_govinfo.json`). 11 laws are set aside with reasons: every target section was shared with another law, or no enrolled XML exists.
- **Protocol:** the even public-law numbers form the **dev half**, used to find and fix errors. The odd ones form the **test half**, which is only measured, never inspected for fixes. The gate (`scripts/m6_gate.py --set govinfo`) reports both halves.

**Results** (substantive false-clean is the gate; the raw rate counts any difference, including OLRC editorial ones):

| Set | Targets | Matched | CLEAN | CLEAN share of targets | Substantive false-clean | Raw false-clean |
| --- | --- | --- | --- | --- | --- | --- |
| GovInfo, first run | 1,312 | — | 452 | 34.5% | 16 (3.5%): dev 8 of 126, test 8 of 326 | — |
| GovInfo, now, all | 1,312 | 529 | 449 | **34.2%** | **7 of 449 (1.56%)** | 82 (74 by the detector, 1 labelled) |
| GovInfo, now, dev half | 459 | 152 | 123 | 26.8% | 0 | 15 |
| GovInfo, now, test half | 853 | 377 | 326 | **38.2%** | **7 of 326 (2.15%)** | 67 |
| Tuning corpus, now | 1,295 | 529 | 372 | 28.7% | 0 | 44 (37 detector, 7 labelled) |
| Release-point held-out, now | 10 | 2 | 0 | 0% | 0 of 0 | 0 |

**Against the targets:**
- **Confident answers:** they meet the 35% target on the untouched test half (38.2%) and fall just short overall (34.2%).
- **False-clean:** it misses the under-1% target on the test half, at 2.15%. Since the test half was not used for fixes, this is the honest unseen-law rate. On the dev half, the errors found were fixed and fell from 8 to 0. The test half fell from 8 to 7 through those same general fixes.

**Fixes from the dev half** (all general rules, re-measured on every set):
- **Chained "such section":** "Paragraph (1) of subsection (c) of such section".
- **Bare section numbers:** "Section X" with no Act takes its root from context (flagged).
- **Location phrases:** "of section"; "each of" and location phrases across a unit chain.
- **Act cited by date:** "Act of <Month d, yyyy>".
- **Headings:** the law's period is kept in "§" headings.
- **Redesignation:** repeal stubs that a redesignation leaves out of order are dropped (WARN).
- **Spacing:** when inserting "before" text.

**Detector change:** it now strips trailing spaces before a removed footnote marker. XHTML puts a no-break space there and USLM a narrow one.

**Labels added:**
- **42 U.S.C. 280i–4:** both the edition and the current USLM print "28,100,000" without "$", where the law has "$".
- **10 U.S.C. 2218:** OLRC dropped a comma along with a References-in-Text footnote.

**Checker fix (M5):** a list-form repeal at 119-60 § 811(b) was graded only against the deepest classification rows, (b)(N)(X). That made its correct resolution (§ 811(b)(1) -> 10 U.S.C. 3372 note) read as a silent mis-resolution. Rows at or below an instruction's location now all count, and M5 is back to 0 silent wrong.

**The 7 test-half false-cleans**, seen in the gate output only and deliberately not fixed:
- 42 U.S.C. 2235, 30 U.S.C. 1721 and 10 U.S.C. 9082 among them.
- Their causes are structural: an inserted subsection numbered "c." where the Code prints "(c)", a missing subsection heading, and a subsection the prediction did not carry.
- These are the classes to address next on the dev half.

**Other gates on the same code:**
- **M3:** passes.
- **M4:** 3,146 = 2,990 + 156 UNPARSED, coverage 0.903.
- **M5:** passes.
- **Unit tests:** 206 pass.

### Second round on the dev half (2026-10-29, Espen: "keep fixing, refining, and testing")

**Measured on the same code:**

| Set | Matched | CLEAN share of targets | Substantive false-clean | Missed |
| --- | --- | --- | --- | --- |
| Tuning corpus | 529 -> **553** | 28.7% -> 29.7% | 0 -> **0** | 404 -> 383 |
| GovInfo, all | 529 -> **574** | 34.2% -> **35.4%** | 7 -> 5 | 373 -> 320 |
| GovInfo, dev half | 152 -> 179 | 26.8% -> 28.8% | 0 -> 0 | — |
| GovInfo, test half | 377 -> 395 | 38.2% -> **38.9%** | 7 of 326 (2.15%) -> **5 of 332 (1.51%)** | — |

**Other gates on the same code:**
- **M4:** 3,146 = 3,018 + 128 UNPARSED (was 156); deterministic coverage 0.903 -> 0.915.
- **M5:** 898 correct Act references (was 842); 0 silent.
- **M3:** passes.
- **Unit tests:** 226 pass.

**Parser:**
- **References clauses:** "wherever in this title an amendment … is expressed in terms of … a section …, the reference shall be considered to be made to … the Social Security Act" (or "title 10, United States Code") now supplies the Act to "Section 425 (42 U.S.C. 625)", within the bill unit the clause names. Before this, 118-258 lost every such instruction.
- **Acts by date or long title:** "the Act of March 3, 1899" and "the Act entitled “…”, approved June 3, 1976". The resolver finds them through the enactment dates in the Code's source credits and notes. Several laws on one day stay SPLIT unless the drafted parenthetical picks one.
- **Act names and units:** "Section 1701 of title I of the … Act"; names ending "Amendments Act of 2003"; "Section 401 of such Act" (the Act named last in the bill section); "Section 3763 of such title" after a subchapter target; "Such subchapter is further amended" in a later bill section.
- **One silent mis-resolution removed:** "Section 3(c) of the Act of August 13, 1946" had taken its root from the previous subsection (Flood Control Act of 1946) and resolved to 33 U.S.C. 701p. A section "of" a law the grammar does not know no longer takes a root from context.
- **Heading edits:**
  - "The heading for section 723 …", "In the section heading for section 430c, …" and "In the subsection heading for subsection (c) of section 3072" were read as text edits. They are now heading edits.
  - New forms: "striking the heading and inserting “…”", "amending the section heading to read as follows", "striking the subsection heading".
- **Insertions and replacements:**
  - Insertions: after units "(as so redesignated)"; at punctuation ("inserting the following before the period at the end: “…”"); after a placement phrase set before "by" ("after subclause (III), by inserting the following:").
  - Several units "to read as follows".
  - "striking section 100905 and inserting the following".
  - "(and conforming the table of sections … accordingly)".
  - "the term “…” … in each place it appears in text or headings" (headings included).
- **Blanket targets:** "Except as provided in paragraph (2)," and "(as defined in section 102 of title 10 …)" no longer name the target. "each covered defense law … is amended" is a blanket target, reported rather than guessed.
- **Delayed effective dates:** "shall take effect on October 1, 2025, and shall apply to payments …" is now delayed. Only the "take effect" part decides. Two false-cleans on the dev half (42 U.S.C. 625, 629i) came from this.
- **Bill typo:** "United Sates Code" (118-159 § 566) is accepted.

**Engine:**
- **Restructuring text edits:** a replacement that starts new enumerated units ("striking “to a county” and inserting “to—“(A) a county”") is built as structure. The text before it becomes a lead-in over new child units, or ends the unit with new sibling units at their own level (an ancestor's, if need be). The rest of the old text continues the last new unit. Edits that would leave later units to move fall back to the literal text edit (WARN). Example: 42 U.S.C. 284g(a)(1), six steps, all built.
- **Ambiguous labels:** "(i)" is subsection or clause. `build_units` now sets synthetic context lines to place it at the needed level.
- **Struck text that begins or ends with punctuation** no longer leaves two words touching ("fishing" + "and").
- **New sections:** a section numbered in a positive-law title is predicted by its number when the unit it is added to does not resolve (WARN). Example: "Subtitle VII of chapter 20" for the Code's subchapter VII.
- **"this Act":** a struck "this Act" that the Code prints as "this chapter" (or subchapter, part, title) is found in that form (WARN).

**Self-checks (`src/ramseyer/dryrun/verify.py`):** independent of R_after. They lower a CLEAN section to WARN when:
- inserted text still holds an enumerator and heading inline ("c. Application reviews.—");
- unit labels are out of order or duplicated;
- an unapplied instruction names the section;
- a blanket instruction strikes words the section contains.

They fire 5 times across all sets. One lowered a test-half false-clean (42 U.S.C. 2235); one lowered a correct answer. The checks are aimed at real drafts, where the parser meets new forms.

**Tried and reverted:** "before the semicolon" in a unit ending "; and" was allowed to anchor at that semicolon. It gained 2 matches but made one test-half false-clean (5 U.S.C. 6323(b)(1), identified only by identifier). It was reverted. The test half was otherwise not inspected.

**What remains on the dev half:**
- **Missed new sections:** 135 of 142 are in non-positive-law titles. The editors assign their numbers (free-standing provisions; new Act sections), so they cannot be predicted.
- **NOT_FOUND:** bill drafting slips ("Secretary of Housing Urban Development"); text the Code prints in another form ("450b" -> "5304", Act-internal "section 3(f)" -> "section 6802(f)"); and bill text that differs from the edition by a comma ("December, 31, 2024").
- **WARN mismatches:** OLRC's editorial choices in inserted text ("this Act" -> "this chapter", proper-noun case in headings, Act-section translations on one witness).

**Open (for Espen):** substantive false-clean on unseen laws is now 1.51% (test half), against the 1% target. Confident answers stand at 38.9% on the same half, against the 35% target.

## M6c: Red-team response (2026-10-29)

**Why this section exists:** an independent session reviewed ramseyer at commit 94712c0 without consulting the builder.
- **Report:** `records/red-team-2026-10.md`.
- **Reproducing cases:** `redteam/synthetic.py`.
- **Finding:** CLEAN meant "applied literally", not "verified".
- **What Espen chose:** fix the critical findings first, then rebuild the measurement and add a drafting-error benchmark. M8 waits.
- **Regression tests:** every finding below has one, in `tests/unit/test_redteam_cases.py` and `tests/unit/test_grammar_forms.py`. 283 unit tests pass.

| Finding | What changed |
| --- | --- |
| F1: ordinals read as "each" | The `nth` group is separate from "each place". An explicit "the first place" is `nth:1`; the default "first" means none was given. |
| F2: chapter- and title-wide edits dropped | Applied section by section to every baseline section of the unit that contains the words (WARN). This happens only when the instruction names no narrower place of its own and says "each place it appears" or names the unit. Otherwise NOT_EXECUTED with the reason. A first version fanned "In subsection (a)(2) of such section 710a" out over 264 sections; the narrower-place rule and "such section 710a" parsing fixed it. |
| F3: Act-wide edits | Applied to the sections the Code credits to the Act (WARN). Act-wide or listed repeals that are not executed (including "(1) The Atomic Energy Defense Act (50 U.S.C. 2501 et seq.)") lower every section of that Act to WARN. |
| F4: unknown verbs vanish | "deleting", "replacing … with", "substituting … for" and the imperatives (strike, insert, add, redesignate) are read as the usual verbs and flagged; they stay WARN. "… shall be applied by substituting …" is a rule of application, not an amendment: NOT_EXECUTED (four M5 "silent wrongs" came from this before the rule). Units that say "is amended" or sit under an "… is—" head with no known verb are UNPARSED. **94 items under "is—" heads (e.g. "(1) transferred to the end of section 2810") had been invisible to both the parser and the M4 counter.** |
| F4: independent counter | M4 now also checks that every quotation after the first verb of an amendatory unit is used by an instruction. This is independent of the verb list. Of the 127 unused found first, 109 were fixed in the grammar or were head names; 18 remain, all in units already reported UNPARSED or low-confidence. |
| F7: delayed amendments not dry-run | Dry-run on a copy. The predicted text stays unamended, as OLRC does, but a missing quote is reported (NOT_FOUND etc.). |
| F8: "$1,000" inside "$1,000,000" | Number boundaries (comma or period plus digit). STALE_BASELINE implemented: on NOT_FOUND, earlier release points are searched and named. |
| F9: sentence splitter | Abbreviation-aware ("U.S.", "Pub.", "No.", initials). A sentence-numbered edit on a unit that has subunits is AMBIGUOUS. A miss inside a qualified part is reported as such, not as CONFLICT. "in the paragraph defining the term “X”" is a locator (it had put a sentence edit at the section's second sentence). |
| F10: one witness | Targets resolved on source credits alone, or on the drafted parenthetical alone, are capped at WARN. |
| F11: structure | A replacement must carry the replaced label. An added label must not duplicate an existing one and must follow its predecessor. After a redesignation, references in the section to the old labels are flagged. |
| F12: labels keyed per section | Each label stores its reason and hashes of the predicted and R_after texts. It expires when either changes. All 8 were re-checked against their documented reasons before restamping. |
| F13: known-bad source text | Sections with XML/XHTML content differences are not CLEAN. |
| F14: no status | Every instruction gets a terminal status: NOT_EXECUTED with the reason for notes, uncodified or unresolved targets, and unsupported unit edits. The M6 gate checks "instructions in = instructions with a status" on every set: 0 missing. |
| Rule 3 | Every prediction carries its release point. |

**More forms found by the independent quote check:**
- strikes anchored on neighbouring words ("striking “or” after “X”", "the period after “21”");
- "both places" and "at each place";
- a location between the quote and "and inserting";
- "through the period", "through the end of the paragraph" and "through “B”";
- inline quotes after "the following:";
- "striking the second sentence and inserting";
- a replacement ending ":" that introduces a quoted block;
- "In subsection (a)" with a capital "In".

### Measurement rebuilt (F5, F6, F15)

**F6, wrong-section edits:**
- The GovInfo sets now fetch, on demand, any section ramseyer reaches outside the answer key (`src/ramseyer/oracle/govinfo_overlay.py`, cached).
- CLEAN predictions on sections no law in the window touched are graded against R_after and count as false-cleans when they differ.
- **Result:** 1 such CLEAN, right. The other 32 sit on sections other laws in the window also changed, so they are reported as not gradable. Predicting through all laws in the window is the remaining step.
- The first, unfiltered count (28 of 33 "wrong") was an artefact of those shared sections.

**F15, resolving against the Code before each law** (`--resolve-before`, tuning corpus):
- With the current code, 364 CLEAN, 363 right, against 363 of 363 with the pinned index.
- The one difference is 14 U.S.C. 319: R_after has the section with no text (moved by a law outside the bill).
- That run first found 2 more errors: Atomic Energy Defense Act sections in title 50, amended CLEAN while the same bill repeals the Act. Fixed: unexecuted Act repeals lower the Act's sections (F3 row above).

**F5, the test half and a sealed set:**
- The GovInfo test half has been looked at repeatedly, so it is no longer clean.
- A **sealed set** was built after all the fixes above: the 2023 laws on GovInfo's 2022 and 2023 editions; 14 laws, 729 target sections.
- Its manifest was committed (dc91387) before its one measurement, on that commit. Its cases have not been inspected.
- The gate reports every set per law and by stratum, with Wilson intervals.

| Set (same code) | Matched | CLEAN share | Substantive false-clean | 95% interval |
| --- | --- | --- | --- | --- |
| Tuning corpus (in-sample) | 565 | 28.0% | 0 of 363 | 0%–1.0% |
| GovInfo 2024, dev half (in-sample) | 182 | 25.7% | 0 of 118 | 0%–3.2% |
| GovInfo 2024, test half (looked at; no longer clean) | 409 | 35.8% | 5 of 306 | 0.7%–3.8% |
| **Sealed 2023 set: all** | 326 | **33.2%** | **5 of 242 (2.07%)** | **0.9%–4.7%** |
| Sealed: FY2024 NDAA (118-31) | — | — | 5 of 206 (2.43%) | 1.0%–5.6% |
| Sealed: the other 13 laws | — | — | 0 of 36 | 0%–9.6% |

**Reading the numbers:**
- On unseen law, about 2% of confident answers are wrong in substance (plausibly 1%–5%).
- The errors cluster in the large defense authorization bills.
- The non-NDAA samples are too small to say more than "no errors seen".
- The 1% target is not met.

### Drafting-error detection benchmark (`scripts/m6c_error_benchmark.py`)

**Method:**
- Instructions known to be right on the tuning corpus are copied with one injected drafting error each.
- Detected means ramseyer no longer calls the edit CLEAN.
- Errors are injected after parsing, so this measures the resolver and engine.
- 300 sampled; 288 controls stay CLEAN alone.

| Injected error | Cases | Detected (not CLEAN) | Rate | Statuses given |
| --- | --- | --- | --- | --- |
| neighbouring section number | 158 | 141 | 89.2% | TARGET_MISSING 98, NOT_FOUND 35, WARN 5, AMBIGUOUS 3 |
| ordinal that does not exist (“the second place it appears”) | 180 | 171 | 95.0% | NOT_FOUND 171 |
| replacement block with the wrong label | 12 | 12 | 100.0% | WARN 12 |
| stale amount (a shorter number that the current one starts with) | 17 | 17 | 100.0% | NOT_FOUND 17 |
| stale quote (one word or number changed) | 184 | 184 | 100.0% | NOT_FOUND 184 |
| wrong unit label in the location | 221 | 197 | 89.1% | NOT_FOUND 94, TARGET_MISSING 92, WARN 6, CONFLICT 4, AMBIGUOUS 1 |
| all | 772 | 722 | 93.5% | |


**What the misses are:**
- **Unit operations** (strike, replace or redesignate "subsection (c)") aimed at a neighbouring section that also has that unit. No text witness exists for these.
- **Punctuation anchors.**
- **Ordinals:** some "misses" are real second occurrences.

The sequence check on added labels (F11) cost nothing on the tuning set but did not move this benchmark: its misses are not additions.

**Open:**
- **Still above target:** the false-clean target is not met on the sealed set (2.07%).
- **Remaining structural limits:**
  - wrong-section unit operations (above);
  - sections changed by several laws in a window (ungradable until laws are chained);
  - the parser is measured on enrolled XML only (red team F16: degraded and introduced-version text is next).

## Order of work revised (2026-10-29)

Espen approved the revised order in `records/handoff-2026-10-29.md`; `docs/00-build-plan.md` holds the milestone table. After M6c: M6d foundations (USLM 1.x and 2.x, the four failure categories including already executed, incorporated-set release-point windows), M6e oracle rebuild on dreamproit/uscode, M8a Act-text layer (Statute Compilations), M8 comparative print with two displays, then M7, M9 to M12, and M13 bill and amendment comparison. M6b stays open: the sealed 2023 set measured 2.07% substantive false-clean against the 1% target.

## M6d: Foundations (2026-10-30) — gate PASS

Gate: `scripts/m6d_gate.py` -> `var/m6d_gate.md`. Three parts, each measured on real data before it was relied on.

### USLM 1.x and 2.x

**What changed:** `uslm.to_v1` reads a Code title in either namespace and hands the rest of ramseyer one form (1.0). Every 2.x element moves to the 1.0 namespace under its own name, and the four constructs 1.0 writes differently are rewritten:
- inline `<footnote>` becomes a footnote note, which operative text skips;
- `<list>`/`<listItem>`/`<listContent>` become `<p role="listItem">`;
- a `<crossHeading>`, or a `<heading>` loose in running text or before a unit's number, becomes `<p>`;
- an XHTML `<caption>` becomes the table's first header row.

The indexer applies it on load and logs a `uslm_schema` issue for every converted title; an unknown namespace is logged and not indexed.

**Check** (`scripts/uslm2_check.py`): OLRC's USLM 2.0.12 sample titles 1, 16 and 49 (converted 2023-06-29; aih/uscode-redesign `samples/uslm2`) indexed through the seam and compared with release point 119-134.

| Measure | Result |
| --- | --- |
| Fidelity: indexed text holds exactly the raw 2.x non-whitespace characters, in order | 6,417 of 6,417 sections |
| Sections in both, with identical source credits (compared) | 6,132 |
| … identical in text, heading, structure and status | 4,431 |
| … text differs only in Act-style headings ("(a) In General.—") | 1,602 |
| … only in layout, footnote markers or the case of a status line | 88 |
| … subunit identifiers differ, as OLRC published them in the 2.x file | 16 |
| … differences in OLRC's published data, reviewed one by one | 11 (`tests/oracle/uslm2_reviewed.json`) |

The 11 reviewed:
- 7 are OLRC editorial changes between 2023 and 2026, such as "the the" corrected, a heading recased, or a bracketed note added.
- 4 have the same source credit but different text (1 U.S.C. 112a, 112b; 16 U.S.C. 8018; 49 U.S.C. 329). The first two are most likely delayed amendments that OLRC credited before executing them. All four are to be traced in the release history (M6e).

The 22 duplicate identifiers the 2.x index reports are the 20 that 1.0 has, plus 2 in 16 U.S.C. 1535 (an identifier as published).

### Release-point windows

**What changed:** `oracle/releases.py` reads labels as sets of laws: incorporated(RP, L) = L ≤ (RP congress, RP law) and L not excluded ("not" parts; "uN" re-issues follow their original). A law's window is the first release point that incorporates it and the one published before. This replaces the rule that special-cased a label ending "not<law>" (aih/uscode-redesign ADR-0074).

**Check** (`scripts/release_windows_check.py`):
- All 24 labels on OLRC's prior-release-points page parse, and the order rule reproduces OLRC's publication order.
- Of 88 classified 119th Congress laws, one window changes: 119-102 now runs 119-100 -> 119-102not101, instead of -> 119-102, which also took in 119-101.
- The tuning corpus keeps its pinned window for 119-102: 119-101 touched only Title 12, so the 16 U.S.C. 2201 target was not contaminated.
- The 385 labels of the full 2013–2026 history (with 17 "u1" labels and labels with several "not" parts) are covered by unit tests on their shapes. They are checked against real data when M6e loads them.

### Failure categories and already-executed amendments

**Categories:** every non-CLEAN status maps to one of the House Comparative Print Suite's four notification categories (`engine.category`), reported by `scripts/m6_gate.py`:
- drafting: NOT_FOUND, TARGET_MISSING, AMBIGUOUS, CONFLICT;
- current-law data: STALE_BASELINE;
- system: UNPARSED, NOT_EXECUTED;
- already executed: ALREADY_EXECUTED.

**ALREADY_EXECUTED** is given only where the matched text shows the place: an insertion already next to its anchor, or a replacement that contains the old text and already stands around the match. The engine no longer applies such an edit a second time; it had done so and reported CLEAN. A change that only an earlier instruction of the same bill made is a CONFLICT.

**What measuring it found** (each version run on the tuning gate and the drafting-error benchmark):
1. The first version also used ALREADY_EXECUTED when the struck text was missing and its replacement occurred in the unit. On the tuning corpus 6 instructions got it. Checked against R_before and R_after:
   - 2 were bill-internal (now CONFLICT);
   - 3 were struck words that **are** in R_before but split by OLRC's "So in original" footnote markers ("the the¹ Secretary", "and¹ 14504", "grand² children");
   - 1 was plausibly executed (10 U.S.C. 710a(a)(2)(A), unchanged across Pub. L. 119-60).
2. On the benchmark, that rule called 8 injected drafting errors "already executed". A deletion's replacement is part of the struck text ("and $13,300,000" -> "$13,300,000"), and common words recur ("contract"). Without the struck text there is no place to check. That case is NOT_FOUND again, with a note when the replacement occurs in the unit. The benchmark now lists any injected error called ALREADY_EXECUTED: 0.
3. **Matching across footnote markers:** a quote that occurs once markers are skipped now matches, and the markers (with their notes) go with the words, as OLRC removes them.

On real data ALREADY_EXECUTED is currently given nowhere; its located forms are covered by unit tests.

### Measured, same code (80701d4)

| Set | CLEAN | Substantive false-clean | Change from M6c |
| --- | --- | --- | --- |
| Tuning corpus | 373 of 1,295 (28.8%) | 0 | +10 CLEAN, all right (footnote markers) |
| Tuning, resolved against R_before | 374 | 1 (14 U.S.C. 319, as before) | +10 CLEAN |
| GovInfo 2024 dev half | 119 | 0 | +1 |
| GovInfo 2024 test half (measured only) | 326 | 5 (1.53%) | +20 CLEAN, same 5 wrong |
| **Sealed 2023 set, measured once** | 249 of 729 (34.2%) | **5 (2.01%, 0.86%–4.61%)** | +7 CLEAN, no new wrong; all 5 in the FY2024 NDAA |
| Drafting-error benchmark | — | 94.4% of 787 injected errors detected | was 93.5% |

M6b's 1% target on unseen law is still not met: the five NDAA cases remain. M6e rebuilds the oracle across 2013–2026, which will tell whether they are an NDAA pattern or chance.

**Commands:**
- `.venv/bin/python scripts/m6d_gate.py`
- `.venv/bin/python scripts/uslm2_check.py`
- `.venv/bin/python scripts/release_windows_check.py`

They are listed here until CLAUDE.md's command list (tier 3) is updated.

## M6e: Oracle rebuild (in progress)

### Step 1: the release-point history (2026-10-30)

**What it is:** `oracle/history.py` keeps the dreamproit/uscode `versions` config in one SQLite store under `var/history/`:
- every distinct text of every section, as published, 2013 to 2026 (USLM XML, zlib-compressed);
- the release points;
- which release points published each text.

It can materialize any release point's titles as an ordinary ramseyer index, so the dry-run and the harness read it like an index built from OLRC's zip. USLM 2.x rows go through the M6d seam.

**Loading** (`scripts/load_history.py`; about 10 minutes; 2.6 GB):
- 20 shards, each checked against the dataset manifest's SHA-256, loaded, then deleted.
- 489,738 versions and 5,466,652 version-to-release rows, both equal to the manifest's counts; 381 release points, 113-21 to 119-102not101.

**Three facts about the dataset, each found by checking and now handled:**
1. Two labels (118-22u1, 118-40) are never a version's first or last release, so the dataset gives them no sequence number of their own. Each was placed in the one gap of the sequence its neighbours bracket under the M6d order rule (314, 319). Sequence 77, between 114-219 and 114-221, is a release point with no section rows.
2. A title is loaded at a release point only where OLRC updated it, about 8 titles per release point. A title at a release point is therefore its text at the latest release point at or before it that loaded the title. Without this rule, whole titles were missing from 8 of the 12 release points compared below.
3. One row is a section published inside another: the model agreement's "SECTION 1." (identifier /us/usc/t25/s1) inside 25 U.S.C. 450l, later 5329. The dataset splits it out and leaves the parent without its own subsections. It is left out, as OLRC keeps it, and the parent is logged as `history_incomplete` so it is not graded.

**Check** (`scripts/history_check.py`) against the 12 release points indexed straight from OLRC's zips (`var/oracle/oracle.sqlite`), same titles:

| Measure | Result |
| --- | --- |
| Sections compared | 175,781 |
| Identical in text, heading, status and subunit identifiers | 175,779 |
| Incomplete in the source data, not graded | 2 (25 U.S.C. 5329 at 119-87 and 119-88) |
| Only in OLRC's zips / only in the history | 0 / 0 |
| History labels that parse; publication order reproduced by the M6d rule | 381 of 381; yes (16 with a `u` re-issue, 24 with several excluded laws) |

**Next steps:**
- **Step 2:** the oracle on every law from 113-21 on, with exact before and after release points under the M6d window rule, and a new sealed sample stratified by Congress, committee and title.
- **Step 3:** GPO's tagging as a second reader, draft versions of enacted laws, and Act text in Code notes.

**To watch** (from the M6d review): an end-insertion now removes the footnote marker after the period. Check that against R_after on the wider data.

**Commands:**
- `uv pip install -p .venv/bin/python -e '.[dev,history]'`
- `.venv/bin/python scripts/load_history.py`
- `.venv/bin/python scripts/history_check.py`

### Step 1, follow-up (review of PR #5)

**Loader:** each shard now loads in one transaction with its completion marker, and writing release rows clears the derived title-to-release map.

**`scripts/history_check.py`** now also compares notes (type, heading, text) and source credits. Same result: 175,779 of 175,781 identical in text, heading, status, subunit identifiers, notes and credits; the other 2 are 25 U.S.C. 5329. Not compared: references, chapter-level structure and notes, and section order within a title.

**Older release points** (`scripts/history_govinfo_check.py`):
- OLRC's zips cover only the 119th Congress, so the history, carry-forward rule included, is spot-checked against GovInfo's 2022–2024 editions (OLRC's XHTML, converted by `data/xhtml_uslm.py`).
- Each edition's release point is the first one that incorporates every law enacted by the edition's "current through" date.

| Edition | Release point chosen | Sections | Match there | A neighbour (±2) matches better | No match within ±2 |
| --- | --- | --- | --- | --- | --- |
| 2022 (current through 2023-01-05) | 118-3 | 534 | 490 (91.8%) | 0 | 44 |
| 2023 (2024-01-03) | 118-34 | 1,050 | 979 (93.2%) | 0 | 71 |
| 2024 (2025-01-06) | 119-1 | 1,310 | 1,201 (91.7%) | 1 (42 U.S.C. 1396a) | 108 |

The sections with no match anywhere nearby are converter and editorial differences (the converter's own check is `scripts/xhtml_check.py`).

**A bug in the M6d window rule, found by this check:**
- "118-2not263not328" holds back 117-263 (the FY2023 NDAA) and 117-328 at the start of the 118th Congress. The rule read both as 118th Congress laws.
- Now an excluded number above the label's own law belongs to the previous Congress (`releases.Label.excluded_laws`).
- Two labels in the history are like this (118-2not263not328, 118-3not328); none of OLRC's current labels are, so nothing merged before is affected.

### Step 2: the oracle sets on the history (2026-10-30)

**Classification tables:** OLRC still publishes them for the 113th–118th Congresses. The older ones let a field run into the next column ("nt repealed EG Act113-7", "(C)(ii)1966") and list several pages ("707,708"). The parser now reads the law as the "C-N" token near its column and the trailing page or pages, glued or not. Every table from the 113th to the 119th Congress parses.
- On the 119th tables, 61 rows change, all corrections: a row listing two pages had the first page in the law section.
- Tuning gate unchanged: 373 CLEAN, 0 wrong.

**The sets** (`scripts/build_history_oracle.py`, seed `m6e-2026-10-30`):
- Who is in: every law of the 113th–119th Congresses with a non-note classification row and a window in the history (978), less the laws already in another oracle set, with 39 set aside with reasons.
- How the split is made: within strata (each Congress, and the National Defense Authorization Acts of all Congresses as one stratum), by the best balanced of 1,000 seeded draws (see the follow-up below).
- Which targets are graded: a target another law in the same window also changes is not graded (listed per law in the set's `_touched.json`); old windows often carry several laws.

| Set | Laws | Graded targets | NDAAs | Use |
| --- | --- | --- | --- | --- |
| dev | 286 | 9,589 | 113-66, 113-291, 117-81, 117-263 | may be tuned on |
| test | 280 | 11,342 | 114-92, 114-328, 116-283 | measured only |
| sealed | 281 | 11,356 | 115-91, 115-232, 116-92 | measured once per round, never inspected |

**Running a set:** `scripts/m6_gate.py --set history_dev` (or `history_test`, `history_sealed`). Release points are materialized from the history on demand, keeping 4 on disk (`oracle.history.ReleaseIndexes`). The dev set takes about 4 hours. Its first measurement follows in its own PR.

**Commands (step 2):**
- `.venv/bin/python scripts/history_govinfo_check.py`
- `.venv/bin/python scripts/build_history_oracle.py`
- `.venv/bin/python scripts/m6_gate.py --set history_dev`

### Step 2, follow-up (review of PR #6)

**Fixes from the review** (Codex and the reviewer session):
- Touched sections are scoped to each law's own window (`{"by_law": ...}`), so a section another law changes in a different window stays gradable.
- `--resolve-before` on a history set resolves against the history's own release points.
- The release-point cache is per set, and a cached release point is rebuilt when it lacks a title asked for.

**Balance across the sets:**
- Committees: one plain seeded draw was within chance (median share deviation 0.08; 45% of 500 random assignments were worse).
- Titles: not within chance (2% of random assignments were worse). Dev held 15 of 22 Title 30 laws, 19 of 30 Title 43 laws and 12 of 18 Title 51 laws.
- A law has several titles and committees, so they cannot be strata. The split is now seeded rerandomization: of 1,000 stratified draws, the one with the least title and committee imbalance (chi-square over groups of 10 or more laws) is kept. Median title deviation went from 0.12 to 0.06, the worst from 0.35 to 0.20; committees from 0.08 to 0.07.
- The FY2021 NDAA's title breaks across a line ("National\nDefense"), so it had fallen outside the NDAA stratum. All 10 NDAAs are now in it, 4/3/3.
- The split changed before any set was measured. A stopped dev run on the first split had printed per-law progress lines, but nothing was tuned on them.

**Older release points, the sections matching no release point within ±2** (`scripts/history_govinfo_check.py`, 223 of 2,894):

| Class | Sections | What it is |
| --- | --- | --- |
| equal / rendering | 36 / 40 | the body matches, or differs only in presentation (converter's comparison) |
| footnote markers | 35 | the only differences are 1–2 digit footnote numbers, placed differently or in one edition only |
| order | 4 | the same lines in a different order: the XHTML places a continuation after the next paragraph (5 U.S.C. 419(d)) |
| content, at a later release point | 37 | GovInfo already carries text the history has only later, e.g. 10 U.S.C. 865 (in the history from 118-47, though Title 10 was reloaded at 118-34): amendments OLRC executes on their effective date, and corrections ("Decemeber", quotation marks) |
| content, at an earlier release point | 1 | 50 U.S.C. 3341: GovInfo still has the older text |
| content, at no release point | 70 | the two publications differ: tables and formulas, bracketed citations, heading layout, capitalization |

Stale history would show as GovInfo text found at a later release point together with matches at a neighbour. Only 1 section of 2,894 matches a neighbour better, and the 37 later matches are spread from weeks to months later, not one release point off. Where OLRC's own zips exist (the 119th Congress), the history is identical to them.


### Step 2: first dev measurement (2026-10-30, 7ab7de6)

`scripts/m6_gate.py --set history_dev`: 286 laws from 2013–2026, 2 h 45 min. The gate now writes each graded law to `var/m6e_dev_checkpoint.jsonl` and resumes after an interruption. Two earlier runs were lost to container restarts; the second graded all 286 laws but held every law's run in memory and reopened each mismatch's R_after in the report step. On the tuning set the change leaves the report, traces and baseline byte-identical.

| | Tuning (2025–26) | History dev (2013–26) |
| --- | --- | --- |
| Targets | 1,295 | 7,612 |
| Matched / mismatched / missed | 573 / 343 / 379 | 2,322 / 2,020 / 3,270 |
| CLEAN | 373 (28.8% of targets) | 1,555 (20.4%) |
| CLEAN and wrong in substance | 0 | 120 (7.77%; 95% interval 6.54–9.20%), plus 1 of 3 off target |
| NDAAs / other laws | 0% / 0% | 5.46% / 9.22% |

Every parsed instruction has a status (23,040). The false-clean check FAILS on dev. The 120 are spread over the 113th–117th Congresses (20, 20, 16, 34, 30). A first pass shows three kinds, not yet counted by hand:
- OLRC editorial conventions the detector does not know: references rewritten to Code citations ("section 101" to "section 1021 of this title"), "Repealed" placeholders for struck subdivisions, "(e)(1)" against "(e) (1)", heading capitals, and enactment dates the date rule misses.
- Engine errors: a missing "and" when a list item is inserted, designations built differently from OLRC's structure, apostrophes inside nested quotations.
- Unclear until read against the enrolled text.

Next: classify all 120 by hand (dev may be inspected), teach the editorial detector only conventions confirmed against the enrolled text and OLRC's notes, fix the engine errors, rerun dev, then measure test once.

### Step 2: the dev set's false cleans (2026-10-30/31, claude/m6e-false-clean)

The 120 CLEAN predictions wrong in substance at the first dev measurement were classified by hand (`records/m6e_dev_false_clean.md`): 16 real errors, 12 whitespace only, 59 the comparison's (delayed effective dates, other laws in the window, OLRC departing from the literal instruction), 32 OLRC editorial conventions, 1 unclear. Changes, each with a test:
- The comparison: a section with an OLRC "Amendment of ..." note citing the law is pending; a target another law's amendment-note entries credit in the window is not graded (new outcome "ungradable").
- The editorial checker, now `oracle/editorial.py`, accepts a convention only where it can be checked: enactment dates; Act citations translated to Code citations that our resolver (at R_after, then the pinned index) maps to that section; outside positive law, headings OLRC supplied and catchlines the law does not amend; heading case and closing punctuation; "Repealed" placeholders citing this law; bracketed Code citations; footnote digits attached to a word; a "probable intent" note, for the passages it quotes; whitespace, reported apart.
- Parser and engine: "the second sentence of ..." targets and "the period at the end of the first sentence"; "in each of sections A, B(c), and C" under a chapter (a missing comma included); "Such subsection is further amended"; a Code parenthetical with no space before it; a references clause scoped to a subsection; nested quotations with a plural possessive; repeated closing marks; an inserted em dash; lead-in text before added units; the section heading as against a subsection heading; a unit added at the end of a unit of its own level (WARN); an identical edit made twice (CONFLICT); a table in a bill (kept as a marker, WARN); an unapplied "each place it appears" strike naming no target.
- Found on the way: the release-point history marks no title positive law; the editorial context and `--resolve-before` now take positive-law status from the pinned index (the engine's default resolver already did). A dropped release point that was never fully indexed no longer corrupts the full-text index (earlier in this step).

| | Tuning | Dev, first | Dev, now |
| --- | --- | --- | --- |
| Targets graded | 1,269 | 7,612 | 7,108 |
| Pending / other laws in the window (not graded) | 14 / 19 | 134 / – | 328 / 310 |
| CLEAN | 370 (29.2%) | 1,555 (20.4%) | 1,461 (20.6%) |
| CLEAN and wrong in substance | 0 | 120 (7.77%) | 27 (1.85%; 95% interval 1.33–2.75% with the off-target one) |
| Raw (any difference) | 44 | 250 (16.08%) | 185 (12.66%) |

The dev set's 9,589 classification rows are 7,746 distinct law-section targets, less 134 pending at the first measurement: 7,612.

The 27 remaining (plus 1 off target):
- 15 are OLRC departing from the literal instruction with no note explaining it (a skipped clause, a corrected comma, a stray quotation mark, "180 days December 27, 2020"). They count as wrong until hand-labelled; `tests/oracle/labels.json` is tier 3, so they go to Espen as a separate proposal.
- 3 are another law's delayed amendments (Pub. L. 116-283 title XVIII) executed in the window but listed in OLRC's notes a release point earlier, so the notes cannot show them.
- 9 others: "this part" translated to "this subchapter" (no Act-unit to Code-unit map yet), a subsection heading the engine built into the text, an "Omitted" placeholder, the LIBOR Act citation the resolver does not know, 49 U.S.C. 46102 and 46107 (Pub. L. 115-254 § 1991(f)), 42 U.S.C. 1395m and 300u-11, and #110 (unclear).
Without the 15 OLRC departures: 12 of 1,461 (0.82%) on target.
