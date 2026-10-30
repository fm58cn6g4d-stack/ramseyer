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
from ramseyer.oracle import releases
from ramseyer.oracle.corpus import ClassifiedRow


def num(label: str) -> int:
    return int(re.match(r"\d+-(\d+)", label).group(1))


@dataclass
class Discovery:
    rps: dict                       # label -> (ReleasePoint, page url)
    plain: list[str]                # release points without a "not" exception, in law order (informational)
    by_law: dict                    # public law -> [ClassifiedRow]
    cands: list[tuple]              # (pl, (before, after), non-note rows), in law order

    def window(self, pl: str) -> tuple[str, str] | None:
        """(R_before, R_after): the first release point incorporating the law and the one published before it.

        Incorporated-set rule (oracle/releases.py, M6d): 119-73not60 holds 119-60 back, so 119-60 enters at 119-73;
        119-102not101 already incorporates 119-102. Replaced the rule that matched only a label ending
        "not<law>" and otherwise took plain labels around the law's number (scripts/release_windows_check.py)."""
        return releases.window(self.rps, pl)


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
        if not w or not targets:
            continue
        d.cands.append((pl, w, targets))
    d.cands.sort(key=lambda c: num(c[0]))
    return d
