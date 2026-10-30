"""USLM helpers: the probe's title summary and the 1.x/2.x schema seam used by the indexer."""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

USLM_NS = "http://xml.house.gov/schemas/uslm/1.0"
# OLRC has announced the Code's move to USLM 2.x (records/landscape-2026-10.md, item 5); bills and laws use it now.
USLM2_NS = "http://schemas.gpo.gov/xml/uslm"
XHTML_NS = "http://www.w3.org/1999/xhtml"
# Verified 2026-10-27 against usc04.xml @119-134: sections carry identifier="/us/usc/t4/s1".
SECTION_ID_RE = re.compile(r"^/us/usc/t(\d+a?)/s([0-9A-Za-z\-–.]+)$")


@dataclass
class TitleSummary:
    member: str
    root_tag: str
    title_identifier: str
    publication: str        # docPublicationName, e.g. "Online@119-134"
    sections: int
    malformed_ids: list[str]


def schema_version(root) -> str | None:
    """'1' or '2' from the root element's namespace; None for anything else."""
    ns = etree.QName(root).namespace
    return {USLM_NS: "1", USLM2_NS: "2"}.get(ns)


def to_v1(root):
    """Return a USLM 1.0 document for a 1.x or 2.x Code title, so everything downstream reads one form.

    A 1.0 root is returned unchanged. For 2.x (checked on OLRC's 2.0.12 sample titles 1, 16 and 49,
    scripts/uslm2_check.py), every element in the 2.x namespace moves to the 1.0 namespace under the same
    local name, and the four constructs 1.0 writes differently are rewritten to their 1.0 form:

    - an inline <footnote> becomes <note type="footnote">, which 1.0 uses and operative text skips;
    - <list>/<listItem>/<listContent> become one <p role="listItem"> per item;
    - a <crossHeading>, or a <heading> standing loose in running text or before a unit's <num> (a centred
      line such as "new mexico principal meridian", or a formula), becomes <p>, as 1.0 writes it;
    - an XHTML <caption> becomes the table's first header row, as in 1.0.
    """
    if schema_version(root) != "2":
        return root
    u1, u2 = f"{{{USLM_NS}}}", f"{{{USLM2_NS}}}"
    nsmap = {k: v for k, v in root.nsmap.items() if v != USLM2_NS}
    nsmap[None] = USLM_NS
    new = etree.Element(u1 + etree.QName(root).localname, attrib=dict(root.attrib), nsmap=nsmap)
    new.text = root.text
    for c in list(root):
        new.append(c)
    for el in new.iter():
        if isinstance(el.tag, str) and el.tag.startswith(u2):
            el.tag = u1 + el.tag[len(u2):]
    for el in list(new.iter(u1 + "footnote")):
        el.tag = u1 + "note"
        el.set("type", "footnote")
    for item in list(new.iter(u1 + "listItem")):
        item.tag = u1 + "p"
        item.set("role", "listItem")
        for lc in list(item.iter(u1 + "listContent")):
            _unwrap(lc)
    for lst in list(new.iter(u1 + "list")):
        _unwrap(lst)
    for el in list(new.iter(u1 + "crossHeading", u1 + "heading")):
        parent = el.getparent()
        prev = el.getprevious()
        loose = (el.tag == u1 + "crossHeading" or local(parent) in RUNNING
                 or (local(parent) in UNITS and parent.find(u1 + "num") is not None
                     and parent.index(parent.find(u1 + "num")) > parent.index(el)))
        if loose and not (prev is not None and local(prev) == "num"):
            el.tag = u1 + "p"
    x = f"{{{XHTML_NS}}}"
    for cap in list(new.iter(x + "caption")):
        table = cap.getparent()
        thead = table.find(x + "thead")
        if thead is None:
            thead = etree.Element(x + "thead")
            table.insert(table.index(cap) + 1, thead)
        tr = etree.Element(x + "tr", {"class": "title"})
        th = etree.SubElement(tr, x + "th")
        p = etree.SubElement(th, u1 + "p")
        p.text = cap.text
        for c in list(cap):
            p.append(c)
        thead.insert(0, tr)
        table.remove(cap)       # its tail is the whitespace between table parts
    etree.cleanup_namespaces(new)
    return new


# Elements holding running text, and structural units, for placing a loose <heading>.
RUNNING = {"content", "chapeau", "continuation", "quotedContent", "p", "inline", "proviso"}
UNITS = {"section", "subsection", "paragraph", "subparagraph", "clause", "subclause", "item", "subitem",
         "subsubitem", "level", "title", "subtitle", "chapter", "subchapter", "part", "subpart", "division",
         "subdivision", "article"}


def local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _unwrap(el) -> None:
    """Replace an element by its children and text, keeping its position."""
    parent = el.getparent()
    i = parent.index(el)
    prev = el.getprevious()
    if el.text:
        if prev is not None:
            prev.tail = (prev.tail or "") + el.text
        else:
            parent.text = (parent.text or "") + el.text
    children = list(el)
    for k, c in enumerate(children):
        parent.insert(i + k, c)
    last = children[-1] if children else (parent[i - 1] if i > 0 else None)
    if el.tail:
        if last is not None:
            last.tail = (last.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def summarize_title_zip(path: Path) -> TitleSummary:
    with zipfile.ZipFile(path) as zf:
        members = [n for n in zf.namelist() if n.endswith(".xml")]
        if len(members) != 1:
            raise ValueError(f"expected one XML member in {path.name}, found {members}")
        with zf.open(members[0]) as fh:
            root = to_v1(etree.parse(fh).getroot())
    ns = {"u": USLM_NS}
    ids = root.xpath("//u:section/@identifier", namespaces=ns)
    return TitleSummary(
        member=members[0],
        root_tag=etree.QName(root).localname,
        title_identifier=root.get("identifier", ""),
        publication=root.findtext(f"{{{USLM_NS}}}meta/{{{USLM_NS}}}docPublicationName") or "",
        sections=len(ids),
        malformed_ids=[i for i in ids if not SECTION_ID_RE.match(i)],
    )
