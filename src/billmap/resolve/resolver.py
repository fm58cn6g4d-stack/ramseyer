"""Resolver (docs/05-resolver.md): a parsed instruction's target -> a node in the index, or exactly why not.

It never guesses. Every source of evidence is cross-checked; when two disagree the result is UNKNOWN with
both candidates and the reason, and a result relying on one unverified source says so in `flags`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from billmap.data.index import Index, LookupError_
from billmap.parse.ir import Target
from billmap.resolve.actcode import ActCodeIndex, Location
from billmap.resolve.cites import parse_parenthetical
from billmap.resolve.popular import norm_name

Outcome = Literal["CODIFIED", "NOTE", "SPLIT", "UNCODIFIED", "UNKNOWN"]
UNIT_ID = {"subtitle": "st", "part": "pt", "subpart": "spt", "chapter": "ch", "subchapter": "sch"}


class Resolution(BaseModel):
    outcome: Outcome
    release_point: str
    cite: str | None = None                       # "42 U.S.C. 247b–23(b)" (the unit), or "10 U.S.C. 1791 note"
    section_id: int | None = None
    node_id: int | None = None                    # the unit within the section, when it exists
    note_id: int | None = None
    candidates: list[str] = Field(default_factory=list)   # SPLIT / UNKNOWN: what the evidence pointed to
    note_anchor: str | None = None                # NOTE: section the note is under or precedes (identifier)
    verified: bool = False                        # two independent sources agree
    positive_law: bool | None = None
    status: str | None = None                     # current, repealed, ... of the section
    evidence: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    reason: str | None = None


class Resolver:
    def __init__(self, ix: Index, popular: dict[str, list[dict]], classification: dict | None = None):
        self.ix = ix
        self.popular = popular
        self.classification = classification or {}
        self.acts = ActCodeIndex(ix)
        self.positive = {r[0] for r in ix.db.execute("SELECT title FROM titles WHERE rp=? AND positive_law=1",
                                                     (ix.rp_id,))}

    # ---- helpers -------------------------------------------------------------------
    def _section_node(self, title: str, section: str):
        try:
            return self.ix.by_identifier(f"/us/usc/t{title}/s{section}")
        except LookupError_ as e:
            return e

    def _unit(self, section_node, path: tuple[str, ...] | list[str]):
        """(unit node id or None, flags) for a path inside a section."""
        if not path:
            return section_node.id, []
        ident = section_node.identifier + "".join("/" + p.strip("()") for p in path)
        try:
            return self.ix.by_identifier(ident).id, []
        except LookupError_ as e:
            return None, [f"unit {''.join(path)} not found in {section_node.cite} ({e.code})"]

    def _first_section(self, node):
        row = self.ix.db.execute("SELECT id FROM nodes WHERE rp=? AND ord > ? AND kind='section' ORDER BY ord LIMIT 1",
                                 (self.ix.rp_id, self.ix.db.execute("SELECT ord FROM nodes WHERE id=?",
                                                                    (node.id,)).fetchone()[0])).fetchone()
        return self.ix._node(row[0]) if row else None

    def _done(self, outcome, section, path=(), note_id=None, **kw) -> Resolution:
        title = section.identifier.split("/")[3][1:]
        flags = kw.pop("flags", [])
        anchor = None
        if note_id is not None:
            unit_id, uflags = None, []
            if section.kind in ("section", "courtRule", "reorganizationPlan"):
                cite, anchor = f"{section.cite or section.identifier} note", section.identifier
            else:
                # A note on a chapter or subchapter heading: OLRC cites it as preceding the unit's first section.
                first = self._first_section(section)
                anchor = first.identifier if first else None
                cite = (f"{title} U.S.C. note prec. {first.identifier.rsplit('/s', 1)[1]}" if first
                        else f"{section.identifier} note")
        else:
            unit_id, uflags = self._unit(section, tuple(path))
            cite = (section.cite or section.identifier) + "".join(path)
        if section.status not in ("current", None):
            flags = flags + [f"section is {section.status} at {self.ix.release_point}", "needs review"]
        flags = flags + uflags
        return Resolution(outcome=outcome, release_point=self.ix.release_point, cite=cite, section_id=section.id,
                          node_id=unit_id, note_id=note_id, note_anchor=anchor, positive_law=title in self.positive,
                          status=section.status, flags=flags, **kw)

    def _fail(self, outcome, reason, **kw) -> Resolution:
        return Resolution(outcome=outcome, release_point=self.ix.release_point, reason=reason, **kw)

    # ---- entry -------------------------------------------------------------------------
    def resolve(self, target: Target) -> Resolution:
        if target.kind == "usc":
            return self._usc(target)
        if target.kind in ("act", "pl"):
            return self._act(target)
        return self._fail("UNKNOWN", "the parser found no target for this instruction",
                          evidence=[target.cite_raw] if target.cite_raw else [])

    def _usc(self, t: Target) -> Resolution:
        if not t.section:
            unit = next((q for q in t.qualifiers if q.split()[0] in UNIT_ID), None)
            if unit:
                # "subchapter i of chapter 8" -> identifier glob "/us/usc/t10/*ch8/schI"
                steps = [p.split() for p in reversed(unit.split(" of "))]
                tail = "/".join(f"{UNIT_ID[k]}{v.upper() if k != 'chapter' else v}" for k, v in steps)
                rows = self.ix.db.execute("SELECT node_id FROM node_ident WHERE rp=? AND (identifier GLOB ? OR "
                                          "identifier GLOB ?)", (self.ix.rp_id, f"/us/usc/t{t.title}/*/{tail}",
                                                                 f"/us/usc/t{t.title}/{tail}")).fetchall()
                if len(rows) == 1:
                    n = self.ix._node(rows[0][0])
                    return Resolution(outcome="CODIFIED", release_point=self.ix.release_point,
                                      cite=f"{t.title} U.S.C. {unit}", node_id=n.id,
                                      positive_law=t.title in self.positive, verified=True, status=n.status,
                                      evidence=[f"{n.identifier}: {n.heading}"])
                return self._fail("UNKNOWN", f"{t.title} U.S.C. {unit}: {len(rows)} matching units",
                                  candidates=[self.ix._node(r[0]).identifier for r in rows[:10]])
            try:
                n = self.ix.by_identifier(f"/us/usc/t{t.title}")
            except LookupError_ as e:
                return self._fail("UNKNOWN", f"title {t.title}: {e.code}")
            return Resolution(outcome="CODIFIED", release_point=self.ix.release_point, cite=f"title {t.title}, U.S.C.",
                              node_id=n.id, positive_law=t.title in self.positive, verified=True,
                              evidence=["the whole title is the target (e.g. a new chapter is inserted)"])
        sec = self._section_node(t.title, t.section)
        if isinstance(sec, LookupError_):
            return self._fail("UNKNOWN", f"{t.title} U.S.C. {t.section}: {sec.code} at {self.ix.release_point}")
        return self._done("CODIFIED", sec, t.path, verified=True, evidence=[f"drafted as {t.cite_raw}"])

    def _identities(self, t: Target, paren) -> tuple[list[str], list[str]]:
        ids, ev = [], []
        pl = t.public_law or paren.public_law
        if pl:
            ids.append(f"pl:{pl.replace(chr(0x2013), '-')}")
            ev.append(f"public law {pl} as drafted")
        if t.act:
            entries = self.popular.get(norm_name(t.act), [])
            pids = [i for e in entries for i in e["identities"]]
            if pids:
                ev.append(f"popular name '{t.act}' -> {', '.join(pids)}")
                if ids and not set(ids) & set(pids):
                    ev.append("popular name and drafted public law differ")
                for i in pids:
                    if i not in ids:
                        ids.append(i)
            elif not ids:
                ev.append(f"'{t.act}' not in the popular name table")
        return ids, ev

    def _act(self, t: Target) -> Resolution:
        paren = parse_parenthetical(t.usc_parenthetical)
        ids, ev = self._identities(t, paren)
        if not t.section:
            return self._fail("UNKNOWN", "Act named without a section", evidence=ev)
        act_path = tuple(t.path)
        if not ids:
            return self._fail("UNKNOWN", f"cannot identify the Act in '{t.cite_raw}'", evidence=ev)
        codified, notes = self.acts.lookup(ids, t.section)

        # Narrow layer-1 locations by the Act path (an Act section split over several Code sections).
        def fit(locs: list[Location]) -> list[Location]:
            exact = [l for l in locs if l.act_path and act_path[:len(l.act_path)] == l.act_path]
            return exact or [l for l in locs if not l.act_path] or locs

        codified, notes = fit(codified), fit(notes)
        sections = {l.section_id for l in codified}
        # The drafter's parenthetical, when it names a Code location.
        pnode = None
        if paren.title and paren.section and not paren.preceding:
            pnode = self._section_node(paren.title, paren.section)
            if isinstance(pnode, LookupError_):
                ev.append(f"parenthetical {paren.title} U.S.C. {paren.section}: {pnode.code}")
                pnode = None
        # Layer 2: classification tables (recent laws).
        l2 = []
        for i in ids:
            for title, sec, is_note, lpath in self.classification.get((i, t.section), []):
                if not lpath or act_path[:len(lpath)] == lpath or lpath[:len(act_path)] == act_path:
                    l2.append((title, sec, is_note))

        def rel_path(loc: Location) -> tuple[str, ...]:
            return act_path[len(loc.act_path):] if loc.act_path and act_path[:len(loc.act_path)] == loc.act_path \
                else act_path

        if len(sections) == 1:
            loc = codified[0]
            sec = self.ix._node(loc.section_id)
            agree = []
            if pnode is not None:
                if pnode.id != sec.id:
                    return self._fail("UNKNOWN", f"source credits place {t.cite_raw} at {sec.cite} but the drafted "
                                      f"parenthetical says {paren.title} U.S.C. {paren.section}",
                                      candidates=[sec.cite, pnode.cite], evidence=ev + [loc.evidence])
                agree.append("drafted parenthetical")
            if l2:
                if any(title == sec.title and s == sec.identifier.split('/s')[-1] and not n for title, s, n in l2):
                    agree.append("classification table")
                else:
                    return self._fail("UNKNOWN", f"source credits ({sec.cite}) and classification table "
                                      f"({l2[:3]}) disagree", candidates=[sec.cite], evidence=ev)
            flags = [] if agree else ["single source: source credits only"]
            return self._done("CODIFIED", sec, rel_path(loc), verified=bool(agree),
                              evidence=ev + [f"source credit: {loc.evidence}"] + [f"agrees: {a}" for a in agree],
                              flags=flags)
        if len(sections) > 1:
            if pnode is not None and pnode.id in sections:
                loc = next(l for l in codified if l.section_id == pnode.id)
                return self._done("CODIFIED", pnode, rel_path(loc), verified=True,
                                  evidence=ev + ["several Code sections credit this Act section; the drafted "
                                                 "parenthetical picks one"],
                                  flags=[f"Act section split over {len(sections)} Code sections"])
            cands = sorted(self.ix._node(s).cite for s in sections)
            return Resolution(outcome="SPLIT", release_point=self.ix.release_point, candidates=cands, evidence=ev,
                              reason=f"{t.cite_raw} is codified in {len(cands)} sections; the path {''.join(act_path) or '(none)'} "
                                     "does not pick one", flags=["needs review"])
        note_secs = {l.section_id for l in notes}
        if len(note_secs) == 1:
            loc = notes[0]
            sec = self.ix._node(loc.section_id)
            agree = []
            if paren.title and paren.note:
                anchor_sec = sec if sec.kind == "section" else self._first_section(sec)
                if anchor_sec is None or (paren.title, paren.section) != (
                        anchor_sec.identifier.split("/")[3][1:], anchor_sec.identifier.rsplit("/s", 1)[1]):
                    return self._fail("UNKNOWN", f"notes place {t.cite_raw} under {sec.cite} but the drafted "
                                      f"parenthetical says {paren.title} U.S.C. {paren.section} note",
                                      candidates=[f"{sec.cite} note"], evidence=ev)
                agree.append("drafted parenthetical")
            if l2 and any(n and title == sec.identifier.split("/")[3][1:] and s == sec.identifier.split("/s")[-1]
                          for title, s, n in l2):
                agree.append("classification table")
            return self._done("NOTE", sec, (), note_id=loc.note_id, verified=bool(agree),
                              evidence=ev + [f"note: {loc.evidence}"] + [f"agrees: {a}" for a in agree],
                              flags=[] if agree else ["single source: note text only"])
        if len(note_secs) > 1:
            return Resolution(outcome="SPLIT", release_point=self.ix.release_point,
                              candidates=sorted(f"{self.ix._node(s).cite} note" for s in note_secs), evidence=ev,
                              reason="the Act section's text appears in notes under several sections",
                              flags=["needs review"])
        # Nothing in the Code's own records. The drafted parenthetical alone is reported, unverified.
        if pnode is not None and not paren.et_seq:
            return self._done("NOTE" if paren.note else "CODIFIED", pnode, act_path, verified=False,
                              evidence=ev + ["only the drafted parenthetical names a location"],
                              flags=["unverified: parenthetical only", "needs review"])
        if paren.preceding and paren.title:
            return self._fail("UNKNOWN", f"drafted as a note preceding {paren.title} U.S.C. {paren.section}; no note "
                              "in the index carries this Act section", evidence=ev, flags=["needs review"])
        if l2:
            return self._fail("UNKNOWN", "only the classification table maps this Act section", evidence=ev,
                              candidates=[f"{a} U.S.C. {b}{' note' if n else ''}" for a, b, n in l2])
        return self._fail("UNCODIFIED", f"no Code section or note carries {t.cite_raw} at {self.ix.release_point}",
                          evidence=ev)


def classification_rows(fetcher, base: str, tables=("tbl119pl_1st.html", "tbl119pl_2nd.html")):
    from billmap.data import olrc
    rows = []
    for t in tables:
        rows += olrc.parse_classification_table(fetcher.get(f"{base}classification/{t}").text())
    return rows

