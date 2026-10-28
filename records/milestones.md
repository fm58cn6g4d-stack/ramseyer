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
