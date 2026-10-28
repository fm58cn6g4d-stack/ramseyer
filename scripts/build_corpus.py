"""Build the M3 oracle corpus manifest (tests/oracle/corpus.json) and the oracle index (var/oracle/).

Selection is deterministic and recorded in the manifest. Run:  .venv/bin/python scripts/build_corpus.py
"""
from __future__ import annotations

import collections
import json
import re
import sys
import time
from urllib.parse import urljoin

from billmap import config
from billmap.data import congress, olrc
from billmap.data.http import Fetcher
from billmap.oracle import store
from billmap.oracle.corpus import ClassifiedRow, Corpus, CorpusLaw, ReleasePointRef, sha256, title_sort_key

SIZE = 20
SELECTION = (
    "Candidates: public laws of the 119th Congress whose OLRC classification rows include at least one "
    "non-note row, and for which OLRC publishes both the release point just before the law's classification "
    "and the one that first includes it (prior release points online on 2026-10-28 start at 119-73not60). "
    "Pick every candidate with at least 2 non-note rows, in public-law order; then fill to 20 with "
    "single-row candidates whose title is not yet covered, in public-law order. No candidate has another "
    "law in the same release-point window touching the same section. The plan asks for laws mostly in "
    "titles 49, 23 and 45; no available release point changes title 45, and title 49/23 text changes "
    "in this window come only from 119-60, so the corpus is spread across titles instead."
)


def num(label: str) -> int:
    return int(re.match(r"\d+-(\d+)", label).group(1))


def main() -> int:
    cfg = config.load()
    f = Fetcher(cfg)
    base = cfg.olrc_base
    prior = f.get(urljoin(base, "priorreleasepoints.html"), refresh=True).text()
    listed = re.findall(r'<a class="releasepoint" href="([^"]+)">([^<]+)</a>', prior)
    rps = {}
    for href, _ in listed:
        u = urljoin(base, href)
        rp = olrc.parse_release_point(f.get(u).text(), u)
        rps[rp.label] = (rp, u)
    plain = sorted((l for l in rps if "not" not in l), key=num)

    rows = []
    for t in ("tbl119pl_1st.html", "tbl119pl_2nd.html"):
        rows += olrc.parse_classification_table(f.get(urljoin(base, f"classification/{t}")).text())
    by_law = collections.defaultdict(list)
    for r in rows:
        by_law[r.public_law].append(ClassifiedRow(title=r.title, section=r.section, description=r.description,
                                                  law_section=r.law_section))

    def window(pl: str) -> tuple[str, str] | None:
        excepted = [l for l in rps if l.endswith(f"not{num(pl)}") and l.startswith("119-")]
        if excepted:          # e.g. 119-73not60 held 119-60 back; 119-73 is the first to include it
            after = excepted[0].split("not")[0]
            return excepted[0], after
        after = next((l for l in plain if num(l) >= num(pl)), None)
        if after is None or plain.index(after) == 0:
            return None
        return plain[plain.index(after) - 1], after

    cands = []
    for pl, rs in by_law.items():
        if not pl.startswith("119-"):
            continue
        w = window(pl)
        targets = [r for r in rs if not r.is_note]
        if not w or not targets or (num(pl) <= num(plain[0]) and "not" not in w[0]):
            continue
        cands.append((pl, w, targets))
    cands.sort(key=lambda c: num(c[0]))
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
    corpus = Corpus(built=time.strftime("%Y-%m-%d"), selection=SELECTION, release_points=refs, laws=laws)
    corpus.save()
    print(f"manifest: {len(laws)} laws, {len(refs)} release points")
    store.build(corpus)
    return 0


if __name__ == "__main__":
    sys.exit(main())
