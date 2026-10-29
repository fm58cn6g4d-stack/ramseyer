# 0 Setup and environment

Build in Claude Code in a new git repo on your own machine, and prove the environment can reach every data source before writing any other code.

## Repo layout

```text
ramseyer/
  docs/                 exported tabs of this doc
  src/ramseyer/
    data/               fetch, index, schema
    parse/              ingest, segment, grammar, ir
    resolve/            cites, actcode
    dryrun/
    outputs/            print, graph, report
    flags/
    fallback/
    mcp_server/
    cli.py
  tests/                unit, corpus, oracle
  var/                  gitignored: downloads, sqlite, caches, residue_log.jsonl
  CLAUDE.md             conventions for the build session
  ramseyer.toml          release point pin, budgets, models, rules path
```

## Stack

- Python 3.11+, lxml, python-docx, sqlite3 with FTS5, pydantic, httpx, typer, pytest, the MCP Python SDK
- Cytoscape.js from cdnjs for the ripple graph, so there is no frontend build step
- A free api.data.gov key for Congress.gov and govinfo, kept in .env (gitignored)

## M0 network test

Write scripts/probe\_sources.py. It attempts each fetch below and writes a pass/fail table to var/probe.md.

| Source | Test | Pass means |
| --- | --- | --- |
| OLRC release point page | GET the current release point page | Page parses and the release point label is extracted |
| OLRC per-title XML | Download one small title as XML | File opens, root element found, section identifiers present |
| OLRC all-titles zip | HEAD request only | Size and URL recorded |
| OLRC classification tables | GET the 119th Congress, 2nd session table | Rows parse |
| Congress.gov API | One bill and its text versions | An XML text URL is returned |
| govinfo bulk data | List one BILLS or PLAW directory | Listing returns |

If any fetch fails from a cloud sandbox, run the build on a local machine and record why in var/probe.md.

## Verify first

- The exact URL pattern for per-title XML zips on the release point page
- The identifier attribute format in the USLM XML (expected to look like /us/usc/t49/s24101; confirm against a real file)
- The HTML structure of the classification tables
- The OLRC site currently runs in a temporary format, so page structure may change; keep fetchers small and covered by tests

## Politeness and keys

Send a User-Agent with a contact address, cache every download, and respect api.data.gov rate limits. Never commit .env, var/ or unpublished drafts.

## CLAUDE.md contents

The eight rules from the kickoff prompt, how to run tests, where each milestone gate lives, commit messages prefixed with the milestone id, and a reminder that unpublished drafts stay under var/.
