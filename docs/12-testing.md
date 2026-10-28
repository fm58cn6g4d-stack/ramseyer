# 11 Testing and acceptance

The main test uses the law itself as the answer key: apply an enacted law's amendments to the Code as it stood before, and the result must equal the Code as it stood after.

## Oracle test

For an enacted law L, with release points R\_before (just before L was classified) and R\_after (just after):

1. Parse L's enrolled text into IR.
2. Resolve and dry-run it against R\_before.
3. Compare each amended section's predicted text with its text in R\_after, after normalization.
4. Classify every mismatch as a parser error, a resolver error, an engine error, or an editorial change by OLRC that is not in the law.

Corpus: start with 20 enacted laws, mostly amending titles 49, 23 and 45 plus a spread across other titles, chosen so that both release points are available. Store references plus cached text under var/.

## Metrics and gates

Targets are starting points; calibrate them after the first measurement.

| Metric | Target | Why |
| --- | --- | --- |
| Instruction accounting | Count in equals IR count plus UNPARSED, always | Nothing is silently dropped |
| False-clean rate | Under 1 percent in substance (tool says CLEAN, oracle disagrees beyond OLRC editorial changes), on held-out laws; the raw rate is always reported beside it | The metric that matters most |
| Deterministic coverage | At least 85 percent of instructions without the model | Token efficiency |
| Resolver silent errors | 0 on 50 Act-section references | A wrong section is the worst failure |
| Tokens per 50-page bill | Measured and recorded every run | Tracks the efficiency goal |

## Other tests

- Unit tests per component; golden files for the print and the report
- Property tests for the engine
- Mutation tests: break a quote and expect NOT\_FOUND; swap a section number and expect TARGET\_MISSING or STALE\_BASELINE
- CI runs the oracle suite on every commit and compares metrics with a stored baseline

## Real-draft trial

Run the American Passenger Rail Network Act and four other drafts. You review the outputs and label each error; labels go in a local, uncommitted folder, and unpublished drafts are never committed.

## Known hard cases (write a named test for each)

- Nested strike-and-insert across subparagraphs
- Strike through, as in and all that follows through
- Amendments to text that another section of the same bill amends
- Bills that amend text a different unenacted bill would change
- Non-positive-law titles
- Tables and formulas inside statute text
- The first place it appears, and other ordinal occurrences
- Section numbers that changed between drafting and the release point
