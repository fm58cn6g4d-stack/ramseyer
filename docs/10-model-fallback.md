# 9 Model fallback and learning log

The model is called only for residue, its output is a proposal, and a proposal counts only if deterministic code verifies it. Everything the model sees is logged, so recurring failures become grammar rules.

## When it is called

- The parser leaves an instruction UNPARSED or below the confidence threshold
- The resolver returns UNKNOWN
- The dry-run returns NOT\_FOUND or AMBIGUOUS and fuzzy candidates exist
- Optional and off by default: a short plain-language summary of the report

## Propose, then verify

1. Build a minimal prompt: the instruction text, its enclosing scope, the operative text of candidate sections (length capped) and the candidate matches. Never the whole bill.
2. Require structured output validated against the IR schema.
3. Verify in code: every quoted string appears in the target after normalization, every cite exists in the index, and the op is in the enum.
4. On failure, retry once with the failure reason; on a second failure mark the item NEEDS\_HUMAN.
5. A model never writes or alters statute text and never judges legal effect.

## Models and budget

- Default: Claude Sonnet 5.5, low to medium effort
- Escalate to Claude Opus 5.5 at high effort only after two failed verifications
- Per-bill token and dollar caps in ramseyer.toml; hitting a cap stops model calls and marks the rest NEEDS\_HUMAN
- Identical shapes are clustered and sent as one call per cluster
- Results are cached by a hash of the normalized item, the target text hash and the release point, so nothing is called twice
- --no-model disables all calls, and the first model call in a session asks for confirmation because drafts are unpublished

## Residue log

var/residue\_log.jsonl holds one line per item: timestamp, bill hash, shape\_hash, item text, outcome, model, tokens and a verified flag.

## Promotion workflow

`ramseyer residue report` lists shapes by frequency. When a shape has appeared at least 3 times and at least 90 percent of its model proposals verified, the tool drafts a grammar rule and test fixtures from the logged items. You review and merge, and CI blocks any rule that lowers accuracy on the corpus.

## Metrics tracked per run

Residue rate, tokens per bill, verified-proposal rate and escalation rate.
