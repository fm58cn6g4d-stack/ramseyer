"""M3 gate: the oracle corpus (20 enacted laws, before/after release points, enrolled-bill text) and a
comparison harness that is shown to measure correctly before any parser exists.

Run:  .venv/bin/python scripts/m3_gate.py      Writes var/m3_gate.md and tests/oracle/baseline.json.
"""
from __future__ import annotations

import json
import sys
import time
from functools import lru_cache

from lxml import etree

from billmap import config
from billmap.data.http import Fetcher
from billmap.oracle import harness, store
from billmap.oracle.corpus import MANIFEST, Corpus, sha256
from billmap.oracle.harness import Prediction

BASELINE = MANIFEST.with_name("baseline.json")


@lru_cache(maxsize=None)
def open_index(label: str):
    return store.index(label)


@lru_cache(maxsize=None)
def gt(pl: str):
    law = CORPUS.law(pl)
    return harness.truth(law, open_index(law.rp_before), open_index(law.rp_after))


def oracle_predictor(law, before):
    return [Prediction(identifier=i, status="CLEAN", text=t["after"]) for i, t in gt(law.pl).items()]


def identity_predictor(law, before):
    return [Prediction(identifier=i, status="CLEAN", text=t["before"]) for i, t in gt(law.pl).items()]


def mutated(law, before):
    """Oracle text, but every changed section with text gets one word altered: each must be caught."""
    out = []
    for i, t in gt(law.pl).items():
        text = t["after"]
        if t["changed"] and text and " " in text:
            head, _, tail = text.partition(" ")
            text = head + " XMUTATEDX " + tail
        out.append(Prediction(identifier=i, status="CLEAN", text=text))
    return out


def partial_with_extra(law, before):
    """Oracle for half the targets, nothing for the rest, plus one untouched section predicted unchanged."""
    items = list(gt(law.pl).items())
    out = [Prediction(identifier=i, status="WARN", text=t["after"]) for i, t in items[::2]]
    ix = open_index(law.rp_after)
    row = ix.db.execute("SELECT identifier, text_plain FROM nodes WHERE rp=? AND kind='section' AND title=? "
                        "ORDER BY id LIMIT 200", (ix.rp_id, law.titles[0])).fetchall()
    spare = next((r for r in row if r[0] not in gt(law.pl)), None)
    if spare:
        out.append(Prediction(identifier=spare[0], status="CLEAN", text=spare[1]))
    return out


def main() -> int:
    global CORPUS
    cfg = config.load()
    CORPUS = Corpus.load()
    f = Fetcher(cfg)
    checks = []
    t0 = time.monotonic()

    # 1. Corpus completeness: 20 laws, enrolled text present and unchanged, both release points loaded.
    problems = []
    for law in CORPUS.laws:
        r = f.get(law.enrolled_url)
        if r.status != 200 or sha256(r.path) != law.enrolled_sha256:
            problems.append(f"{law.pl}: enrolled text missing or hash changed")
        elif etree.parse(str(r.path)).getroot().tag != "bill":
            problems.append(f"{law.pl}: enrolled XML root is not <bill>")
        for label in (law.rp_before, law.rp_after):
            ix = open_index(label)
            have = {x[0] for x in ix.db.execute("SELECT title FROM titles WHERE rp=?", (ix.rp_id,))}
            if not set(law.titles) <= have:
                problems.append(f"{law.pl}: {label} lacks titles {sorted(set(law.titles) - have)}")
    rps = {lab for law in CORPUS.laws for lab in (law.rp_before, law.rp_after)}
    checks.append(("20 enacted laws with enrolled text and before/after release points",
                   len(CORPUS.laws) == 20 and not problems,
                   f"{len(CORPUS.laws)} laws, {len(rps)} release points, {sum(len(l.targets) for l in CORPUS.laws)} "
                   f"target rows; problems: {problems or 'none'}"))

    # 2. Ground truth: every law changes text somewhere; classified sections exist where expected.
    rows, weak, credit_hits, credit_total = [], [], 0, 0
    for law in CORPUS.laws:
        t = gt(law.pl)
        changed = sum(v["changed"] for v in t.values())
        absent_after = [i for i, v in t.items() if v["after_status"] == "absent"]
        ix = open_index(law.rp_after)
        for ident, v in t.items():
            if v["after_status"] in ("absent", "ambiguous"):
                continue
            node = ix.by_identifier(ident)
            credit_total += 1
            credit_hits += bool(ix.db.execute("SELECT 1 FROM source_credits WHERE section_id=? AND pl=?",
                                              (node.id, law.pl)).fetchone())
        rows.append(f"{law.pl}: {len(t)} sections, {changed} changed, {len(absent_after)} absent at {law.rp_after}")
        if changed == 0:
            weak.append(law.pl)
    checks.append(("Every corpus law changes classified section text between its release points", not weak,
                   f"{credit_hits}/{credit_total} targeted sections at R_after carry the law in their source credit; "
                   f"laws with no text change: {weak or 'none'}. " + "; ".join(rows)))

    # 3. Harness measures correctly on predictors with known answers.
    rep = {name: harness.evaluate(CORPUS, fn, name, open_index, labels={}) for name, fn in [
        ("oracle", oracle_predictor), ("identity", identity_predictor), ("mutated", mutated),
        ("partial", partial_with_extra)]}
    n_targets = rep["oracle"].metrics["targets"]
    n_changed = sum(v["changed"] for law in CORPUS.laws for v in gt(law.pl).values())
    n_mutated = sum(1 for law in CORPUS.laws for v in gt(law.pl).values()
                    if v["changed"] and v["after"] and " " in v["after"])
    n_half = sum((len(gt(law.pl)) + 1) // 2 for law in CORPUS.laws)
    expect = [
        ("oracle match_rate 1.0", rep["oracle"].metrics["match_rate"] == 1.0),
        ("oracle false_clean 0", rep["oracle"].metrics["false_clean"] == 0),
        ("identity mismatches = changed sections", rep["identity"].metrics["mismatched"] == n_changed),
        ("identity false_clean = changed sections", rep["identity"].metrics["false_clean"] == n_changed),
        ("every mutation caught", rep["mutated"].metrics["mismatched"] == n_mutated),
        ("partial: missed = unpredicted targets", rep["partial"].metrics["missed"] == n_targets - n_half),
        ("partial: WARN never counted clean", rep["partial"].metrics["false_clean"] == 0),
        ("partial: untouched section reported extra", rep["partial"].metrics["extra"] == len(CORPUS.laws)),
    ]
    failed = [e for e, ok in expect if not ok]
    checks.append(("Harness self-test on known predictors", not failed,
                   f"targets {n_targets}, changed {n_changed}; " + "; ".join(
                       f"{k}: match {r.metrics['match_rate']}, mismatched {r.metrics['mismatched']}, missed "
                       f"{r.metrics['missed']}, extra {r.metrics['extra']}, false_clean_rate {r.metrics['false_clean_rate']}"
                       for k, r in rep.items()) + f"; failed expectations: {failed or 'none'}"))

    # 4. Baseline for CI: the no-op (identity) predictor. Any real pipeline must beat it.
    regressions = harness.compare_with_baseline(rep["oracle"], json.loads(BASELINE.read_text())) \
        if BASELINE.exists() else []
    BASELINE.write_text(json.dumps({"predictor": "identity (no-op)", "release_points": sorted(rps),
                                    "metrics": rep["identity"].metrics}, indent=1) + "\n")
    checks.append(("Baseline stored for CI comparison", not regressions,
                   f"tests/oracle/baseline.json: identity match_rate {rep['identity'].metrics['match_rate']}"))

    lines = ["# M3 gate", "", f"Run {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}; "
             f"{time.monotonic() - t0:.0f}s.", "", "| Check | Result | Measured |", "| --- | --- | --- |"]
    lines += [f"| {n} | {'PASS' if ok else 'FAIL'} | {d.replace('|', '/')} |" for n, ok, d in checks]
    (cfg.var / "m3_gate.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
