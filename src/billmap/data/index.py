"""Read-only queries over the index. Every result carries the release point it came from."""
from __future__ import annotations

import sqlite3
import zlib
from pathlib import Path

from pydantic import BaseModel

from billmap.data import cite as citemod

SECTION_KINDS = ("section", "courtRule", "reorganizationPlan")


class LookupError_(LookupError):
    """Raised with a code from the statute-server error set: not_found, ambiguous."""

    def __init__(self, code: str, detail: str, release_point: str):
        super().__init__(f"{code}: {detail} (release point {release_point})")
        self.code, self.detail, self.release_point = code, detail, release_point


class Node(BaseModel):
    release_point: str
    id: int
    identifier: str
    cite: str | None              # "49 U.S.C. 24101(a)(2)"; None for units above a section
    title: str
    kind: str
    num: str | None
    heading: str | None
    path: str
    status: str
    text: str


class Index:
    def __init__(self, db_path: Path, release_point: str | None = None):
        if not db_path.exists():
            raise FileNotFoundError(f"no index at {db_path}; run `billmap sync`")
        # Read-only; the MCP server calls tools from a worker thread.
        self.db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
        if release_point is None:
            row = self.db.execute("SELECT id, label FROM release_points WHERE complete=1 "
                                  "ORDER BY id DESC LIMIT 1").fetchone()
        else:
            row = self.db.execute("SELECT id, label FROM release_points WHERE label=? AND complete=1",
                                  (release_point,)).fetchone()
        if row is None:
            raise LookupError(f"release point {release_point or '(latest)'} is not fully indexed")
        self.rp_id, self.release_point = row

    def release_points(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT label FROM release_points WHERE complete=1 ORDER BY id")]

    def _node(self, node_id: int) -> Node:
        r = self.db.execute("SELECT id, identifier, title, kind, num, heading, path, status, text_plain "
                            "FROM nodes WHERE id=? AND rp=?", (node_id, self.rp_id)).fetchone()
        if r is None:
            raise LookupError_("not_found", f"node {node_id}", self.release_point)
        try:
            c = str(citemod.from_identifier(r[1]))
        except citemod.CiteError:
            c = None
        return Node(release_point=self.release_point, id=r[0], identifier=r[1], cite=c, title=r[2],
                    kind=r[3], num=r[4], heading=r[5], path=r[6], status=r[7], text=r[8])

    def by_identifier(self, identifier: str) -> Node:
        ids = [r[0] for r in self.db.execute("SELECT node_id FROM node_ident WHERE rp=? AND identifier=?",
                                             (self.rp_id, identifier))]
        if not ids:
            raise LookupError_("not_found", identifier, self.release_point)
        if len(ids) > 1:
            raise LookupError_("ambiguous", f"{identifier} names {len(ids)} units: node ids {ids}",
                               self.release_point)
        return self._node(ids[0])

    def resolve_cite(self, text: str) -> Node:
        """A citation string ("49 U.S.C. 24101(a)(2)") to its unit. Never guesses a nearby unit."""
        try:
            parsed = citemod.parse(text)
        except citemod.CiteError as e:
            raise LookupError_("not_found", str(e), self.release_point) from None
        return self.by_identifier(parsed.identifier)

    def get_section(self, cite_or_identifier: str) -> Node:
        ident = cite_or_identifier if cite_or_identifier.startswith("/us/") else \
            citemod.parse(cite_or_identifier).section_identifier
        node = self.by_identifier(ident)
        if node.kind not in SECTION_KINDS:
            raise LookupError_("not_found", f"{ident} is a {node.kind}, not a section", self.release_point)
        return node

    def section_xml(self, node: Node) -> str:
        row = self.db.execute("SELECT xml_zlib FROM section_xml WHERE node_id=?", (node.id,)).fetchone()
        if row is None:
            raise LookupError_("not_found", f"no stored XML for {node.identifier}", self.release_point)
        return zlib.decompress(row[0]).decode("utf-8")

    def children(self, node: Node) -> list[Node]:
        return [self._node(r[0]) for r in self.db.execute(
            "SELECT id FROM nodes WHERE parent_id=? ORDER BY ord", (node.id,))]
