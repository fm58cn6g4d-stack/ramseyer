# 6 Comparative print

The print shows existing law with the bill's changes marked. It is rendered directly from the dry-run edit list, so it cannot disagree with the analysis.

## Two styles

- **Working redline.** Struck text and underlined new text, for your own review.
- **Committee convention.** The House (Ramseyer) and Senate (Cordon) comparative prints show omitted text in black brackets and new text in italics, with unchanged existing law in roman type. Verify the current rule text (House Rule XIII, clause 3(e); Senate Rule XXVI, paragraph 12) against a recent committee report before claiming compliance.

## Contents

1. Header: bill identifier or file name, input hash, release point, generation time, tool version
2. Summary box: counts of CLEAN, WARN and unresolved instructions, with links
3. Each changed section: heading, citation, and either the full section or the changed unit plus N units of context (configurable)
4. Statutory note changes, shown separately
5. Uncodified provisions, listed at the end with the Act text they amend
6. A visible marker on every instruction that is not CLEAN

## Rendering

- Build from the edit list (span operations), not from a text diff; use a diff only to render REDESIGNATE reflow
- HTML with CSS for screen and print
- DOCX through python-docx with real strike, underline, italic and bracket formatting, so staff can paste it into a committee document

## Tests

- Stripping the markup recovers exactly the pre-amendment text, and applying the changes recovers exactly the post-amendment text
- Golden-file renders for five corpus laws
- A non-CLEAN instruction always appears with its marker

## Two displays (added Oct 29, 2026)

Each provision gets the display that fits it. Most bills mix both, so the choice is made per provision, not per bill.

| Provision | Display | Shows |
| --- | --- | --- |
| Amends existing text | Redline in context | The existing law with struck and inserted text, Ramseyer style |
| Creates new statute (a new section, chapter or free-standing program) | Structure and placement | The new provisions as structure; where they would sit (after section X of chapter Y, or an estimated classification, labelled as an estimate); the existing law they lean on (definitions used, cross-references, conforming amendments) |

**Answer key.** Committee reports carry a "changes in existing law" print (Ramseyer in the House, Cordon in the Senate) for reported bills that are not yet law. It is published on GovInfo (CRPT) as PDF and text. Collect a sample, extract the redlines and grade ramseyer on those bills before building the print. USLM 2.1.1 proposes `changesInExistingLaw` with `deletedText` and `addedText`; use it as the model for the output format.

**Closest analog.** The House Comparative Print Suite (compare.house.gov, House staff since October 2022) shows how a bill changes current law, bill-to-bill differences and how an amendment changes a bill. Bill-to-bill and amendment-to-bill comparison is M13.
