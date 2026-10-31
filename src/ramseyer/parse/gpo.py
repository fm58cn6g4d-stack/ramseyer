"""GPO's reading of an enacted law (M6e): the amendingAction verbs and Code citations GPO tags in a public law's USLM,
by bill location, as a second reader of ramseyer's parse (docs/06-dry-run.md).

GPO tags each amending verb (<amendingAction type="delete">striking</amendingAction>) and each Code citation
(<ref href="/us/usc/t10/s1501/a/1">). The tagging is verb-level, has known errors, and covers enacted laws (and some
bill versions) only: a witness, not an answer key.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

from ramseyer.data import congress

NS = "http://schemas.gpo.gov/xml/uslm"
# GPO identifier segments -> ramseyer's bill-location prefixes (parse/segment.py LEVEL_PREFIX).
PREFIX = {"d": "div", "t": "title", "st": "subt", "pt": "part", "spt": "subpart", "ch": "ch", "sch": "subch",
          "s": "sec"}
UNIT = {"subsection", "paragraph", "subparagraph", "clause", "subclause", "item", "subitem", "subsubitem"}


@dataclass
class Reading:
    loc: str                                          # ramseyer's bill location, "divA.titleV.subtI.sec581.a.1"
    verbs: list[str] = field(default_factory=list)    # amendingAction types in the unit's own text
    usc: list[str] = field(default_factory=list)      # Code citations in the unit's own text, or inherited


def _local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def loc_of(identifier: str) -> str | None:
    """"/us/pl/113/66/dA/tV/stI/s581/a/1" -> "divA.titleV.subtI.sec581.a.1"."""
    m = re.match(r"^/us/pl/\d+/\d+/(.+)$", identifier or "")
    if not m:
        return None
    out, in_section = [], False
    for seg in m.group(1).split("/"):
        p = None if in_section else re.match(r"^(d|t|st|pt|spt|ch|sch|s)([A-Za-z0-9].*)$", seg)
        if p:
            out.append(PREFIX[p.group(1)] + p.group(2))
            in_section = p.group(1) == "s"
        else:
            out.append(seg)                       # a unit label below the section, as ramseyer writes it
    return ".".join(out)


def _own(el):
    """The unit's own text elements: its chapeau, content and continuation, never quoted matter or subunits."""
    for c in el:
        if _local(c) in ("chapeau", "content", "continuation", "text"):
            yield c


def readings(path) -> dict[str, Reading]:
    """Bill location -> GPO's reading, for every identified section and unit of a public law's USLM."""
    root = etree.parse(str(path)).getroot()
    out: dict[str, Reading] = {}

    def walk(el, inherited: list[str]) -> None:
        ident = el.get("identifier")
        here = inherited
        if ident and (_local(el) == "section" or _local(el) in UNIT):
            loc = loc_of(ident)
            verbs, usc = [], []
            for part in _own(el):
                for x in part.iter():
                    if any(_local(a) in ("quotedContent", "quotedText") for a in x.iterancestors()):
                        continue
                    if _local(x) == "amendingAction":
                        verbs.append(x.get("type") or "unknown")
                    elif _local(x) == "ref" and (x.get("href") or "").startswith("/us/usc/"):
                        usc.append(x.get("href"))
            here = usc or inherited
            if loc:
                out[loc] = Reading(loc, verbs, here)
        for c in el:
            if isinstance(c.tag, str) and _local(c) not in ("quotedContent", "quotedText"):
                walk(c, here)

    walk(root, [])
    return out


def section_of(href: str) -> str | None:
    """"/us/usc/t10/s1501/a/1" -> "/us/usc/t10/s1501"."""
    m = re.match(r"^(/us/usc/t\w+/s[^/]+)", href or "")
    return m.group(1) if m else None


def uslm_path(fetcher, cfg, pl: str):
    """The path of a public law's USLM (Congress.gov's "United States Legislative Markup" version), or None."""
    import json
    c, n = pl.split("-")
    law = json.loads(fetcher.get(f"{cfg.congress_api}law/{c}/pub/{n}?format=json&api_key={cfg.api_key}").text())
    bill = law.get("bill") or {}
    if not bill:
        return None
    versions = congress.text_versions(fetcher, int(bill["congress"]), bill["type"].lower(), int(bill["number"]))
    urls = congress.xml_urls([v for v in versions if v.get("type") == "Public Law"], "United States Legislative Markup")
    if not urls:
        return None
    r = fetcher.get(urls[0])
    return r.path if r.status == 200 and r.path.read_bytes()[:200].find(b"<pLaw") >= 0 else None


def approved_date(path) -> str | None:
    """The law's approval date from its USLM metadata, "2013-12-26"."""
    root = etree.parse(str(path)).getroot()
    el = root.find(f".//{{{NS}}}approvedDate")
    return el.text.strip() if el is not None and el.text else None
