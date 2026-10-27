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
| Congress.gov API | BLOCKED | No `API_DATA_GOV_KEY`. The shared DEMO_KEY is rate-limited (429) |
| Congress.gov bill text | PASS | `BILLS-119hr1enr.xml` from congress.gov, 1,754,658 bytes, root `<bill>` (URL built from the pattern, not from the API) |
| govinfo bulk data | PASS | `BILLS/119/1/hr` lists 8,042 XML files; `PLAW/119/public` lists 132; one bill XML downloaded |

**Gate status:** the download gate passes; all three required downloads succeed. The
Congress.gov API row stays open until a key is in `.env`. Bill text needs no API, so M1 to M3
can proceed. The API is needed only for bill metadata, such as version listings.

Unit tests: 10 passed (`pytest -q`), all offline.
