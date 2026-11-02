"""M8a: HOLC's Statute Compilations as a second current-law source, indexed like a release point.

Each compilation file (`COMPS-<fileId>.xml`, USLM 2.x, root `statuteCompilation`) is one Act or part of one, with its
currency: `currentThroughPublicLaw`, or, where that is missing, the "As Amended Through ..." edition note, or "[This
law has not been amended]" (current through the Act itself). A file with none of these is loaded with currency
"unknown" and says so; its currency is never guessed (records/verify-first.md, M8a).

The files share one index under a single label (by default "comps"): each file is loaded as its own "title" whose code
is `comp<fileId>`, so `Index(db, "comps").by_identifier("/us/sComp/95/617/s1")` finds a section of the Public Utility
Regulatory Policies Act of 1978. The compilation's own identifiers are kept; nothing is renumbered.
"""
from __future__ import annotations

import hashlib
import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from ramseyer.data import uslm
from ramseyer.data.indexer import Indexer

FILE_RE = re.compile(r"^COMPS-(\d+)\.xml$")
UNAMENDED = re.compile(r"^\[\s*This (?:law|Act) has not been amended\s*\]$", re.I)
AMENDED_THROUGH = re.compile(r"^\[\s*(?:As )?Amended Through\s+(.+?)\s*\]$", re.I)


@dataclass
class Compilation:
    file_id: str
    title: str | None              # dc:title
    citable_as: list[str]          # "Public Law 95–617", "Chapter 38 of the 81st Congress", ...
    current_through: str | None    # "117–58", or the text of an "As Amended Through" note, or None
    currency_basis: str            # "currentThroughPublicLaw" | "edition note" | "unamended" | "unknown"


def _meta(root, name: str) -> list[str]:
    return [" ".join("".join(e.itertext()).split()) for e in
            root.xpath(f"./*[local-name()='meta']/*[local-name()='{name}']")]


def describe(root, file_id: str) -> Compilation:
    """The compilation's identity and currency, from its meta and preface; never guessed."""
    title = next(iter(_meta(root, "title")), None)
    cites = list(dict.fromkeys(_meta(root, "citableAs")))
    cur = next(iter(_meta(root, "currentThroughPublicLaw")), None)
    if cur:
        return Compilation(file_id, title, cites, cur, "currentThroughPublicLaw")
    for note in root.xpath(".//*[local-name()='editionNote']"):
        text = " ".join("".join(note.itertext()).split())
        if UNAMENDED.match(text):
            return Compilation(file_id, title, cites, cites[0] if cites else "the Act as enacted", "unamended")
        m = AMENDED_THROUGH.match(text)
        if m:
            return Compilation(file_id, title, cites, m.group(1), "edition note")
    return Compilation(file_id, title, cites, None, "unknown")


def _as_title(root, file_id: str, title: str | None):
    """The compilation in the shape the Code indexer reads: a USLM 1.0 document whose <main> holds one <title> with
    the file's identifier (`/us/comp/<fileId>`), wrapping the Act's own units."""
    doc = uslm.to_v1(root)
    ns = uslm.USLM_NS
    ident = f"/us/comp/{file_id}"
    doc.set("identifier", ident)
    main = doc.find(f"{{{ns}}}main")
    if main is None:
        return doc
    wrapper = etree.Element(f"{{{ns}}}title", identifier=ident)
    head = etree.SubElement(wrapper, f"{{{ns}}}heading")
    head.text = title or f"Compilation {file_id}"
    for child in list(main):
        wrapper.append(child)
    main.append(wrapper)
    return doc


def load_compilations(indexer: Indexer, source: Path, label: str = "comps", source_url: str = "", log=print) -> int:
    """Index every COMPS-*.xml in `source` (a directory or COMPS.zip) under one label; returns the release point id.
    Each file's currency goes in the titles table (currency column: "<basis>: <value>")."""
    db = indexer.db
    existing = db.execute("SELECT id, complete FROM release_points WHERE label=?", (label,)).fetchone()
    if existing:
        if existing[1]:
            log(f"{label} already indexed")
            return existing[0]
        indexer.drop_release_point(existing[0])
    if source.is_dir():
        files = [(p.name, p.read_bytes) for p in sorted(source.iterdir()) if FILE_RE.match(p.name)]
        sha = hashlib.sha256(b"".join(hashlib.sha256(p.read_bytes()).digest()
                                      for p in sorted(source.iterdir()) if FILE_RE.match(p.name))).hexdigest()
    else:
        zf = zipfile.ZipFile(source)
        files = [(Path(n).name, (lambda n=n: zf.read(n))) for n in sorted(zf.namelist()) if FILE_RE.match(Path(n).name)]
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
    rp = db.execute("INSERT INTO release_points(label, date, source_url, source_sha256, loaded_at) VALUES (?,?,?,?,?)",
                    (label, None, source_url, sha, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))).lastrowid
    for name, read in files:
        file_id = FILE_RE.match(name).group(1)
        raw = etree.fromstring(read())
        comp = describe(raw, file_id)
        code = f"comp{file_id}"
        load = indexer._load_title(_as_title(raw, file_id, comp.title), rp, code)
        indexer._write(load, rp)
        currency = f"{comp.currency_basis}: {comp.current_through}" if comp.current_through else "unknown"
        db.execute("INSERT INTO titles VALUES (?,?,?,?,?,?,?,?)",
                   (rp, code, name, comp.title, None, currency, load.title_node, load.sections))
    indexer._resolve_refs(rp)
    indexer._resolve_definition_scopes(rp)
    db.execute("INSERT INTO fts_nodes(rowid, heading, text_plain) SELECT id, coalesce(heading,''), text_plain "
               "FROM nodes WHERE rp=? AND kind IN ('section','courtRule','reorganizationPlan')", (rp,))
    db.commit()
    log(f"{label}: {len(files)} compilations")
    return rp
