"""Build a GovInfo held-out set: the laws enacted between two of GovInfo's annual U.S. Code editions, checked
against them (default: laws of 2024 on the 2023 and 2024 editions).

The editions are OLRC's XHTML (one granule per section), converted to USLM by src/ramseyer/data/xhtml_uslm.py
(measured by scripts/xhtml_check.py) and loaded with the standard indexer as release points "usc-<year>" in
var/oracle/govinfo[_<year>].sqlite. A law is in the window when it was enacted after the first edition's
"current through" date and on or before the second's, per title. A target row is usable when no other law in the
window touches the same section. Writes tests/oracle/heldout_govinfo[_<year>].json and the touched-sections list.
Run:  .venv/bin/python scripts/build_govinfo_heldout.py [--editions 2022 2023] [--titles 49] [--limit-laws N]
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import time
import zipfile
from datetime import date
from urllib.parse import urljoin

from ramseyer import config
from ramseyer.data import congress, govinfo, olrc
from ramseyer.data.cite import normalize_section
from ramseyer.data.http import Fetcher
from ramseyer.data.index import Index
from ramseyer.data.indexer import Indexer
from ramseyer.data.xhtml_uslm import chunks, title_document
from ramseyer.oracle.corpus import ClassifiedRow, Corpus, CorpusLaw, ReleasePointRef, sha256, title_sort_key

TABLES = {2021: "tbl117pl_1st.html", 2022: "tbl117pl_2nd.html", 2023: "tbl118pl_1st.html",
          2024: "tbl118pl_2nd.html", 2025: "tbl119pl_1st.html"}


def paths(editions: tuple[int, int]):
    """Manifest, touched-sections list and index for a pair of editions; (2023, 2024) keeps the original names."""
    suffix = "" if editions == (2023, 2024) else f"_{editions[1]}"
    manifest = config.ROOT / "tests" / "oracle" / f"heldout_govinfo{suffix}.json"
    return (manifest, manifest.with_name(f"heldout_govinfo{suffix}_touched.json"),
            config.VAR / "oracle" / f"govinfo{suffix}.sqlite")
SELECTION = (
    "Held out (GovInfo): public laws enacted after the {a} U.S. Code edition's 'current through' date and on or "
    "before the {b} edition's (per title, read from the editions), with the sections each changes alone in that "
    "window (classification rows, notes excluded). Text is GovInfo's per-section XHTML, converted to USLM (98.2% "
    "exact on the 119-134 release, scripts/xhtml_check.py)."
)


def ymd(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8])) if "-" not in s else date.fromisoformat(s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--titles", nargs="*", help="limit to these Code titles")
    ap.add_argument("--limit-laws", type=int, default=0)
    ap.add_argument("--touched-only", action="store_true", help="write the touched-sections list and stop")
    ap.add_argument("--editions", nargs=2, type=int, default=[2023, 2024], help="the before and after editions")
    args = ap.parse_args()
    EDITIONS = tuple(args.editions)
    LABEL = {y: f"usc-{y}" for y in EDITIONS}
    MANIFEST, TOUCHED, DB = paths(EDITIONS)
    cfg = config.load()
    f = Fetcher(cfg)
    pinned = Index(cfg.index_path, cfg.release_pin)
    positive = {r[0] for r in pinned.db.execute("SELECT title FROM titles WHERE rp=? AND positive_law=1",
                                                (pinned.rp_id,))}

    rows = []
    for t in sorted({TABLES[y] for y in (EDITIONS[0], EDITIONS[1], EDITIONS[1] + 1) if y in TABLES}):
        rows += olrc.parse_classification_table(f.get(urljoin(cfg.olrc_base, f"classification/{t}")).text())
    titles = sorted({r.title for r in rows if not r.title.startswith("A") and re.fullmatch(r"\d+a?", r.title)
                     and (not args.titles or r.title in args.titles)}, key=title_sort_key)

    # Each edition's granules and its "current through" date, per title.
    granules: dict[tuple[int, str], dict[str, str]] = {}
    through: dict[tuple[int, str], date] = {}
    for t in titles:
        for y in EDITIONS:
            try:
                granules[(y, t)] = govinfo.uscode_granules(f, y, t)
            except RuntimeError as e:
                print(f"title {t} {y}: {e}", file=sys.stderr)
                continue
            first = next(iter(granules[(y, t)].values()), None)
            ct = govinfo.current_through(govinfo.uscode_section_htm(f, y, t, first)) if first else None
            if ct:
                through[(y, t)] = ymd(ct)
    print("current through:", {f"{t}": (str(through.get((EDITIONS[0], t))), str(through.get((EDITIONS[1], t))))
                               for t in titles if (EDITIONS[0], t) in through}, file=sys.stderr)

    def in_window(r) -> bool:
        lo, hi = through.get((EDITIONS[0], r.title)), through.get((EDITIONS[1], r.title))
        return bool(lo and hi and r.enacted and lo < date.fromisoformat(r.enacted) <= hi)

    win = [r for r in rows if r.title in titles and in_window(r)]
    touch = collections.defaultdict(set)
    for r in win:
        if "nt" not in r.description.split():
            touch[(r.title, normalize_section(r.section))].add(r.public_law)
    # Every section any law in the window changed: an off-target prediction on one of these cannot be graded against
    # the next edition, which carries the other laws' changes too (scripts/m6_gate.py, red team F6).
    TOUCHED.write_text(json.dumps({f"/us/usc/t{t.lower()}/s{sec}": sorted(pls) for (t, sec), pls in
                                   sorted(touch.items())}, indent=0, ensure_ascii=False) + "\n")
    if args.touched_only:
        return 0
    by_law = collections.defaultdict(list)
    for r in win:
        by_law[r.public_law].append(r)
    hard, laws, need = [], [], collections.defaultdict(set)
    pls = sorted(by_law, key=lambda p: tuple(int(x) for x in p.split("-")))
    for pl in pls:
        usable = [r for r in by_law[pl] if "nt" not in r.description.split()
                  and touch[(r.title, normalize_section(r.section))] == {pl}]
        dropped = [r for r in by_law[pl] if "nt" not in r.description.split() and r not in usable]
        if not usable:
            if dropped:
                hard.append({"pl": pl, "reason": f"all {len(dropped)} target sections also changed by another law "
                                                  "in the window"})
            continue
        meta = json.loads(f.get(f"{cfg.congress_api}law/{pl.split('-')[0]}/pub/{pl.split('-')[1]}?format=json&api_key="
                                f"{cfg.api_key}").text())
        bill = meta["bill"]
        versions = congress.text_versions(f, int(bill["congress"]), bill["type"].lower(), int(bill["number"]))
        urls = congress.xml_urls([v for v in versions if (v.get("type") or "").lower().startswith("enrolled")])
        if not urls:
            hard.append({"pl": pl, "reason": "no enrolled Formatted XML on Congress.gov"})
            continue
        resp = f.get(urls[0])
        crow = [ClassifiedRow(title=r.title, section=r.section, description=r.description, law_section=r.law_section)
                for r in usable + [r for r in by_law[pl] if "nt" in r.description.split()]]
        law_titles = sorted({r.title for r in usable}, key=title_sort_key)
        laws.append(CorpusLaw(pl=pl, name=bill.get("title") or "", bill=f"{bill['congress']} {bill['type'].lower()} "
                              f"{bill['number']}", enrolled_url=urls[0], enrolled_sha256=sha256(resp.path),
                              rp_before=LABEL[EDITIONS[0]], rp_after=LABEL[EDITIONS[1]], titles=law_titles, rows=crow,
                              reason=f"{len(usable)} section(s) changed by this law alone in the window"
                                     + (f"; {len(dropped)} shared with another law dropped" if dropped else "")))
        for r in usable:
            need[r.title].add(normalize_section(r.section))
        if args.limit_laws and len(laws) >= args.limit_laws:
            break

    # Download the needed sections from both editions; convert; load as two release points.
    ix = Indexer(DB)
    refs = []
    for y in EDITIONS:
        zips = []
        for t in sorted(need, key=title_sort_key):
            gmap = granules.get((y, t), {})
            pages = []
            for s in sorted(need[t]):
                gid = gmap.get(s) or gmap.get(s.replace("–", "-"))
                if gid:
                    pages.append(govinfo.uscode_section_htm(f, y, t, gid))
            cs = [c for p in pages for c in chunks(p)]
            doc = title_document(cs, t, f"GovInfo U.S. Code {y} edition", t in positive)
            m = re.fullmatch(r"(\d+)(a?)", t)
            member = f"usc{int(m.group(1)):02d}{'A' if m.group(2) else ''}.xml"
            out = config.VAR / "oracle" / "govinfo" / f"{y}" / member.replace(".xml", ".zip")
            out.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(member, doc)
            zips.append(out)
            print(f"{y} title {t}: {len(pages)} of {len(need[t])} sections", file=sys.stderr)
        row = ix.db.execute("SELECT id FROM release_points WHERE label=?", (LABEL[y],)).fetchone()
        if row:
            ix.drop_release_point(row[0])
        rp = ix.load_release_point(zips, LABEL[y], f"{y} edition", f"{cfg.govinfo_api}packages/USCODE-{y}-title*",
                                   log=lambda s: None)
        ix.mark_complete(rp)
        refs.append(ReleasePointRef(label=LABEL[y], date=f"{y} edition", page_url=f"https://www.govinfo.gov/app/collection/uscode/{y}",
                                    titles=sorted(need, key=title_sort_key),
                                    zip_urls=[f"{cfg.govinfo_api}packages/USCODE-{y}-title{t}" for t in sorted(need, key=title_sort_key)]))
    corpus = Corpus(built=time.strftime("%Y-%m-%d"), selection=SELECTION.format(a=EDITIONS[0], b=EDITIONS[1]),
                    release_points=refs, laws=laws, hard_cases=hard)
    corpus.save(MANIFEST)
    print(f"GovInfo held-out: {len(laws)} laws, {sum(len(l.targets) for l in laws)} target rows, "
          f"{sum(len(v) for v in need.values())} sections; {len(hard)} laws set aside")
    return 0


if __name__ == "__main__":
    sys.exit(main())
