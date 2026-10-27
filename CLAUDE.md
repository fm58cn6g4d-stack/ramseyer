# billmap: build-session conventions

billmap maps draft bills onto the U.S. Code. The plan is in `docs/` (mirrored from the
Build Plan Claude doc; see `docs/README.md`). It is developed on its own branch inside the
project-2050 repo and is **not merged to main** until Espen says so.

## Rules (from the kickoff prompt)

1. Work one milestone at a time (M0 to M12). At the end of each, run its acceptance gate, commit, and report measured results before starting the next.
2. Build the oracle corpus and comparison harness (M3) before the parser. Nothing after it ships without a measurable check.
3. Never hardcode statute text or rely on memory for law. All statute text comes from the local index, and every output carries the release point it was checked against.
4. Deterministic code first. Call a model only for residue, and verify every model proposal deterministically before using it. A model never writes or alters statute text.
5. Unresolved items are reported with their source text and a reason. Never guess, never drop.
6. Stack: Python 3.11, lxml, sqlite3 with FTS5, pydantic, pytest, typer. Keep drafts and downloads under var/, which is gitignored.
7. Anything flagged 'verify first' in the docs must be confirmed against the real source before you rely on it. Record what you find (in `records/verify-first.md`).
8. Ask Espen only when blocked on a decision that is theirs.

## Running

```sh
uv venv -p python3.11 .venv && uv pip install -p .venv/bin/python -e '.[dev]'
.venv/bin/python -m pytest -q                 # offline unit tests
.venv/bin/python scripts/probe_sources.py     # M0 gate; writes var/probe.md
```

Secrets go in `.env` (see `.env.example`): `API_DATA_GOV_KEY`, `BILLMAP_CONTACT`.

## Milestone gates

| Milestone | Gate lives in |
| --- | --- |
| M0 | `scripts/probe_sources.py` -> `var/probe.md`; result recorded in `records/milestones.md` |
| M1+ | added as each milestone is built; listed in `records/milestones.md` |

## Commits and files

- Prefix commit messages with the milestone id, e.g. `M0: ...`.
- Unpublished drafts, downloads, sqlite indexes, caches and the residue log stay under `var/`. Never commit `.env` or `var/`.
- Test fixtures hold page *structure* only; statute text in tests is synthetic placeholder text.
