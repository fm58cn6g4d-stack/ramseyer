"""Parsers for OLRC pages (uscode.house.gov).

The site runs in a temporary format (notice on every page as of 2026-10-27), so these
parsers are deliberately small and pinned by fixture tests in tests/unit/test_olrc.py.
"""
from __future__ import annotations

import html as htmlmod
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from lxml import html as lhtml

# Verified 2026-10-27 against download.html:
#   download/releasepoints/us/pl/{congress}/{law}/{fmt}_usc{NN}@{congress}-{law}.zip
#   fmt in xml|htm|pcc|pdf; NN is zero-padded title, with appendix suffix "a" (05a, 11a, ...);
#   "All" for the all-titles archive.
ZIP_RE = re.compile(
    r"releasepoints/us/pl/(?P<congress>\d+)/(?P<law>[\w-]+)/"
    r"(?P<fmt>xml|htm|pcc|pdf)_usc(?P<title>\d+a?|All)@(?P<label>[\w-]+)\.zip$"
)
LABEL_RE = re.compile(r"Public Law\s+(\d+-\d+)")
DATE_RE = re.compile(r"current through Public Law \d+-\d+ \(([^)]+)\)", re.I)


@dataclass
class ReleasePoint:
    label: str                      # e.g. "119-134"
    date: str | None                # as printed, e.g. "October 20, 2026"
    xml_titles: dict[str, str] = field(default_factory=dict)   # "04" -> absolute URL
    xml_all: str | None = None
    currency: dict[str, str] = field(default_factory=dict)      # "4" -> "119-134", as printed


def parse_release_point(page: str, base: str) -> ReleasePoint:
    doc = lhtml.fromstring(page)
    heading = doc.xpath('string(//h3[contains(@class,"releasepointinformation")])')
    m = LABEL_RE.search(heading)
    if not m:
        raise ValueError("release point heading not found on download page")
    label = m.group(1)
    text = " ".join(doc.xpath("//p[contains(@class,'releasepointdescription')]//text()"))
    d = DATE_RE.search(" ".join(text.split()))
    rp = ReleasePoint(label=label, date=d.group(1) if d else None)
    for href in doc.xpath("//a/@href"):
        z = ZIP_RE.search(href)
        if not z or z.group("fmt") != "xml":
            continue
        if z.group("label") != label:
            raise ValueError(f"link {href} does not match release point {label}")
        url = urljoin(base, href)
        if z.group("title") == "All":
            rp.xml_all = url
        else:
            rp.xml_titles[z.group("title")] = url
    for item in doc.xpath('//div[contains(@class,"uscitem")]'):
        links = [ZIP_RE.search(h) for h in item.xpath(".//a/@href")]
        code = next((z.group("title") for z in links if z and z.group("title") != "All"), None)
        current = " ".join(item.xpath('string(.//div[contains(@class,"itemcurrency")])').split())
        if code and current:
            rp.currency[str(int(code[:2])) + code[2:].lower()] = current
    if not rp.xml_titles:
        raise ValueError("no per-title XML links found on download page")
    return rp


@dataclass(frozen=True)
class ClassificationRow:
    title: str        # "42", or "A"-prefixed appendix marker kept as printed
    section: str
    description: str  # "nt new", "repealed", "" (amended), ...
    public_law: str   # "119-75"
    law_section: str  # "7070(b)(1) \"33\"" kept verbatim
    stat_page: str


_PL_RE = re.compile(r"^\d+-\d+$")
# Stat page or range ("762-764"). A quoted new-section number can run straight into the
# page column with no space: '7201(c)(1) "Subchapter I"1677'.
_TAIL_RE = re.compile(r'^(.*?)(?:\s+|(?<="))(\d+(?:-\d+)?)\s*$')


def parse_classification_table(page: str) -> list[ClassificationRow]:
    """Parse a 'Sorted in Public Law order' table (fixed-width text inside <PRE>).

    Column starts come from the header line, so a shifted layout still parses.
    Lines that do not fit the layout raise rather than being skipped silently.
    """
    start = page.upper().find("<PRE>")
    end = page.upper().find("</PRE>", start)
    if start < 0 or end < 0:
        raise ValueError("classification table <PRE> block not found")
    raw = re.sub(r"<[^>]+>", "", page[start:end])
    lines = [htmlmod.unescape(l).rstrip() for l in raw.splitlines()]
    header_i = next(i for i, l in enumerate(lines) if l.startswith("Title") and "Pub. L." in l)
    h = lines[header_i]
    cols = [0, h.index("Section"), h.index("Description"), h.index("Pub. L."), h.index("Sec.")]
    rows: list[ClassificationRow] = []
    for line in lines[header_i + 2:]:
        if not line.strip():
            continue
        pl =line[cols[3]:cols[4]].strip()
        title = line[cols[0]:cols[1]].strip()
        section = line[cols[1]:cols[2]].strip()
        desc = line[cols[2]:cols[3]].strip()
        tail = _TAIL_RE.match(line[cols[4]:])
        if not _PL_RE.match(pl) or not tail:
            raise ValueError(f"unparsed classification line: {line!r}")
        rows.append(ClassificationRow(title, section, desc, pl, tail.group(1).strip(), tail.group(2)))
    return rows
