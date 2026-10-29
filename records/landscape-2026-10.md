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

## The House Comparative Print Suite (added 2026-10-29)

The suite is the most direct analog to ramseyer, as Espen pointed out. It is internal to the House; there is no public version. Sources:
- Hershowitz and Mador-Haim, "“Comparative Prints Suite” of the United States House of Representatives", JURIX 2023, doi:10.3233/FAIA230993;
- the Clerk's quarterly reports to the Committee on House Administration (QR1, 15 October 2020; QR10, 30 December 2022);
- the POPVOX write-up.

**What it is:**
- Built by the Clerk's Legislative Computer Systems with the House Office of the Legislative Counsel (HOLC) and contractors: Xcential, plus XCiteDB, a version-controlled XML database with "branches".
- Required by clause 12 of rule XXI.
- Live at compare.house.gov since October 2022 for House staff, with instances for CBO, the Library of Congress (CRS, which uses it for bill summaries) and the Joint Committee on Taxation. Senate staff asked for access.

**Its tools:**
1. **How a Bill Changes Current Law** (two versions). Its print is patterned on the Ramseyer report.
2. **Bill to Bill Differences**: any two versions of a bill, resolution or amendment.
3. **How an Amendment Changes a Bill**: the amendment impact program, carried over from HOLC.
4. **Bill Viewer**, with planned "smart reading": defined terms, effective dates and short titles listed in the outline. The Clerk's report argues that free-standing provisions matter as much as amendatory ones.

**Parsing:**
- AMPL, the Amendment Modeling and Parsing Language, is a model grammar for amending instructions.
- CIMPL is the same for citations.
- Neither is published.

**Point in time:**
- Every comparison is "on-demand, point-in-time".
- A bill is processed against the law as of its introduction or as of today, using XCiteDB branches.

**Current-law repository:**
- Positive-law titles of the Code, the Statutes at Large, and HOLC's Statute Compilations (also published in USLM on GovInfo, COMPS).
- Non-codified law is in scope.

**Automated notifications** (the suite's equivalent of ramseyer's non-CLEAN statuses):
- Each says why an amendment could not be carried out:
  1. an error in drafting (typos, wrong citations);
  2. an error in the current-law data;
  3. an error in the system (an unsupported instruction);
  4. **the amendment has already been executed into current law.**
- Example messages: "The Act being amended could not be found", "The provision of the Act could not be found", "The range of provisions could not be found".
- The outline groups all amendments to one law together, in execution order rather than bill order.

### Where ramseyer stands against it

| | Comparative Print Suite | ramseyer now |
| --- | --- | --- |
| Bill → current law | Yes (Code, Statutes at Large, compilations) | Code text; Act text in notes and uncodified Acts reported NOT_EXECUTED (17% of instructions) |
| Bill → bill (versions) | Yes | No |
| Amendment → bill | Yes | No |
| Draft → adopted Act | Through bill-to-bill comparison when the vehicle is the same bill | No |
| Point in time | Introduction date or today | Pinned release point; STALE_BASELINE searches earlier ones; the 2013–2026 history is available but not loaded |
| "Already executed" detection | Yes | **No** (a struck text that is gone with the inserted text present is reported NOT_FOUND) |
| Measured accuracy, published | Not public | Oracle on enacted law, sealed set, error-injection benchmark, red-team report |
| Availability | House staff and some legislative-branch agencies | Open; anyone, including Senate staff, outside groups and the public |

**The case for ramseyer:** the suite's existence shows that the House values this kind of tool, and that model grammar plus a versioned law store is the working design. ramseyer's room is in being open, auditable (measured against the enacted record, with the method published) and strict about never dropping an instruction. It also offers checks the suite describes but cannot show publicly. Committee reports' "changes in existing law" sections are now probably produced with the suite, so grading ramseyer against them amounts to grading it against the suite and HOLC.

## Draft bill → the Act it amends, as currently in force (Espen, 2026-10-29)

Espen's point: compare a draft not only with the Code but with **the current text of the Act it amends**.

**The second current-law source:**
- It is the Act as amended, which is what drafters write against: "Section 5 of the X Act".
- It comes from HOLC's Statute Compilations: about 2,710 USLM files in GovInfo bulk data (`bulkdata/json/COMPS`).
- Each states its currency, e.g. `<currentThroughPublicLaw>116–260</currentThroughPublicLaw>` for the Geothermal Steam Act of 1970.

**The two sources are two witnesses:**
- **In a positive-law title**, the Code is the law and is the only text.
- **In a non-positive title**, the Act is the law; the Code is prima facie evidence, and OLRC rewrites the Act's text into Code form ("this Act" → "this chapter", Act section numbers → Code cites).
- **Executing against both is a cross-check.** Run a draft against the Act's own text, then against the Code text, and compare where the two land:
  - A quote found in the Act but not in the Code points to OLRC's editorial form.
  - A quote found in neither points to a drafting error or a stale draft.
  - A quote found in both, with the same effect, is the strongest result ramseyer can give.
  - Several of ramseyer's WARN and NOT_FOUND classes today are Code-form mismatches that the Act text would settle directly.

**Two displays, chosen per provision:**
- **An amendment to existing text** gets a comparative print in context: the existing law with struck and inserted text, Ramseyer-style.
- **A draft that largely creates new statute** gets a different view (a new section, a new chapter, a free-standing program):
  - the new provisions as structure;
  - where they would sit (inserted after section X of chapter Y; or, for free-standing text, an estimated classification, labelled as an estimate);
  - what existing law they lean on (definitions used, cross-references, conforming amendments).

  Most bills mix both, so the choice is made per provision.

## Testing on draft versions of enacted laws

The point in this section was raised in the discussion and kept as a method:
- An enacted law's change to the Code is known from the release points.
- Its earlier versions (introduced, reported) can be run through ramseyer as if they were drafts.
- Their predicted changes can be graded against what the enacted version actually did, wherever the provision was carried into law.

**The second layer:** match a draft (or an introduced or reported version) to the Act as adopted, and show what survived, what changed and what was dropped. Ramseyer so far does draft → Code.

**How the two layers reinforce each other:**
- **The Code checks the alignment.** Suppose a draft instruction and an enacted instruction produce the same change to the Code when both are dry-run. Then they are the same amendment, however differently worded. Two instructions that touch the same provision but change it differently are a real substantive difference.
- **The alignment checks the dry-run, on real drafts.**
  - For a draft whose provision was carried into an enacted law, the Code after that law is known from the release-point history.
  - So ramseyer's prediction for the *draft* can be graded against what actually happened, with the rewording between versions set aside.
  - That is the measurement on draft-stage text the red team asked for (F16), on thousands of introduced bills.

**Matching:**
- A draft is often enacted inside another vehicle: a section of an introduced bill folded into an NDAA or an appropriations act.
- **Candidate vehicles:**
  - Congress.gov related bills, which carry relationship details including text similarities identified by CRS (to be verified);
  - the same bill's later versions;
  - section-level text similarity.
- **Provision alignment** goes in order of confidence:
  1. identical normalized instruction (same target, operation and quotes);
  2. same Code effect;
  3. same target with a different effect (a substantive change);
  4. similar free-standing text (the BillMap/FlatGov technique);
  5. unmatched, reported as such.
- **Every pairing records its evidence**, and nothing is dropped. Every draft provision ends as carried unchanged, carried with changes, moved, or not carried.

**Bill versions to use:** GovInfo BILLS in USLM and the bill DTD XML, by version code (IH, RH, RS, EH, ES, EAS, ENR) through the Congress.gov text-versions API, which ramseyer already uses for enrolled text.
