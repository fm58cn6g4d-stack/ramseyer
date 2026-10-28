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
.venv/bin/billmap sync                        # index the current release point (~3 min, 1.6 GB)
.venv/bin/python scripts/m1_gate.py           # M1 gate; writes var/m1_gate.md
.venv/bin/python scripts/m2_gate.py           # M2 gate; writes var/m2_gate.md
.venv/bin/python scripts/build_corpus.py      # M3 corpus + oracle index (~15 min, ~7 GB under var/oracle)
.venv/bin/python scripts/m3_gate.py           # M3 gate; writes var/m3_gate.md
.venv/bin/python scripts/m4_gate.py           # M4 gate; writes var/m4_gate.md
.venv/bin/billmap parse draft.txt --out var/ir.json   # parse a draft (drafts stay under var/)
```

Secrets go in `.env` (see `.env.example`): `API_DATA_GOV_KEY`, `BILLMAP_CONTACT`.

## Milestone gates

| Milestone | Gate lives in |
| --- | --- |
| M0 | `scripts/probe_sources.py` -> `var/probe.md`; result recorded in `records/milestones.md` |
| M1 | `billmap sync` builds `var/index/billmap.sqlite`; `scripts/m1_gate.py` -> `var/m1_gate.md` |
| M2 | `scripts/m2_gate.py` -> `var/m2_gate.md` |
| M3 | `scripts/build_corpus.py` builds `tests/oracle/corpus.json` and `var/oracle/oracle.sqlite`; `scripts/m3_gate.py` -> `var/m3_gate.md`, `tests/oracle/baseline.json` |
| M4 | `scripts/m4_gate.py` -> `var/m4_gate.md`, residue in `var/m4_residue.jsonl`; pattern fixtures from `scripts/harvest_patterns.py` |
| M5+ | added as each milestone is built; listed in `records/milestones.md` |

## Commits and files

- Prefix commit messages with the milestone id, e.g. `M0: ...`.
- Unpublished drafts, downloads, sqlite indexes, caches and the residue log stay under `var/`. Never commit `.env` or `var/`.
- Test fixtures hold page *structure* only; statute text in tests is synthetic placeholder text.
