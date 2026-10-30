"""M6 gate (docs/06-dry-run.md, docs/12-testing.md): on the oracle corpus, predicted post-amendment section text
matches the next release point, and the false-clean rate is measured.

Each law's enrolled text is parsed (M4), every target resolved against the pinned index (M5), and each reached
section dry-run on its text at the law's R_before release point. The harness compares the result with R_after.

Run:  .venv/bin/python scripts/m6_gate.py [--law 119-118] [--show 30]
Writes var/m6_gate.md, var/m6_report.json and tests/oracle/m6_baseline.json.
With --set govinfo (M6b): 2024 laws on GovInfo's 2023/2024 Code editions (tests/oracle/heldout_govinfo.json,
built by scripts/build_govinfo_heldout.py); writes var/m6b_govinfo_gate.md and tests/oracle/m6b_govinfo_baseline.json.
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

from ramseyer import config
from ramseyer.data.http import Fetcher
from ramseyer.data.index import Index, LookupError_
from ramseyer.data.indexer import text_of
from ramseyer.dryrun.engine import category
from ramseyer.dryrun.predict import run_bill
from ramseyer.oracle import harness, store
from ramseyer.oracle.govinfo_overlay import GovInfoOverlay
from ramseyer.oracle.corpus import MANIFEST, Corpus
from ramseyer.parse import parse_text
from ramseyer.parse.xmltext import render
from ramseyer.resolve import popular
from ramseyer.resolve.actcode import classification_map
from ramseyer.resolve.resolver import Resolver, classification_rows

HELDOUT = MANIFEST.with_name("heldout.json")
HELDOUT_DB = store.ORACLE_DB.with_name("heldout.sqlite")
SETS = {   # name: (manifest, oracle db, output tag, heading)
    "tuning": (MANIFEST, store.ORACLE_DB, "m6", ""),
    "heldout": (HELDOUT, HELDOUT_DB, "m6b", " (held-out laws)"),
    "govinfo": (MANIFEST.with_name("heldout_govinfo.json"), store.ORACLE_DB.with_name("govinfo.sqlite"), "m6b_govinfo",
                " (held-out: 2024 laws on GovInfo's 2023/2024 editions)"),
    # Sealed (red team F5): built after the second red-team round; measured, never inspected case by case.
    "govinfo2023": (MANIFEST.with_name("heldout_govinfo_2023.json"), store.ORACLE_DB.with_name("govinfo_2023.sqlite"),
                    "m6b_govinfo2023", " (sealed held-out: 2023 laws on GovInfo's 2022/2023 editions)"),
}
FALSE_CLEAN_TARGET = 0.01


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k of n."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return max(0.0, c - h), min(1.0, c + h)


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
            prev.tail = (prev.tail or "").rstrip("\u202f\u00a0 ") + tail
        else:
            parent.text = (parent.text or "").rstrip("\u202f\u00a0 ") + tail
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
    ap.add_argument("--heldout", action="store_true", help="run on the held-out laws (M6b); same as --set heldout")
    ap.add_argument("--set", choices=sorted(SETS), default="tuning")
    ap.add_argument("--resolve-before", action="store_true",
                    help="resolve each law against its R_before release point instead of the pinned index (tuning)")
    ap.add_argument("--refresh-labels", action="store_true",
                    help="re-stamp the hashes of hand labels on this set after checking each difference by hand")
    args = ap.parse_args()
    cfg = config.load()
    f = Fetcher(cfg)
    t0 = time.monotonic()
    resolver = Resolver(Index(cfg.index_path, cfg.release_pin), popular.load(),
                        classification_map(classification_rows(f, cfg.olrc_base)))
    manifest, db, tag, heading = SETS["heldout" if args.heldout else args.set]
    if args.resolve_before:
        tag, heading = tag + "_resolve_before", heading + " (targets resolved against each law's R_before)"
    corpus = Corpus.load(manifest)
    if args.law:
        corpus.laws = [corpus.law(args.law)]
    if args.set.startswith("govinfo") and not args.heldout:
        # Sections outside the answer key are fetched from the same edition on demand (red team F6).
        open_index = lru_cache(maxsize=None)(lambda label: GovInfoOverlay(store.index(label, db), int(label[-4:]), f,
                                                                          resolver.positive))
    else:
        open_index = lru_cache(maxsize=None)(lambda label: store.index(label, db))
    statuses = collections.Counter()
    runs = {}

    missing_status: list[str] = []

    pop, cmap = resolver.popular, resolver.classification
    before_resolver = lru_cache(maxsize=2)(lambda label: Resolver(store.index(label, db), pop, cmap))

    def predictor(law, before):
        instructions = parse_text(render(f.get(law.enrolled_url).path)).instructions
        # --resolve-before: resolve against the Code as it stood before the law (red team F15), as a drafter would.
        res = before_resolver(law.rp_before) if args.resolve_before else resolver
        run = run_bill(instructions, res, before)
        runs[law.pl] = run
        with_status = {tr.instruction.id for tr in run.traces if tr.result is not None and tr.result.status}
        missing_status.extend(f"{law.pl} {i.id}" for i in instructions if i.id not in with_status)
        for tr in run.traces:
            statuses[tr.result.status if tr.result else f"unattributed:{tr.resolution.outcome}"] += 1
        return run.predictions

    rep = harness.evaluate(corpus, predictor, "ramseyer M6", open_index, labels=None)
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
    # Off-target CLEAN predictions are graded only on sections no law in the window touched: elsewhere the next
    # edition carries the other laws' changes too.
    touched_path = manifest.with_name(manifest.stem + "_touched.json")
    touched = json.loads(touched_path.read_text()) if touched_path.exists() else {}
    ungradable = [o for o in rep.outcomes if o.outcome in ("extra", "unexpected_change") and o.status == "CLEAN"
                  and o.identifier in touched]
    for o in ungradable:
        o.after_differs = None
        o.stage = "ungradable"
    m["clean_off_target"] -= len(ungradable)
    off = [o for o in rep.outcomes if o.outcome in ("extra", "unexpected_change") and o.status == "CLEAN"
           and o.after_differs is not False and o.stage != "ungradable"]
    off_sub = 0
    for o in off:
        law = corpus.law(o.pl)
        work = runs[o.pl].working.get(o.identifier)
        try:
            ix = open_index(law.rp_after)
            after_xml = ix.section_xml(ix.by_identifier(o.identifier))
        except LookupError_:
            after_xml = None
        if not (work is not None and not work.removed and editorial_equal(work.el, after_xml)):
            off_sub += 1
            o.stage = "unclassified"
        else:
            o.stage = "editorial"
    graded = m["matched"] + m["mismatched"]
    clean_mism = [o for o in mism if o.status == "CLEAN"]
    labels = json.loads(harness.LABELS.read_text()) if harness.LABELS.exists() else {}
    # Hand labels bind to the exact texts they were checked against; list the ones that no longer apply.
    label_rows = []
    for o in mism:
        key = f"{o.pl} {o.identifier}"
        if key not in labels:
            continue
        work = runs[o.pl].working.get(o.identifier)
        pred = work.render() if work is not None else None
        try:
            after = harness.section_text(open_index(corpus.law(o.pl).rp_after), o.identifier)[0]
        except LookupError_:
            after = None
        lab = labels[key]
        applies = harness.label_stage(lab, pred, after) is not None
        label_rows.append(f"- {key}: {'applies' if applies else 'EXPIRED'}: {o.detail[:200]}")
        if args.refresh_labels and not applies:
            reason = lab.get("reason", "") if isinstance(lab, dict) else ""
            labels[key] = {"stage": "editorial", "reason": reason, "pred": harness.text_hash(pred),
                           "after": harness.text_hash(after)}
    if args.refresh_labels:
        harness.LABELS.write_text(json.dumps(labels, indent=1, ensure_ascii=False) + "\n")
    labelled = sum(1 for o in clean_mism if f"{o.pl} {o.identifier}" in labels and o.stage == "editorial"
                   and (o.pl, o.identifier) not in detected_ids)
    detected = sum(1 for o in clean_mism if (o.pl, o.identifier) in detected_ids)
    substantive = sum(1 for o in clean_mism if o.stage != "editorial")
    checks = [
        ("Every parsed instruction has a status (never drop)", not missing_status,
         f"{sum(statuses.values())} statuses; instructions without one: {len(missing_status)}"
         + (f" (e.g. {', '.join(missing_status[:5])})" if missing_status else "")),
        ("Predicted post-amendment text matches the next release point (measured)", True,
         f"targets {m['targets']}: matched {m['matched']}, mismatched {m['mismatched']}, missed {m['missed']} "
         f"(match rate {m['match_rate']}; {m['matched']}/{graded} of predicted targets); pending-effective-date "
         f"{m['pending']}; extra {m['extra']}, unexpected change {m['unexpected_change']}; of the mismatches, "
         f"{editorial} differ only editorially (enactment date substituted, footnote markers, heading case)"),
        (f"False-clean rate under {FALSE_CLEAN_TARGET:.0%} (substantive: OLRC editorial differences excluded)",
         (substantive + off_sub) / max(m["clean"] + m["clean_off_target"], 1) < FALSE_CLEAN_TARGET,
         f"{substantive} of {m['clean']} CLEAN predictions differ from R_after in substance "
         f"(rate {substantive / max(m['clean'], 1):.4f}); off target (sections not classified to the law): "
         f"{off_sub} of {m['clean_off_target']} CLEAN differ in substance ({len(ungradable)} more on sections other "
         f"laws in the window also changed, not gradable); combined rate "
         f"{(substantive + off_sub) / max(m['clean'] + m['clean_off_target'], 1):.4f}; raw rate {m['false_clean_rate']} ({m['false_clean']} differ "
         f"in any way: {detected} editorial-only by the detector, {labelled} labelled editorial in "
         f"tests/oracle/labels.json after checking against the enrolled text)"),
        ("Confident answers (measured)", True,
         f"{m['clean']} of {m['targets']} targets have a CLEAN prediction ({m['clean'] / max(m['targets'], 1):.1%}); "
         f"{m['clean'] - substantive} of them right in substance ({(m['clean'] - substantive) / max(m['targets'], 1):.1%} "
         f"of targets)"),
    ]
    by_stage = collections.Counter(o.stage for o in mism)
    halves = []
    if tag == "m6b_govinfo":
        # Dev half (even public-law numbers) is used to find and fix errors; the test half (odd) is only measured.
        for name, keep in (("dev (even laws)", 0), ("test (odd laws)", 1)):
            os_ = [o for o in rep.outcomes if int(o.pl.split("-")[1]) % 2 == keep]
            tg = sum(o.outcome in ("match", "mismatch", "missed") for o in os_)
            cl = [o for o in os_ if o.outcome in ("match", "mismatch") and o.status == "CLEAN"]
            sub = sum(o.outcome == "mismatch" and o.stage != "editorial" for o in cl)
            offc = [o for o in os_ if o.outcome in ("extra", "unexpected_change") and o.status == "CLEAN"
                    and o.stage != "ungradable"]
            offw = sum(o.after_differs is not False and o.stage != "editorial" for o in offc)
            halves.append(f"- {name}: targets {tg}, matched {sum(o.outcome == 'match' for o in os_)}, CLEAN {len(cl)} "
                          f"({len(cl) / max(tg, 1):.1%} of targets), substantive false-clean {sub} "
                          f"({sub / max(len(cl), 1):.2%}), raw {sum(o.outcome == 'mismatch' for o in cl)}; "
                          f"off target: CLEAN {len(offc)}, wrong {offw}; combined "
                          f"{(sub + offw) / max(len(cl) + len(offc), 1):.2%}")
    # Per law, and NDAA vs other laws (red team F5): CLEAN, substantive false-clean, 95% Wilson interval.
    def tally(os_):
        cl = [o for o in os_ if o.outcome in ("match", "mismatch") and o.status == "CLEAN"]
        sub = sum(o.outcome == "mismatch" and o.stage != "editorial" for o in cl)
        offc = [o for o in os_ if o.outcome in ("extra", "unexpected_change") and o.status == "CLEAN"
                and o.stage != "ungradable"]
        offw = sum(o.after_differs is not False and o.stage != "editorial" for o in offc)
        tg = sum(o.outcome in ("match", "mismatch", "missed") for o in os_)
        return tg, len(cl) + len(offc), sub + offw

    def row(name, os_):
        tg, n, k = tally(os_)
        lo, hi = wilson(k, n)
        return f"| {name} | {tg} | {n} | {k} | {k / max(n, 1):.2%} | {lo:.2%}–{hi:.2%} |"
    ndaa = {l.pl for l in corpus.laws if "National Defense Authorization" in (l.name or "")}
    strata = ["| Laws | Targets | CLEAN (incl. off target) | Wrong in substance | Rate | 95% interval |",
              "| --- | --- | --- | --- | --- | --- |",
              row("all", rep.outcomes), row("National Defense Authorization Acts", [o for o in rep.outcomes if o.pl in ndaa]),
              row("all other laws", [o for o in rep.outcomes if o.pl not in ndaa])]
    per_law = [row(pl, [o for o in rep.outcomes if o.pl == pl]) for pl in sorted(rep.by_law, key=lambda p: tuple(
        int(x) for x in p.split("-")))]
    lines = [f"# {tag.upper()} gate" + heading, "", f"Index {cfg.release_pin}; run {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}; "
             f"{time.monotonic() - t0:.0f}s.", "", "| Check | Result | Measured |", "| --- | --- | --- |"]
    lines += [f"| {n} | {'PASS' if ok else 'FAIL'} | {d.replace('|', '/')} |" for n, ok, d in checks]
    cats = collections.Counter()
    for k, v in statuses.items():
        cats[category(k) or "carried out or nothing to do"] += v
    lines += ["", "Instruction statuses: " + ", ".join(f"{k} {v}" for k, v in statuses.most_common()),
              "", "Failure categories (Comparative Print Suite): " + ", ".join(f"{k} {v}" for k, v in cats.most_common()),
              "", "Mismatches by stage: " + ", ".join(f"{k} {v}" for k, v in by_stage.most_common()),
              *(["", "Halves:", *halves] if halves else []),
              "", "## Strata", "", *strata, "", "## CLEAN and wrong per law", "",
              "| Law | Targets | CLEAN | Wrong | Rate | 95% interval |", "| --- | --- | --- | --- | --- | --- |", *per_law,
              "", "Hand labels on this set (tests/oracle/labels.json):", *(label_rows or ["- none"]),
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
        MANIFEST.with_name(f"{tag}_baseline.json").write_text(json.dumps({"predictor": "ramseyer M6", "metrics": m}, indent=1) + "\n")
    print("\n".join(lines))
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
