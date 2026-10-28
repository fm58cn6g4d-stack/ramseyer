"""M6 gate (docs/06-dry-run.md, docs/12-testing.md): on the oracle corpus, predicted post-amendment section text
matches the next release point, and the false-clean rate is measured.

Each law's enrolled text is parsed (M4), every target resolved against the pinned index (M5), and each reached
section dry-run on its text at the law's R_before release point. The harness compares the result with R_after.

Run:  .venv/bin/python scripts/m6_gate.py [--law 119-118] [--show 30]
Writes var/m6_gate.md, var/m6_report.json and tests/oracle/m6_baseline.json.
"""
from __future__ import annotations

import argparse
import re
import collections
import json
import sys
import time
from functools import lru_cache

from billmap import config
from billmap.data.http import Fetcher
from billmap.data.index import Index
from billmap.dryrun.predict import run_bill
from billmap.oracle import harness, store
from billmap.oracle.corpus import MANIFEST, Corpus
from billmap.parse import parse_text
from billmap.parse.xmltext import render
from billmap.resolve import popular
from billmap.resolve.actcode import classification_map
from billmap.resolve.resolver import Resolver, classification_rows

BASELINE = MANIFEST.with_name("m6_baseline.json")
FALSE_CLEAN_TARGET = 0.01


DATE_PHRASE = re.compile(r"(?:the )?date of (?:the )?enactment of (?:this (?:Act|section|subsection|paragraph)|the [A-Z][\w ,.\u2019'()-]*?Act(?: of \d{4})?(?: for Fiscal Year \d{4})?)")
DATE = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}")


def editorial_equal(pred: str | None, after: str | None) -> bool:
    if pred is None or after is None:
        return False
    def norm(s):
        s = harness.normalize(s)
        s = DATE_PHRASE.sub("DATE", s)
        s = DATE.sub("DATE", s)
        s = re.sub(r"(?<=[.,;:a-z\u201d)])\s?\d{1,2}(?=\s|$)", "", s)      # footnote markers
        return re.sub(r"\s+", " ", s)
    return norm(pred) == norm(after)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--law")
    ap.add_argument("--show", type=int, default=30)
    args = ap.parse_args()
    cfg = config.load()
    f = Fetcher(cfg)
    t0 = time.monotonic()
    resolver = Resolver(Index(cfg.index_path, cfg.release_pin), popular.load(),
                        classification_map(classification_rows(f, cfg.olrc_base)))
    corpus = Corpus.load()
    if args.law:
        corpus.laws = [corpus.law(args.law)]
    open_index = lru_cache(maxsize=None)(store.index)
    statuses = collections.Counter()
    runs = {}

    def predictor(law, before):
        run = run_bill(parse_text(render(f.get(law.enrolled_url).path)).instructions, resolver, before)
        runs[law.pl] = run
        for tr in run.traces:
            statuses[tr.result.status if tr.result else f"unattributed:{tr.resolution.outcome}"] += 1
        return run.predictions

    rep = harness.evaluate(corpus, predictor, "billmap M6", open_index, labels=None)
    m = rep.metrics
    mism = [o for o in rep.outcomes if o.outcome == "mismatch"]
    # Editorial-only differences: OLRC substitutes the enactment date for "the date of enactment of ..." and
    # removes or adds footnote markers. Counted separately; they remain mismatches in the match rate.
    preds = {(pl, p.identifier): p for pl, run in runs.items() for p in run.predictions}
    editorial = 0
    for o in mism:
        law = corpus.law(o.pl)
        t = harness.truth(law, open_index(law.rp_before), open_index(law.rp_after)).get(o.identifier, {})
        p = preds.get((o.pl, o.identifier))
        if p and editorial_equal(p.text, t.get("after")):
            o.stage = "editorial"
            editorial += 1
    graded = m["matched"] + m["mismatched"]
    checks = [
        ("Predicted post-amendment text matches the next release point (measured)", True,
         f"targets {m['targets']}: matched {m['matched']}, mismatched {m['mismatched']}, missed {m['missed']} "
         f"(match rate {m['match_rate']}; {m['matched']}/{graded} of predicted targets); pending-effective-date "
         f"{m['pending']}; extra {m['extra']}, unexpected change {m['unexpected_change']}; of the mismatches, "
         f"{editorial} differ only editorially (enactment date substituted, footnote markers)"),
        (f"False-clean rate under {FALSE_CLEAN_TARGET:.0%}", m["false_clean_rate"] < FALSE_CLEAN_TARGET,
         f"{m['false_clean']} of {m['clean']} CLEAN predictions disagree with R_after "
         f"(rate {m['false_clean_rate']})"),
    ]
    by_stage = collections.Counter(o.stage for o in mism)
    lines = ["# M6 gate", "", f"Index {cfg.release_pin}; run {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}; "
             f"{time.monotonic() - t0:.0f}s.", "", "| Check | Result | Measured |", "| --- | --- | --- |"]
    lines += [f"| {n} | {'PASS' if ok else 'FAIL'} | {d.replace('|', '/')} |" for n, ok, d in checks]
    lines += ["", "Instruction statuses: " + ", ".join(f"{k} {v}" for k, v in statuses.most_common()),
              "", "Mismatches by stage: " + ", ".join(f"{k} {v}" for k, v in by_stage.most_common()),
              "", "## Per law", ""]
    lines += [f"- {pl}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())) for pl, c in rep.by_law.items()]
    lines += ["", f"## Mismatches (first {args.show}; CLEAN ones first)", ""]
    for o in sorted(mism, key=lambda o: o.status != "CLEAN")[:args.show]:
        lines.append(f"- {o.pl} {o.identifier} [{o.status}, {o.stage}] {o.detail[:300]}")
    (cfg.var / "m6_gate.md").write_text("\n".join(lines) + "\n")
    (cfg.var / "m6_report.json").write_text(rep.model_dump_json(indent=1))
    if not args.law:
        BASELINE.write_text(json.dumps({"predictor": "billmap M6", "metrics": m}, indent=1) + "\n")
    print("\n".join(lines))
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
