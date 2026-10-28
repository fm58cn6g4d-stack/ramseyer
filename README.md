# billmap

Maps draft bills onto the U.S. Code. Every statute text comes from a local index of an official
OLRC release point, and every output names that release point. The build plan is in `docs/`;
measured results per milestone are in `records/milestones.md`.

Status: M0–M2 built (source probe, data layer, free statute server). Not for main yet.

## Setup

```sh
uv venv -p python3.11 .venv && uv pip install -p .venv/bin/python -e '.[dev]'
cp .env.example .env            # API_DATA_GOV_KEY (free, api.data.gov), BILLMAP_CONTACT
.venv/bin/billmap sync          # download and index the current release point (~3 min, ~1.6 GB)
```

## Statute tools

The same functions work from Python (`billmap.statute.StatuteService`), the CLI and MCP.

```sh
.venv/bin/billmap statute resolve_cite citation="49 U.S.C. 24101(a)"
.venv/bin/billmap statute get_section citation="4 U.S.C. 1" format=plain
.venv/bin/billmap statute search query="intercity rail passenger" title=49 limit=5
```

Tools: `resolve_cite`, `get_section` (operative, plain or xml; `as_of` a loaded release point),
`get_pincite`, `cross_refs`, `cited_by`, `definitions`, `neighbors`, `search`, `changes`,
`coverage`, `act_to_code`. Errors come back as `{"error": "not_found" | "ambiguous" | "repealed" |
"out_of_range", "message": ..., "release_point": ...}`.

### Claude Code

```sh
claude mcp add billmap -- /path/to/billmap/.venv/bin/billmap serve-mcp
```

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "billmap": {
      "command": "/path/to/billmap/.venv/bin/billmap",
      "args": ["serve-mcp"]
    }
  }
}
```

## Checks

```sh
.venv/bin/python -m pytest -q             # offline unit tests
.venv/bin/python scripts/probe_sources.py # M0
.venv/bin/python scripts/m1_gate.py       # M1
.venv/bin/python scripts/m2_gate.py       # M2 (fetches 50 pages from uscode.house.gov, cached)
```
