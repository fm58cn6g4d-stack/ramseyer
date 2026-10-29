# 10 Packaging and review

One command turns a draft into a report folder you can open, and a review loop lets you settle the items the tool could not.

## Commands

| Command | Does |
| --- | --- |
| ramseyer sync | Fetch and index the current release point; keep prior ones |
| ramseyer analyze draft.docx --out report/ | Run the full pipeline |
| ramseyer analyze --decisions decisions.json | Re-run applying your review decisions |
| ramseyer residue report | Show recurring unfamiliar shapes (tab 9) |
| ramseyer serve-mcp | Start the MCP server from tab 2, including an analyze\_draft tool so Claude can run the pipeline |

## Report folder

| File | Contents |
| --- | --- |
| summary.html | Three buckets (Clean, Needs review, Broken) with counts, release point and input hash |
| comparative.html and comparative.docx | Tab 6 output |
| ripple.html | Tab 7 output |
| ledger.csv and flags.json | Tab 8 output |
| ir.json | Parsed instructions with statuses |
| run.log | Versions, timings, model calls and costs |

## Review loop

Each Needs-review item in summary.html shows the source text, the candidates, and accept or reject controls. Because the page is static, choices save in the browser and export as decisions.json; re-running with that file applies them. A small web app is a v2 option.

## Config (ramseyer.toml)

Release point pin, how many prior release points to keep, cache paths, model names and budgets, the rules file path, and a no-model switch.

## Privacy

Unpublished drafts stay on your machine. The only outbound content is the minimal snippets sent for residue calls, and only when enabled and confirmed. Nothing is uploaded to the statute sources beyond ordinary downloads.

## Operations

- A weekly scheduled `ramseyer sync`
- Every output records tool version, release point and input hash, so any run can be reproduced
- A README with a 10-minute quickstart and a sample draft built from public enacted-bill text

## Done when

A clean machine runs the quickstart end to end and produces every file in the report folder.
