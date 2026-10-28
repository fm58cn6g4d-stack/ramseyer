# 8 Flags and ledger

Deterministic detectors scan the bill and the dry-run results for the items staff track by hand, and every finding quotes the text that triggered it. Judgment stays with you; the tool only surfaces.

## Authorization ledger

Every new or changed authorization of appropriations becomes one row: amount, fiscal-year range, program or account, target section, bill location and the exact sentence. Detection uses patterns for authorized to be appropriated, there is authorized, dollar amounts and fiscal years X through Y. Anything it cannot parse completely is listed as UNRESOLVED rather than estimated. Output is ledger.csv and ledger.json, which feed the scoring tool.

## Flags

| Flag | How it is detected | Output |
| --- | --- | --- |
| Expiring or sunset | Final fiscal year in an authorization; sunset and termination clauses; effective dates | Date and the triggering sentence |
| New deadlines | shall within N days, not later than, shall establish, shall promulgate regulations | Deadline list with bill location |
| New programs, offices, reports | Verbs and nouns for establishing programs and offices; report requirements | List with citations |
| Cross-cutting requirements | Presence or absence of references to Buy America, Davis-Bacon, NEPA and similar in new text | Present or absent only; no judgment |
| Likely committee referral | Hand-maintained table mapping Code titles and chapters to committees, from House Rule X and Senate Rule XXV | Ranked guesses labeled heuristic |
| Byrd rule screening (v2) | Heuristic list of provisions with no budgetary effect | Screening only; never a determination |

## Rules live in data, not code

Detectors read a YAML rules file holding the patterns, the statute cites for each requirement and the referral table. You maintain it. The build session writes the first version and marks every cite verify first.

## Output

flags.json with id, severity (info or review), rule id, evidence quote and bill location, also rendered into the report summary.

## Tests

- The ledger on three enacted laws that carry authorizations matches the totals printed in the law text
- Every flag carries an evidence quote
- Removing a rule from the YAML removes its flags and nothing else
