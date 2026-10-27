"""Minimal USLM helpers used by the probe; the full indexer arrives in M1."""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

USLM_NS = "http://xml.house.gov/schemas/uslm/1.0"
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


def summarize_title_zip(path: Path) -> TitleSummary:
    with zipfile.ZipFile(path) as zf:
        members = [n for n in zf.namelist() if n.endswith(".xml")]
        if len(members) != 1:
            raise ValueError(f"expected one XML member in {path.name}, found {members}")
        with zf.open(members[0]) as fh:
            root = etree.parse(fh).getroot()
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
