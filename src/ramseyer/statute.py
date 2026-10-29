"""The free statute server's library (docs/03-free-statute-server.md).

Every function returns a plain dict that includes "release_point". Failures raise StatuteError with one of
the documented codes: not_found, ambiguous, repealed, out_of_range. The MCP tools and the CLI are thin
wrappers over this module, so each function is built and tested once.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from ramseyer import config
from ramseyer.data import cite as citemod
from ramseyer.data.index import SECTION_KINDS, Index, LookupError_, Node

ERROR_CODES = ("not_found", "ambiguous", "repealed", "out_of_range")
DEFAULT_MAX_CHARS = 20_000
MAX_LIMIT = 500


class StatuteError(Exception):
    def __init__(self, code: str, message: str, release_point: str | None):
        assert code in ERROR_CODES, code
        super().__init__(message)
        self.code, self.message, self.release_point = code, message, release_point

    def as_dict(self) -> dict:
        return {"error": self.code, "message": self.message, "release_point": self.release_point}


def _natural(num: str) -> tuple:
    """Sort key for Code section numbers: '8B' < '8J', '1395w–22' < '1395w–23', '42' < '101'."""
    parts = re.findall(r"\d+|[A-Za-z]+|[–-]", num)
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts if p not in "–-")


class StatuteService:
    def __init__(self, index_path: Path | None = None, release_point: str | None = None):
        cfg = config.load()
        self.index_path = index_path or cfg.index_path
        self.default_rp = release_point or cfg.release_pin
        self._indexes: dict[str, Index] = {}
        self.ix = self._index(self.default_rp)

    # ---- plumbing ------------------------------------------------------------------
    def _index(self, rp: str | None) -> Index:
        rp = rp or self.default_rp
        if rp not in self._indexes:
            try:
                self._indexes[rp] = Index(self.index_path, rp)
            except LookupError as e:
                raise StatuteError("out_of_range", f"release point {rp} is not indexed ({e})", rp) from None
        return self._indexes[rp]

    @property
    def db(self) -> sqlite3.Connection:
        return self.ix.db

    def _wrap(self, ix: Index, fn):
        try:
            return fn()
        except LookupError_ as e:
            raise StatuteError(e.code if e.code in ERROR_CODES else "not_found", e.detail, ix.release_point) from None
        except citemod.CiteError as e:
            raise StatuteError("not_found", str(e), ix.release_point) from None

    def link(self, node: Node, ix: Index) -> str | None:
        """Page for the section on uscode.house.gov at this release point (ASCII hyphen, first number)."""
        m = re.match(r"^/us/usc/t(\d+a?)/s([^/~]+)", node.identifier)
        if not m or "~" in node.identifier:
            return None
        section = m.group(2).split("...")[0].replace(citemod.EN_DASH, "-")
        return f"https://uscode.house.gov/us/usc/{ix.release_point}/t{m.group(1)}/s{section}/"

    def _section_of(self, node: Node, ix: Index) -> Node:
        if node.kind in SECTION_KINDS:
            return node
        sid = ix.db.execute("SELECT section_id FROM nodes WHERE id=?", (node.id,)).fetchone()[0]
        if sid is None:
            raise StatuteError("not_found", f"{node.identifier} is a {node.kind}, not within a section",
                               ix.release_point)
        return ix._node(sid)

    def _brief(self, node: Node, ix: Index) -> dict:
        return {"cite": node.cite, "identifier": node.identifier, "kind": node.kind, "heading": node.heading,
                "status": node.status, "link": self.link(node, ix)}

    def _lookup(self, citation: str, ix: Index) -> tuple[Node, str]:
        """Citation or identifier -> unit. Returns (node, how it matched). Never guesses a nearby unit."""
        if citation.startswith("/us/"):
            return ix.by_identifier(citation), "identifier"
        parsed = citemod.parse(citation)
        try:
            return ix.by_identifier(parsed.identifier), "exact"
        except LookupError_ as e:
            if e.code != "not_found":
                raise
        if parsed.path:
            try:
                ix.by_identifier(parsed.section_identifier)
            except LookupError_:
                pass
            else:
                raise LookupError_("not_found", f"{parsed} : section {parsed.section_identifier} exists but has "
                                   f"no unit {''.join(f'({p})' for p in parsed.path)}", ix.release_point)
        # A section inside a published range, e.g. 2 U.S.C. 1002 within /us/usc/t2/s1001...1004.
        key = _natural(parsed.section)
        hits = []
        for (ident,) in ix.db.execute("SELECT identifier FROM node_ident WHERE rp=? AND identifier GLOB ?",
                                      (ix.rp_id, f"/us/usc/t{parsed.title}/s*...*")):
            lo, _, hi = ident.rsplit("/s", 1)[1].partition("...")
            if "/" not in hi and _natural(lo) <= key <= _natural(hi):
                hits.append(ident)
        if len(hits) == 1 and not parsed.path:
            return ix.by_identifier(hits[0]), f"within range {hits[0]}"
        if len(hits) > 1:
            raise LookupError_("ambiguous", f"{parsed} falls within several ranges: {hits}", ix.release_point)
        raise LookupError_("not_found", f"{parsed} ({parsed.identifier}) is not in the index", ix.release_point)

    def _section_node_ids(self, section: Node, ix: Index) -> list[int]:
        return [r[0] for r in ix.db.execute("SELECT id FROM nodes WHERE section_id=?", (section.id,))]

    @staticmethod
    def _cap(text: str, max_chars: int) -> tuple[str, bool]:
        return (text, False) if len(text) <= max_chars else (text[:max_chars], True)

    # ---- tools ---------------------------------------------------------------------
    def resolve_cite(self, citation: str, as_of: str | None = None) -> dict:
        ix = self._index(as_of)
        node, how = self._wrap(ix, lambda: self._lookup(citation, ix))
        return {"release_point": ix.release_point, "input": citation, "matched": how, "node_id": node.id,
                **self._brief(node, ix)}

    def get_section(self, citation: str, format: str = "operative", as_of: str | None = None,
                    include_tree: bool = False, max_chars: int = DEFAULT_MAX_CHARS) -> dict:
        if format not in ("plain", "xml", "operative"):
            raise StatuteError("out_of_range", f"format must be plain, xml or operative, not {format!r}", as_of)
        ix = self._index(as_of)
        node, how = self._wrap(ix, lambda: self._lookup(citation, ix))
        section = self._section_of(node, ix)
        if format == "xml":
            text = self._wrap(ix, lambda: ix.section_xml(section))
        elif format == "operative":
            text = section.text
        else:
            credit = ix.db.execute("SELECT DISTINCT raw FROM source_credits WHERE section_id=?",
                                   (section.id,)).fetchall()
            notes = ix.db.execute("SELECT note_type, heading, text FROM notes WHERE section_id=? ORDER BY id",
                                  (section.id,)).fetchall()
            text = "\n\n".join([section.text] + [c[0] for c in credit] +
                               [f"[{t}] {h or ''}\n{x}".strip() for t, h, x in notes])
        text, truncated = self._cap(text, max_chars)
        out = {"release_point": ix.release_point, "matched": how, **self._brief(section, ix), "format": format,
               "text": text, "truncated": truncated}
        diff = ix.db.execute("SELECT kind, detail FROM edition_diffs WHERE node_id=?", (section.id,)).fetchone()
        if diff and diff[0] != "rendering":
            out["warning"] = (f"OLRC's XML and XHTML editions differ on this section ({diff[0]}): {diff[1]}. "
                              "Text shown is the XML.")
        if include_tree:
            out["tree"] = [{"path": r[0], "kind": r[1], "num": r[2], "heading": r[3], "status": r[4]}
                           for r in ix.db.execute("SELECT path, kind, num, heading, status FROM nodes "
                                                  "WHERE section_id=? AND id<>? ORDER BY ord",
                                                  (section.id, section.id))]
        return out

    def get_pincite(self, citation: str, as_of: str | None = None, max_chars: int = DEFAULT_MAX_CHARS) -> dict:
        ix = self._index(as_of)
        node, how = self._wrap(ix, lambda: self._lookup(citation, ix))
        section = self._section_of(node, ix)
        parent_heading, cur = None, node.id
        while parent_heading is None:
            row = ix.db.execute("SELECT parent_id FROM nodes WHERE id=?", (cur,)).fetchone()
            if row is None or row[0] is None:
                break
            cur = row[0]
            parent_heading = ix.db.execute("SELECT heading FROM nodes WHERE id=?", (cur,)).fetchone()[0]
        text, truncated = self._cap(node.text, max_chars)
        return {"release_point": ix.release_point, "matched": how, **self._brief(node, ix), "path": node.path,
                "section": section.cite, "section_heading": section.heading, "parent_heading": parent_heading,
                "text": text, "truncated": truncated}

    def cross_refs(self, citation: str, include_notes: bool = False, limit: int = 200,
                   as_of: str | None = None) -> dict:
        ix = self._index(as_of)
        limit = self._limit(limit, ix)
        node, _ = self._wrap(ix, lambda: self._lookup(citation, ix))
        section = self._section_of(node, ix)
        contexts = ("text", "note", "credit") if include_notes else ("text",)
        rows = ix.db.execute(
            f"SELECT r.dst_raw, r.kind, r.dst_id, r.reason, r.anchor_text, r.context, s.path FROM refs r "
            f"JOIN nodes s ON s.id=r.src_id WHERE s.section_id=? AND r.context IN ({','.join('?' * len(contexts))}) "
            f"ORDER BY s.ord, r.id", (section.id, *contexts)).fetchall()
        refs = []
        for raw, kind, dst, reason, anchor, ctx, path in rows[:limit]:
            item = {"from_path": path, "context": ctx, "kind": kind, "target_raw": raw, "anchor_text": anchor,
                    "resolved": dst is not None, "reason": reason}
            if dst is not None:
                item["target_cite"] = ix._node(dst).cite
            refs.append(item)
        return {"release_point": ix.release_point, "section": section.cite, "total": len(rows),
                "returned": len(refs), "refs": refs}

    def cited_by(self, citation: str, limit: int = 100, include_notes: bool = False,
                 as_of: str | None = None) -> dict:
        """Units that cite the section (or any unit inside it), with the citing sentence."""
        ix = self._index(as_of)
        limit = self._limit(limit, ix)
        node, _ = self._wrap(ix, lambda: self._lookup(citation, ix))
        targets = self._section_node_ids(node, ix) if node.kind in SECTION_KINDS else [node.id]
        contexts = ("text", "note", "credit") if include_notes else ("text",)
        rows = ix.db.execute(
            f"SELECT r.id, r.src_id, r.dst_id, r.anchor_text, r.context FROM refs r JOIN nodes s ON s.id=r.src_id "
            f"WHERE r.dst_id IN ({','.join('?' * len(targets))}) AND r.context IN "
            f"({','.join('?' * len(contexts))}) ORDER BY s.ord, r.id", (*targets, *contexts)).fetchall()
        items = []
        for ref_id, src, dst, anchor, ctx in rows[:limit]:
            s = ix._node(src)
            try:
                sec = self._section_of(s, ix)
            except StatuteError:      # cited from a chapter or title outside any section
                sec = s
            items.append({"ref_id": ref_id, "citing_cite": s.cite or s.identifier,
                          "citing_section": sec.cite or sec.identifier,
                          "citing_heading": sec.heading, "context": ctx, "target_cite": ix._node(dst).cite,
                          "sentence": self._sentence(s.text, anchor)})
        return {"release_point": ix.release_point, "target": node.cite, "total": len(rows),
                "returned": len(items), "cited_by": items}

    @staticmethod
    def _sentence(text: str, anchor: str | None) -> str:
        if not anchor:
            return ""
        i = text.find(anchor)
        if i < 0:
            return anchor
        start = max(text.rfind(". ", 0, i), text.rfind("\n", 0, i), text.rfind("; ", 0, i))
        ends = [e for e in (text.find(". ", i), text.find("\n", i), text.find("; ", i)) if e >= 0]
        end = min(ends) + 1 if ends else len(text)
        return text[start + 1:end].strip()[:600]

    def definitions(self, citation: str, as_of: str | None = None) -> dict:
        ix = self._index(as_of)
        node, _ = self._wrap(ix, lambda: self._lookup(citation, ix))
        section = self._section_of(node, ix)
        rows = ix.db.execute(
            "SELECT d.term, d.scope_kind, d.scope_id, d.reason, d.evidence, n.path FROM definitions d "
            "JOIN nodes n ON n.id=d.section_id WHERE n.section_id=? ORDER BY n.ord, d.id", (section.id,)).fetchall()
        defs = []
        for term, scope_kind, scope_id, reason, evidence, path in rows:
            scope = ix._node(scope_id) if scope_id else None
            defs.append({"term": term, "defined_at": path, "scope_kind": scope_kind,
                         "scope": (scope.cite or scope.identifier) if scope else None,
                         "scope_heading": scope.heading if scope else None, "reason": reason, "evidence": evidence})
        return {"release_point": ix.release_point, "section": section.cite, "definitions": defs}

    def neighbors(self, citation: str, as_of: str | None = None) -> dict:
        ix = self._index(as_of)
        node, _ = self._wrap(ix, lambda: self._lookup(citation, ix))
        section = self._section_of(node, ix)
        parent_id = ix.db.execute("SELECT parent_id FROM nodes WHERE id=?", (section.id,)).fetchone()[0]
        parent = ix._node(parent_id) if parent_id else None
        sibs = [r[0] for r in ix.db.execute("SELECT id FROM nodes WHERE parent_id=? AND kind IN "
                                            "('section','courtRule','reorganizationPlan') ORDER BY ord",
                                            (parent_id,))] if parent_id else []
        i = sibs.index(section.id) if section.id in sibs else -1
        prev_ = ix._node(sibs[i - 1]) if i > 0 else None
        next_ = ix._node(sibs[i + 1]) if 0 <= i < len(sibs) - 1 else None
        return {"release_point": ix.release_point, "section": self._brief(section, ix),
                "parent": ({"identifier": parent.identifier, "kind": parent.kind, "num": parent.num,
                            "heading": parent.heading} if parent else None),
                "previous": self._brief(prev_, ix) if prev_ else None,
                "next": self._brief(next_, ix) if next_ else None,
                "siblings": len(sibs)}

    def search(self, query: str, title: str | None = None, limit: int = 10, phrase: bool = False,
               as_of: str | None = None) -> dict:
        ix = self._index(as_of)
        limit = self._limit(limit, ix)
        words = re.findall(r"[\w’'§.\-–]+", query)
        if not words:
            raise StatuteError("not_found", "empty query", ix.release_point)
        # Quote every token so user text is never parsed as FTS5 syntax.
        q = '"' + " ".join(w.replace('"', "") for w in words) + '"' if phrase else \
            " ".join('"' + w.replace('"', "") + '"' for w in words)
        sql = ("SELECT n.id, snippet(fts_nodes, 1, '[', ']', '…', 18), bm25(fts_nodes) FROM fts_nodes "
               "JOIN nodes n ON n.id = fts_nodes.rowid WHERE fts_nodes MATCH ? AND n.rp=?")
        args: list = [q, ix.rp_id]
        if title:
            sql += " AND n.title=?"
            args.append(str(title))
        sql += " ORDER BY bm25(fts_nodes) LIMIT ?"
        args.append(limit)
        hits = []
        for nid, snip, score in ix.db.execute(sql, args):
            n = ix._node(nid)
            hits.append({**self._brief(n, ix), "snippet": snip, "score": round(score, 3)})
        return {"release_point": ix.release_point, "query": query, "phrase": phrase, "title": title,
                "returned": len(hits), "results": hits}

    def changes(self, citation: str, from_rp: str, to_rp: str, max_chars: int = 4000) -> dict:
        """Units of one section added, removed or changed between two indexed release points."""
        a, b = self._index(from_rp), self._index(to_rp)

        def units(ix):
            try:
                node, _ = self._lookup(citation, ix)
            except (LookupError_, citemod.CiteError):
                return None, {}
            sec = self._section_of(node, ix)
            rows = ix.db.execute("SELECT n.identifier, h.hash, n.text_plain, n.status FROM nodes n JOIN text_hash h "
                                 "ON h.node_id=n.id WHERE n.section_id=? ORDER BY n.ord", (sec.id,)).fetchall()
            return sec, {r[0]: r[1:] for r in rows}

        sa, ua = units(a)
        sb, ub = units(b)
        if sa is None and sb is None:
            raise StatuteError("not_found", f"{citation} is in neither {from_rp} nor {to_rp}", to_rp)
        out = {"release_point": to_rp, "from_release_point": from_rp, "to_release_point": to_rp,
               "section": (sb or sa).cite, "added": [], "removed": [], "changed": []}
        for ident in ub.keys() - ua.keys():
            out["added"].append({"identifier": ident, "text": ub[ident][1][:max_chars]})
        for ident in ua.keys() - ub.keys():
            out["removed"].append({"identifier": ident, "text": ua[ident][1][:max_chars]})
        for ident in ua.keys() & ub.keys():
            if ua[ident][0] != ub[ident][0] or ua[ident][2] != ub[ident][2]:
                out["changed"].append({"identifier": ident, "before": ua[ident][1][:max_chars],
                                       "after": ub[ident][1][:max_chars],
                                       "status": [ua[ident][2], ub[ident][2]]})
        for k in ("added", "removed", "changed"):
            out[k].sort(key=lambda x: x["identifier"])
        return out

    def coverage(self) -> dict:
        db, ix = self.db, self.ix
        titles = db.execute("SELECT title, sections, positive_law, currency FROM titles WHERE rp=? ORDER BY rowid",
                            (ix.rp_id,)).fetchall()
        return {"release_point": ix.release_point, "release_points_loaded": ix.release_points(),
                "titles": [{"title": t, "sections": s, "positive_law": bool(p) if p is not None else None,
                            "current_through": c} for t, s, p, c in titles],
                "sections": sum(t[1] for t in titles),
                "nodes": db.execute("SELECT count(*) FROM nodes WHERE rp=?", (ix.rp_id,)).fetchone()[0],
                "edition_content_differences": db.execute(
                    "SELECT count(*) FROM edition_diffs WHERE rp=? AND kind='content'", (ix.rp_id,)).fetchone()[0]}

    def act_to_code(self, public_law: str, section: str, as_of: str | None = None, act: str | None = None) -> dict:
        """Code location of an Act section via the resolver (docs/05-resolver.md): source credits, notes,
        classification tables and the popular name table, cross-checked; never a guess."""
        from ramseyer.parse.ir import Target
        ix = self._index(as_of)
        m = re.search(r"(\d+)\s*[\u2013-]\s*(\d+)", public_law or "")
        if not m and not act:
            raise StatuteError("not_found", f"not a public law number: {public_law!r}", ix.release_point)
        sec = str(section).strip().lstrip("\u00a7 ").strip()
        path = re.findall(r"\([\w]+\)", sec)
        sec = re.sub(r"\(.*$", "", sec)
        target = Target(kind="pl" if m else "act", section=sec, path=path, act=act,
                        public_law=f"{m.group(1)}-{m.group(2)}" if m else None,
                        cite_raw=f"section {section} of {public_law or act}")
        res = self.resolver(ix).resolve(target)
        return {"release_point": ix.release_point, "public_law": target.public_law, "act": act, "act_section": sec,
                **res.model_dump(exclude={"release_point"})}

    def resolver(self, ix: Index):
        if not hasattr(self, "_resolvers"):
            self._resolvers = {}
        if ix.release_point not in self._resolvers:
            from ramseyer.data.http import Fetcher
            from ramseyer.resolve import popular
            from ramseyer.resolve.actcode import classification_map
            from ramseyer.resolve.resolver import Resolver, classification_rows
            cfg = config.load()
            self._resolvers[ix.release_point] = Resolver(ix, popular.load(), classification_map(
                classification_rows(Fetcher(cfg), cfg.olrc_base)))
        return self._resolvers[ix.release_point]

    def _limit(self, limit: int, ix: Index) -> int:
        if not 1 <= int(limit) <= MAX_LIMIT:
            raise StatuteError("out_of_range", f"limit must be 1..{MAX_LIMIT}", ix.release_point)
        return int(limit)


TOOLS = ("resolve_cite", "get_section", "get_pincite", "cross_refs", "cited_by", "definitions", "neighbors",
         "search", "changes", "coverage", "act_to_code")


def call(service: StatuteService, tool: str, **kwargs) -> dict:
    """Run a tool by name, turning StatuteError into its structured error dict."""
    if tool not in TOOLS:
        raise ValueError(f"unknown tool {tool}")
    try:
        return getattr(service, tool)(**kwargs)
    except StatuteError as e:
        return e.as_dict()
