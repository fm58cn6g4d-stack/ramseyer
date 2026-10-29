"""Act-to-Code mapping (docs/05-resolver.md, three layers), built from one release point of the index.

Layer 1, derived from the Code: each section's enacting source credit names the Act and the Act section it
came from. Only non-positive-law titles are used: in a positive-law title the first credit names the law
that inserted the section, not an Act section codified there (e.g. 10 U.S.C. 1791 credits Pub. L. 104-106
§ 568(a)(1)), and treating that as codification would mis-resolve references to that law.
Act text placed in notes ("Pub. L. 116–283, div. A, title V, § 589, ..., provided that:") gives NOTE locations.

Layer 2, OLRC classification tables, cross-checks recent laws. Layer 3 (the Act's own text) is the dry-run's
concern; here an Act section with no Code location is UNCODIFIED.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from billmap.data.index import Index
from billmap.resolve.cites import parse_designation

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                      "nov", "dec"], 1)}
NOTE_TYPES_EXCLUDED = {"amendments", "effectiveDateOfAmendment", "priorProvisions", "referencesInText",
                       "codification", "removalDescription", "historicalAndRevision", "derivation", "footnote",
                       "editorialNotes", "shortTitleOfAmendment", "repeals", "crossReferences", "dispositionOfSections"}
PL_CITE = re.compile(r"Pub\. L\. (\d+)[–-](\d+)")
ACT_CITE = re.compile(r"\bact (\w+)\.? (\d+), (\d{4}), ch\. (\w+)", re.I)
SECTION_IN = re.compile(r"§+\s*([\w–.-]+?)((?:\([\w]+\))*)(?=[,;\s)]|$)")
CREDIT_DATE = re.compile(r"\b([A-Z][a-z]{2,8})\.? (\d{1,2}), (\d{4})\b")
PROVIDED = re.compile(r"\b(?:provided(?: that)?:|provided as follows|which (?:read|provided)|enacted)", re.I)


@dataclass(frozen=True)
class Location:
    section_id: int            # Code section node (in the index release point)
    act_path: tuple[str, ...]  # path inside the Act section that this location holds ((), whole section)
    note_id: int | None = None
    evidence: str = ""


def _act_identity(href: str | None, raw: str) -> str | None:
    m = re.match(r"^/us/act/(\d{4}-\d{2}-\d{2})/ch(\w+)", href or "")
    return f"act:{m.group(1)}:{m.group(2)}" if m else None


def _enacting_segment(raw: str) -> str:
    """'(July 1, 1944, ch. 373, title III, §317U, as added Pub. L. ...; amended ...)' -> up to 'as added'."""
    seg = raw.strip().lstrip("(").split(";")[0]
    return re.split(r",?\s+as (?:added|amended|renumbered|redesignated|transferred)\b", seg)[0]


def _date_key(month: str, day: str, year: str) -> str | None:
    m = MONTHS.get(month.lower()[:3])
    return f"{year}-{m:02d}-{int(day):02d}" if m else None


class ActCodeIndex:
    def __init__(self, ix: Index):
        self.ix = ix
        self.codified: dict[tuple[str, str], list[Location]] = defaultdict(list)
        self.notes: dict[tuple[str, str], list[Location]] = defaultdict(list)
        self.by_date: dict[str, set[str]] = defaultdict(set)   # "1976-06-03" -> {"pl:94-304"}: enactment dates
        self._build()

    def _build(self) -> None:
        db, rp = self.ix.db, self.ix.rp_id
        positive = {r[0] for r in db.execute("SELECT title FROM titles WHERE rp=? AND positive_law=1", (rp,))}
        rows = db.execute(
            "SELECT c.section_id, c.pl, c.pl_section, c.act_ref, c.raw, n.title FROM source_credits c "
            "JOIN (SELECT section_id, min(id) AS first FROM source_credits GROUP BY section_id) f ON f.first = c.id "
            "JOIN nodes n ON n.id = c.section_id WHERE n.rp=? AND n.kind='section'", (rp,))
        for sid, pl, pl_section, act_ref, raw, title in rows:
            if title in positive:
                continue
            if pl:
                parts = (pl_section or "").split("/")
                k = next((i for i, p in enumerate(parts) if re.fullmatch(r"s\w[\w–.-]*", p)), None)
                if k is None:
                    continue
                sec = parts[k][1:]
                path = tuple(f"({p})" for p in parts[k + 1:])
                self.codified[(f"pl:{pl}", sec)].append(Location(sid, path, evidence=raw[:160]))
                d = CREDIT_DATE.search(_enacting_segment(raw))
                if d and (key := _date_key(*d.groups())):
                    self.by_date[key].add(f"pl:{pl}")
            else:
                ident = _act_identity(act_ref, raw)
                if not ident:
                    continue
                self.by_date[ident.split(":")[1]].add(ident)
                for m in SECTION_IN.finditer(_enacting_segment(raw)):
                    sec, path = m.group(1).rstrip("."), tuple(re.findall(r"\([\w]+\)", m.group(2)))
                    self.codified[(ident, sec)].append(Location(sid, path, evidence=raw[:160]))
        for nid, sid, ntype, text in db.execute(
                "SELECT t.id, t.section_id, t.note_type, t.text FROM notes t JOIN nodes n ON n.id=t.section_id "
                "WHERE n.rp=?", (rp,)):
            if ntype in NOTE_TYPES_EXCLUDED:
                continue
            body = text.split("\n", 1)[1] if "\n" in text else text
            head = body[:400]
            if not PROVIDED.search(head):
                continue
            ident, cite_end = None, None
            m = PL_CITE.search(head)
            if m and m.start() < 40:
                ident, cite_end = f"pl:{m.group(1)}-{m.group(2)}", m.end()
            else:
                a = ACT_CITE.search(head)
                if a and a.start() < 40:
                    d = _date_key(a.group(1), a.group(2), a.group(3))
                    ident, cite_end = (f"act:{d}:{a.group(4)}" if d else None), a.end()
            if not ident:
                continue
            if ident.startswith("act:"):
                self.by_date[ident.split(":")[1]].add(ident)
            seg = head[cite_end:].split(";")[0]
            s = SECTION_IN.search(seg)
            if s and s.start() < 80:
                sec, path = s.group(1).rstrip("."), tuple(re.findall(r"\([\w]+\)", s.group(2)))
                self.notes[(ident, sec)].append(Location(sid, path, note_id=nid, evidence=head[:160]))

    def lookup(self, identities: list[str], section: str) -> tuple[list[Location], list[Location]]:
        cod, nts = [], []
        for ident in identities:
            cod += self.codified.get((ident, section), [])
            nts += self.notes.get((ident, section), [])
        return cod, nts


def classification_map(rows) -> dict[tuple[str, str], list[tuple[str, str, bool, tuple[str, ...]]]]:
    """Layer 2: (pl, law section) -> [(title, Code section, is_note, law path)] from OLRC classification rows."""
    out: dict[tuple[str, str], list] = defaultdict(list)
    for r in rows:
        sec, path = parse_designation(r.law_section)
        if sec:
            out[(f"pl:{r.public_law}", sec)].append((r.title.lower(), r.section, "nt" in r.description.split(),
                                                      path))
    return out
