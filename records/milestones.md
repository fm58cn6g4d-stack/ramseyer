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

**Open items found by a full-population text comparison** (beyond the gate; not yet fixed):
- Every section compared against the XHTML: 52,833 equal and 491 differ (0.9%). Most differences
  are rendering: fractions (⅓ against 1/3), blank-line lengths, formulas, Unicode normalization, dot leaders.
- **Likely extraction bug: tables.** Table body rows appear to be missing or reordered in
  `text_plain` for roughly 10 sections (e.g. 38 U.S.C. 1311 and 42 U.S.C. 7412, 7511, 7521, 7541).
  The tables use the XHTML namespace inside USLM. Fix this before M2's spot checks.
- **Decision pending: bracketed status text on subunits.** "[Repealed.]", "[Omitted]" and "[reserved]" sit in a
  `<note topic="miscellaneous">` inside the subunit (e.g. 12 U.S.C. 1464(g)). The index treats them as
  notes; the XHTML prints them in the statute text. For the dry-run, it may be better to show
  them as the unit's status.
- **Data defect in the OLRC XML:** "Medicare+ÐChoice" carries a stray "Ð" in about 15 title 42 sections;
  the XHTML has "Medicare+Choice". Quote matching in M6 must expect it.
