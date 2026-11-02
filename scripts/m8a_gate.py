"""M8a gate: run each instruction against the Act's own text (HOLC's Statute Compilations) and the Code, and report
every disagreement with a reason (docs/06-dry-run.md, "Act and Code cross-check"; src/ramseyer/dryrun/actside.py).

The oracle laws are enacted, and the compilations are current only, so for a law the compilation already incorporates
the Act side should find the change made (ALREADY_EXECUTED) or, where later laws changed the text again, not find the
quote; the Code side runs at the law's R_before as in M6. Each instruction that targets an Act gets one reading, and
each reading's reason is listed; none is dropped.

Run:  .venv/bin/python scripts/m8a_gate.py [--set tuning] [--law 116-136 ...]
      Needs var/comps/comps.sqlite (ramseyer.data.comps.load_compilations). Writes var/m8a_gate.md and var/m8a_rows.jsonl.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import time
from pathlib import Path

from ramseyer import config
from ramseyer.data.http import Fetcher
from ramseyer.data.index import Index
from ramseyer.dryrun.actside import confirmation, reading, run_on_act
from ramseyer.dryrun.engine import SEVERITY
from ramseyer.dryrun.predict import run_bill
from ramseyer.oracle import store
from ramseyer.oracle.corpus import MANIFEST, Corpus
from ramseyer.parse import parse_text
from ramseyer.parse.xmltext import render
from ramseyer.resolve import popular
from ramseyer.resolve.actcode import classification_map
from ramseyer.resolve.cites import parse_parenthetical
from ramseyer.resolve.resolver import Resolver, classification_rows


def law_key(text: str | None) -> tuple[int, int] | None:
    """(Congress, law number) from a currency such as "currentThroughPublicLaw: 119–103" or "P.L. 119–118, Enacted
    ..."; None when the currency names no public law."""
    m = re.search(r"(\d+)\s*[–-]\s*(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def incorporates(currency: list[str], pl: str) -> bool:
    """Every compilation file used is current through this law or a later one, so its text already carries the law
    (compilations are current versions only: records/verify-first.md, M8a)."""
    want = law_key(pl)
    keys = [law_key(c) for c in currency]
    return bool(keys) and want is not None and all(k is not None and k >= want for k in keys)


def worst(statuses):
    return max(statuses, key=SEVERITY.index) if statuses else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--law", nargs="+")
    args = ap.parse_args()
    cfg = config.load()
    f = Fetcher(cfg)
    comps_db = cfg.var / "comps" / "comps.sqlite"
    acts = Index(comps_db, "comps")
    rows = classification_rows(f, cfg.olrc_base)
    resolver = Resolver(Index(cfg.index_path, cfg.release_pin), popular.load(), classification_map(rows))
    corpus = Corpus.load(MANIFEST)
    if args.law:
        corpus.laws = [corpus.law(pl) for pl in args.law]
    out_rows, readings, reasons = [], collections.Counter(), collections.defaultdict(collections.Counter)
    t0 = time.monotonic()
    for law in corpus.laws:
        print(f"{time.strftime('%H:%M:%S')} {law.pl}", file=sys.stderr, flush=True)
        instructions = parse_text(render(f.get(law.enrolled_url).path)).instructions
        before = store.index(law.rp_before, store.ORACLE_DB)
        r = Resolver(before, resolver.popular, resolver.classification)
        r.positive = set(resolver.positive)
        run = run_bill(instructions, r, before)
        code = collections.defaultdict(list)
        for tr in run.traces:
            if tr.result is not None:
                code[tr.instruction.id].append(tr.result.status)
        for ins in instructions:
            t = ins.target
            if not (t.act or t.public_law):
                continue                              # a Code citation only: no Act to compare
            ids, _ = resolver._identities(t, parse_parenthetical(t.usc_parenthetical))
            act = run_on_act(ins, ids, acts)
            c = worst(code.get(ins.id, []))
            name, why = reading(act, c)
            if act.status not in ("UNAVAILABLE", "CLEAN", "WARN", "ALREADY_EXECUTED") and \
                    incorporates(act.currency, law.pl):
                # The compilation already carries this law: the quote it strikes may be gone. The test is whether the
                # law's new words are in the Act's section now.
                name = "act already amended"
                why = (f"the compilation ({'; '.join(act.currency)}) already includes Pub. L. {law.pl}; "
                       + confirmation(ins.replace or ins.new_text, act.text))
                act.reason = why
            readings[name] += 1
            key = why.rsplit("; ", 1)[-1] if name == "act already amended" else \
                act.reason if name == "act unavailable" else f"Act {act.status} / Code {c}"
            reasons[name][key] += 1
            out_rows.append({"pl": law.pl, "instruction": ins.id, "act": t.act, "section": t.section,
                             "act_status": act.status, "code_status": c, "reading": name, "reason": why,
                             "files": act.files, "currency": act.currency, "identifier": act.identifier})
    total = sum(readings.values())
    lines = ["# M8a gate: Act and Code cross-check", "",
             f"Set: tuning ({len(corpus.laws)} laws); compilations: {comps_db}; {time.monotonic() - t0:.0f}s", "",
             f"Instructions that target an Act: {total}. Every one has a reading and a reason "
             f"(var/m8a_rows.jsonl).", "", "| Reading | Instructions | Share |", "| --- | --- | --- |"]
    lines += [f"| {k} | {v} | {v / max(total, 1):.1%} |" for k, v in readings.most_common()]
    for k, cnt in sorted(reasons.items()):
        lines += ["", f"## {k}", ""] + [f"- {v} × {why}" for why, v in cnt.most_common(15)]
    gate = all(r["reason"] for r in out_rows)
    lines += ["", f"**Gate (every instruction that targets an Act has a reading with a reason): "
                  f"{'PASS' if gate else 'FAIL'}**"]
    (cfg.var / "m8a_gate.md").write_text("\n".join(lines) + "\n")
    with open(cfg.var / "m8a_rows.jsonl", "w") as fh:
        for row in out_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("\n".join(lines[:12 + len(readings)]))
    return 0 if gate else 1


if __name__ == "__main__":
    sys.exit(main())
