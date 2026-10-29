"""Laws OLRC has classified for which both the release point before and the one first including them are online.

Shared by the tuning corpus (scripts/build_corpus.py) and the held-out set (scripts/build_heldout.py).
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass
from urllib.parse import urljoin

from ramseyer.data import olrc
from ramseyer.data.http import Fetcher
from ramseyer.oracle.corpus import ClassifiedRow


def num(label: str) -> int:
    return int(re.match(r"\d+-(\d+)", label).group(1))


@dataclass
class Discovery:
    rps: dict                       # label -> (ReleasePoint, page url)
    plain: list[str]                # release points without a "not" exception, in law order
    by_law: dict                    # public law -> [ClassifiedRow]
    cands: list[tuple]              # (pl, (before, after), non-note rows), in law order

    def window(self, pl: str) -> tuple[str, str] | None:
        excepted = [l for l in self.rps if l.endswith(f"not{num(pl)}") and l.startswith("119-")]
        if excepted:          # e.g. 119-73not60 held 119-60 back; 119-73 is the first to include it
            return excepted[0], excepted[0].split("not")[0]
        after = next((l for l in self.plain if num(l) >= num(pl)), None)
        if after is None or self.plain.index(after) == 0:
            return None
        return self.plain[self.plain.index(after) - 1], after


def discover(f: Fetcher, base: str, include_current: bool = False) -> Discovery:
    prior = f.get(urljoin(base, "priorreleasepoints.html"), refresh=True).text()
    pages = [urljoin(base, href) for href, _ in re.findall(r'<a class="releasepoint" href="([^"]+)">([^<]+)</a>', prior)]
    if include_current:
        pages.append(urljoin(base, "download.html"))
    rps = {}
    for u in pages:
        rp = olrc.parse_release_point(f.get(u, refresh=u.endswith("download.html")).text(), u)
        rps[rp.label] = (rp, u)
    plain = sorted((l for l in rps if "not" not in l), key=num)
    rows = []
    for t in ("tbl119pl_1st.html", "tbl119pl_2nd.html"):
        rows += olrc.parse_classification_table(f.get(urljoin(base, f"classification/{t}")).text())
    by_law = collections.defaultdict(list)
    for r in rows:
        by_law[r.public_law].append(ClassifiedRow(title=r.title, section=r.section, description=r.description,
                                                  law_section=r.law_section))
    d = Discovery(rps, plain, by_law, [])
    for pl, rs in by_law.items():
        if not pl.startswith("119-"):
            continue
        w = d.window(pl)
        targets = [r for r in rs if not r.is_note]
        if not w or not targets or (num(pl) <= num(plain[0]) and "not" not in w[0]):
            continue
        d.cands.append((pl, w, targets))
    d.cands.sort(key=lambda c: num(c[0]))
    return d
