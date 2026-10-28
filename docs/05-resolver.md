# 4 Resolver and Act-to-Code

The resolver turns every reference in an instruction into a node in the index. It either finds the node or says exactly why it could not; it never guesses a section.

## Citation resolution

| Draft wording | Resolves to |
| --- | --- |
| 49 U.S.C. 24101(a)(2) | Section 24101 of title 49, path (a)(2); confirm the id format in M0 |
| section 24101 of title 49, United States Code | Same node |
| such section, that subsection, this chapter | The enclosing scope from the instruction stack |
| section 5337 of such title | Title taken from the enclosing instruction |
| chapter 241 of title 49 | The chapter node |

Anything else returns UNRESOLVED with the raw text and a reason.

## Act references

Take section 301 of the Infrastructure Investment and Jobs Act (Public Law 117-58) as the model case.

1. Detect the Act reference (named Act, public law number, or both).
2. Resolve to a public law number: use the explicit citation if present, else the Popular Name table, else UNRESOLVED.
3. Look up the Act section's Code location with the three layers below.
4. Return the location or a typed non-Code outcome.

## Act-to-Code mapping: three layers, in priority order

1. **Derived index from the Code itself.** Invert the source\_credits table, which records section, public law and public law section, into a map from (public law, section) to Code sections. Also index statutory notes that say where Act text sits, such as 49 U.S.C. 5301 note. This covers laws of any age. It is my proposal rather than a documented OLRC method, so validate it on the corpus before trusting it.
2. **OLRC classification tables** for recent laws, as a cross-check. Disagreement between layers is flagged and never silently resolved.
3. **The Act's own text** (public law text from govinfo or Congress.gov) when the provision is uncodified or sits in a non-positive-law title. The dry-run then runs against the Act text, not the Code.

Outcomes: CODIFIED, NOTE, SPLIT, UNCODIFIED, UNKNOWN. UNKNOWN goes to the review bucket.

## Positive-law titles

Ingest the OLRC list of positive-law titles. For targets in non-positive-law titles, stamp the result: the Code is prima facie evidence of the law, and the Act text controls.

## Edge cases to test

- Sections renumbered or transferred since the Act (follow the transfer notes)
- Omitted and repealed sections
- Act sections split across several Code sections
- Two Acts that share a popular name
- The Act used for an Act defined earlier in the same bill

## Done when

Zero silent mis-resolutions on 50 Act-section references drawn from the oracle corpus, checked against the next release point.
