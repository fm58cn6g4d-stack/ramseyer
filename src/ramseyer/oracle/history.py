"""The Code's release-point history (M6e): every section text from 113-21 (July 2013) on, from the dreamproit/uscode
dataset (CC0; built by aih/uscode-redesign from OLRC's release-point archive, whose older zips are no longer
served). See records/landscape-2026-10.md.

One SQLite file under var/history/:
  releases(label, seq, congress, law, excluded, reissue, currency_date)   one row per release point
  versions(vid, identifier, title, ...)                                    one row per distinct text of a section,
                                                                           its USLM XML zlib-compressed, as published
  version_releases(vid, seq)                                               which release points published it

A section at a release point is the version whose release list holds it; a release point can be materialized as an
ordinary ramseyer index (oracle.history.materialize) so the dry-run and the harness read it like any other.
"""
from __future__ import annotations

import json
import sqlite3
import zlib
from dataclasses import dataclass
from pathlib import Path

from ramseyer.oracle import releases as rl

SCHEMA = """
CREATE TABLE IF NOT EXISTS releases (
    label TEXT PRIMARY KEY, seq INTEGER UNIQUE NOT NULL, congress INTEGER NOT NULL, law INTEGER NOT NULL,
    excluded TEXT NOT NULL, reissue INTEGER NOT NULL, currency_date TEXT
);
CREATE TABLE IF NOT EXISTS versions (
    vid INTEGER PRIMARY KEY, identifier TEXT NOT NULL, title TEXT NOT NULL, num_value TEXT, heading TEXT,
    status TEXT, positive_law INTEGER, uslm_version TEXT, content_hash TEXT NOT NULL, parent_identifier TEXT,
    seq_in_title INTEGER, collision INTEGER NOT NULL, source_credit TEXT, xml_zlib BLOB NOT NULL,
    first_seq INTEGER, last_seq INTEGER
);
CREATE TABLE IF NOT EXISTS version_releases (vid INTEGER NOT NULL, seq INTEGER NOT NULL, PRIMARY KEY (seq, vid))
    WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS pending_releases (vid INTEGER NOT NULL, label TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS loaded_shards (name TEXT PRIMARY KEY, sha256 TEXT, rows INTEGER);
CREATE INDEX IF NOT EXISTS versions_ident ON versions(identifier);
"""


@dataclass
class Release:
    label: str
    seq: int
    currency_date: str | None


class History:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    # ---- loading -------------------------------------------------------------------------------------------
    def load_rows(self, rows) -> int:
        """Insert rows of the dataset's `versions` config (dicts with its field names). Returns rows added."""
        n = 0
        for r in rows:
            for lab, seq, date in ((r["first_release"], r["first_release_seq"], r["first_currency_date"]),
                                   (r["last_release"], r["last_release_seq"], r["last_currency_date"])):
                if lab and seq is not None:
                    self._release(lab, seq, date)
            cur = self.db.execute(
                "INSERT INTO versions(identifier, title, num_value, heading, status, positive_law, uslm_version, "
                "content_hash, parent_identifier, seq_in_title, collision, source_credit, xml_zlib, first_seq, "
                "last_seq) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r["identifier"], r["title"], r["num_value"], r["heading"], r["status"],
                 None if r["title_is_positive_law"] is None else int(r["title_is_positive_law"]), r["uslm_version"],
                 r["content_hash"], r["parent_identifier"], r["seq_in_title"], int(bool(r["identifier_collision"])),
                 r["source_credit"], zlib.compress(r["xml"].encode("utf-8"), 6), r["first_release_seq"],
                 r["last_release_seq"]))
            vid = cur.lastrowid
            # Held until the label's sequence is known (a label's sequence comes from rows where it is first or last).
            self.db.executemany("INSERT INTO pending_releases VALUES (?,?)", [(vid, lab) for lab in r["releases"] or []])
            n += 1
        return n

    def _release(self, label: str, seq: int, date) -> None:
        p = rl.parse(label)
        self.db.execute("INSERT OR IGNORE INTO releases VALUES (?,?,?,?,?,?,?)",
                        (label, seq, p.congress, p.law, json.dumps(sorted(p.excluded)), p.reissue,
                         str(date) if date else None))

    def flush_release_map(self) -> list[str]:
        """Write the version -> release rows whose label's sequence is known. Returns labels still without one."""
        self.db.execute("INSERT OR IGNORE INTO version_releases SELECT p.vid, r.seq FROM pending_releases p "
                        "JOIN releases r ON r.label=p.label")
        self.db.execute("DELETE FROM pending_releases WHERE label IN (SELECT label FROM releases)")
        self.db.commit()
        return [l for (l,) in self.db.execute("SELECT DISTINCT label FROM pending_releases ORDER BY label")]

    def place_unsequenced(self, total: int) -> tuple[dict[str, int], list[int]]:
        """Give a sequence to each label that is never a version's first or last release: the one gap in 1..total
        whose neighbours bracket it under the label order rule (oracle/releases.py). Returns the placements and the
        gaps left empty (release points with no section rows in the dataset)."""
        known = dict(self.db.execute("SELECT seq, label FROM releases"))
        gaps = sorted(set(range(1, total + 1)) - set(known))
        placed: dict[str, int] = {}
        for label in sorted(self.flush_release_map(), key=lambda l: rl.parse(l).order):
            order = rl.parse(label).order
            fits = []
            for g in gaps:
                before = max((s for s in known if s < g), default=None)
                after = min((s for s in known if s > g), default=None)
                if (before is None or rl.parse(known[before]).order < order) and \
                        (after is None or order < rl.parse(known[after]).order):
                    fits.append(g)
            if len(fits) == 1:
                g = fits[0]
                p = rl.parse(label)
                self.db.execute("INSERT INTO releases VALUES (?,?,?,?,?,?,?)",
                                (label, g, p.congress, p.law, json.dumps(sorted(p.excluded)), p.reissue, None))
                known[g] = label
                gaps.remove(g)
                placed[label] = g
        self.flush_release_map()
        return placed, gaps

    # ---- reading -------------------------------------------------------------------------------------------
    def releases(self) -> list[Release]:
        return [Release(*r) for r in self.db.execute("SELECT label, seq, currency_date FROM releases ORDER BY seq")]

    def seq(self, label: str) -> int:
        r = self.db.execute("SELECT seq FROM releases WHERE label=?", (label,)).fetchone()
        if r is None:
            raise LookupError(f"release point {label} is not in the history")
        return r[0]

    def section_xml(self, identifier: str, label: str) -> list[str]:
        """The section's published XML at a release point: [] when absent, two items at an identifier collision."""
        rows = self.db.execute("SELECT v.xml_zlib FROM versions v JOIN version_releases m ON m.vid=v.vid "
                               "WHERE m.seq=? AND v.identifier=? ORDER BY v.vid", (self.seq(label), identifier))
        return [zlib.decompress(x).decode("utf-8") for (x,) in rows]

    def title_sections(self, title: str, label: str):
        """(identifier, parent_identifier, seq_in_title, positive_law, xml) for every section of a title at a release
        point, in reading order."""
        rows = self.db.execute(
            "SELECT v.identifier, v.parent_identifier, v.seq_in_title, v.positive_law, v.xml_zlib FROM versions v "
            "JOIN version_releases m ON m.vid=v.vid WHERE m.seq=? AND v.title=? ORDER BY v.seq_in_title, v.vid",
            (self.seq(label), title))
        for ident, parent, sit, pos, x in rows:
            yield ident, parent, sit, pos, zlib.decompress(x).decode("utf-8")


# ---- materializing a release point as an ordinary index ------------------------------------------------------
CONTAINER = [("sch", "subchapter"), ("spt", "subpart"), ("sd", "subdivision"), ("art", "article"),
             ("ch", "chapter"), ("pt", "part"), ("st", "subtitle"), ("d", "division")]


def _container_kind(segment: str) -> str | None:
    for prefix, kind in CONTAINER:
        if segment.startswith(prefix) and len(segment) > len(prefix):
            return kind
    return None


def title_document(history: History, title: str, label: str) -> tuple[bytes, int, list[str]]:
    """A USLM 1.0 title document for one title at a release point, built from its sections: each section under its
    published parent (chapter, subchapter ...), in reading order; 2.x sections through uslm.to_v1. Returns the XML,
    the section count and notes (parents that could not be placed)."""
    from lxml import etree

    from ramseyer.data import uslm

    u = f"{{{uslm.USLM_NS}}}"
    base = f"/us/usc/t{title}"
    root = etree.Element(u + "uscDoc", nsmap={None: uslm.USLM_NS}, identifier=base)
    meta = etree.SubElement(root, u + "meta")
    etree.SubElement(meta, u + "docPublicationName").text = f"History@{label}"
    pos_el = etree.SubElement(meta, u + "property", role="is-positive-law")
    main = etree.SubElement(root, u + "main")
    title_el = etree.SubElement(main, u + "title", identifier=base)
    etree.SubElement(title_el, u + "num", value=title).text = f"Title {title}—"
    containers = {base: title_el}
    notes, n, positive = [], 0, None

    def container(ident: str):
        if ident in containers:
            return containers[ident]
        if not ident.startswith(base + "/"):
            notes.append(f"parent {ident} is outside the title")
            return title_el
        parent_ident, _, seg = ident.rpartition("/")
        kind = _container_kind(seg)
        if kind is None:
            notes.append(f"parent {ident}: unknown container kind")
            containers[ident] = container(parent_ident)
            return containers[ident]
        el = etree.SubElement(container(parent_ident), u + kind, identifier=ident)
        containers[ident] = el
        return el

    for ident, parent, _, pos, xml in history.title_sections(title, label):
        el = uslm.to_v1(etree.fromstring(xml.encode("utf-8")))
        container(parent or base).append(el)
        positive = positive if pos is None else pos
        n += 1
    pos_el.text = {1: "yes", 0: "no"}.get(positive, "")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8"), n, notes


def materialize(history: History, label: str, titles: list[str], db_path: Path, log=print) -> int:
    """Index `titles` of a release point from the history into db_path, as the oracle store indexes an OLRC zip.
    Returns the release point's id there; an index already complete with these titles is reused."""
    import zipfile

    from ramseyer.data.indexer import Indexer

    ix = Indexer(db_path)
    row = ix.db.execute("SELECT id, complete FROM release_points WHERE label=?", (label,)).fetchone()
    if row and row[1]:
        have = {r[0] for r in ix.db.execute("SELECT title FROM titles WHERE rp=?", (row[0],))}
        if have >= set(titles):
            return row[0]
        ix.drop_release_point(row[0])
    work = db_path.parent / "materialize"
    work.mkdir(parents=True, exist_ok=True)
    zp = work / f"{label}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
        for t in titles:
            doc, n, notes = title_document(history, t, label)
            if n:
                zf.writestr(f"usc{t}.xml", doc)
            for note in notes:
                log(f"{label} title {t}: {note}")
    rp = ix.load_release_point(zp, label, None, f"dreamproit/uscode history ({label})", log=lambda s: None)
    ix.mark_complete(rp)
    zp.unlink()
    return rp
