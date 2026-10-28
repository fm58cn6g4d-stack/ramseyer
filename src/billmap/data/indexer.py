"""Build the SQLite index for one release point from the OLRC all-titles XML zip."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

USLM = "http://xml.house.gov/schemas/uslm/1.0"
SCHEMA = Path(__file__).with_name("schema.sql")

HIER = {"title", "subtitle", "chapter", "subchapter", "part", "subpart", "division", "subdivision",
        "article", "appendix", "courtRules", "reorganizationPlans", "compiledAct"}
SECTIONLIKE = {"section", "courtRule", "reorganizationPlan"}
SUB = {"subsection", "paragraph", "subparagraph", "clause", "subclause", "item", "subitem",
       "subsubitem", "level"}
# Never part of operative text, and never searched for structural units.
NON_OPERATIVE = {"notes", "note", "sourceCredit", "toc", "meta"}
BLOCK = SUB | SECTIONLIKE | {"chapeau", "content", "continuation", "p", "quotedContent", "tr",
                             "table", "proviso", "heading_block"}

MEMBER_RE = re.compile(r"^usc(\d+)([aA]?)\.xml$")
SCOPE_WORDS = {"section", "subsection", "paragraph", "subparagraph", "clause", "chapter",
               "subchapter", "part", "subpart", "title", "subtitle", "division", "article"}
_SCOPE = r"(?:In|For (?:the )?purposes? of|As used in) this (\w+)"
_TERMS = r"the terms? ((?:“[^”]{1,120}”(?:,? (?:and|or) |, )?)+) (?:means?|includes?|has the meaning)"
DEF_INLINE = re.compile(_SCOPE + r"[^.;:]{0,120}?,?\s*" + _TERMS)
DEF_TERM = re.compile(_TERMS)
SCOPE_ONLY = re.compile(_SCOPE + r"[^.;]{0,120}?[:—]\s*$")
QUOTED = re.compile(r"“([^”]{1,120})”")


def local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def text_of(el, skip: frozenset[str] = frozenset(NON_OPERATIVE)) -> str:
    """Plain text of an element: blocks on their own lines, inline whitespace collapsed."""
    parts: list[str] = []

    def walk(e, top=False):
        name = local(e)
        if not top and name in skip:
            return
        block = name in BLOCK
        if block:
            parts.append("\n")
        if name == "td" or name == "th":
            parts.append(" \t ")
        if e.text and isinstance(e.tag, str):
            parts.append(e.text)
        for c in e:
            walk(c)
            if c.tail:
                parts.append(c.tail)
        if name == "num":
            parts.append(" ")
        if block:
            parts.append("\n")

    walk(el, top=True)
    # U+00AD soft hyphens are typesetting marks ("Psycho\xadtropic"); the stored section XML keeps them.
    lines = (" ".join(line.split()) for line in "".join(parts).replace("\u00ad", "").split("\n"))
    return "\n".join(line for line in lines if line)


def title_code(member: str) -> str:
    m = MEMBER_RE.match(member)
    if not m:
        raise ValueError(f"unexpected zip member {member}")
    return str(int(m.group(1))) + ("a" if m.group(2) else "")


@dataclass
class TitleLoad:
    nodes: list[tuple] = field(default_factory=list)
    idents: list[tuple] = field(default_factory=list)
    xml: list[tuple] = field(default_factory=list)
    refs: list[tuple] = field(default_factory=list)
    notes: list[tuple] = field(default_factory=list)
    credits: list[tuple] = field(default_factory=list)
    defs: list[tuple] = field(default_factory=list)
    issues: list[tuple] = field(default_factory=list)
    sections: int = 0
    title_node: int | None = None


class Indexer:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.executescript(SCHEMA.read_text())
        self.db.execute("PRAGMA journal_mode=WAL")
        self.next_id = (self.db.execute("SELECT max(id) FROM nodes").fetchone()[0] or 0) + 1
        self.ord = 0

    # ---- release point -------------------------------------------------------------
    def load_release_point(self, zip_path: Path, label: str, date: str | None, source_url: str,
                           currency: dict[str, str] | None = None, titles: list[str] | None = None,
                           log=print) -> int:
        existing = self.db.execute("SELECT id, complete FROM release_points WHERE label=?", (label,)).fetchone()
        if existing:
            if existing[1]:
                log(f"release point {label} already indexed")
                return existing[0]
            self.drop_release_point(existing[0])
        sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        cur = self.db.execute(
            "INSERT INTO release_points(label, date, source_url, source_sha256, loaded_at) VALUES (?,?,?,?,?)",
            (label, date, source_url, sha, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
        rp = cur.lastrowid
        with zipfile.ZipFile(zip_path) as zf:
            for member in sorted(zf.namelist(), key=lambda m: (int(MEMBER_RE.match(m).group(1)), m)):
                code = title_code(member)
                if titles and code not in titles:
                    continue
                t0 = time.monotonic()
                with zf.open(member) as fh:
                    tree = etree.parse(fh)
                load = self._load_title(tree.getroot(), rp, code)
                self._write(load, rp)
                root = tree.getroot()
                pos = root.xpath("string(//*[local-name()='meta']/*[local-name()='property'][@role='is-positive-law'])")
                pub = root.xpath("string(//*[local-name()='meta']/*[local-name()='docPublicationName'])")
                self.db.execute("INSERT INTO titles VALUES (?,?,?,?,?,?,?,?)",
                                (rp, code, member, pub or None, {"yes": 1, "no": 0}.get(pos),
                                 (currency or {}).get(code), load.title_node, load.sections))
                self.db.commit()
                log(f"title {code:>3}: {load.sections:5d} sections, {len(load.nodes):7d} nodes, "
                    f"{len(load.refs):7d} refs  ({time.monotonic() - t0:.1f}s)")
                del tree
        self._resolve_refs(rp)
        self._resolve_definition_scopes(rp)
        self.db.execute("INSERT INTO fts_nodes(rowid, heading, text_plain) SELECT id, coalesce(heading,''), "
                        "text_plain FROM nodes WHERE rp=? AND kind IN ('section','courtRule','reorganizationPlan')",
                        (rp,))
        self.db.commit()
        return rp

    def mark_complete(self, rp: int) -> None:
        self.db.execute("UPDATE release_points SET complete=1 WHERE id=?", (rp,))
        self.db.commit()

    def drop_release_point(self, rp: int) -> None:
        ids = "SELECT id FROM nodes WHERE rp=?"
        self.db.execute("INSERT INTO fts_nodes(fts_nodes, rowid, heading, text_plain) SELECT 'delete', id, "
                        "coalesce(heading,''), text_plain FROM nodes WHERE rp=? AND kind IN "
                        "('section','courtRule','reorganizationPlan')", (rp,))
        for table, col in [("definitions", "section_id"), ("source_credits", "section_id"),
                           ("notes", "section_id"), ("section_xml", "node_id")]:
            self.db.execute(f"DELETE FROM {table} WHERE {col} IN ({ids})", (rp,))
        for table in ["refs", "node_ident", "text_hash", "load_issues", "titles"]:
            self.db.execute(f"DELETE FROM {table} WHERE rp=?", (rp,))
        self.db.execute("DELETE FROM nodes WHERE rp=?", (rp,))
        self.db.execute("DELETE FROM release_points WHERE id=?", (rp,))
        self.db.commit()

    # ---- one title -----------------------------------------------------------------
    def _load_title(self, root, rp: int, code: str) -> TitleLoad:
        load = TitleLoad()
        node_of: dict = {}            # element -> node id
        title_ident = root.get("identifier") or f"/us/usc/t{code}"
        def synthetic_identifier(el):
            """For an unidentified section stub (appendix compiled Acts): <base>/~<container-slug>/s<num>."""
            base, container = title_ident, None
            for a in el.iterancestors():
                if a.get("identifier"):
                    base = a.get("identifier").split()[0]
                    break
                if container is None and local(a) in HIER | {"level"}:
                    h = a.find(f"{{{USLM}}}heading")
                    if h is not None:
                        container = re.sub(r"[^a-z0-9]+", "-", "".join(h.itertext()).lower()).strip("-")
            num_el = el.find(f"{{{USLM}}}num")
            num = "".join(num_el.itertext()) if num_el is not None else f"line{el.sourceline}"
            token = re.sub(r"\s+to\s+", "...", re.sub(r"[\[\]§.\u202f]", " ", num).strip())
            tokens = [re.sub(r"\s+", "", t) for t in token.split(",")] if token else []
            # "§§ 11, 12" -> two identifiers, as OLRC does for identified multi-section stubs.
            return [f"{base}/~{container or 'unnamed'}/s{t}" for t in tokens if t] or \
                [f"{base}/~{container or 'unnamed'}/sline{el.sourceline}"]

        def add_node(el, kind, parent_id, section_id, section_ident, own_ids, synthetic=False):
            nid = self.next_id
            self.next_id += 1
            self.ord += 1
            num_el, head_el = el.find(f"{{{USLM}}}num"), el.find(f"{{{USLM}}}heading")
            num = " ".join("".join(num_el.itertext()).split()) if num_el is not None else None
            heading = " ".join("".join(head_el.itertext()).split()) if head_el is not None else None
            ident = own_ids[0]
            if kind in SECTIONLIKE:
                path, section_id = "", nid
            elif kind in SUB:
                if section_ident and ident.startswith(section_ident + "/"):
                    path = "".join(f"({p})" for p in ident[len(section_ident) + 1:].split("/"))
                else:
                    path = ident
                    load.issues.append((rp, code, "path_from_identifier", ident))
            else:
                path = ident[len(title_ident) + 1:] if ident.startswith(title_ident + "/") else (
                    "" if ident == title_ident else ident)
            if kind in SECTIONLIKE or kind in SUB:
                text = text_of(el)
            else:
                text = " ".join(x for x in (num, heading) if x)
            load.nodes.append((nid, rp, code, parent_id, section_id, kind, ident, num, heading, path,
                               el.get("status") or "current", text, el.sourceline, self.ord, int(synthetic)))
            for i in own_ids:
                load.idents.append((rp, i, nid))
            if kind in SECTIONLIKE:
                load.xml.append((nid, zlib.compress(etree.tostring(el, encoding="utf-8"), 6)))
            node_of[el] = nid
            return nid

        def visit(el, parent_id, section_id, section_ident):
            visit_list(list(el), parent_id, section_id, section_ident)

        def visit_list(children, parent_id, section_id, section_ident):
            for child in children:
                name = local(child)
                if not name or name in {"quotedContent", "num", "heading"}:
                    continue
                if name in {"notes", "note"}:
                    self._notes(child, parent_id, load)
                    continue
                if name == "sourceCredit":
                    self._credit(child, parent_id, load)
                    continue
                if name in NON_OPERATIVE:
                    continue
                ident = child.get("identifier")
                kind_known = name in HIER or name in SECTIONLIKE or name in SUB
                if name in SECTIONLIKE and section_id is not None:
                    # e.g. 25 U.S.C. 5329 holds a model agreement whose "SECTION 1." is marked up as a real
                    # section claiming /us/usc/t25/s1. Its text stays in the enclosing section.
                    load.issues.append((rp, code, "section_inside_section",
                                        f"{ident or '(no identifier)'} at line {child.sourceline} inside {section_ident}; "
                                        "kept as text of the enclosing section, not indexed"))
                    continue
                if name == "section" and not ident:
                    synth = synthetic_identifier(child)
                    load.issues.append((rp, code, "synthetic_identifier", f"line {child.sourceline}: {' '.join(synth)}"))
                    nid = add_node(child, name, parent_id, section_id, section_ident, synth, synthetic=True)
                    load.sections += 1
                    visit(child, nid, nid, synth[0])
                    continue
                if ident and kind_known:
                    own = ident.split()
                    nid = add_node(child, name, parent_id, section_id, section_ident, own)
                    if name == "section":
                        load.sections += 1
                    if name in SECTIONLIKE:
                        visit(child, nid, nid, own[0])
                    else:
                        visit(child, nid, section_id, section_ident)
                else:
                    if ident:
                        load.issues.append((rp, code, "identified_unknown_kind", f"{name} {ident}"))
                    elif name in SECTIONLIKE or name in HIER:
                        load.issues.append((rp, code, "unidentified_unit", f"{name} line {child.sourceline}"))
                    visit(child, parent_id, section_id, section_ident)

        main = root.find(f"{{{USLM}}}main")
        if main is None:
            # Appendix titles (5a, 11a, 18a, 28a, 50a) carry <appendix identifier="/us/usc/t5a"> instead.
            appendix = root.find(f"{{{USLM}}}appendix")
            if appendix is None:
                load.issues.append((rp, code, "no_main", "uscDoc has neither <main> nor <appendix>"))
                return load
            load.title_node = add_node(appendix, "appendix", None, None, None,
                                       (appendix.get("identifier") or title_ident).split())
            visit(appendix, load.title_node, None, None)
            self._refs(root, node_of, rp, load)
            self._definitions(load, node_of)
            return load

        top = [c for c in main if local(c) in HIER or local(c) in SECTIONLIKE]
        title_el = next((c for c in top if c.get("identifier") == title_ident), None)
        if title_el is not None and local(title_el) == "title":
            load.title_node = add_node(title_el, "title", None, None, None, title_ident.split())
            visit(title_el, load.title_node, None, None)
            others = [c for c in main if c is not title_el]
        else:
            load.issues.append((rp, code, "no_title_element", title_ident))
            others = list(main)
        visit_list(others, load.title_node, None, None)

        self._refs(root, node_of, rp, load)
        self._definitions(load, node_of)
        return load

    def _owner(self, el, node_of):
        for a in el.iterancestors():
            nid = node_of.get(a)
            if nid is not None:
                return nid
        return None

    def _refs(self, root, node_of, rp, load):
        for ref in root.iter(f"{{{USLM}}}ref"):
            src = self._owner(ref, node_of)
            if src is None:
                continue
            context = "text"
            for a in ref.iterancestors():
                n = local(a)
                if n == "sourceCredit":
                    context = "credit"
                    break
                if n in ("note", "notes"):
                    context = "note"
                    break
                if a in node_of:
                    break
            href = (ref.get("href") or "").strip()
            kind = next((k for p, k in (("/us/usc/", "usc"), ("/us/pl/", "pl"), ("/us/act/", "act"),
                                        ("/us/stat/", "stat")) if href.startswith(p)), "other")
            if kind == "usc":
                reason = "pending"
            elif not href:
                reason = "footnote marker" if "footnoteRef" in (ref.get("class") or "") else "empty href"
            else:
                reason = f"non-Code target ({kind})"
            anchor = " ".join("".join(ref.itertext()).split())[:200]
            load.refs.append((rp, src, None, href, kind, context, anchor, reason))

    def _notes(self, el, owner, load):
        notes = [el] if local(el) == "note" else [n for n in el if local(n) == "note"]
        for n in notes:
            ntype = n.get("topic") or ("footnote" if n.get("type") == "footnote" else n.get("role") or "untyped")
            head = n.find(f"{{{USLM}}}heading")
            heading = " ".join("".join(head.itertext()).split()) if head is not None else None
            load.notes.append((owner, ntype, heading, text_of(n, frozenset())))

    def _credit(self, el, owner, load):
        raw = " ".join("".join(el.itertext()).split())
        rows, current = [], None
        for c in el.iter():
            name = local(c)
            if name == "ref":
                href = c.get("href") or ""
                m = re.match(r"^/us/pl/(\d+)/(\d+)(?:/(.*))?$", href)
                if m:
                    current = [owner, f"{m.group(1)}-{m.group(2)}", m.group(3), None, None, raw]
                    rows.append(current)
                elif href.startswith("/us/act/"):
                    d = re.match(r"^/us/act/(\d{4}-\d{2}-\d{2})/", href)
                    current = [owner, None, None, href, d.group(1) if d else None, raw]
                    rows.append(current)
            elif name == "date" and current is not None and current[4] is None:
                current[4] = c.get("date")
        if not rows:
            rows = [[owner, None, None, None, None, raw]]
        load.credits.extend(tuple(r) for r in rows)

    def _definitions(self, load, node_of):
        by_id = {n[0]: n for n in load.nodes}
        own_cache: dict[int, str] = {}
        el_of = {v: k for k, v in node_of.items()}

        def own_text(nid):
            if nid not in own_cache:
                own_cache[nid] = text_of(el_of[nid], frozenset(NON_OPERATIVE | SUB))
            return own_cache[nid]

        for n in load.nodes:
            nid, kind = n[0], n[5]
            if kind not in SUB and kind not in SECTIONLIKE:
                continue
            text = own_text(nid)
            if "the term" not in text:
                continue
            for m in DEF_INLINE.finditer(text):
                for term in QUOTED.findall(m.group(2)):
                    load.defs.append([nid, term, m.group(1).lower(), m.group(0)[:300]])
            if DEF_INLINE.search(text):
                continue
            for m in DEF_TERM.finditer(text):
                scope, anc = "unknown", n[3]
                while anc in by_id and by_id[anc][5] not in HIER:
                    s = SCOPE_ONLY.search(own_text(anc).split("\n")[-1]) or SCOPE_ONLY.search(own_text(anc))
                    if s:
                        scope = s.group(1).lower()
                        break
                    anc = by_id[anc][3]
                for term in QUOTED.findall(m.group(1)):
                    load.defs.append([nid, term, scope, m.group(0)[:300]])

    # ---- write and resolve ---------------------------------------------------------
    def _write(self, load: TitleLoad, rp: int) -> None:
        db = self.db
        db.executemany("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", load.nodes)
        db.executemany("INSERT OR IGNORE INTO node_ident VALUES (?,?,?)", load.idents)
        db.executemany("INSERT INTO section_xml VALUES (?,?)", load.xml)
        db.executemany("INSERT INTO refs(rp, src_id, dst_id, dst_raw, kind, context, anchor_text, reason) "
                       "VALUES (?,?,?,?,?,?,?,?)", load.refs)
        db.executemany("INSERT INTO notes(section_id, note_type, heading, text) VALUES (?,?,?,?)",
                       [nt for nt in load.notes if nt[0] is not None])
        db.executemany("INSERT INTO source_credits(section_id, pl, pl_section, act_ref, date, raw) "
                       "VALUES (?,?,?,?,?,?)", [c for c in load.credits if c[0] is not None])
        db.executemany("INSERT INTO definitions(section_id, term, scope_kind, scope_id, reason, evidence) "
                       "VALUES (?,?,?,NULL,'pending',?)", [tuple(d) for d in load.defs])
        db.executemany("INSERT INTO text_hash VALUES (?,?,?)",
                       [(n[0], rp, hashlib.sha256(n[11].encode()).hexdigest()) for n in load.nodes])
        orphan = len([x for x in load.notes if x[0] is None]) + len([c for c in load.credits if c[0] is None])
        if orphan:
            load.issues.append((rp, load.nodes[0][2] if load.nodes else None, "orphan_note_or_credit", str(orphan)))
        db.executemany("INSERT INTO load_issues(rp, title, kind, detail) VALUES (?,?,?,?)", load.issues)

    def _resolve_refs(self, rp: int) -> None:
        db = self.db
        db.execute("""UPDATE refs SET dst_id = (SELECT min(node_id) FROM node_ident i
                      WHERE i.rp = refs.rp AND i.identifier = refs.dst_raw),
                      reason = CASE (SELECT count(*) FROM node_ident i WHERE i.rp = refs.rp
                                     AND i.identifier = refs.dst_raw)
                               WHEN 0 THEN 'no unit with this identifier at this release point'
                               WHEN 1 THEN 'resolved'
                               ELSE 'ambiguous: identifier on several nodes' END
                      WHERE rp = ? AND kind = 'usc'""", (rp,))
        db.execute("UPDATE refs SET dst_id = NULL WHERE rp=? AND reason LIKE 'ambiguous%'", (rp,))
        # Say why a Code ref did not resolve: missing section, or a section without that subunit.
        rows = db.execute("SELECT id, dst_raw FROM refs WHERE rp=? AND kind='usc' AND reason LIKE 'no unit%'",
                          (rp,)).fetchall()
        sections = {r[0] for r in db.execute("SELECT identifier FROM node_ident WHERE rp=?", (rp,))}
        updates = []
        for rid, raw in rows:
            m = re.match(r"^(/us/usc/t[0-9]+a?/s[^/]+)(/.*)?$", raw)
            if not m:
                updates.append(("no Code unit with this identifier at this release point", rid))
            elif m.group(2) and m.group(1) in sections:
                updates.append(("section exists at this release point; subunit has no identifier", rid))
            else:
                updates.append(("section not at this release point", rid))
        db.executemany("UPDATE refs SET reason=? WHERE id=?", updates)
        dup = db.execute("SELECT identifier, count(*) FROM node_ident WHERE rp=? GROUP BY identifier "
                         "HAVING count(*) > 1", (rp,)).fetchall()
        db.executemany("INSERT INTO load_issues(rp, title, kind, detail) VALUES (?,NULL,'duplicate_identifier',?)",
                       [(rp, f"{i} x{c}") for i, c in dup])

    def _resolve_definition_scopes(self, rp: int) -> None:
        db = self.db
        rows = db.execute("SELECT d.id, d.section_id, d.scope_kind FROM definitions d JOIN nodes n "
                          "ON n.id = d.section_id WHERE n.rp=? AND d.reason='pending'", (rp,)).fetchall()
        updates = []
        for did, nid, scope in rows:
            if scope not in SCOPE_WORDS:
                why = "no scope phrase found" if scope == "unknown" else f"scope '{scope}' is not a Code unit"
                updates.append((None, why, did))
                continue
            cur, found = nid, None
            while cur is not None:
                parent, kind = db.execute("SELECT parent_id, kind FROM nodes WHERE id=?", (cur,)).fetchone()
                if kind == scope:
                    found = cur
                    break
                cur = parent
            updates.append((found, "resolved" if found else f"no enclosing {scope}", did))
        db.executemany("UPDATE definitions SET scope_id=?, reason=? WHERE id=?", updates)
