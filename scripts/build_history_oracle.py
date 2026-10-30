"""M6e: build the oracle on the release-point history: every classified law from 113-21 on, split into dev, test and
sealed sets (tests/oracle/history_{dev,test,sealed}.json and *_touched.json).

For each law of the 113th-119th Congresses with at least one non-note row in OLRC's classification tables:
  - window: the first release point incorporating it and the one before (oracle/releases.py, M6d), from the history's
    381 release points;
  - targets: its non-note rows; a target another law in the same window also changes is not graded (it goes to the
    set's touched list, per law: {"by_law": {law: [sections]}}, scoped to that law's window), since R_after carries
    both changes;
  - enrolled text: the enrolled bill's Formatted XML from Congress.gov.
Laws already in another set (the tuning corpus, the M6b held-out sets, the GovInfo sets) are left out. Each remaining
law goes to one set by a seeded hash, balanced within strata: each Congress, and the National Defense Authorization
Acts of all Congresses as one stratum (they dominate the errors so far). Titles and committees overlap (a law has several),
so they are balanced by seeded rerandomization instead: of 1,000 seeded stratified draws, the one with the least title
and committee imbalance is kept (one plain draw left Titles 30, 43 and 51 mostly in dev, p = 0.02 against chance).
Run:  .venv/bin/python scripts/build_history_oracle.py [--seed N] [--limit N]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
import time
from urllib.parse import urljoin

from ramseyer import config
from ramseyer.data import congress, olrc
from ramseyer.data.http import Fetcher
from ramseyer.oracle import releases
from ramseyer.oracle.corpus import (MANIFEST, ClassifiedRow, Corpus, CorpusLaw, ReleasePointRef, sha256,
                                    title_sort_key)
from ramseyer.oracle.history import History

SETS = ("dev", "test", "sealed")
OTHER_SETS = ["corpus.json", "heldout.json", "heldout_govinfo.json", "heldout_govinfo_2023.json"]
NDAA = re.compile(r"National\s+Defense\s+Authorization\s+Act", re.I)    # titles can break across lines
SELECTION = (
    "Every public law of the 113th-119th Congresses with at least one non-note row in OLRC's classification tables "
    "and a release-point window in the dreamproit/uscode history (113-21 on; window by the incorporated-set rule), not "
    "already in another oracle set; assigned to dev, test or sealed by a seeded hash, balanced within strata of "
    "Congress, with the National Defense Authorization Acts of all Congresses as one stratum, and the best balanced by "
    "title and committee of --draws seeded draws kept. Targets another law in the same window also changes are "
    "not graded (listed in the set's touched file).")


def classification(f: Fetcher, base: str) -> dict[str, list[ClassifiedRow]]:
    by_law = collections.defaultdict(list)
    for c in range(113, 120):
        for half in ("1st", "2nd"):
            r = f.get(urljoin(base, f"classification/tbl{c}pl_{half}.html"))
            if r.status != 200:
                continue
            for x in olrc.parse_classification_table(r.text()):
                by_law[x.public_law].append(ClassifiedRow(title=x.title, section=x.section,
                                                          description=x.description, law_section=x.law_section))
    return by_law


def imbalance(assign: dict[str, str], groups: dict[str, list[tuple[str, str]]], minimum: int = 10) -> float:
    """Chi-square of the set counts against an even split, summed over every title and committee with at least
    `minimum` laws (a law counts once per title it changes and once per committee)."""
    counts = collections.defaultdict(collections.Counter)
    for pl, s in assign.items():
        for g in set(groups.get(pl, ())):
            counts[g][s] += 1
    total = 0.0
    for c in counts.values():
        n = sum(c.values())
        if n >= minimum:
            total += sum((c[s] - n / len(SETS)) ** 2 / (n / len(SETS)) for s in SETS)
    return total


def rerandomize(strata: dict, groups: dict[str, list[tuple[str, str]]], seed: str, draws: int):
    """Seeded rerandomization: each draw orders every stratum by a hash of (seed, draw, law) and deals its laws to the
    sets in turn, so each Congress (and the NDAA stratum) stays split evenly; the draw with the least title and
    committee imbalance is kept. Deterministic for a seed; fixed before any set is measured."""
    best = None
    for d in range(draws):
        assign = {}
        for key in sorted(strata):
            ordered = sorted(strata[key], key=lambda pl: hashlib.sha256(f"{seed} {d} {pl}".encode()).hexdigest())
            for k, pl in enumerate(ordered):
                assign[pl] = SETS[k % len(SETS)]
        score = imbalance(assign, groups)
        if best is None or score < best[1]:
            best = (assign, score)
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default="m6e-2026-10-30")
    ap.add_argument("--draws", type=int, default=1000, help="seeded assignments to draw; the best balanced is kept")
    ap.add_argument("--limit", type=int, default=0, help="build only the first N candidate laws (a trial run)")
    a = ap.parse_args()
    cfg = config.load()
    f = Fetcher(cfg)
    t0 = time.monotonic()
    labels = [r.label for r in History(cfg.var / "history" / "history.sqlite").releases()]
    by_law = classification(f, cfg.olrc_base)
    used = set()
    for name in OTHER_SETS:
        p = MANIFEST.with_name(name)
        if p.exists():
            used |= {law["pl"] for law in json.loads(p.read_text())["laws"]}
    windows = {pl: releases.window(labels, pl) for pl in by_law}
    entering = collections.defaultdict(list)            # window -> laws whose window it is
    for pl, w in windows.items():
        if w:
            entering[w].append(pl)
    cands, hard = [], []
    for pl in sorted(by_law, key=releases.law_number):
        targets = [r for r in by_law[pl] if not r.is_note]
        w = windows[pl]
        if not targets:
            continue
        if not w:
            hard.append({"pl": pl, "reason": "no release-point window in the history"})
            continue
        if pl in used:
            continue
        cands.append(pl)
    if a.limit:
        cands = cands[:a.limit]

    laws, touched = {s: [] for s in SETS}, {s: {} for s in SETS}
    strata = collections.defaultdict(list)
    meta = {}
    for i, pl in enumerate(cands):
        c, n = releases.law_number(pl)
        law_meta = json.loads(f.get(f"{cfg.congress_api}law/{c}/pub/{n}?format=json&api_key={cfg.api_key}").text())
        bill = law_meta.get("bill") or {}
        if not bill:
            hard.append({"pl": pl, "reason": "Congress.gov has no bill for the law"})
            continue
        versions = congress.text_versions(f, int(bill["congress"]), bill["type"].lower(), int(bill["number"]))
        urls = congress.xml_urls([v for v in versions if (v.get("type") or "").lower().startswith("enrolled")])
        if not urls:
            hard.append({"pl": pl, "reason": f"no enrolled Formatted XML ({[v.get('type') for v in versions]})"})
            continue
        resp = f.get(urls[0])
        if resp.status != 200:
            hard.append({"pl": pl, "reason": f"enrolled XML HTTP {resp.status}"})
            continue
        cm = json.loads(f.get(f"{cfg.congress_api}bill/{bill['congress']}/{bill['type'].lower()}/{bill['number']}"
                              f"/committees?format=json&api_key={cfg.api_key}").text())
        committees = sorted({x.get("name", "") for x in cm.get("committees", [])})
        name = bill.get("title") or ""
        meta[pl] = (bill, urls[0], sha256(resp.path), committees, name)
        # NDAAs form one stratum across Congresses (one or two a Congress would all start at "dev").
        strata[("NDAA", 0) if NDAA.search(name) else ("Congress", c)].append(pl)
        if i % 50 == 0:
            print(f"{i}/{len(cands)} laws read ({time.monotonic() - t0:.0f}s)", flush=True)

    groups = {pl: [("title", r.title.lower()) for r in by_law[pl] if not r.is_note] + [("committee", x) for x in m[3]]
              for pl, m in meta.items()}
    assign, score = rerandomize(strata, groups, a.seed, a.draws)
    print(f"assignment: best of {a.draws} seeded draws, imbalance {score:.1f}")

    for pl, s in sorted(assign.items(), key=lambda x: releases.law_number(x[0])):
        bill, url, digest, committees, name = meta[pl]
        before, after = windows[pl]
        others = [o for o in entering[(before, after)] if o != pl]
        shared = {r.identifier for o in others for r in by_law[o] if not r.is_note}
        rows = [r for r in by_law[pl] if r.is_note or r.identifier not in shared]
        clash = sorted({r.identifier for r in by_law[pl] if not r.is_note and r.identifier in shared})
        touched[s][pl] = sorted(shared)            # scoped to this law's window (the gate reads it per law)
        if not any(not r.is_note for r in rows):
            hard.append({"pl": pl, "set": s, "reason": "every target is also changed by another law in the window "
                         f"{before} -> {after}"})
            continue
        titles = sorted({r.title.lower() for r in rows if not r.is_note}, key=title_sort_key)
        laws[s].append((CorpusLaw(
            pl=pl, name=name, bill=f"{bill['congress']} {bill['type'].lower()} {bill['number']}", enrolled_url=url,
            enrolled_sha256=digest, rp_before=before, rp_after=after, titles=titles, rows=rows,
            reason=f"set {s}; committees: {'; '.join(committees) or 'none listed'}"
                   + (f"; not graded (also changed in the window): {', '.join(clash)}" if clash else "")),
            committees))

    built = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for s in SETS:
        need = collections.defaultdict(set)
        for law, _ in laws[s]:
            need[law.rp_before] |= set(law.titles)
            need[law.rp_after] |= set(law.titles)
        refs = [ReleasePointRef(label=l, date=None, page_url="dreamproit/uscode history", zip_urls=[],
                                titles=sorted(t, key=title_sort_key)) for l, t in
                sorted(need.items(), key=lambda x: labels.index(x[0]))]
        corpus = Corpus(built=built, selection=SELECTION + f" Seed {a.seed!r}; set {s}.", release_points=refs,
                        laws=[law for law, _ in laws[s]], hard_cases=[h for h in hard if h.get("set") in (s, None)])
        path = MANIFEST.with_name(f"history_{s}.json")
        corpus.save(path)
        path.with_name(path.stem + "_touched.json").write_text(
            json.dumps({"by_law": {pl: t for pl, t in touched[s].items() if t}}, indent=0) + "\n")
        n_t = sum(len(law.targets) for law, _ in laws[s])
        print(f"{s}: {len(laws[s])} laws, {n_t} graded targets, {len(refs)} release points, "
              f"{sum(len(t) for t in touched[s].values())} law/section pairs not gradable -> {path.name}")
    print(f"set aside: {len(hard)}; done in {time.monotonic() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
