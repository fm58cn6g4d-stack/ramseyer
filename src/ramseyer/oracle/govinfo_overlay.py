"""GovInfo editions on demand (red team F6). The GovInfo held-out index holds only the sections each law is
classified to, so an edit ramseyer applies to any other section could not be checked. This overlay serves such a
section by fetching it from the same GovInfo edition (cached by the Fetcher) and converting it with the same
XHTML -> USLM converter, so a wrong-section edit is graded like any other prediction."""
from __future__ import annotations

import zlib

from lxml import etree

from ramseyer.data import govinfo
from ramseyer.data.http import Fetcher
from ramseyer.data.index import Index, LookupError_, Node
from ramseyer.data.indexer import text_of
from ramseyer.data.xhtml_uslm import NS, chunks, title_document


class GovInfoOverlay:
    """Index-like: the indexed release point, plus any other section of the same GovInfo edition on request."""

    def __init__(self, base: Index, year: int, fetcher: Fetcher, positive: set[str]):
        self.base, self.year, self.f, self.positive = base, year, fetcher, positive
        self.db, self.rp_id, self.release_point = base.db, base.rp_id, base.release_point
        self._granules: dict[str, dict[str, str]] = {}
        self._xml: dict[str, str] = {}
        self.fetched: list[str] = []

    def by_identifier(self, identifier: str) -> Node:
        try:
            return self.base.by_identifier(identifier)
        except LookupError_:
            node = self._fetch(identifier)
            if node is None:
                raise
            return node

    def section_xml(self, node: Node) -> str:
        return self._xml[node.identifier] if node.id < 0 else self.base.section_xml(node)

    def children(self, node: Node) -> list[Node]:
        return [] if node.id < 0 else self.base.children(node)

    def _fetch(self, identifier: str) -> Node | None:
        parts = identifier.split("/")
        if len(parts) != 5 or not parts[4].startswith("s"):
            return None
        title, sec = parts[3][1:], parts[4][1:]
        try:
            if title not in self._granules:
                self._granules[title] = govinfo.uscode_granules(self.f, self.year, title)
            gid = self._granules[title].get(sec) or self._granules[title].get(sec.replace("–", "-"))
            if not gid:
                return None
            page = govinfo.uscode_section_htm(self.f, self.year, title, gid)
        except RuntimeError:
            return None
        doc = etree.fromstring(title_document(chunks(page), title, f"GovInfo U.S. Code {self.year} edition",
                                              title in self.positive))
        el = next((e for e in doc.iter(NS + "section") if e.get("identifier") == identifier), None)
        if el is None:
            return None
        self._xml[identifier] = etree.tostring(el, encoding="unicode")
        self.fetched.append(identifier)
        h = el.find(NS + "heading")
        return Node(release_point=self.release_point, id=-(zlib.crc32(identifier.encode()) or 1),
                    identifier=identifier, cite=f"{title} U.S.C. {sec}", title=title, kind="section", num=sec,
                    heading=(text_of(h).strip() if h is not None else None), path="", status="current",
                    text=text_of(el))
