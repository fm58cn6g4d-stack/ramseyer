"""Drafting-error detection benchmark (red team, question 1). Known-good instructions from the tuning corpus (applied
CLEAN, section text equal to R_after) are copied with one realistic drafting error each; billmap should no longer
call the result CLEAN. Errors are injected into the parsed instruction, so this measures the resolver and the
dry-run engine, not the parser. Writes var/m6c_errors.md.
Run:  .venv/bin/python scripts/m6c_error_benchmark.py [--sample 300] [--seed 20261029] [--set tuning]
"""
from __future__ import annotations

import argparse
import collections
import random
import re
import sys
import time

from billmap import config
from billmap.data.http import Fetcher
from billmap.data.index import Index, LookupError_
from billmap.dryrun.predict import run_bill
from billmap.oracle import harness, store
from billmap.oracle.corpus import MANIFEST, Corpus
from billmap.parse import parse_text
from billmap.parse.xmltext import render
from billmap.resolve import popular
from billmap.resolve.actcode import classification_map
from billmap.resolve.resolver import Resolver, classification_rows

TEXT_OPS = ("STRIKE_INSERT", "STRIKE", "INSERT_AFTER", "INSERT_BEFORE", "STRIKE_THROUGH")


def change_word(s: str, rnd: random.Random) -> str | None:
    """A stale quote: one word or number of the quoted text changed."""
    words = [m for m in re.finditer(r"[A-Za-z]{4,}|\d+", s)]
    if not words:
        return None
    m = rnd.choice(words)
    w = m.group(0)
    new = str(int(w) + 1) if w.isdigit() else (w[:-1] + ("s" if w[-1] != "s" else "x"))
    return s[:m.start()] + new + s[m.end():]


def next_label(lab: str) -> str | None:
    x = lab.strip("()")
    if x.isdigit():
        return f"({int(x) + 1})"
    if len(x) == 1 and x.isalpha() and x not in "zZ":
        return f"({chr(ord(x) + 1)})"
    return None


def mutations(ins, ix, rnd):
    """(kind, mutated instruction) pairs applicable to one instruction."""
    out = []
    t = ins.target
    if ins.op in TEXT_OPS and ins.find and len(ins.find) > 3:
        f = change_word(ins.find, rnd)
        if f and f != ins.find:
            out.append(("stale quote (one word or number changed)", ins.model_copy(update={"find": f})))
        m = re.search(r"\$?\d[\d,]*\d", ins.find)
        if m and "," in m.group(0):
            shorter = m.group(0).rsplit(",", 1)[0]
            out.append(("stale amount (a shorter number that the current one starts with)",
                        ins.model_copy(update={"find": ins.find.replace(m.group(0), shorter, 1)})))
        if ins.occurrence == "first":
            out.append(("ordinal that does not exist (“the second place it appears”)",
                        ins.model_copy(update={"occurrence": "nth:2"})))
    if t.kind == "usc" and t.section and re.fullmatch(r"\d+", t.section):
        for d in (1, -1):
            sec = str(int(t.section) + d)
            try:
                ix.by_identifier(f"/us/usc/t{t.title}/s{sec}")
            except LookupError_:
                continue
            tt = t.model_copy(update={"section": sec, "cite_norm": None})
            out.append(("neighbouring section number", ins.model_copy(update={"target": tt})))
            break
    if t.path:
        lab = next_label(t.path[-1])
        if lab:
            tt = t.model_copy(update={"path": t.path[:-1] + [lab]})
            out.append(("wrong unit label in the location", ins.model_copy(update={"target": tt})))
    if ins.op == "REPLACE_UNIT" and ins.unit and ins.new_text:
        m = re.match(r"^(“?)\((\w+)\)", ins.new_text)
        lab = next_label(f"({m.group(2)})") if m else None
        if lab:
            out.append(("replacement block with the wrong label",
                        ins.model_copy(update={"new_text": ins.new_text.replace(f"({m.group(2)})", lab, 1)})))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20261029)
    args = ap.parse_args()
    cfg = config.load()
    f = Fetcher(cfg)
    t0 = time.monotonic()
    resolver = Resolver(Index(cfg.index_path, cfg.release_pin), popular.load(),
                        classification_map(classification_rows(f, cfg.olrc_base)))
    corpus = Corpus.load(MANIFEST)
    rnd = random.Random(args.seed)
    good = []                                   # (law, before index, instruction) applied CLEAN on a matching section
    for law in corpus.laws:
        before, after = store.index(law.rp_before), store.index(law.rp_after)
        instructions = parse_text(render(f.get(law.enrolled_url).path)).instructions
        run = run_bill(instructions, resolver, before)
        preds = {p.identifier: p for p in run.predictions}
        for tr in run.traces:
            p = preds.get(tr.section or "")
            if not (tr.result and tr.result.status == "CLEAN" and p and p.status == "CLEAN"):
                continue
            at, _ = harness.section_text(after, tr.section)
            if harness.normalize(p.text) == harness.normalize(at) and "." not in tr.instruction.id.split("#")[1]:
                good.append((law, before, tr.instruction))
    sample = rnd.sample(good, min(args.sample, len(good)))
    tally = collections.defaultdict(lambda: [0, 0])     # kind -> [applicable, detected]
    misses = collections.defaultdict(list)
    reasons = collections.defaultdict(collections.Counter)
    controls = 0
    for law, before, ins in sample:
        base = run_bill([ins], resolver, before).traces[0].result
        controls += base is not None and base.status == "CLEAN"
        for kind, mut in mutations(ins, before, rnd):
            r = run_bill([mut], resolver, before).traces[0].result
            tally[kind][0] += 1
            if r is not None and r.status != "CLEAN":
                tally[kind][1] += 1
                reasons[kind][r.status] += 1
            else:
                misses[kind].append(f"{law.pl} {ins.id}: {mut.target.cite_norm or mut.target.cite_raw} "
                                    f"{''.join(mut.target.path)} find={mut.find!r:.60} occ={mut.occurrence}")
    total = [sum(v[0] for v in tally.values()), sum(v[1] for v in tally.values())]
    lines = ["# M6c drafting-error detection benchmark", "",
             f"Run {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}; {time.monotonic() - t0:.0f}s; seed {args.seed}. "
             f"{len(good)} known-good instructions on the tuning corpus; {len(sample)} sampled; unmutated controls "
             f"still CLEAN: {controls} of {len(sample)}.", "",
             "| Injected error | Cases | Detected (not CLEAN) | Rate | Statuses given |", "| --- | --- | --- | --- | --- |"]
    for kind, (n, d) in sorted(tally.items()):
        lines.append(f"| {kind} | {n} | {d} | {d / max(n, 1):.1%} | "
                     + ", ".join(f"{k} {v}" for k, v in reasons[kind].most_common()) + " |")
    lines.append(f"| all | {total[0]} | {total[1]} | {total[1] / max(total[0], 1):.1%} | |")
    lines += ["", "## Missed (still CLEAN), first 10 per kind", ""]
    for kind, ms in sorted(misses.items()):
        lines += [f"### {kind}", ""] + [f"- {m}" for m in ms[:10]] + [""]
    (cfg.var / "m6c_errors.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
