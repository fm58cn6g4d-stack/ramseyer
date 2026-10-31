# 10 Packaging and review

One command turns a draft into a report folder you can open, and a review loop lets you settle the items the tool could not.

## App

ramseyer is used through a local app: a page that opens in the web browser but runs entirely on your own machine, started from an icon. Nothing is uploaded, so drafts stay private. Decided by Espen on 2026-10-31.

- **Install:** once, in Terminal, from a step-by-step guide written for a non-programmer (a one-click installer if the guide proves too fiddly).
- **Analyze:** drag a draft onto the page and click Analyze.
- **Results:** tabs for the summary, the redline, the ripple graph, and the ledger and flags, with a button to download the Word version.
- **Review:** each open item has accept and reject buttons, applied at once.
- **Settings:** update the copy of the Code; the app reminds you when it is out of date.
- **Files:** the report folder is still written, for sharing and for the record.

The app is first built with M8, so its first results appear in it, and finished in M12.

## Commands

| Command | Does |
| --- | --- |
| ramseyer app | Start the local app and open it in the browser (what the icon runs) |
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

Each Needs-review item in summary.html shows the source text, the candidates, and accept or reject controls. In the app, choices apply at once and are saved as decisions.json beside the report; from the command line, re-running with that file applies them.

## Config (ramseyer.toml)

Release point pin, how many prior release points to keep, cache paths, model names and budgets, the rules file path, and a no-model switch.

## Privacy

Unpublished drafts stay on your machine. The only outbound content is the minimal snippets sent for residue calls, and only when enabled and confirmed. Nothing is uploaded to the statute sources beyond ordinary downloads.

## Operations

- A weekly scheduled `ramseyer sync`
- Every output records tool version, release point and input hash, so any run can be reproduced
- A README with a 10-minute quickstart and a sample draft built from public enacted-bill text

## Done when

A clean machine runs the quickstart end to end and produces every file in the report folder, and the install guide takes a non-programmer from nothing to a first report in the app, checked by Espen on their own machine.
