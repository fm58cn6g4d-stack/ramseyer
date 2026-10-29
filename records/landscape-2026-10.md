# How billmap compares, and what the official schemas offer (2026-10-29)

Requested by Espen, who asked for a comparison with:
- uscode.linkedlegislation.org and its blog post;
- the dreamproit/uscode dataset;
- the unitedstates GitHub organization;
- a full pass over github.com/usgpo/uslm.

What was read for this record:
- **The architecture blog post.**
- **The site's public status endpoint and OpenAPI document.** The reader at /app is closed to crawling by robots.txt, so it was not fetched.
- **The source repository, aih/uscode-redesign:** README, PLAN.md, ADRs 0002, 0074 and others, and docs.
- **The Hugging Face dataset card and manifest.**
- **The usgpo/uslm main branch and the `proposed` branch:**
  - the User Guide;
  - the 2.0, 2.0.17, 2.1, 2.1.1 and 2.1.2 review guides;
  - the CHANGELOG;
  - the schemas;
  - every sample file was counted for amendment tagging.
- **unitedstates repositories:** congress, citation, uslaw.link, uscode and BillMap.

## The short version

1. **Nobody in this set does what billmap does.**
   - uscode.linkedlegislation.org is a reader for the Code as it stands and as it stood. It has release-point history, redlines between versions and classification-table lookups. It deliberately uses no generative AI in the site.
   - The unitedstates/BillMap project (Demand Progress / FlatGov, also by Ari Hershowitz) finds *similar bills* (Elasticsearch "more like this" at the section level). It does not apply amendments.
   - The `citation` and `uslaw.link` projects extract and resolve citations.
   - None of them parses amending instructions or predicts the amended Code. billmap's core is still unique, but its name collides with BillMap.
2. **The dreamproit/uscode dataset is the biggest single opportunity.**
   - It holds every section's verbatim USLM XML at 381 OLRC release points from 113-21 (July 2013) to 119-102not101, with publication order and currency dates (CC0, about 3 GB of Parquet).
   - OLRC's own site now serves only release points from 119-73not60 on, and older release-point zips return 404 (checked: 113-21 and 118-158). So this is the only practical source of the 2013–2026 history.
   - It lets billmap's oracle test run on thirteen years of laws against the exact release points before and after each. That fixes the red team's F5 (one Congress, mostly the NDAA) and replaces the GovInfo-edition workaround (annual windows and an XHTML conversion).
3. **GPO's USLM bills and laws carry amendment tagging billmap does not use.**
   - Enrolled bills, public laws (PLAW) and the Statutes at Large in USLM mark:
     - each amending verb as `<amendingAction type="amend|insert|delete|add|redesignate|repeal|substitute">`;
     - quotes as `<quotedText>` and blocks as `<quotedContent>`;
     - citations as `<ref href="/us/usc/t29/s3111/b/1/C">`.
   - Counts in the samples:

     | Sample | Amending actions | References to the Code |
     | --- | --- | --- |
     | 114publ113 | 1,408 | 2,154 |
     | Statutes at Large vol. 120 | 13,795 | 6,455 |

   - The schema also defines `@pos`, `@posText` and `@posCount` (the place of an edit) and `<ref idref portion>` (a reference built from an earlier one). None appears in any sample: the published tagging is verb-level only, and it makes mistakes (the verb "adding" in a findings paragraph of H1000_IH is tagged as an amendment).
   - So it can serve as a **second, independent reading** of which verbs and which Code citations an instruction has. It is not a ready-made structured amendment.
4. **The committee-report schema (USLM 2.1.1, proposed) models the Ramseyer / Cordon "changes in existing law" print.** This is the redline House and Senate rules require in committee reports:
   - `<changesInExistingLaw>` > `<existingLaw source="/us/usc/t42@118-34">`;
   - `<deletedText>` / `<addedText>` / `<proposedContent changed="added|deleted">`.

   These prints are produced by the committees and Legislative Counsel for **reported bills that are not yet law**. That makes them the closest public answer key for billmap's real use (drafts against the current Code) and for the M8 comparative print. Today they are published as PDF and text on GovInfo (CRPT); the USLM form is a proposal.
5. **OLRC plans to move the Code itself to USLM 2.x**, namespace `http://schemas.gpo.gov/xml/uslm`. Source: OLRC's migration note, cited in aih/uscode-redesign ADR-0002. The note's page is offline while uscode.house.gov runs in a temporary format.
   - Sample titles exist in USLM 2.0.12.
   - **billmap's indexer hardcodes the 1.0 namespace.** On the day OLRC switches, billmap would index nothing.
   - Per OLRC, the main differences for the Code are tables of contents, tables and the indent model; 2.0.17 adds MathML.

## What billmap already does the same way (and should keep)

- **The USLM identifier as the key** (`/us/usc/t16/s45f/c/5`), section as the unit of storage, release point stamped on every output. The User Guide's referencing model (§12) and both projects agree.
- **Deterministic text comparison and no model in the statute-text path.** The linkedlegislation author draws the same line for an official site: AI is acceptable for documentation, not in the search or text-comparison features of the site.
- **Classification tables as the attribution source.**
- **A dual-schema seam is still missing** (see 5 above).

## Lessons from aih/uscode-redesign that apply to billmap

| Their finding | What it means for billmap |
| --- | --- |
| Release-point labels do not describe their contents. `116-344not283u1` → `116-344` is Pub. L. 116-283 entering, below both labels. Use incorporated(RP, L) = L ≤ (RP.congress, RP.law) and L not in RP's excluded laws (ADR-0074). | billmap's `Discovery.window` only special-cases a label ending "not<this law>". Checked on the tuning corpus: no target is contaminated (the builder already drops sections another law in the window touches; 0 of 1,699), but the rule must be replaced before using 381 release points. 17 of 385 labels carry a `u1` re-issue suffix, and some have several "not" parts (`277not255not268`). |
| In the release history, 72.7% of section version transitions are structure-only (converter drift, whitespace), 18.9% notes-only, 8.4% text. Compare whitespace-removed text. | billmap compares normalized text already; early (2013–2015) release points have converter attribute drift, so the oracle on older laws must normalize the same way. |
| Only 50.5% of text transitions match a classification row in their window. | The classification-table answer key is incomplete: a law can change sections OLRC did not classify to it. The off-target grading added in M6c must allow for this (sections no window law is classified to can still change). |
| `@id` GUIDs are regenerated at every release point; `@identifier` is the cross-release identity; renumbering and transfers break identifier continuity (`status="transferred"`). | billmap already keys on `@identifier`. Transfers and renumberings (several M6b misses) need a redirects map. |
| 160 (identifier, release) pairs publish two elements under one identifier. | billmap's index assumes one node per identifier; check how the indexer handles duplicates. |

## USLM elements billmap does not use yet

| Element or attribute | Where | Use for billmap |
| --- | --- | --- |
| `<amendingAction type>`, `<quotedText>`, `<quotedContent>`, `<ref href>` in bills and laws | GovInfo BILLS / PLAW / STATUTE in USLM | Independent second reading: billmap's parse versus GPO's tagging, instruction by instruction. A disagreement (a verb billmap missed, a Code citation it resolved differently) lowers CLEAN to WARN. Measurable on every enrolled law in USLM. |
| `@status` on levels (`repealed`, `transferred`, `renumbered`, `omitted`, `reserved`) | Code XML | Predict repeal stubs and transfers. Read status rather than text patterns. |
| `<note topic=…>` / `@role` (e.g. amendments, effective date notes) | Code XML | Find "Amendment of Section" (delayed) notes and Act text set out in notes by topic rather than heading text. |
| Act text quoted inside notes ("… provided that: “…”") | Code XML | **583 of about 3,400 tuning instructions (17%)** amend Act text in a note (363) or uncodified text (220) and are NOT_EXECUTED today. The 363 note cases could be dry-run against the note's quoted text and graded against the next release's note. |
| `<changesInExistingLaw>` / `<deletedText>` / `<addedText>` | Committee reports (2.1.1, proposed); PDF/text today | An answer key for reported, not-yet-enacted bills, and a model for M8's output format. |
| USLM 2.x namespace and models | Code (announced), bills and laws now | Namespace-agnostic parsing in the indexer and xmltext. |
| Amendment documents and engrossed amendments (2.1) | Floor amendments | Later: amendments that amend a bill rather than the Code. |
| Statute Compilations (COMPS) in USLM | GovInfo | Current text of major Acts not codified in Code text; a baseline for the 220 UNCODIFIED cases where a compilation exists. |

## unitedstates organization

| Repository | What it does | Relevance |
| --- | --- | --- |
| congress | Collectors for bills, BILLSTATUS, votes, Statutes at Large, GovInfo bulk data | A tested downloader for bill text versions (introduced, reported, engrossed, enrolled). Useful for the "introduced version" robustness test the red team proposed (F16). |
| citation | Regex citation extractor (U.S.C., Pub. L., Stat., CFR) | Same job as billmap's cite patterns; its test cases (ranges "10a-10c", "App.", "note", "et seq") are worth adding to billmap's unit tests. |
| uslaw.link | Citation resolver with parallel citations (Stat. ↔ Pub. L. via GovInfo MODS) | Parallel citations help resolve "Act of <date>" targets: an independent witness for the date-to-law lookup billmap does from source credits. |
| uscode | 2014 Code parser (archived) | Superseded. |
| BillMap | Similar-bill finder (FlatGov) | Different purpose; **same name**. |
| legisworks-historical-statutes | Statutes at Large metadata to 1951 | Old Acts cited by date and chapter. |

## Proposed changes to the plan (for Espen)

1. **Rebuild the oracle on dreamproit/uscode.**
   - Every law from 113-21 on, with exact before/after release points under incorporated-set windows.
   - A sealed held-out sample stratified by Congress, committee and title, never looked at case by case.
   - This replaces the GovInfo-edition sets for measurement; keep them as a cross-check.
2. **A dual-schema seam now:** namespace-agnostic indexer and parser, tested on the USLM 2.0.12 sample titles.
3. **GPO tagging as a second reading** for enacted laws, measured on the oracle: how often billmap and GPO disagree, and how often a disagreement marks a real error.
4. **Dry-run amendments to Act text in notes** (17% of instructions today).
5. **Ramseyer / Cordon prints as the draft-stage answer key.** Collect a sample of committee reports with "changes in existing law" sections, extract their redlines, and grade billmap on the reported bills. This is the measurement closest to the real use, and it should come before M8.
6. **Rename billmap** to avoid confusion with unitedstates/BillMap.
