"""Parse -> resolve -> dry-run for one bill, producing per-section predictions for the oracle harness."""
from __future__ import annotations

import copy
import re
import sqlite3
from collections import OrderedDict
from dataclasses import dataclass, field

from ramseyer.data.index import Index, LookupError_
from lxml import etree

from ramseyer.data.indexer import text_of
from ramseyer.dryrun.engine import NS, Engine, Result, Working, build_units, fold, nested_to_double, worst
from ramseyer.dryrun.verify import structure_problems, unapplied_mentions
from ramseyer.oracle.harness import Prediction
from ramseyer.parse.grammar import quote_free
from ramseyer.parse.ir import Instruction, Target
from ramseyer.resolve.cites import parse_parenthetical
from ramseyer.resolve.resolver import Resolution, Resolver

TEXT_OPS = ("STRIKE_INSERT", "STRIKE", "INSERT_AFTER", "INSERT_BEFORE", "STRIKE_THROUGH")
RESTATEMENT = 10        # more new sections than this from one instruction: a restatement (codification)
STAGE = {"UNPARSED": "parser", "TARGET_MISSING": "engine", "NOT_FOUND": "engine", "AMBIGUOUS": "engine",
         "CONFLICT": "engine", "STALE_BASELINE": "engine", "WARN": "engine", "ALREADY_EXECUTED": "engine"}


@dataclass
class Trace:
    instruction: Instruction
    resolution: Resolution
    section: str | None = None
    result: Result | None = None


@dataclass
class BillRun:
    predictions: list[Prediction]
    traces: list[Trace] = field(default_factory=list)
    working: dict[str, Working] = field(default_factory=dict)     # identifier -> amended working copy


def run_bill(instructions: list[Instruction], resolver: Resolver, baseline: Index,
             prior: list[Index] = ()) -> BillRun:
    """Instructions in bill order -> one Prediction per Code section they reach (text at `baseline` + edits).
    `prior`: earlier release points, searched when quoted text is not found (STALE_BASELINE)."""
    ix = resolver.ix
    by_section: "OrderedDict[str, list[tuple[Instruction, list[str], Trace]]]" = OrderedDict()
    traces: list[Trace] = []
    fanned: dict[str, list[str]] = {}            # instruction id -> statuses in the sections it reached

    def fan_out(ins: Instruction, res: Resolution, tr: Trace, sections: list[str] | None = None,
                where: str | None = None) -> None:
        """Apply a unit-wide (or Act-wide) text edit to each section of the unit that contains the struck words."""
        needle = fold(nested_to_double(ins.find), True)[0]
        hits = []
        if sections is None:
            try:
                unit = baseline.by_identifier(ix._node(res.node_id).identifier)
            except LookupError_:
                tr.result = Result(ins.id, "TARGET_MISSING", f"{ix._node(res.node_id).identifier} is not in the "
                                   "baseline")
                return
            where, stack, sections = res.cite or unit.identifier, [unit], []
            while stack:
                n = stack.pop()
                if n.kind == "section":
                    sections.append(n.identifier)
                else:
                    stack.extend(baseline.children(n))
        for ident in sections:
            try:
                xml = baseline.section_xml(baseline.by_identifier(ident))
            except LookupError_:
                continue
            if needle in fold(text_of(etree.fromstring(xml.encode())), True)[0]:
                hits.append(ident)
        if not hits:
            tr.result = Result(ins.id, "NOT_FOUND", f"no section of {where} contains “{ins.find[:60]}”")
        elif ins.occurrence != "each" and len(hits) > 1:
            tr.result = Result(ins.id, "AMBIGUOUS", f"{len(hits)} sections of {where} contain “{ins.find[:60]}” and "
                               "the instruction names no single place", matches=len(hits))
        else:
            fanned[ins.id] = []
            for ident in sorted(hits):
                by_section.setdefault(ident, []).append((ins, ["FAN"], tr))
            tr.section = sorted(hits)[0]

    for ins in instructions:
        res = resolver.resolve(ins.target)
        tr = Trace(ins, res)
        traces.append(tr)
        if "rule of application, not an amendment" in ins.flags:
            tr.result = Result(ins.id, "NOT_EXECUTED", "a rule of application (“shall be applied by substituting …”), "
                               "not an amendment: the Code text is unchanged")
            continue
        t = ins.target
        if res.outcome == "UNKNOWN" and t.kind in ("act", "pl") and not t.section and ins.op in TEXT_OPS and ins.find \
                and unit_wide(ins):
            # "The Placeholder Act is amended by striking “Administrator” each place it appears and inserting
            # “Director”": the sections the Code credits to that Act.
            ids, _ = resolver._identities(t, parse_parenthetical(t.usc_parenthetical))
            secs = sorted(ix._node(i).identifier for i in resolver.acts.sections_of(ids))
            if secs:
                fan_out(ins, res, tr, secs, f"the sections of {t.act or t.public_law}")
                continue
        if res.outcome != "CODIFIED":
            # A new section numbered in a positive-law title ("§ 2069.") is placed by its number even when the unit
            # it is added to does not resolve ("Subtitle VII of chapter 20" for the Code's subchapter VII).
            if ins.target.kind == "usc" and ins.target.title in resolver.positive and ins.new_text and \
                    ins.op in ("ADD_END", "ADD_UNIT_AFTER", "ADD_UNIT_BEFORE"):
                for u in build_units(ins.new_text, True)[0]:
                    if u.tag == NS + "section":
                        ident = f"/us/usc/t{ins.target.title}/s{u.find('{*}num').get('value')}"
                        by_section.setdefault(ident, []).append((ins, ["NEW", "UNPLACED"], tr))
                        tr.section = ident
            continue
        if res.section_id is not None:
            ident = ix._node(res.section_id).identifier
            by_section.setdefault(ident, []).append((ins, list(res.path), tr))
            tr.section = ident
            continue
        # A repealed chapter (subchapter, part) repeals each section in it at the baseline.
        if res.node_id is not None and ins.op == "REPEAL":
            try:
                unit = baseline.by_identifier(ix._node(res.node_id).identifier)
            except LookupError_:
                unit = None
            stack = [unit] if unit is not None else []
            while stack:
                n = stack.pop()
                if n.kind == "section":
                    by_section.setdefault(n.identifier, []).append((ins, ["REPEAL_ALL"], tr))
                    tr.section = n.identifier
                else:
                    stack.extend(baseline.children(n))
            continue
        # A text edit to a whole chapter or title ("Chapter 1 ... is amended by striking “Board” each place it appears
        # and inserting “Commission”"): every section of the unit at the baseline that contains the words.
        if res.node_id is not None and ins.op in TEXT_OPS and ins.find:
            if unit_wide(ins):
                fan_out(ins, res, tr)
            else:
                tr.result = Result(ins.id, "NOT_EXECUTED", f"resolved to {res.cite or 'a whole unit'}, but the "
                                   "instruction names a narrower place the parser did not place; not applied "
                                   "unit-wide")
            continue
        # A title or chapter target: instructions that add whole sections create new section predictions.
        if res.node_id is not None and ins.new_text and ins.op in ("ADD_END", "ADD_UNIT_AFTER", "ADD_UNIT_BEFORE"):
            title = ix._node(res.node_id).identifier.split("/")[3]
            units, _ = build_units(ins.new_text, title[1:] in resolver.positive)
            for u in units:
                if u.tag == NS + "section":
                    ident = f"/us/usc/{title}/s{u.find('{*}num').get('value')}"
                    by_section.setdefault(ident, []).append((ins, ["NEW"], tr))
                    tr.section = ident
    cache: dict[tuple, tuple[str, str, bool] | None] = {}

    def act_refs(ins: Instruction):
        """Bare "section 407(d)(6)" in text inserted into an Act: the same Act's section. Translated when the resolver
        is sure, or has one witness (source credits; the engine then reports WARN); otherwise left as drafted."""
        def lookup(sec: str, here: str) -> tuple[str, str, bool] | None:
            key = (ins.target.act, ins.target.public_law, sec, here)
            if key not in cache:
                t = ins.target.model_copy(deep=True)
                t.section, t.path, t.cite_raw, t.usc_parenthetical, t.qualifiers = sec, [], f"section {sec}", None, []
                r = resolver.resolve(t)
                cache[key] = None
                weak = r.flags == ["single source: source credits only"]
                if r.outcome == "CODIFIED" and r.section_id is not None and (r.verified and not r.flags or weak):
                    title, s = ix._node(r.section_id).identifier.split("/")[3:5]
                    cache[key] = (s[1:], " of this title" if title == here else f" of title {title[1:]}", weak)
            return cache[key]
        return lambda sec: lookup(sec, current_title[0])

    # An Act-wide edit that reached no section ("The Placeholder Act is amended by striking “Administrator” each
    # place it appears"): every section the Code credits to that Act may be affected.
    act_wide: dict[str, list[Instruction]] = {}
    for tr in traces:
        t = tr.instruction.target
        if tr.section is None and t.kind == "unknown" and tr.instruction.op == "REPEAL" and t.cite_raw:
            # A listed repeal item naming a whole Act: "(1) The Atomic Energy Defense Act (50 U.S.C. 2501 et seq.)."
            m = re.match(r"^\(?\w*\)?\s*(?:The |the )?(?P<act>[A-Z][^()]*?(?:Act|Code)(?: of \d{4})?)\s*(?:\((?P<p>[^()]*)\))?",
                         t.cite_raw)
            if m:
                t = Target(kind="act", act=m["act"].strip(), usc_parenthetical=m["p"], cite_raw=t.cite_raw)
        if tr.section is None and t.kind in ("act", "pl") and not t.section and tr.instruction.op in TEXT_OPS + (
                "REPEAL",):
            ids, _ = resolver._identities(t, parse_parenthetical(t.usc_parenthetical))
            for sid in resolver.acts.sections_of(ids):
                act_wide.setdefault(ix._node(sid).identifier, []).append(tr.instruction)
    # Instructions that reached the Code somewhere (or edit only a table of contents); the rest are unapplied.
    applied = {tr.instruction.id for tr in traces if tr.section is not None or tr.instruction.op == "CONFORM_TOC"
               or tr.resolution.outcome in ("CODIFIED", "NOTE")}
    current_title = [""]
    predictions, workings, pending = [], {}, []
    for ident, items in by_section.items():
        try:
            node = baseline.by_identifier(ident)
            xml = baseline.section_xml(node)
        except LookupError_:
            xml = None
        work = Working(xml, ident, positive_law=ident.split("/")[3][1:] in resolver.positive)
        workings[ident] = work
        current_title[0] = ident.split("/")[3]
        eng = Engine(work)
        statuses, stage, deterministic = [], None, True
        for ins, path, tr in items:
            if path == ["REPEAL_ALL"]:
                work.removed = True
                tr.result = Result(ins.id, "WARN", "repealed with the unit that contains it; the Code sets out "
                                   "a repealed section as a stub or removes it")
            elif path[:1] == ["NEW"]:
                units, _ = build_units(ins.new_text, work.positive_law)
                sec = next(u for u in units if u.tag == NS + "section" and
                           f"/s{u.find('{*}num').get('value')}" == ident[ident.rfind('/s'):])
                sec.set("identifier", ident)
                if work.el is None:
                    work.el, work.removed = sec, False
                    n_new = sum(1 for u in units if u.tag == NS + "section")
                    if n_new > RESTATEMENT:
                        # A codification enacts many sections at once; the bill's other amendments to the source
                        # provisions may be carried into them (10 U.S.C. 6101 ff., Pub. L. 119-60 sec. 3111).
                        tr.result = Result(ins.id, "WARN", f"new section, one of {n_new} enacted by one instruction "
                                           "(a restatement): amendments elsewhere in the bill to the restated "
                                           "provisions are not carried into it")
                    elif path[1:] == ["UNPLACED"]:
                        tr.result = Result(ins.id, "WARN", f"new section added by its number; the unit it is added "
                                           f"to did not resolve: {tr.resolution.reason or ins.target.cite_raw}")
                    else:
                        tr.result = Result(ins.id, "CLEAN", "new section added")
                else:
                    tr.result = Result(ins.id, "TARGET_MISSING", "section to add already exists at the baseline")
            elif path == ["FAN"]:
                r = eng.run(ins, [])
                if r.status == "CLEAN":
                    r.status, r.detail = "WARN", "; ".join(x for x in (r.detail, "a unit-wide or Act-wide edit, "
                                                                       "applied section by section") if x)
                fanned[ins.id].append(r.status)
                tr.result = r
            elif any(f.startswith("delayed effective date") for f in ins.flags):
                # Takes effect later: OLRC sets it out in a note until then, so the predicted text stays as it is.
                # The edit is still dry-run on a copy, so a quote that is not there is reported (red team F7).
                why = next(f for f in ins.flags if f.startswith("delayed effective date"))
                probe = Engine(copy.deepcopy(work))
                probe.act_ref = act_refs(ins) if ins.target.kind in ("act", "pl") else None
                r = probe.run(ins, path)
                tr.result = Result(ins.id, "WARN" if r.status == "CLEAN" else r.status,
                                   f"not applied now ({why}); "
                                   + ("the edit applies cleanly to the current text" if r.status == "CLEAN"
                                      else f"checked against the current text: {r.detail}"))
            else:
                eng.act_ref = act_refs(ins) if ins.target.kind in ("act", "pl") else None
                tr.result = eng.run(ins, path)
                if tr.result.status == "NOT_FOUND" and ins.find and prior:
                    tr.result = stale_or(tr.result, ins, ident, prior)
            st = tr.result.status
            if st == "CLEAN" and any(f == "needs review" or f.startswith("single source") or
                                     f.startswith("unverified") for f in tr.resolution.flags):
                # One witness for the target (source credits, or the drafted parenthetical alone) is not enough for
                # a confident answer (red team F10).
                st = "WARN"
                tr.result.status = "WARN"
                tr.result.detail = "; ".join(x for x in (tr.result.detail, "target resolved on one witness: "
                                                         + ", ".join(tr.resolution.flags)) if x)
            statuses.append(st)
            if st not in ("CLEAN", "NOT_APPLICABLE") and stage is None:
                stage = STAGE.get(st, "engine") if "needs review" not in tr.resolution.flags else "resolver"
        pending.append((ident, work, items, worst(statuses), stage, deterministic))
    # Self-checks run once every section has been dry-run: an instruction placed (and failed) in one section may
    # name another ("by transferring paragraph (5) to appear as subsection (b) of section 564", 14 U.S.C. 564).
    failed = applied - {tr.instruction.id for tr in traces if tr.result is not None and
                        tr.result.status in ("CLEAN", "WARN", "NOT_APPLICABLE")}
    for ident, work, items, status, stage, deterministic in pending:
        if status == "CLEAN":
            problems = structure_problems(work) + unapplied_mentions(ident, instructions, applied - failed, work) + \
                [f"the Act-wide instruction {i.id} ({'repeals the Act' if i.op == 'REPEAL' else i.op}) was not "
                 "executed and may change this section"
                 f"{' (it contains “' + i.find[:40] + '”)' if i.find else ''}" for i in act_wide.get(ident, [])
                 if not i.find or fold(i.find, True)[0] in fold(work.render() or "", True)[0]]
            problems = [p for p in problems if not any(f"instruction {ins.id} " in p for ins, _, _ in items)]
            if problems:
                status, stage = "WARN", "verify"
                traces.append(Trace(items[0][0], items[0][2].resolution, ident,
                                    Result(items[0][0].id, "WARN", "self-check: " + "; ".join(problems))))
        if status == "CLEAN" and (bad := edition_diff(baseline, ident)):
            # OLRC's XML and XHTML editions differ on this section's content (19 U.S.C. 2702(b)'s country list):
            # the text the edit was checked against may be incomplete (red team F13).
            status, stage = "WARN", "verify"
            traces.append(Trace(items[0][0], items[0][2].resolution, ident,
                                Result(items[0][0].id, "WARN", f"source text in doubt: {bad}")))
        predictions.append(Prediction(identifier=ident, status="CLEAN" if status == "NOT_APPLICABLE" else status,
                                      text=work.render(), stage=stage, deterministic=deterministic,
                                      release_point=baseline.release_point))
    for tr in traces:
        if tr.instruction.id in fanned and fanned[tr.instruction.id]:
            sts = fanned[tr.instruction.id]
            tr.result = Result(tr.instruction.id, worst(sts), f"applied to {len(sts)} section(s) containing the "
                               "words", matches=len(sts))
        elif tr.result is None:
            tr.result = Result(tr.instruction.id, "NOT_EXECUTED", not_executed_reason(tr))
    return BillRun(predictions, traces, workings)


# A location of the instruction's own ("in subparagraph (A)", "in the chapter heading", "the item relating to"):
# a unit-wide reading would be wrong.
OWN_PLACE = re.compile(r"\b(?:[Ii]n|[Oo]f|[Ff]or|[Uu]nder) (?:the )?(?:(?:sub)?sections?|paragraphs?|subparagraphs?|clauses?|"
                       r"subclauses?|items?|subitems?)\s*[\d(]|\bheading\b|\bsuch section\b|\btable\b|"
                       r"\bitem relating\b|\bdeemed\b|\bsentence\b|\bmatter (?:preceding|following)\b|\bcolumn\b")


def unit_wide(ins: Instruction) -> bool:
    """A text edit is applied across a whole chapter, title or Act only when the instruction says so: it names no
    narrower place of its own, and it either reaches "each place it appears" or itself names the unit."""
    own = quote_free(ins.source_text or "")
    if OWN_PLACE.search(own):
        return False
    return ins.occurrence == "each" or bool(ins.target.cite_raw and ins.target.cite_raw in (ins.source_text or ""))


def stale_or(r: Result, ins: Instruction, ident: str, prior: list[Index]) -> Result:
    """NOT_FOUND, or STALE_BASELINE when an earlier release point has the quoted text: the draft may have been
    written against older text that a later law changed (docs/06-dry-run.md)."""
    needle = fold(nested_to_double(ins.find), True)[0]
    for ix in prior:
        try:
            xml = ix.section_xml(ix.by_identifier(ident))
        except LookupError_:
            continue
        if needle in fold(text_of(etree.fromstring(xml.encode())), True)[0]:
            return Result(ins.id, "STALE_BASELINE", f"“{ins.find[:60]}” is not in the current text but was at release "
                          f"point {ix.release_point}: the draft may predate a later amendment", matches=0)
    return r


def edition_diff(ix: Index, ident: str) -> str | None:
    try:
        node = ix.by_identifier(ident)
        row = ix.db.execute("SELECT kind, detail FROM edition_diffs WHERE node_id=? AND kind<>'rendering'",
                            (node.id,)).fetchone()
    except (LookupError_, sqlite3.OperationalError):
        return None
    return f"OLRC's XML and XHTML editions differ ({row[0]}): {row[1][:120]}" if row else None


def not_executed_reason(tr: Trace) -> str:
    """Why an instruction reached no Code section text (it still gets a status: nothing is dropped)."""
    res, ins = tr.resolution, tr.instruction
    if ins.op == "UNPARSED":
        return ins.reason or "the parser could not read the instruction"
    if res.outcome == "NOTE":
        return f"amends Act text set out in a note ({res.cite or ''} note); notes are not dry-run"
    if res.outcome == "CODIFIED":
        return f"{ins.op} on {res.cite or 'a unit above the section level'} is not executed by the engine"
    return f"{res.outcome}: {res.reason or 'no Code location'}"
