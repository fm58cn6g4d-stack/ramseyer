# Contributing to ramseyer

ramseyer is built by Claude Code sessions working for Espen. These are the merge rules in plain
language. The machine-readable version is `.github/merge-policy.json`, read by
`.github/scripts/agent_gate.py`. If the two disagree, the JSON is what the gate enforces; fix this
file to match.

## How a change gets to main

1. Work on a branch that starts with `claude/`. Never push to main; the ruleset blocks it.
2. Open one pull request per coherent change. Put this line in the PR description:

   ```
   Agent-Author: claude-code <session id>
   ```

3. Run `bash .github/scripts/run-checks.sh` before you push. CI runs the same script.
4. Mark the PR ready for review when it is done.
5. A **different** Claude Code session reviews the diff at the PR's current head, then comments
   these three lines:

   ```
   Agent-Review: approve
   Reviewed-Head: <full or short sha of the head it read>
   Reviewer: claude-code <its own session id>
   ```

   Use `Agent-Review: changes-requested` to block. A block stands until the same reviewer
   approves. A review of an older head does not count, unless the only later change is a merge
   of main.
6. The gate merges the PR when its tier allows (below) and every required check passes:
   `rebuild-and-tests`, `merge-tier` and `agent-review`.

The author session may not review its own PR. Starting the reviewer session is the author's job:
leave the request in the PR, and start or message a separate session to do it. A comment alone does
not start another session.

## Tiers

The tier comes from the changed path that ranks highest. The first matching rule in the policy
file wins for each path.

| Tier | Paths | Who merges |
| --- | --- | --- |
| 3 | `.github/`, `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, `tests/oracle/labels.json` | Espen only: they add the label `espen-approved` |
| 2 | `tests/oracle/` (manifests and baselines), `ramseyer.toml`, `pyproject.toml`, `docs/`, anything not listed | The gate, after checks and review; Espen is notified |
| 1 | `src/`, `scripts/`, `tests/`, `redteam/`, `records/`, `README.md` | The gate, after checks and review |

The hand labels in `tests/oracle/labels.json` are tier 3 because each one excuses a mismatch from
the false-clean rate.

## Labels

Only Espen's account counts for these. An agent never adds them.

- `espen-approved`: approves a tier 3 PR at its current head. A push that changes the PR's own
  content removes it.
- `espen-override`: merge even though an agent review blocks.
- `needs-espen`: the PR waits for a decision of Espen's.
- `hold`: do not merge.

Agents never add `espen-approved` and never turn on auto-merge for a tier 3 PR.

## Automatic merging

The gate merges only when the repository variable `AGENT_AUTOMERGE` is `on` (Settings, Secrets
and variables, Actions, Variables). With it off, the gate still reports, and Espen merges by hand.

## What never goes in the repository

- `.env`, API keys, personal contact details;
- anything under `var/` (downloads, drafts, indexes, caches);
- statute text written from memory or by a model. Test fixtures use synthetic text.
