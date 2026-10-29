# ramseyer: build-session conventions

ramseyer maps draft bills onto the U.S. Code. The plan is in `docs/` (mirrored from the
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
.venv/bin/ramseyer sync                        # index the current release point (~3 min, 1.6 GB)
.venv/bin/python scripts/m1_gate.py           # M1 gate; writes var/m1_gate.md
.venv/bin/python scripts/m2_gate.py           # M2 gate; writes var/m2_gate.md
.venv/bin/python scripts/build_corpus.py      # M3 corpus + oracle index (~15 min, ~7 GB under var/oracle)
.venv/bin/python scripts/m3_gate.py           # M3 gate; writes var/m3_gate.md
.venv/bin/python scripts/m4_gate.py           # M4 gate; writes var/m4_gate.md
.venv/bin/ramseyer parse draft.txt --out var/ir.json   # parse a draft (drafts stay under var/)
.venv/bin/python scripts/m5_gate.py           # M5 gate; writes var/m5_gate.md
.venv/bin/ramseyer resolve "Section 317U(b) of the Public Health Service Act (42 U.S.C. 247b-23)"
.venv/bin/python scripts/m6_gate.py           # M6 gate; writes var/m6_gate.md (~3 min)
.venv/bin/python scripts/build_heldout.py     # M6b held-out manifest + index (tests/oracle/heldout.json, var/oracle/heldout.sqlite)
.venv/bin/python scripts/m6_gate.py --heldout # M6b gate; writes var/m6b_gate.md
.venv/bin/python scripts/xhtml_check.py      # XHTML->USLM converter check on the current release; writes var/xhtml_check.md
.venv/bin/python scripts/build_govinfo_heldout.py  # GovInfo held-out set (tests/oracle/heldout_govinfo.json, var/oracle/govinfo.sqlite)
.venv/bin/python scripts/m6_gate.py --set govinfo  # M6b GovInfo gate; writes var/m6b_govinfo_gate.md
.venv/bin/python scripts/build_govinfo_heldout.py --editions 2022 2023  # sealed held-out set (2023 laws)
.venv/bin/python scripts/m6_gate.py --set govinfo2023  # sealed set: measure once per round, never inspect cases
.venv/bin/python scripts/m6_gate.py --resolve-before   # tuning set, targets resolved against each law's R_before
.venv/bin/python scripts/m6_gate.py --refresh-labels   # re-stamp hand-label hashes after checking each difference
.venv/bin/python scripts/m6c_error_benchmark.py        # drafting-error detection benchmark; writes var/m6c_errors.md
.venv/bin/python redteam/synthetic.py [CASE]           # the red team's adversarial cases on a synthetic index
```

Secrets go in `.env` (see `.env.example`): `API_DATA_GOV_KEY`, `RAMSEYER_CONTACT`.

## Milestone gates

| Milestone | Gate lives in |
| --- | --- |
| M0 | `scripts/probe_sources.py` -> `var/probe.md`; result recorded in `records/milestones.md` |
| M1 | `ramseyer sync` builds `var/index/ramseyer.sqlite`; `scripts/m1_gate.py` -> `var/m1_gate.md` |
| M2 | `scripts/m2_gate.py` -> `var/m2_gate.md` |
| M3 | `scripts/build_corpus.py` builds `tests/oracle/corpus.json` and `var/oracle/oracle.sqlite`; `scripts/m3_gate.py` -> `var/m3_gate.md`, `tests/oracle/baseline.json` |
| M4 | `scripts/m4_gate.py` -> `var/m4_gate.md`, residue in `var/m4_residue.jsonl`; pattern fixtures from `scripts/harvest_patterns.py` |
| M5 | `scripts/m5_gate.py` -> `var/m5_gate.md` |
| M6 | `scripts/m6_gate.py` -> `var/m6_gate.md`, `var/m6_report.json`, `var/m6_traces.jsonl`, `tests/oracle/m6_baseline.json`; editorial labels in `tests/oracle/labels.json` |
| M6b | `scripts/build_heldout.py`; `scripts/m6_gate.py --heldout` -> `var/m6b_gate.md`, `tests/oracle/m6b_baseline.json`; `scripts/build_govinfo_heldout.py`; `scripts/m6_gate.py --set govinfo` -> `var/m6b_govinfo_gate.md`, `tests/oracle/m6b_govinfo_baseline.json` (dev half = even laws, test half = odd laws, measured only); converter check `scripts/xhtml_check.py` |
| M6c | `scripts/m6c_error_benchmark.py` -> `var/m6c_errors.md` (drafting-error detection); sealed set `scripts/m6_gate.py --set govinfo2023` -> `var/m6b_govinfo2023_gate.md`; red-team regression tests in `tests/unit/test_redteam_cases.py` |
| M7+ | added as each milestone is built; listed in `records/milestones.md` (M8 now comes before M7) |

## Commits and files

- Prefix commit messages with the milestone id, e.g. `M0: ...`.
- Unpublished drafts, downloads, sqlite indexes, caches and the residue log stay under `var/`. Never commit `.env` or `var/`.
- Test fixtures hold page *structure* only; statute text in tests is synthetic placeholder text.
