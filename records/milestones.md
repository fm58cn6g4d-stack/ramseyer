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

**Run:** `.venv/bin/billmap sync` (3.3 min) then `.venv/bin/python scripts/m1_gate.py` (about 30 s); output in `var/m1_gate.md`.

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

`billmap sync` now cross-checks every section against the XHTML edition and stores each difference
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

**Built:** `billmap.statute.StatuteService`, with 11 tools: resolve_cite, get_section (operative, plain or
xml; as_of), get_pincite, cross_refs, cited_by, definitions, neighbors, search (FTS5 BM25), changes,
coverage, act_to_code. Thin wrappers expose them as an MCP server over stdio (`billmap serve-mcp`,
MCP SDK 2.3) and as a CLI (`billmap statute <tool> k=v`). Sample client configs are in `README.md`.

**Run:** `.venv/bin/python scripts/m2_gate.py` (52 s with a cold page cache); output in `var/m2_gate.md`.

| Check | Result | Measured |
| --- | --- | --- |
| Tools work over MCP (stdio client spawns `billmap serve-mcp`) | PASS | 11 tools listed; 7 calls, each with release point 119-134; the deliberate bad cite returns a structured not_found |
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

**Harness** (`billmap.oracle.harness`): a predictor returns, per law, a status and the predicted
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

**Built** (`billmap.parse`):
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
- **CLI:** `billmap parse draft.txt --out ir.json`.

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

**Built** (`billmap.resolve`):
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
- **Wiring:** the statute server's `act_to_code` tool now uses the resolver, and `billmap resolve "<target as drafted>"` runs it from the command line.

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

**Built:** `src/billmap/dryrun/engine.py` applies parsed instructions, in bill order, to a working copy of
each section's USLM XML at the law's R_before release point. Text edits run on a linear view of the scope's
text mapped back to the XML text nodes. New units are built as USLM elements from the quoted block.
`src/billmap/dryrun/predict.py` runs parse, resolve and dry-run for a bill, one prediction per Code section
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
- **Files:** `scripts/build_heldout.py` writes `tests/oracle/heldout.json` and builds `var/oracle/heldout.sqlite`. Selection is shared with the tuning corpus through `src/billmap/oracle/candidates.py`; the tuning manifest is reproduced byte for byte.
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
- **Converter:** `src/billmap/data/xhtml_uslm.py` turns OLRC's XHTML into USLM, and the standard indexer loads it as release points `usc-2023` and `usc-2024` in `var/oracle/govinfo.sqlite`.
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

**Self-checks (`src/billmap/dryrun/verify.py`):** independent of R_after. They lower a CLEAN section to WARN when:
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
