# ramseyer: Build Plan

Oct 15, 2026 · @espen

## Purpose and design principles

The tool takes a draft bill (Word file, pasted text, or published bill XML) and returns five things: the U.S. Code sections it amends, a dry-run of every amendatory instruction against current law (the U.S. Code and, where one exists, the Act's current compiled text), a comparative print, a ripple map of what those sections touch, and a ledger of new authorizations and flags. Every output is stamped with the Code release point it was checked against.

Five rules shape every component:

- **Law is fetched, never remembered.** All statute text comes from a local index built from OLRC release points, which are free and official.
- **Deterministic first, model last.** Code handles parsing, lookup, matching and rendering. The model sees only residue, and its output is a proposal that must pass deterministic verification.
- **Fail loud and narrow.** An instruction the tool cannot resolve is reported with its source text and a reason. It is never guessed and never dropped.
- **Promote by recurrence.** A new grammar rule is added only after the same unfamiliar shape shows up three times in the residue log.
- **Free and local.** No paid APIs. Lookups cost no tokens, and unpublished drafts never leave your machine except as minimal snippets sent to a model, which you can disable.

## Architecture

&#91;embedded content: pipeline architecture · 10 components\]

A draft flows left to right through parse, resolve and dry-run, and the three outputs are built from the dry-run result. Statute text is always fetched from the data layer, and the model sits outside the main path, called only on residue. Box numbers match the detail tabs; tab 11 covers testing and acceptance.

## Build order

Nineteen milestones, each with a gate that must pass before the next starts. The oracle corpus (M3) comes before the parser so every later step has a measurable check. Revised Oct 29, 2026, approved by Espen: after the red-team review and a survey of related work, foundations (M6d), an oracle rebuild (M6e) and an Act-text layer (M8a) come before the comparative print. The print now has two displays, and bill and amendment comparison (M13) comes last. Earlier revision, Oct 28: the held-out check (M6b) was added and the comparative print (M8) moved ahead of Word ingestion (M7).

| # | Milestone | Status | Done when | Detail tab |
| --- | --- | --- | --- | --- |
| M0 | Environment and network test | Done | One OLRC title, one Congress.gov bill text and one govinfo bulk file download from the build environment; results logged | 0 Setup |
| M1 | Data layer | Done | All titles for one release point indexed; 100 random sections round-trip cite, section and text with no nulls | 1 Data layer |
| M2 | Free statute server | Done | resolve\_cite, get\_section, cited\_by and search work over MCP and match uscode.house.gov on 50 spot checks | 2 Free statute server |
| M3 | Oracle corpus | Done | 20 enacted laws with before and after release points and enrolled-bill text, plus the comparison harness | 11 Testing |
| M4 | Parser and IR (pasted text) | Done | Instruction count in equals count out on the corpus; deterministic coverage measured and logged | 3 Draft parser |
| M5 | Resolver and Act-to-Code | Done | Zero silent mis-resolutions on 50 Act-section references from the corpus | 4 Resolver |
| M6 | Dry-run engine | Done | Match rate, confident-answer (CLEAN) share and false-clean rate measured on the corpus; false-clean under 1% in substance, with the raw rate (OLRC editorial changes included) reported beside it | 5 Dry-run |
| M6b | Held-out check and coverage | Open | On laws not used for tuning, substantive false-clean under 1% with the raw rate reported; repealed sections, chapter tables of sections and new sections predicted; confident-answer share meets the target Espen sets. Sealed 2023 set measured once: 2.07%, all in the FY2024 NDAA | 11 Testing |
| M6c | Red-team response | Done | Red-team findings fixed with regression tests; every instruction gets a status; drafting-error benchmark and sealed set measured | 11 Testing |
| M6d | Foundations | Next | Indexer and text extraction read USLM 1.x and 2.x, checked on OLRC's 2.0.12 sample titles; dry-run reports the Comparative Print Suite's four failure categories, including already executed into current law; before and after release points chosen by incorporated-set window, including `not` and `u1` labels | 1 Data layer, 5 Dry-run |
| M6e | Oracle rebuild | Planned | Oracle rebuilt on the dreamproit/uscode release points (381, 2013–2026); GPO amendingAction tagging compared as a second reader; introduced and reported versions of enacted laws graded against the enacted change; amendments to Act text quoted in Code notes dry-run; substantive false-clean under 1% on a sealed set | 11 Testing |
| M8a | Act-text layer | Planned | Statute Compilations (about 2,710) loaded with their currentThroughPublicLaw; each draft run against both the Act and the Code; every disagreement between the two reported with a reason | 1 Data layer |
| M8 | Comparative print | Planned | Each provision shown as a redline (amends existing text) or a structure-and-placement view (new statute); HTML and DOCX render; stripping markup recovers before and after text exactly; checked against the changes-in-existing-law sections of committee reports; shown in the first version of the local app (tab 10) | 6 Comparative print |
| M7 | Word ingestion | Planned | Five real drafts parse, with tracked changes and manual numbering handled | 3 Draft parser |
| M9 | Ripple graph | Planned | Interactive HTML for 50 amended sections loads in seconds; edges match the refs table | 7 Ripple graph |
| M10 | Flags and ledger | Planned | Authorization ledger CSV and flag report produced for the American Passenger Rail Network Act | 8 Flags |
| M11 | Model fallback | Planned | Residue handled by propose-then-verify; log, cache and budget caps working | 9 Model fallback |
| M12 | Packaging and hardening | Planned | The local app and one command both produce the full report folder; a non-programmer installs from the guide on a clean machine (checked by Espen on their own) | 10 Packaging |
| M13 | Bill and amendment comparison | Later | Bill-to-bill and amendment-to-bill comparison and bill viewer features; gate set when it is scheduled | 6 Comparative print |

## Model and effort

Run the build in Claude Code (desktop or web) in a fresh git repo on your own machine, not in a chat. The project needs a persistent repo, a test loop and open access to government sites, which a chat sandbox usually blocks. Use Claude Opus 5.5 at high effort for the logic-heavy parts and Claude Sonnet 5.5 at medium effort for the mechanical parts.

| Phase | Model | Effort | Why |
| --- | --- | --- | --- |
| Planning, schema and IR design, oracle harness (M0, M1 design, M3, M6d, M6e) | Claude Opus 5.5 | High | Decisions here are expensive to reverse |
| Parser, resolver, dry-run engine, fallback layer (M4 to M6c, M8a, M11) | Claude Opus 5.5 | High | Edge-case heavy; mistakes here produce silent wrong answers |
| Plumbing and outputs (M1 ingestion, M2, M7 to M10, M12, tests) | Claude Sonnet 5.5 | Medium | Well specified once the schema and IR exist; faster and cheaper |
| Residue calls inside the finished tool | Claude Sonnet 5.5 | Low to medium, structured output | Every proposal is verified deterministically; escalate to Opus 5.5 at high effort only after two failed verifications |

- Switch models at milestone boundaries and commit before switching.
- If your picker labels effort differently, choose the nearest level.
- Claude Fable 5.1 is optional: one review of the IR schema and dry-run semantics after M6, if you have access. The build does not need it.
- This is my judgment from the model tiers, not a benchmark on this task. After M4, check the residue rate and cost per bill, then adjust.

## Kickoff prompt

Export each tab to Markdown into a docs/ folder in the new repo, then paste this into the build session:

```text
You are building ramseyer, a tool that maps draft bills onto the U.S. Code. The full plan is in docs/ (exported from the Build Plan doc). Read docs/00-build-plan.md first, then each component file as you reach its milestone.

Rules:
1. Work one milestone at a time (M0 to M12). At the end of each, run its acceptance gate, commit, and report measured results before starting the next.
2. Build the oracle corpus and comparison harness (M3) before the parser. Nothing after it ships without a measurable check.
3. Never hardcode statute text or rely on memory for law. All statute text comes from the local index, and every output carries the release point it was checked against.
4. Deterministic code first. Call a model only for residue, and verify every model proposal deterministically before using it. A model never writes or alters statute text.
5. Unresolved items are reported with their source text and a reason. Never guess, never drop.
6. Stack: Python 3.11, lxml, sqlite3 with FTS5, pydantic, pytest, typer. Keep drafts and downloads under var/, which is gitignored.
7. Anything flagged 'verify first' in the docs must be confirmed against the real source before you rely on it. Record what you find.
8. Ask me only when blocked on a decision that is mine.

Start with M0.
```
