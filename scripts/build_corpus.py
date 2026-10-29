"""Build the M3 oracle corpus manifest (tests/oracle/corpus.json) and the oracle index (var/oracle/).

Selection is deterministic and recorded in the manifest. Run:  .venv/bin/python scripts/build_corpus.py
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
from ramseyer.oracle import store
from ramseyer.oracle.candidates import discover, num
from ramseyer.oracle.corpus import Corpus, CorpusLaw, ReleasePointRef, sha256, title_sort_key

SIZE = 20
SELECTION = (
    "Candidates: public laws of the 119th Congress whose OLRC classification rows include at least one "
    "non-note row, and for which OLRC publishes both the release point just before the law's classification "
    "and the one that first includes it (prior release points online on 2026-10-28 start at 119-73not60). "
    "Pick every candidate with at least 2 non-note rows, in public-law order; then fill to 20 with "
    "single-row candidates whose title is not yet covered, in public-law order. No candidate has another "
    "law in the same release-point window touching the same section. The plan asks for laws mostly in "
    "titles 49, 23 and 45; no available release point changes title 45, and title 49/23 text changes "
    "in this window come only from 119-60, so the corpus is spread across titles instead. "
    "A candidate must also be cited by the source credit of at least one targeted section at the pinned "
    "release point, which shows it changed section text: laws that only amend Act text kept in notes "
    "(e.g. 119-84 and 119-87, FISA sunset extensions) are listed under hard_cases instead."
)


def main() -> int:
    cfg = config.load()
    f = Fetcher(cfg)
    d = discover(f, cfg.olrc_base)
    rps, by_law, cands = d.rps, d.by_law, d.cands
    # Keep laws that changed section text: the pinned index's source credits cite them.
    from ramseyer.data.index import Index
    main_ix = Index(cfg.index_path, cfg.release_pin)
    hard_cases = []

    def credits_cite(pl: str, targets) -> bool:
        for r in targets:
            row = main_ix.db.execute("SELECT node_id FROM node_ident WHERE rp=? AND identifier=?",
                                     (main_ix.rp_id, r.identifier)).fetchone()
            if row and main_ix.db.execute("SELECT 1 FROM source_credits WHERE section_id=? AND pl=?",
                                          (row[0], pl)).fetchone():
                return True
        return False

    kept = []
    for c in cands:
        if credits_cite(c[0], c[2]):
            kept.append(c)
        else:
            hard_cases.append({"pl": c[0], "reason": "classified rows, but no targeted section's source credit "
                               f"cites it at {cfg.release_pin}: amends Act text held in notes"})
    cands = kept
    # Contamination: another candidate in the same window touching the same section.
    touch = collections.defaultdict(set)
    for pl, w, t in cands:
        for r in t:
            touch[(w, r.identifier)].add(pl)
    picked = [(c, "at least 2 non-note rows") for c in cands if len(c[2]) >= 2]
    covered = {r.title for c, _ in picked for r in c[2]}
    for c in cands:
        if len(picked) >= SIZE:
            break
        if len(c[2]) == 1 and c[2][0].title not in covered:
            picked.append((c, f"single row; adds title {c[2][0].title}"))
            covered.add(c[2][0].title)
    picked = sorted(picked[:SIZE], key=lambda x: num(x[0][0]))

    laws, need = [], collections.defaultdict(set)
    for (pl, (before, after), targets), reason in picked:
        contaminated = [r.identifier for r in targets if len(touch[((before, after), r.identifier)]) > 1]
        if contaminated:
            print(f"{pl}: contaminated sections {contaminated}", file=sys.stderr)
            return 1
        meta = json.loads(f.get(f"{cfg.congress_api}law/119/pub/{num(pl)}?format=json&api_key={cfg.api_key}").text())
        bill = meta["bill"]
        versions = congress.text_versions(f, int(bill["congress"]), bill["type"].lower(), int(bill["number"]))
        enr = [v for v in versions if (v.get("type") or "").lower().startswith("enrolled")]
        urls = congress.xml_urls(enr)
        if not urls:
            print(f"{pl}: no enrolled Formatted XML among {[v.get('type') for v in versions]}", file=sys.stderr)
            return 1
        resp = f.get(urls[0])
        titles = sorted({r.title.lower() for r in targets}, key=title_sort_key)
        laws.append(CorpusLaw(pl=pl, name=bill.get("title") or "", bill=f"{bill['congress']} {bill['type'].lower()} "
                              f"{bill['number']}", enrolled_url=urls[0], enrolled_sha256=sha256(resp.path),
                              rp_before=before, rp_after=after, titles=titles, rows=by_law[pl], reason=reason))
        need[before] |= set(titles)
        need[after] |= set(titles)
        print(f"{pl:8} {before:>12} -> {after:<8} {len(targets):5} target rows  titles {','.join(titles):40} "
              f"{bill['type']} {bill['number']}  {(bill.get('title') or '')[:60]}")

    refs = []
    for label in sorted(need, key=lambda l: (num(l), l)):
        rp, page = rps[label]
        titles = sorted(need[label], key=title_sort_key)
        key = {t: (f"{int(re.sub(r'[a-z]', '', t)):02d}" + ("a" if t.endswith("a") else "")) for t in titles}
        refs.append(ReleasePointRef(label=label, date=rp.date, page_url=page, titles=titles,
                                    zip_urls=[rp.xml_titles[key[t]] for t in titles]))
    corpus = Corpus(built=time.strftime("%Y-%m-%d"), selection=SELECTION, release_points=refs, laws=laws,
                    hard_cases=hard_cases)
    corpus.save()
    print(f"manifest: {len(laws)} laws, {len(refs)} release points")
    store.build(corpus)
    return 0


if __name__ == "__main__":
    sys.exit(main())
