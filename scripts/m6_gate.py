"""M6 gate (docs/06-dry-run.md, docs/12-testing.md): on the oracle corpus, predicted post-amendment section text
matches the next release point, and the false-clean rate is measured.

Each law's enrolled text is parsed (M4), every target resolved against the pinned index (M5), and each reached
section dry-run on its text at the law's R_before release point. The harness compares the result with R_after.

Run:  .venv/bin/python scripts/m6_gate.py [--law 119-118] [--show 30]
Writes var/m6_gate.md, var/m6_report.json and tests/oracle/m6_baseline.json. Each graded law is appended to
var/<tag>_checkpoint.jsonl; an interrupted run started again with the same code and inputs resumes from it.
With --set govinfo (M6b): 2024 laws on GovInfo's 2023/2024 Code editions (tests/oracle/heldout_govinfo.json,
built by scripts/build_govinfo_heldout.py); writes var/m6b_govinfo_gate.md and tests/oracle/m6b_govinfo_baseline.json.
With --heldout (M6b): the held-out laws (tests/oracle/heldout.json, built by scripts/build_heldout.py); writes
var/m6b_gate.md, var/m6b_report.json and tests/oracle/m6b_baseline.json.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sqlite3
import sys
import time
from functools import lru_cache
from pathlib import Path

from ramseyer import config
from ramseyer.data.http import Fetcher
from ramseyer.data.index import Index, LookupError_
from ramseyer.dryrun.engine import category
from ramseyer.dryrun.predict import run_bill
from ramseyer.oracle import editorial, harness, store
from ramseyer.oracle.govinfo_overlay import GovInfoOverlay
from ramseyer.oracle.history import History, ReleaseIndexes
from ramseyer.oracle.corpus import MANIFEST, Corpus
from ramseyer.parse import gpo, parse_text
from ramseyer.parse.grammar import Ctx, apply_head, lift_quotes
from ramseyer.parse.xmltext import render
from ramseyer.resolve import popular
from ramseyer.resolve.actcode import classification_map
from ramseyer.resolve.resolver import Resolver, classification_rows

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "ramseyer"
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
    # M6e: laws from 113-21 on, on the release-point history (scripts/build_history_oracle.py). dev and dev 2 (the
    # former test set) may be tuned on; sealed is measured once per round and never inspected case by case.
    "history_dev": (MANIFEST.with_name("history_dev.json"), store.ORACLE_DB.with_name("history_cache"),
                    "m6e_dev", " (2013-2026 history: dev)"),
    # Measured once as a held-out set (8.17%, records/milestones.md); since 2026-10-31 a second dev set (Espen).
    "history_test": (MANIFEST.with_name("history_test.json"), store.ORACLE_DB.with_name("history_cache"),
                     "m6e_test", " (2013-2026 history: dev 2, formerly test)"),
    "history_sealed": (MANIFEST.with_name("history_sealed.json"), store.ORACLE_DB.with_name("history_cache"),
                       "m6e_sealed", " (2013-2026 history: sealed, measured once per round)"),
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


def data_fingerprint(cfg, set_name: str, db: Path) -> dict:
    """What the loaded data says about itself: the history's shards, or the oracle store's release points, and the
    pinned index's release points (label and source hash)."""
    out = {}
    stores = {"pinned": cfg.index_path}
    if set_name.startswith("history_"):
        stores["history"] = cfg.var / "history" / "history.sqlite"
    else:
        stores["oracle"] = db
    for name, path in stores.items():
        if not Path(path).exists():
            out[name] = None
            continue
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        q = ("SELECT name, sha256, rows FROM loaded_shards ORDER BY name" if name == "history" else
             "SELECT label, source_sha256, complete FROM release_points ORDER BY id")
        out[name] = con.execute(q).fetchall()
        con.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--law", nargs="+", help="only these laws (outputs tagged _laws)")
    ap.add_argument("--dump", action="store_true",
                    help="write each CLEAN prediction that differs from R_after in substance, in full, with its "
                         "instructions and R_after's new notes, to var/<tag>_dump.jsonl (for diagnosis)")
    ap.add_argument("--show", type=int, default=30)
    ap.add_argument("--heldout", action="store_true", help="run on the held-out laws (M6b); same as --set heldout")
    ap.add_argument("--set", choices=sorted(SETS), default="tuning")
    ap.add_argument("--resolve-before", action="store_true",
                    help="resolve each law against its R_before release point instead of the pinned index (tuning)")
    ap.add_argument("--rerun", type=int, default=0,
                    help="a repeat run N of the same code and data, with its own checkpoint, outputs (tagged _rerunN) "
                         "and freshly built release points, to check that a run reproduces (compare_runs.py)")
    ap.add_argument("--refresh-labels", action="store_true",
                    help="re-stamp the hashes of hand labels on this set after checking each difference by hand")
    args = ap.parse_args()
    cfg = config.load()
    f = Fetcher(cfg)
    t0 = time.monotonic()
    rows = classification_rows(f, cfg.olrc_base)
    resolver = Resolver(Index(cfg.index_path, cfg.release_pin), popular.load(), classification_map(rows))
    manifest, db, tag, heading = SETS["heldout" if args.heldout else args.set]
    if args.resolve_before:
        tag, heading = tag + "_resolve_before", heading + " (targets resolved against each law's R_before)"
    corpus = Corpus.load(manifest)
    if args.law:
        corpus.laws = [corpus.law(pl) for pl in args.law]
        tag += "_laws"
    if args.rerun:
        tag += f"_rerun{args.rerun}"
    if args.set.startswith("govinfo") and not args.heldout:
        # Sections outside the answer key are fetched from the same edition on demand (red team F6).
        open_index = lru_cache(maxsize=None)(lambda label: GovInfoOverlay(store.index(label, db), int(label[-4:]), f,
                                                                          resolver.positive))
    elif args.set.startswith("history_"):
        # Release points are materialized from the history on demand, a few at a time (oracle/history.py).
        # One cache directory per set: a set may need more titles at a release point than another set built there.
        open_index = ReleaseIndexes(History(cfg.var / "history" / "history.sqlite"),
                                    {rp.label: rp.titles for rp in corpus.release_points},
                                    db / (args.set + (f"_rerun{args.rerun}" if args.rerun else "")),
                                    log=lambda s: None)
    else:
        open_index = lru_cache(maxsize=None)(lambda label: store.index(label, db))
    statuses = collections.Counter()
    runs = {}

    missing_status: list[str] = []

    pop, cmap = resolver.popular, resolver.classification
    # History sets keep release points in ReleaseIndexes (db is its cache directory, not a file).
    before_index = open_index if args.set.startswith("history_") else (lambda label: store.index(label, db))
    def make_before_resolver(label):
        r = Resolver(before_index(label), pop, cmap)
        # Positive-law status comes from the pinned index: the release-point history marks no title positive law,
        # and no title's status changed within the sets' windows (title 54 did not exist before it was enacted).
        r.positive = set(resolver.positive)
        return r
    before_resolver = lru_cache(maxsize=2)(make_before_resolver)

    def predictor(law, before):
        print(f"{time.strftime('%H:%M:%S')} {law.pl} ({len(law.targets)} targets)", file=sys.stderr, flush=True)
        instructions = parse_text(render(f.get(law.enrolled_url).path)).instructions
        # --resolve-before: resolve against the Code as it stood before the law (red team F15), as a drafter would.
        res = before_resolver(law.rp_before) if args.resolve_before else resolver
        run = run_bill(instructions, res, before)
        runs[law.pl] = (run, instructions)
        return run.predictions

    # Off-target CLEAN predictions are graded only on sections no law in the window touched: elsewhere the next
    # edition carries the other laws' changes too.
    touched_path = manifest.with_name(manifest.stem + "_touched.json")
    touched = json.loads(touched_path.read_text()) if touched_path.exists() else {}
    # History sets scope the list per law, to the law's own window (laws span 2013-2026); GovInfo sets share one.
    by_law = touched.get("by_law") if isinstance(touched, dict) else None

    def is_touched(o) -> bool:
        return o.identifier in (by_law.get(o.pl, ()) if by_law is not None else touched)
    labels = json.loads(harness.LABELS.read_text()) if harness.LABELS.exists() else {}

    @lru_cache(maxsize=None)
    def enacted_date(pl_or_date: str | None) -> str | None:
        """A law's approval date from its USLM ("2020-03-27"); a date passes through; None when unknown."""
        if pl_or_date is None or re.fullmatch(r"\d{4}-\d{2}-\d{2}", pl_or_date):
            return pl_or_date
        path = gpo.uslm_path(f, cfg, pl_or_date)
        return gpo.approved_date(path) if path is not None else None

    def act_law(name: str) -> str | None:
        """The public law (or, for an older Act, the date) an Act's popular name points to, if exactly one."""
        ids = {i for e in pop.get(popular.norm_name(name), []) for i in e.get("identities", [])}
        if len(ids) != 1:
            return None
        i = next(iter(ids))
        return i[3:] if i.startswith("pl:") else i.split(":")[1] if i.startswith("act:") else None

    def after_law(law, outs, before, after) -> dict:
        """Everything the report needs from this law's run, taken while its release points are open; the run is
        then let go (a set of hundreds of laws does not fit in memory, and reopening release points is slow)."""
        run, instructions = runs.pop(law.pl)

        after_resolver = lru_cache(maxsize=1)(lambda: Resolver(after, pop, cmap))

        def resolve_at_after(cite: str) -> str | None:
            ctx = Ctx()
            head, quotes, _ = lift_quotes(cite)
            apply_head(head, ctx, quotes)
            # R_after first; it holds only the titles this set needs, so then the pinned index (a section renumbered
            # since then reads differently from R_after's text and is not accepted).
            for r in (after_resolver(), resolver):
                try:
                    res = r.resolve(ctx.target_out())
                    if res.node_id:
                        return r.ix._node(res.node_id).identifier
                except Exception:                    # an unresolvable citation is simply not accepted
                    continue
            return None

        def notes(ix, ident) -> list[str]:
            try:
                sid = ix.by_identifier(ident).id
            except LookupError_:
                return []
            return [t for (t,) in ix.db.execute("SELECT text FROM notes WHERE section_id=? ORDER BY id", (sid,))]

        def editorial_kind(ident) -> str | None:
            """Why the prediction differs from R_after only editorially (oracle/editorial.py), or None."""
            work = run.working.get(ident)
            try:
                after_xml = after.section_xml(after.by_identifier(ident))
            except LookupError_:
                after_xml = None
            if work is None or work.removed:
                return None
            title = re.match(r"^/us/usc/t(\w+)/", ident)
            ctx = editorial.Context(
                pl=law.pl, positive_law=(title.group(1) in resolver.positive) if title else None,   # as above
                heading_amended=any(tr.section == ident and tr.instruction.op == "AMEND_HEADING" for tr in run.traces),
                new_notes=[t for t in notes(after, ident) if t not in set(notes(before, ident))],
                resolve=resolve_at_after, title=title.group(1) if title else "",
                date_of=lambda act: enacted_date(law.pl if act is None else act_law(act)),
                inserted=[(tr.instruction.target.path, t) for tr in run.traces if tr.section == ident
                          for t in (tr.instruction.new_text, tr.instruction.replace) if t])
            return editorial.kind(work.el, after_xml, ctx)
        kinds = {o.identifier: editorial_kind(o.identifier) for o in outs
                 if o.outcome == "mismatch" or (o.outcome in ("extra", "unexpected_change") and o.status == "CLEAN"
                                                and o.after_differs is not False and not is_touched(o))}

        def editorial_at_after(ident) -> bool:
            return kinds.get(ident) is not None
        with_status = {tr.instruction.id for tr in run.traces if tr.result is not None and tr.result.status}
        if args.dump:
            with open(cfg.var / f"{tag}_dump.jsonl", "a") as fh:
                for o in outs:
                    if not (o.outcome == "mismatch" and o.status == "CLEAN") or editorial_at_after(o.identifier):
                        continue
                    work = run.working.get(o.identifier)

                    fh.write(json.dumps({
                        "pl": law.pl, "identifier": o.identifier, "rp_before": law.rp_before,
                        "rp_after": law.rp_after, "predicted": work.render() if work is not None else None,
                        "before": harness.section_text(before, o.identifier)[0],
                        "after": harness.section_text(after, o.identifier)[0],
                        "new_notes": [t for t in notes(after, o.identifier)
                                      if t not in set(notes(before, o.identifier))],
                        "instructions": [{"id": tr.instruction.id, "op": tr.instruction.op,
                                          "find": tr.instruction.find, "new": tr.instruction.new_text,
                                          "path": list(tr.resolution.path),
                                          "status": tr.result.status if tr.result else None,
                                          "detail": tr.result.detail if tr.result else None}
                                         for tr in run.traces if tr.section == o.identifier]},
                        ensure_ascii=False) + "\n")
        law_labels = {}
        for o in outs:
            key = f"{o.pl} {o.identifier}"
            if o.outcome == "mismatch" and key in labels:
                work = run.working.get(o.identifier)
                pred = work.render() if work is not None else None
                try:
                    after_text = harness.section_text(after, o.identifier)[0]
                except LookupError_:
                    after_text = None
                law_labels[key] = {"applies": harness.label_stage(labels[key], pred, after_text) is not None,
                                   "pred": harness.text_hash(pred), "after": harness.text_hash(after_text)}
        return {
            "editorial": {o.identifier: kinds[o.identifier] for o in outs if o.outcome == "mismatch"
                          and editorial_at_after(o.identifier)},
            "off_editorial": [o.identifier for o in outs if o.outcome in ("extra", "unexpected_change")
                              and o.status == "CLEAN" and o.after_differs is not False and not is_touched(o)
                              and editorial_at_after(o.identifier)],
            "missing_status": [f"{law.pl} {i.id}" for i in instructions if i.id not in with_status],
            "statuses": dict(collections.Counter(tr.result.status if tr.result else
                                                 f"unattributed:{tr.resolution.outcome}" for tr in run.traces)),
            "labels": law_labels,
            # Per section graded or predicted: hashes of the predicted, R_before and R_after texts, so two runs can be
            # compared section by section (scripts/compare_runs.py).
            "hashes": {o.identifier: [harness.text_hash(run.working[o.identifier].render())
                                      if o.identifier in run.working else None,
                                      harness.text_hash(harness.section_text(before, o.identifier)[0]),
                                      harness.text_hash(harness.section_text(after, o.identifier)[0])] for o in outs},
            "traces": [{"pl": law.pl, "section": tr.section, "id": tr.instruction.id, "op": tr.instruction.op,
                        "unit": tr.instruction.unit, "find": tr.instruction.find, "new": tr.instruction.new_text,
                        "replace": tr.instruction.replace, "flags": tr.instruction.flags,
                        "resolution": tr.resolution.outcome, "path": list(tr.resolution.path),
                        "status": tr.result.status if tr.result else None,
                        "detail": tr.result.detail if tr.result else None,
                        "before": tr.result.before_span if tr.result else None,
                        "after": tr.result.after_span if tr.result else None} for tr in run.traces],
        }

    # A run is checkpointed law by law and resumes after an interruption, as long as nothing it depends on changed.
    digest = hashlib.sha256()
    for path in sorted(SRC.rglob("*.py")) + [Path(__file__), manifest, touched_path, harness.LABELS]:
        if path.exists():
            digest.update(str(path.relative_to(ROOT)).encode() + b"\0" + path.read_bytes())
    digest.update(json.dumps([args.set, args.heldout, args.resolve_before, args.law, args.dump, args.rerun]).encode())
    # The data, too: the release points graded against, the pinned index the resolver reads, OLRC's classification
    # tables and each enrolled bill as fetched (the materialized release points derive from the history and the code).
    digest.update(json.dumps(data_fingerprint(cfg, args.set, db), sort_keys=True).encode())
    digest.update(repr(rows).encode())
    for law in corpus.laws:
        digest.update(law.pl.encode() + f.get(law.enrolled_url).path.read_bytes())
    extras: dict[str, dict] = {}
    rep = harness.evaluate(corpus, predictor, "ramseyer M6", open_index, labels=None, after_law=after_law,
                           checkpoint=cfg.var / f"{tag}_checkpoint.jsonl", key=digest.hexdigest(), extras=extras)
    for x in extras.values():
        statuses.update(x["statuses"])
        missing_status.extend(x["missing_status"])
    m = rep.metrics
    mism = [o for o in rep.outcomes if o.outcome == "mismatch"]
    # Editorial-only differences are counted separately; they remain mismatches in the match rate.
    n_editorial = 0
    detected_ids: set[tuple[str, str]] = set()
    editorial_kinds = collections.Counter()
    for o in mism:
        if o.identifier in extras[o.pl]["editorial"]:
            editorial_kinds[extras[o.pl]["editorial"][o.identifier]] += 1
            o.stage = "editorial"
            detected_ids.add((o.pl, o.identifier))
            n_editorial += 1
    ungradable = [o for o in rep.outcomes if o.outcome in ("extra", "unexpected_change") and o.status == "CLEAN"
                  and is_touched(o)]
    for o in ungradable:
        o.after_differs = None
        o.stage = "ungradable"
    m["clean_off_target"] -= len(ungradable)
    off = [o for o in rep.outcomes if o.outcome in ("extra", "unexpected_change") and o.status == "CLEAN"
           and o.after_differs is not False and o.stage != "ungradable"]
    off_sub = 0
    for o in off:
        if o.identifier not in extras[o.pl]["off_editorial"]:
            off_sub += 1
            o.stage = "unclassified"
        else:
            o.stage = "editorial"
    graded = m["matched"] + m["mismatched"]
    clean_mism = [o for o in mism if o.status == "CLEAN"]
    # Hand labels bind to the exact texts they were checked against; list the ones that no longer apply.
    label_rows = []
    for o in mism:
        key = f"{o.pl} {o.identifier}"
        if key not in labels:
            continue
        seen = extras[o.pl]["labels"][key]
        label_rows.append(f"- {key}: {'applies' if seen['applies'] else 'EXPIRED'}: {o.detail[:200]}")
        if args.refresh_labels and not seen["applies"]:
            lab = labels[key]
            reason = lab.get("reason", "") if isinstance(lab, dict) else ""
            labels[key] = {"stage": "editorial", "reason": reason, "pred": seen["pred"], "after": seen["after"]}
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
         f"{m['pending']}; also changed by other laws in the window (not graded) {m.get('ungradable', 0)}; not yet executed by OLRC in the section at R_after (not graded) {m.get('unexecuted', 0)}; extra {m['extra']}, unexpected change {m['unexpected_change']}; of the mismatches, "
         f"{n_editorial} differ only editorially or in whitespace (kinds below)"),
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
    # Names may carry line breaks ("William M. (Mac) Thornberry National \r\nDefense Authorization Act ...").
    ndaa = {l.pl for l in corpus.laws if "National Defense Authorization" in " ".join((l.name or "").split())}
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
              "", "Editorial or whitespace-only mismatches by kind (oracle/editorial.py): "
              + (", ".join(f"{k} {v}" for k, v in editorial_kinds.most_common()) or "none"),
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
        for law in corpus.laws:
            for t in extras[law.pl]["traces"]:
                fh.write(json.dumps(t, ensure_ascii=False) + "\n")
    if not args.law:
        MANIFEST.with_name(f"{tag}_baseline.json").write_text(json.dumps({"predictor": "ramseyer M6", "metrics": m}, indent=1) + "\n")
    print("\n".join(lines))
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
