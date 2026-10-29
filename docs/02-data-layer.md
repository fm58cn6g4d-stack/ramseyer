# 1 Data layer

The data layer turns official, free files into one local SQLite index that every other component queries. Nothing else in the tool holds statute text.

## Sources

| Source | Use | Format | Notes |
| --- | --- | --- | --- |
| OLRC U.S. Code release points | Primary statute text | USLM XML, one zip per title or all titles | Each release point is labeled by the last public law included; keep the current one plus four prior for as-of checks |
| OLRC classification tables | Cross-check for Act-to-Code mapping | HTML, one pair per session | Recent laws only; older tables sit on a prior-tables page |
| OLRC Popular Name tool | Act name to public law number | HTML | Scrape once and cache |
| Congress.gov API v3 | Introduced and enrolled bill text, laws, amendments | JSON with links to XML text | Free key; used for the test corpus and for published bills |
| govinfo bulk data and API | Public law text, bill status, Code mirror | XML | Same api.data.gov key |
| eCFR API | CFR text for v2 ripple edges | JSON or XML | No key |

## Index schema (SQLite)

| Table | Key columns | Purpose |
| --- | --- | --- |
| release\_points | id, label, date, loaded\_at | One row per loaded release point |
| nodes | id, rp, title, parent\_id, kind, num, heading, path, status, text\_plain | Every unit from title down to subparagraph; status is current, repealed, omitted or transferred |
| refs | src\_id, dst\_id, dst\_raw, kind, rp | Cross-references; kind is usc, act, cfr, stat or internal |
| notes | section\_id, note\_type, text | Statutory notes, including References in Text, Effective Date and Short Title |
| source\_credits | section\_id, pl, pl\_section, date, raw | Parsed Pub. L. credit lines; feeds Act-to-Code in tab 4 |
| definitions | section\_id, term, scope\_id | Terms defined by In this chapter, the term patterns |
| text\_hash | node\_id, rp, hash | Drives as-of diffs and incremental reloads |
| fts\_nodes | heading, text\_plain | FTS5 index with BM25 ranking |

## Build steps

1. Fetch the release point page; record the label and per-title currency.
2. For each title, stream-parse the XML with lxml iterparse and keep the identifier attribute of every unit.
3. Flatten each section into subsection-level nodes with a path like (a)(2)(B); keep plain text and original XML offsets.
4. Extract refs from reference elements; resolve targets to node ids where possible, else store dst\_raw with a reason.
5. Parse source credits and notes into their tables.
6. Detect defined terms with a conservative pattern and mark each definition's scope.
7. Build the FTS5 index and the hashes.

## Incremental updates

A weekly `ramseyer sync` checks the release point label, reloads only titles marked updated, and keeps prior release points according to ramseyer.toml.

## Invariants (tests)

- Every node has a non-null id, kind and path
- Section count per title matches OLRC's own listing
- 100 random sections round-trip from cite to node to text
- Every ref either resolves or is stored with dst\_raw and a reason
- Every query function returns the release point label with its results

Measure the index size in M1 and record it; with FTS expect gigabytes, not megabytes.
