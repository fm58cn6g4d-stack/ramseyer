"""M6e: does a gate run reproduce? Compares two checkpoints of the same set, section by section.

For each law and section, both runs' outcome and status are compared, and so are the hashes of the predicted, R_before
and R_after texts (recorded by scripts/m6_gate.py). The R_before and R_after hashes show whether the release points
themselves were materialized the same; the predicted hash whether the parse and engine gave the same text on the same
inputs. Any difference is listed.
Run:  .venv/bin/python scripts/compare_runs.py var/m6e_dev_checkpoint.jsonl var/m6e_dev_rerun1_checkpoint.jsonl
      Writes var/compare_runs.md; exits 1 when the runs differ.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

from ramseyer import config


def load(path: Path) -> dict[tuple[str, str], dict]:
    out = {}
    for line in path.read_text().splitlines()[1:]:
        rec = json.loads(line)
        hashes = rec["extra"].get("hashes")
        if hashes is None:
            sys.exit(f"{path}: no per-section hashes (run by a gate older than --rerun)")
        for o in rec["outcomes"]:
            out[(rec["pl"], o["identifier"])] = {"outcome": o["outcome"], "status": o["status"],
                                                 "pred": hashes.get(o["identifier"], [None] * 3)[0],
                                                 "before": hashes.get(o["identifier"], [None] * 3)[1],
                                                 "after": hashes.get(o["identifier"], [None] * 3)[2],
                                                 "editorial": rec["extra"]["editorial"].get(o["identifier"])}
    return out


def main() -> int:
    a_path, b_path = Path(sys.argv[1]), Path(sys.argv[2])
    a, b = load(a_path), load(b_path)
    fields = ("outcome", "status", "pred", "before", "after", "editorial")
    diffs = collections.Counter()
    rows = []
    for key in sorted(a.keys() | b.keys()):
        x, y = a.get(key), b.get(key)
        if x is None or y is None:
            diffs["only in one run"] += 1
            rows.append(f"- {key[0]} {key[1]}: only in {'the second' if x is None else 'the first'} run")
            continue
        changed = [f for f in fields if x[f] != y[f]]
        for f in changed:
            diffs[f] += 1
        if changed:
            rows.append(f"- {key[0]} {key[1]}: " + "; ".join(f"{f} {x[f]} → {y[f]}" for f in changed))
    out = [f"# Do two runs reproduce? {a_path.name} vs {b_path.name}", "",
           f"Sections compared: {len(a.keys() & b.keys())}; differing: {len(rows)}"
           + (" (" + ", ".join(f"{k} {v}" for k, v in diffs.most_common()) + ")" if rows else ""), "",
           "## Differences", ""] + (rows or ["None."])
    path = config.load().var / "compare_runs.md"
    path.write_text("\n".join(out) + "\n")
    print("\n".join(out[:3]))
    return 1 if rows else 0


if __name__ == "__main__":
    sys.exit(main())
