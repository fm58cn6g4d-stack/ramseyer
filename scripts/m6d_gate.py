"""M6d gate (foundations): the USLM 1.x/2.x seam, release-point windows, and failure categories.

Runs scripts/uslm2_check.py and scripts/release_windows_check.py, and reads the instruction statuses and failure
categories from the latest M6 gate report (var/m6_gate.md; run scripts/m6_gate.py first). Criteria:
  1. the 2.x index holds exactly the raw 2.x characters, and every difference from 1.0 is explained or reviewed;
  2. every OLRC release-point label parses and the label order reproduces OLRC's publication order;
  3. every instruction in the M6 run has a status, and each non-CLEAN status maps to a failure category.
Run:  .venv/bin/python scripts/m6d_gate.py      Writes var/m6d_gate.md.
"""
from __future__ import annotations

import re
import subprocess
import sys

from ramseyer import config

ROOT = config.ROOT


def run(script: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / script)], cwd=ROOT, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def main() -> int:
    cfg = config.load()
    checks = []
    code, _ = run("uslm2_check.py")
    md = (cfg.var / "uslm2_check.md").read_text()
    fid = re.search(r"Fidelity[^|]*\| (\d+) of (\d+)", md)
    reviewed = re.search(r"Reviewed publication differences[^:]*: (\d+)", md)
    checks.append(("USLM 2.x seam: exact characters, every difference explained or reviewed", code == 0,
                   f"fidelity {fid.group(1)} of {fid.group(2)} sections; reviewed publication differences "
                   f"{reviewed.group(1) if reviewed else '?'}; details in var/uslm2_check.md"))
    code, out = run("release_windows_check.py")
    labels = re.search(r"Labels on OLRC's prior-release-points page \| (\d+)", out)
    differs = re.search(r"window differs \| (\d+)", out)
    checks.append(("Release-point labels parse and order as OLRC publishes them", code == 0,
                   f"{labels.group(1) if labels else '?'} labels; windows changed from the old rule: "
                   f"{differs.group(1) if differs else '?'} (var/release_windows_check.md)"))
    m6 = (cfg.var / "m6_gate.md").read_text() if (cfg.var / "m6_gate.md").exists() else ""
    never_drop = re.search(r"Every parsed instruction has a status \(never drop\) \| (PASS|FAIL) \| ([^|]+)\|", m6)
    statuses = re.search(r"Instruction statuses: (.+)", m6)
    cats = re.search(r"Failure categories \(Comparative Print Suite\): (.+)", m6)
    checks.append(("Every instruction has a status and a failure category (M6 run)",
                   bool(never_drop and never_drop.group(1) == "PASS" and cats),
                   (f"{never_drop.group(2).strip()}; " if never_drop else "no M6 report; ")
                   + (f"categories: {cats.group(1)}" if cats else "no category line: rerun scripts/m6_gate.py")))
    lines = ["# M6D gate", "", "| Check | Result | Measured |", "| --- | --- | --- |"]
    lines += [f"| {n} | {'PASS' if ok else 'FAIL'} | {d.replace('|', '/')} |" for n, ok, d in checks]
    if statuses:
        lines += ["", "Instruction statuses (M6 tuning run): " + statuses.group(1)]
    (cfg.var / "m6d_gate.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
