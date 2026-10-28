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
