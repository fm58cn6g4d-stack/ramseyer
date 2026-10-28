# Verify-first findings

Each item flagged "verify first" in `docs/`, checked against the live source before use.

## M0 (checked 2026-10-27, release point 119-134)

| Item | Finding | Source |
| --- | --- | --- |
| Per-title XML zip URL pattern | `download/releasepoints/us/pl/{congress}/{law}/xml_usc{NN}@{congress}-{law}.zip`, relative to `https://uscode.house.gov/`. `NN` is a zero-padded title number with an `a` suffix for appendices (`05a`, `11a`, `18a`, `28a`, `50a`). All titles: `xml_uscAll@{label}.zip` (108.7 MB at 119-134). Other formats swap the `xml_` prefix for `htm_`, `pcc_`, `pdf_`. 58 per-title XML links at 119-134 (no title 53). | https://uscode.house.gov/download.html |
| Release point page location | The plan's old `download/download.shtml` path now returns 404. The page is `download.html`; the root `/` redirects to `browse.html`. The label is in `<h3 class="releasepointinformation">Public Law 119-134</h3>`; the date is in `p.releasepointdescription` ("current through Public Law 119-134 (October 20, 2026)"). Prior release points: `priorreleasepoints.html` (not yet parsed; needed in M3). | same |
| USLM identifier format | Confirmed as expected: sections carry `identifier="/us/usc/t4/s1"`; title root `<uscDoc identifier="/us/usc/t4">` in namespace `http://xml.house.gov/schemas/uslm/1.0` (schema USLM-1.0.15). Chapters use `/us/usc/t4/ch1`. `meta/docPublicationName` is `Online@119-134`, which gives a second, in-file release point stamp. Each zip holds one member (`usc04.xml`). | `xml_usc04@119-134.zip` |
| Classification table structure | Index at `classification/tables.html` (not `.shtml`) links `tbl119pl_1st.html`, `tbl119pl_2nd.html` (Public Law order) and `tbl119cd_*` (Code order). The rows are fixed-width text in a `<PRE>` block, not an HTML table. Columns: Title, Section, Description, Pub. L., Sec., Stat. page. Quirks found: the Stat. page can be a range (`762-764`), and a quoted new-section label can run into the page column with no space (`7201(c)(1) "Subchapter I"1677`). The parser takes column starts from the header line and raises on any line it cannot fit. 119th 1st session: 3,049 rows; 2nd session: 647 rows, PL 119-70 to 119-134. | https://uscode.house.gov/classification/tables.html |
| Temporary site format | Every OLRC page carries "currently operating in a temporary format" (2026-10-27). Fetchers are small and pinned by fixture tests in `tests/unit/test_olrc.py`. | all OLRC pages |
| Congress.gov API | Needs an api.data.gov key. The shared `DEMO_KEY` returns 429 OVER_RATE_LIMIT, and a missing key returns 403. Verified with a key on 2026-10-28: `/bill/119/hr/1/text` lists 6 text versions. Each version offers `Formatted XML` (GPO bill DTD, root `<bill>`), and some also offer `United States Legislative Markup` (`*_uslm.xml`, namespace `http://schemas.gpo.gov/xml/uslm`). The Public Law version has only the USLM form (`PLAW-119publ21_uslm.xml`). `congress.xml_urls` picks a format by name, never by position. | https://api.congress.gov/v3/ |
| Congress.gov bill text files | Downloadable without a key at `https://www.congress.gov/{congress}/bills/{type}{number}/BILLS-{congress}{type}{number}{version}.xml`. The same file is at `https://www.govinfo.gov/content/pkg/BILLS-.../xml/BILLS-....xml` (byte-identical size for 119 hr 1 enr: 1,754,658). | direct fetch |
| govinfo bulk data | JSON listings at `https://www.govinfo.gov/bulkdata/json/{collection}/{congress}/{session}/{type}`, no key. Each entry has `link`, `size`, `fileExtension`. `PLAW/119/public` lists 132 entries. | direct fetch |

## M1 (checked 2026-10-28, release point 119-134)

| Item | Finding |
| --- | --- |
| All-titles XML zip | 58 members, 698 MB uncompressed. Member names mix case: `usc05A.xml`, but `usc11a.xml` |
| Appendix titles | 5a, 11a, 18a, 28a and 50a use a top-level `<appendix identifier="/us/usc/t5a">` in place of `<main>`. Court rules use identifiers such as `/us/usc/t18a/courtRules/Crim/rule1`, and some 11a rules have no title in the identifier (`/us/usc/ptI/rule1002`). 18a compiled Acts use `/us/usc/t18a/pl/91/538/s1` (no U.S.C. citation form) |
| Section-number dashes | 5,416 section identifiers use an en dash (`s136a–2`); none use an ASCII hyphen |
| Multi-section and range identifiers | A single `section` element can carry several identifiers separated by spaces (`/us/usc/t2/s3 /us/usc/t2/s4`) or a range (`/us/usc/t2/s1001...1004`). The index stores every identifier. Ranges are not expanded, so "2 U.S.C. 1002" returns not_found; the resolver (M5) must check ranges |
| Unidentified sections | Sections quoted inside notes have no identifier and are not Code sections. The repealed or transferred stubs of appendix compiled Acts (5a, 18a) also have none. The index gives them synthetic identifiers marked `~` (`synthetic=1`) |
| Markup error | 25 U.S.C. 5329 contains a model agreement whose "SECTION 1." is marked up as a real section claiming `/us/usc/t25/s1`. Sections nested inside sections are not indexed; their text stays with the enclosing section (`load_issues`) |
| Duplicate section numbers | 15 section identifiers occur twice (e.g. 10 U.S.C. 130g). Lookups return `ambiguous`, never one of them |
| Status values | current 51,009; repealed 5,131; omitted 2,037; transferred 1,911; renumbered 368; vacant 17; reserved 16; unknown 1 (sections) |
| Ref hrefs | `/us/pl/{congress}/{law}/[dX/][tX/]s{sec}/...`, `/us/stat/{vol}/{page}`, `/us/act/{date}/ch{n}/s{sec}`, `/us/usc/...`. Footnote markers are `<ref class="footnoteRef">` with no href |
| Soft hyphens | The XML contains U+00AD ("Psycho\xadtropic"). `text_plain` strips them; the stored section XML keeps them |
| XHTML edition | Independent per-title listing via `<!-- itempath:... -->` comments: "Sec. N", "Secs. 3, 4", "[Sec. 2" for repealed, "130g_2" for duplicates. One section can span two documents (18a § 2). Three files contain GPO locator escapes (`\xffAE1`) that are not valid UTF-8 |

## M2 (checked 2026-10-28)

| Item | Finding |
| --- | --- |
| Section pages on uscode.house.gov | The site is still in its temporary format. A section lives at `https://uscode.house.gov/us/usc/{release point}/t{title}/s{section}/`, e.g. `/us/usc/119-134/t4/s1/`; the unversioned `/us/usc/t4/s1/` is the current one. The section number uses an ASCII hyphen (`s1395w-22`); an en dash returns 404. Multi-section stubs live at their first number (`/t2/s3/` shows "§§3, 4"). The old `view.xhtml?req=granuleid:...` links return 404 |
| Page structure | `<span class="lawsInEffect">Text contains those laws in effect through Public Law 119-134 (October 20, 2026).</span>`, `<h3 class="section-head">`, body in `statutory-body*` elements, then `<p class="source-credit">`, then notes. The page inserts U+2060 (word joiner) before em dashes |
| MCP Python SDK | Version 2.3.0: `FastMCP` is now `mcp.server.mcpserver.MCPServer`, and `CallToolResult.structured_content` is snake_case. Tools run in a worker thread, so the read-only SQLite connection uses `check_same_thread=False` |
