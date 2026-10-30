"""M6e: spot-check the release-point history on 2022-2024 against GovInfo's annual U.S. Code editions.

The OLRC zips that history_check.py compares with cover only the 119th Congress (older zips are no longer served).
GovInfo's 2022, 2023 and 2024 editions are an independent source (OLRC's XHTML, converted by data/xhtml_uslm.py and
indexed for the M6b sets). For each section in those indexes, the edition's "current through" date for its title
picks a history release point: the first one that incorporates every law enacted on or before that date (enactment
dates from OLRC's classification tables; a currency date alone is not enough, since a release point current through
a date can hold a law back, as 117-362not263not328 does the FY2023 NDAA). The section's history text there
(carry-forward rule included) is compared with the edition's, and so are the two release points before and after,
so a wrongly chosen release point shows up as a better match next to it. The converter's own differences
(scripts/xhtml_check.py) set the floor.
Run:  .venv/bin/python scripts/history_govinfo_check.py      Writes var/history_govinfo_check.md.
"""
from __future__ import annotations

import collections
import sqlite3
import sys
from datetime import date

from lxml import etree

from ramseyer import config
from urllib.parse import urljoin

from ramseyer.data import govinfo, olrc, uslm
from ramseyer.data.http import Fetcher
from ramseyer.data.indexer import text_of
from ramseyer.oracle.harness import normalize
from ramseyer.oracle import releases as rl
from ramseyer.oracle.history import History

INDEXES = {2022: "govinfo_2023.sqlite", 2023: "govinfo.sqlite", 2024: "govinfo.sqlite"}


def edition_sections(db: sqlite3.Connection, year: int):
    rp = db.execute("SELECT id FROM release_points WHERE label=?", (f"usc-{year}",)).fetchone()[0]
    return db.execute("SELECT title, identifier, text_plain FROM nodes WHERE rp=? AND kind='section'", (rp,))


def main() -> int:
    cfg = config.load()
    f = Fetcher(cfg)
    h = History(cfg.var / "history" / "history.sqlite")
    rel = h.releases()
    parsed = [rl.parse(r.label) for r in rel]
    enacted: dict[str, date] = {}
    for c in (117, 118, 119):
        for half in ("1st", "2nd"):
            r = f.get(urljoin(cfg.olrc_base, f"classification/tbl{c}pl_{half}.html"))
            for x in olrc.parse_classification_table(r.text()) if r.status == 200 else []:
                if x.enacted:
                    enacted[x.public_law] = date.fromisoformat(x.enacted)

    def release_for(d: date) -> int | None:
        need = [rl.law_number(pl) for pl, e in enacted.items() if e <= d]
        return next((k for k, p in enumerate(parsed) if all(p.incorporates(*law) for law in need)), None)
    lines = ["# Release-point history vs GovInfo editions (M6e)", "",
             "| Edition | Sections | Matches at the chosen release point | Best match elsewhere (±2) | "
             "No match within ±2 |", "| --- | --- | --- | --- | --- |"]
    totals = collections.Counter()
    examples, lines_rp = [], []
    for year, name in INDEXES.items():
        db = sqlite3.connect(cfg.var / "oracle" / name)
        through: dict[str, date | None] = {}
        chosen: dict[date, int | None] = {}
        c = collections.Counter()
        for title, ident, text in edition_sections(db, year):
            if title not in through:
                gr = govinfo.uscode_granules(f, year, title)
                first = next(iter(gr.values()), None)
                ct = govinfo.current_through(govinfo.uscode_section_htm(f, year, title, first)) if first else None
                through[title] = date(int(ct[:4]), int(ct[4:6]), int(ct[6:8])) if ct else None
            d = through[title]
            if d is None:
                c["no currency date"] += 1
                continue
            if d not in chosen:
                chosen[d] = release_for(d)
            i = chosen[d]
            if i is None:
                c["no release point incorporates every law enacted by then"] += 1
                continue
            want = normalize(text)

            def at(k):
                if not 0 <= k < len(rel):
                    return None
                xs = h.section_xml(ident, rel[k].label)
                return normalize(text_of(uslm.to_v1(etree.fromstring(xs[0].encode())))) if xs else None
            c["sections"] += 1
            if at(i) == want:
                c["chosen"] += 1
            elif any(at(k) == want for k in (i - 2, i - 1, i + 1, i + 2)):
                c["neighbour"] += 1
                examples.append(f"{year} {ident}: matches a neighbour of {rel[i].label} (current through {d})")
            else:
                c["none"] += 1
        for d, i in chosen.items():
            lines_rp.append(f"{year}: current through {d} -> {rel[i].label if i is not None else 'none'}")
        totals.update(c)
        lines.append(f"| {year} | {c['sections']} | {c['chosen']} ({c['chosen'] / max(c['sections'], 1):.1%}) | "
                     f"{c['neighbour']} | {c['none']} |")
    lines += ["", f"Total: {totals['chosen']} of {totals['sections']} at the chosen release point; "
              f"{totals['neighbour']} better matched by a neighbour; {totals['none']} by none within ±2 "
              f"(converter or editorial differences; scripts/xhtml_check.py measures the converter).", ""]
    lines += ["Release points chosen:", *[f"- {x}" for x in lines_rp], ""]
    if examples:
        lines += ["## Better matched by a neighbouring release point", ""] + [f"- {e}" for e in examples[:40]]
    (cfg.var / "history_govinfo_check.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))
    # A wrong release-point choice shows as many neighbour matches; a stray one (a late execution) is listed.
    return 0 if totals["sections"] and totals["neighbour"] <= 0.01 * totals["sections"] else 1


if __name__ == "__main__":
    sys.exit(main())
