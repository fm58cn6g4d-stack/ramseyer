"""M6 gate (docs/06-dry-run.md, docs/12-testing.md): on the oracle corpus, predicted post-amendment section text
matches the next release point, and the false-clean rate is measured.

Each law's enrolled text is parsed (M4), every target resolved against the pinned index (M5), and each reached
section dry-run on its text at the law's R_before release point. The harness compares the result with R_after.

Run:  .venv/bin/python scripts/m6_gate.py [--law 119-118] [--show 30]
Writes var/m6_gate.md, var/m6_report.json and tests/oracle/m6_baseline.json.
With --heldout (M6b): the held-out laws (tests/oracle/heldout.json, built by scripts/build_heldout.py); writes
var/m6b_gate.md, var/m6b_report.json and tests/oracle/m6b_baseline.json.
"""
from __future__ import annotations

import argparse
import copy
import re
import collections
import json
import sys
import time
from functools import lru_cache

from lxml import etree

from billmap import config
from billmap.data.http import Fetcher
from billmap.data.index import Index, LookupError_
from billmap.data.indexer import text_of
from billmap.dryrun.predict import run_bill
from billmap.oracle import harness, store
from billmap.oracle.corpus import MANIFEST, Corpus
from billmap.parse import parse_text
from billmap.parse.xmltext import render
from billmap.resolve import popular
from billmap.resolve.actcode import classification_map
from billmap.resolve.resolver import Resolver, classification_rows

HELDOUT = MANIFEST.with_name("heldout.json")
HELDOUT_DB = store.ORACLE_DB.with_name("heldout.sqlite")
FALSE_CLEAN_TARGET = 0.01


DATE_PHRASE = re.compile(r"(?:the )?date of (?:the )?enactment of (?:this (?:Act|section|subsection|paragraph)|the [A-Z][\w ,.\u2019'()-]*?Act(?: of \d{4})?(?: for Fiscal Year \d{4})?)")
DATE = r"(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}"


def _text(el) -> str:
    """Section text with footnote reference markers removed (OLRC adds and removes footnotes editorially)."""
    el = copy.deepcopy(el)
    marks = el.xpath(".//*[local-name()='ref'][@class='footnoteRef'] | .//*[local-name()='note'][@type='footnote']"
                     " | .//*[local-name()='sup'][re:test(., '^\\s*\\d+\\s*$')]",
                     namespaces={"re": "http://exslt.org/regular-expressions"})
    for ref in marks:
        parent, tail = ref.getparent(), ref.tail or ""
        prev = ref.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "").rstrip("\u202f") + tail
        else:
            parent.text = (parent.text or "").rstrip("\u202f") + tail
        parent.remove(ref)
    for h in el.iter("{*}heading"):     # heading case is OLRC's editorial choice (records/milestones.md, M6)
        for n in h.iter():
            n.text = n.text.lower() if n.text else n.text
            if n is not h and n.tail:
                n.tail = n.tail.lower()
    return re.sub(r"\s+", " ", harness.normalize(text_of(el)))


def editorial_equal(pred_el, after_xml: str | None) -> bool:
    """True when the prediction equals R_after except for OLRC's editorial work: footnote markers, the letter
    case of headings, and the enactment date set in place of "the date of the enactment of this Act" (any date
    is accepted there)."""
    if pred_el is None or after_xml is None:
        return False
    pred, after = _text(pred_el), _text(etree.fromstring(after_xml.encode("utf-8")))
    parts = DATE_PHRASE.split(pred)
    rx = f"(?:{DATE}|{DATE_PHRASE.pattern})".join(re.escape(p) for p in parts)
    return re.fullmatch(rx, after) is not None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--law")
    ap.add_argument("--show", type=int, default=30)
    ap.add_argument("--heldout", action="store_true", help="run on the held-out laws (M6b)")
    args = ap.parse_args()
    cfg = config.load()
    f = Fetcher(cfg)
    t0 = time.monotonic()
    resolver = Resolver(Index(cfg.index_path, cfg.release_pin), popular.load(),
                        classification_map(classification_rows(f, cfg.olrc_base)))
    corpus = Corpus.load(HELDOUT if args.heldout else MANIFEST)
    tag = "m6b" if args.heldout else "m6"
    if args.law:
        corpus.laws = [corpus.law(args.law)]
    db = HELDOUT_DB if args.heldout else store.ORACLE_DB
    open_index = lru_cache(maxsize=None)(lambda label: store.index(label, db))
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
    editorial = 0
    detected_ids: set[tuple[str, str]] = set()
    for o in mism:
        law = corpus.law(o.pl)
        work = runs[o.pl].working.get(o.identifier)
        try:
            ix = open_index(law.rp_after)
            after_xml = ix.section_xml(ix.by_identifier(o.identifier))
        except LookupError_:
            after_xml = None
        if work is not None and not work.removed and editorial_equal(work.el, after_xml):
            o.stage = "editorial"
            detected_ids.add((o.pl, o.identifier))
            editorial += 1
    graded = m["matched"] + m["mismatched"]
    clean_mism = [o for o in mism if o.status == "CLEAN"]
    labels = json.loads(harness.LABELS.read_text()) if harness.LABELS.exists() else {}
    labelled = sum(1 for o in clean_mism if f"{o.pl} {o.identifier}" in labels and o.stage == "editorial"
                   and (o.pl, o.identifier) not in detected_ids)
    detected = sum(1 for o in clean_mism if (o.pl, o.identifier) in detected_ids)
    substantive = sum(1 for o in clean_mism if o.stage != "editorial")
    checks = [
        ("Predicted post-amendment text matches the next release point (measured)", True,
         f"targets {m['targets']}: matched {m['matched']}, mismatched {m['mismatched']}, missed {m['missed']} "
         f"(match rate {m['match_rate']}; {m['matched']}/{graded} of predicted targets); pending-effective-date "
         f"{m['pending']}; extra {m['extra']}, unexpected change {m['unexpected_change']}; of the mismatches, "
         f"{editorial} differ only editorially (enactment date substituted, footnote markers, heading case)"),
        (f"False-clean rate under {FALSE_CLEAN_TARGET:.0%} (substantive: OLRC editorial differences excluded)",
         substantive / max(m["clean"], 1) < FALSE_CLEAN_TARGET,
         f"{substantive} of {m['clean']} CLEAN predictions differ from R_after in substance "
         f"(rate {substantive / max(m['clean'], 1):.4f}); raw rate {m['false_clean_rate']} ({m['false_clean']} differ "
         f"in any way: {detected} editorial-only by the detector, {labelled} labelled editorial in "
         f"tests/oracle/labels.json after checking against the enrolled text)"),
        ("Confident answers (measured)", True,
         f"{m['clean']} of {m['targets']} targets have a CLEAN prediction ({m['clean'] / max(m['targets'], 1):.1%}); "
         f"{m['clean'] - substantive} of them right in substance ({(m['clean'] - substantive) / max(m['targets'], 1):.1%} "
         f"of targets)"),
    ]
    by_stage = collections.Counter(o.stage for o in mism)
    lines = [f"# {tag.upper()} gate" + (" (held-out laws)" if args.heldout else ""), "", f"Index {cfg.release_pin}; run {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}; "
             f"{time.monotonic() - t0:.0f}s.", "", "| Check | Result | Measured |", "| --- | --- | --- |"]
    lines += [f"| {n} | {'PASS' if ok else 'FAIL'} | {d.replace('|', '/')} |" for n, ok, d in checks]
    lines += ["", "Instruction statuses: " + ", ".join(f"{k} {v}" for k, v in statuses.most_common()),
              "", "Mismatches by stage: " + ", ".join(f"{k} {v}" for k, v in by_stage.most_common()),
              "", "## Per law", ""]
    lines += [f"- {pl}: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())) for pl, c in rep.by_law.items()]
    lines += ["", f"## Mismatches (first {args.show}; CLEAN ones first)", ""]
    for o in sorted(mism, key=lambda o: o.status != "CLEAN")[:args.show]:
        lines.append(f"- {o.pl} {o.identifier} [{o.status}, {o.stage}] {o.detail[:300]}")
    (cfg.var / f"{tag}_gate.md").write_text("\n".join(lines) + "\n")
    (cfg.var / f"{tag}_report.json").write_text(rep.model_dump_json(indent=1))
    with open(cfg.var / f"{tag}_traces.jsonl", "w") as fh:      # per-instruction trace, for diagnosis
        for pl, run in runs.items():
            for tr in run.traces:
                i, r = tr.instruction, tr.result
                fh.write(json.dumps({"pl": pl, "section": tr.section, "id": i.id, "op": i.op, "unit": i.unit,
                                     "find": i.find, "new": i.new_text, "replace": i.replace, "flags": i.flags,
                                     "resolution": tr.resolution.outcome, "path": list(tr.resolution.path),
                                     "status": r.status if r else None, "detail": r.detail if r else None,
                                     "before": r.before_span if r else None, "after": r.after_span if r else None},
                                    ensure_ascii=False) + "\n")
    if not args.law:
        MANIFEST.with_name(f"{tag}_baseline.json").write_text(json.dumps({"predictor": "billmap M6", "metrics": m}, indent=1) + "\n")
    print("\n".join(lines))
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
