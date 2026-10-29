"""Build the M6b held-out manifest (tests/oracle/heldout.json) and its oracle index (var/oracle/heldout.sqlite).

Held out = every law the tuning corpus (tests/oracle/corpus.json) did not use and the engine was never run on
while it was being tuned, chosen by the same availability rules. The set grows as OLRC publishes new release
points: rerun this script, then scripts/m6b_gate.py. Run:  .venv/bin/python scripts/build_heldout.py
"""
from __future__ import annotations

import collections
import json
import re
import sys
import time

from ramseyer import config
from ramseyer.data import congress
from ramseyer.data.http import Fetcher
from ramseyer.data.index import Index
from ramseyer.oracle import store
from ramseyer.oracle.candidates import discover, num
from ramseyer.oracle.corpus import Corpus, CorpusLaw, ReleasePointRef, sha256, title_sort_key

HELDOUT = config.ROOT / "tests" / "oracle" / "heldout.json"
HELDOUT_DB = config.VAR / "oracle" / "heldout.sqlite"
SELECTION = (
    "Held out: every public law of the 119th Congress that meets the tuning corpus's availability rules "
    "(classified, at least one non-note row, both bounding release points online, the current release point "
    "included) and is not in tests/oracle/corpus.json. A law is set aside (hard_cases) when the source credits "
    "at its R_after release point cite it for none of its targeted sections (it amends Act text kept in notes), "
    "or when another law in the same release-point window touches one of its sections. Not tuned on: the "
    "engine was developed against the tuning corpus only."
)


def main() -> int:
    cfg = config.load()
    f = Fetcher(cfg)
    d = discover(f, cfg.olrc_base, include_current=True)
    tuning = Corpus.load()
    used = {law.pl for law in tuning.laws}
    touch = collections.defaultdict(set)
    for pl, w, t in d.cands:
        for r in t:
            touch[(w, r.identifier)].add(pl)
    picked, hard = [], []
    for pl, w, targets in d.cands:
        if pl in used:
            continue
        clash = sorted({r.identifier for r in targets if len(touch[(w, r.identifier)]) > 1})
        if clash:
            hard.append({"pl": pl, "reason": f"another law in window {w[0]} -> {w[1]} touches {', '.join(clash)}"})
            continue
        picked.append((pl, w, targets))

    laws, need = [], collections.defaultdict(set)
    for pl, (before, after), targets in picked:
        meta = json.loads(f.get(f"{cfg.congress_api}law/119/pub/{num(pl)}?format=json&api_key={cfg.api_key}").text())
        bill = meta["bill"]
        versions = congress.text_versions(f, int(bill["congress"]), bill["type"].lower(), int(bill["number"]))
        enr = [v for v in versions if (v.get("type") or "").lower().startswith("enrolled")]
        urls = congress.xml_urls(enr)
        if not urls:
            hard.append({"pl": pl, "reason": "no enrolled Formatted XML on Congress.gov"})
            continue
        resp = f.get(urls[0])
        titles = sorted({r.title.lower() for r in targets}, key=title_sort_key)
        laws.append(CorpusLaw(pl=pl, name=bill.get("title") or "", bill=f"{bill['congress']} {bill['type'].lower()} "
                              f"{bill['number']}", enrolled_url=urls[0], enrolled_sha256=sha256(resp.path),
                              rp_before=before, rp_after=after, titles=titles, rows=d.by_law[pl],
                              reason="not in the tuning corpus"))
        need[before] |= set(titles)
        need[after] |= set(titles)

    refs = []
    for label in sorted(need, key=lambda l: (num(l), l)):
        rp, page = d.rps[label]
        titles = sorted(need[label], key=title_sort_key)
        key = {t: (f"{int(re.sub(r'[a-z]', '', t)):02d}" + ("a" if t.endswith("a") else "")) for t in titles}
        refs.append(ReleasePointRef(label=label, date=rp.date, page_url=page, titles=titles,
                                    zip_urls=[rp.xml_titles[key[t]] for t in titles]))
    corpus = Corpus(built=time.strftime("%Y-%m-%d"), selection=SELECTION, release_points=refs, laws=laws,
                    hard_cases=hard)
    store.build(corpus, db_path=HELDOUT_DB)

    # Set aside laws that changed no section text: no targeted section's credits cite them at R_after.
    kept = []
    for law in corpus.laws:
        ix = Index(HELDOUT_DB, law.rp_after)
        cited = False
        for r in law.targets:
            row = ix.db.execute("SELECT node_id FROM node_ident WHERE rp=? AND identifier=?",
                                (ix.rp_id, r.identifier)).fetchone()
            if row and ix.db.execute("SELECT 1 FROM source_credits WHERE section_id=? AND pl=?",
                                     (row[0], law.pl)).fetchone():
                cited = True
                break
        if cited:
            kept.append(law)
        else:
            corpus.hard_cases.append({"pl": law.pl, "reason": "no targeted section's source credit cites it at "
                                      f"{law.rp_after}: amends Act text held in notes"})
    corpus.laws = kept
    corpus.save(HELDOUT)
    for law in kept:
        print(f"{law.pl:8} {law.rp_before:>12} -> {law.rp_after:<8} {len(law.targets):4} rows  titles "
              f"{','.join(law.titles):12} {law.bill:14} {law.name[:60]}")
    for h in corpus.hard_cases:
        print(f"set aside {h['pl']}: {h['reason']}")
    print(f"held-out manifest: {len(kept)} laws, {sum(len(l.targets) for l in kept)} target rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
