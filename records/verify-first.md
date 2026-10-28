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

## M3 (checked 2026-10-28)

| Item | Finding |
| --- | --- |
| Prior release points | `https://uscode.house.gov/priorreleasepoints.html` lists 24, from 119-134 back to 119-73not60 (January 23, 2026). Each entry is `<a class="releasepoint" href="download/{label}.html">Public Law {label} ({date}), affecting titles ...</a>`. Older labels (e.g. `download/118-158.html`) return 404. A release point page has the same layout as `download.html`, with zips under `download/releasepoints/us/pl/{congress}/{law}/` |
| "Except" release points | `119-73not60` (through 119-73 except 119-60) and `119-102not101` exist. The label carries the exception, and so do the zip names (`xml_usc49@119-73not60.zip`). The "not" release point comes before the plain one, which is the first to include the held-back law |
| Newer release point | 119-136 (October 22, 2026) is now current. The pin stays at 119-134 until a deliberate re-index |
| Congress.gov law endpoint | `/v3/law/{congress}/pub/{number}` returns `bill.type`, `bill.number` and `bill.title`; e.g. 119-75 is H.R. 7148 |

## M5 (checked 2026-10-28)

| Item | Finding |
| --- | --- |
| Popular Name tool | `https://uscode.house.gov/popularnames/popularnames.html` is one 8 MB page with 13,661 names. Each entry is `div.popular-name-table-entry` > `p.popular-name` plus one or more `p.popular-name-information[content-type=cite]`, whose `t3searchkey` is a public law ("107-188") or year:chapter ("1944:373"), with `datekey` the enactment date. Each entry also has a `release-point` attribute (119-136 on the day fetched) |
| Positive-law titles | The browse page marks positive-law titles with "*" ("This title has been enacted as positive law. However, any Appendix to this title has not been enacted"). Its 27 titles (1, 3, 4, 5, 9, 10, 11, 13, 14, 17, 18, 23, 28, 31, 32, 35, 36, 37, 38, 39, 40, 41, 44, 46, 49, 51, 54) are exactly the titles whose XML has `is-positive-law = yes` |
| Source-credit links | For Acts cited by date and chapter, the credit link is `/us/act/1944-07-01/ch373` with no section. The Act section appears only in the credit text ("title III, §317U, as added …"). Links for public laws carry the full path (`/us/pl/116/94/dN/tI/s404/b`) |
| Act text in notes | Statutory notes that carry an Act section's text open with its citation and "provided that:" ("Pub. L. 116–283, div. A, title V, § 589, Jan. 1, 2021, …, provided that:"). Notes on a chapter heading are what OLRC cites as "note prec. <first section>" |
| Delayed amendments | An amendment with a delayed effective date is not executed at the next release point. It appears as an "Amendment of Section" note ("provided that, effective one year after Dec. 18, 2025, this section is amended as follows: …") |

## M6 (checked 2026-10-28 on the oracle corpus)

| Item | Finding |
| --- | --- |
| Heading ".—" | Follows the amended unit's existing style, not the title. 15 U.S.C. 2625(b) (title 15, not positive law) keeps ".—"; other subsections of the same section have none |
| Heading case | In positive-law titles, subsection headings are title case. Prepositions such as "With", "From" and "Under" are capitalized. The part after a hyphen is lowercase in 210 of 378 cases, so it is left as drafted. Paragraph and lower headings are sentence case: OLRC printed "Senior leader of the coast guard" for the bill's "Senior leader of the Coast Guard". In non-positive titles, OLRC also fixes case editorially ("Sunshine act", "PDP sponsors"), which is unpredictable |
| Footnotes | Two markups: `<ref class="footnoteRef">n</ref><note type="footnote">…` and ` <sup>n</sup>`. OLRC removes a footnote attached to words an amendment replaces (10 U.S.C. 139a, "section 2334"). It adds "So in original" footnotes where an amendment leaves an odd result |
| Bracketed cites | OLRC's "[42 U.S.C. 5121 et seq.]" after an Act name disappears when the Act name is struck (42 U.S.C. 5306, 5321) |
| Delayed effective dates | 119-60 § 6404(g) delays § 6404(c) by 180 days. At R_after, 50 U.S.C. 3025 shows an "Amendment of Subsection (c)" note, while the same section's immediate amendment (§ 6402(c)(2)(A)(i)) is executed |
| Codification | 119-60 § 3111 enacts the Atomic Energy Defense Act as 10 U.S.C. 6101 ff. OLRC's text differs from the bill's quoted text: some paragraph headings are absent ("(1) Not later than …" where the bill has "(1) Initial briefing.—"), and later amendments in the same bill to the AEDA's title 50 sections are carried in |
| OLRC deviations from the enrolled text | "section section 3221" (10 U.S.C. 139a); "18 months" without the apostrophe (46 U.S.C. 7307–7309); an insertion at "regular component" where the law says "reserve component" (37 U.S.C. 204(h)(1)); a SAFE Port Act provision placed in 46 U.S.C. 70001 as subsection (l). These are labelled editorial in `tests/oracle/labels.json` |

## M6b (checked 2026-10-28)

| Item | Finding |
| --- | --- |
| Older Code snapshots | OLRC's prior release points start at 119-73not60 (January 2026). Guessed URLs for annual archives (`download/annualhistoricalarchives/...`, `download/annualtitlefiles.shtml`) return 404, and `download.html` links only "Prior Release Points" |
| govinfo annual editions | `api.govinfo.gov/packages/USCODE-{year}-title{N}/summary` exists (e.g. `USCODE-2024-title49`, dateIssued 2024-12-31), with txt, pdf, zip, mods and premis links but no USLM link. The title 49 zip is 265 MB; the download through the proxy cut off at 202 MB |
| Free-standing provisions | The Code's editors classify free-standing bill sections as new Code sections (classification row "new", no amending instruction): 119-94 § 2 -> 34 U.S.C. 51101, 119-129 § 2 -> 15 U.S.C. 45g |
| New Act sections | A new Act section gets an editor-assigned Code number: Federal Power Act § 37 "after section 36 (16 U.S.C. 823g)" -> 16 U.S.C. 823h; Social Security Act § 714 -> 42 U.S.C. 915 |

## Held-out sources suggested by Espen (checked 2026-10-28)

| Source | Finding |
| --- | --- |
| uscode.ecfr.io (`/api/v1/titles`, `/search`, `/section`; MCP at `/mcp`) | Free, no key. It serves only its current OLRC release: 119-134 on 2026-10-28, ingested the same day. There is no date or release parameter (OpenAPI: `path`, `offset`, `length` only), so it gives no history. Section text is flattened ("(a) In generalAll money …"). Usable only as a second current-text cross-check |
| github.com/CourtGPT/us-code | A JSON mirror of OLRC, flattened to section `text`. Its history is 4 commits, with one data snapshot (release 119-100, 2026-07-13), so it has no earlier versions |
| GovInfo USCODE collection (api.govinfo.gov with the api.data.gov key) | 1,552 packages, annual editions from 1994. Title 49's 2023 edition has 1,761 granules, one per section (e.g. `USCODE-2023-title49-subtitleV-partC-chap243-sec24301`), with htm, pdf, mods and premis links but no USLM. The htm is OLRC's XHTML: `documentid`, `itempath`, `currentthrough` comments, `field-start:statute`, and `p.statutory-body`, `-1em`, `-2em` with the enumerators inline. Currency: 2023 edition `currentthrough:20240103`, 2024 edition `currentthrough:20250106` |
| GovInfo bulk data (github.com/usgpo/bulk-data; `www.govinfo.gov/bulkdata/{json,xml}/...` with an Accept header) | 15 collections: CFR, FR, BILLSTATUS, CBD, PPP, SCD, BILLS, GOVMAN, BILLSUM, PAI, ECFR, HMAN, PLAW (USLM beta, Congresses 113–119), STATUTE (USLM beta) and COMPS (USLM beta). **No USCODE**: `bulkdata/json/USCODE` returns 404. COMPS is one file per compiled Act (e.g. `COMPS-10282.xml`) plus `COMPS.zip`, current versions only. None of these gives a dated Code snapshot |
