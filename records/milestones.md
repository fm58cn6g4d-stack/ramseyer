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
- **Act targets:** 63% of corpus instructions target Acts, through an Act section plus a parenthetical
  U.S.C. cite (the resolver's Act-to-Code job), not Code sections directly.
