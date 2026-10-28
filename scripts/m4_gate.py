"""M4 gate (docs/04-draft-parser.md): on the oracle corpus, instructions counted in the source equal IR
instructions plus UNPARSED, and deterministic coverage is measured and logged.

The parser reads only the pasted-style text rendered from each enrolled bill; the source count comes from
the XML markup (xmltext.xml_counts), an independent reading of quote and unit boundaries.

Run:  .venv/bin/python scripts/m4_gate.py [--show 25]      Writes var/m4_gate.md and var/m4_residue.jsonl.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time

from billmap import config
from billmap.data.http import Fetcher
from billmap.oracle.corpus import Corpus
from billmap.parse import parse_text
from billmap.parse.grammar import CONFIDENCE_THRESHOLD
from billmap.parse.xmltext import render, xml_counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=25)
    args = ap.parse_args()
    cfg = config.load()
    f = Fetcher(cfg)
    corpus = Corpus.load()
    t0 = time.monotonic()
    rows, mismatches = [], []
    total_in = total_ir = total_unparsed = total_low = 0
    shapes = collections.Counter()
    examples = {}
    ops = collections.Counter()
    residue = (cfg.var / "m4_residue.jsonl").open("w")
    for law in corpus.laws:
        path = f.get(law.enrolled_url).path
        src = xml_counts(path)
        result = parse_text(render(path))
        # One source instruction may fan out over several scopes (ids "#0.0", "#0.1"); count it once.
        firsts = [i for i in result.instructions if "." not in i.id.split("#")[1] or i.id.endswith(".0")]
        out = collections.Counter(i.bill_loc for i in firsts)
        n_in = sum(src.values())
        n_ir = sum(1 for i in firsts if i.op != "UNPARSED")
        n_un = sum(1 for i in result.instructions if i.op == "UNPARSED")
        low = [i for i in firsts if i.op != "UNPARSED" and i.confidence < CONFIDENCE_THRESHOLD]
        for loc in sorted(set(src) | set(out)):
            if src.get(loc, 0) != out.get(loc, 0):
                mismatches.append(f"{law.pl} {loc}: source {src.get(loc, 0)}, parsed {out.get(loc, 0)}")
        for i in firsts:
            ops[i.op] += 1
            if i.op == "UNPARSED" or i.confidence < CONFIDENCE_THRESHOLD:
                key = i.reason or "; ".join(x for x in i.flags if x.startswith(("unconsumed", "expected", "unbalanced")))
                shapes[i.shape_hash] += 1
                examples.setdefault(i.shape_hash, (law.pl, i.id, key[:200]))
                residue.write(json.dumps({"pl": law.pl, "id": i.id, "shape_hash": i.shape_hash, "op": i.op,
                                          "confidence": i.confidence, "reason": key}) + "\n")
        total_in += n_in
        total_ir += n_ir
        total_unparsed += n_un
        total_low += len(low)
        cov = (n_ir - len(low)) / n_in if n_in else 1.0
        rows.append(f"{law.pl}: in {n_in}, IR {n_ir}, UNPARSED {n_un}, low-confidence {len(low)}, coverage {cov:.3f}")
    residue.close()
    coverage = (total_ir - total_low) / total_in if total_in else 1.0
    checks = [
        ("Instruction count in equals IR count plus UNPARSED on the corpus", not mismatches and
         total_in == total_ir + total_unparsed,
         f"in {total_in}; IR {total_ir} + UNPARSED {total_unparsed} = {total_ir + total_unparsed}; per-location "
         f"mismatches {len(mismatches)}" + ("" if not mismatches else ": " + "; ".join(mismatches[:15]))),
        ("Deterministic coverage measured and logged", True,
         f"{coverage:.4f} ({total_ir - total_low} of {total_in} parsed at confidence >= {CONFIDENCE_THRESHOLD}; "
         f"{total_low} low-confidence, {total_unparsed} UNPARSED). Ops: " +
         ", ".join(f"{k} {v}" for k, v in ops.most_common())),
    ]
    lines = ["# M4 gate", "", f"Run {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}; {time.monotonic() - t0:.0f}s.",
             "", "| Check | Result | Measured |", "| --- | --- | --- |"]
    lines += [f"| {n} | {'PASS' if ok else 'FAIL'} | {d.replace('|', '/')} |" for n, ok, d in checks]
    lines += ["", "## Per law", ""] + [f"- {r}" for r in rows]
    lines += ["", f"## Residue shapes (top {args.show})", "", "| Count | Shape | Example |", "| --- | --- | --- |"]
    lines += [f"| {c} | {h} | {examples[h][0]} {examples[h][1]}: {examples[h][2].replace('|', '/')} |"
              for h, c in shapes.most_common(args.show)]
    (cfg.var / "m4_gate.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
