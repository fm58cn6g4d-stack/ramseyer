"""Parse -> resolve -> dry-run for one bill, producing per-section predictions for the oracle harness."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from billmap.data.index import Index, LookupError_
from billmap.dryrun.engine import NS, Engine, Result, Working, build_units, worst
from billmap.dryrun.verify import structure_problems, unapplied_mentions
from billmap.oracle.harness import Prediction
from billmap.parse.ir import Instruction
from billmap.resolve.resolver import Resolution, Resolver

RESTATEMENT = 10        # more new sections than this from one instruction: a restatement (codification)
STAGE = {"UNPARSED": "parser", "TARGET_MISSING": "engine", "NOT_FOUND": "engine", "AMBIGUOUS": "engine",
         "CONFLICT": "engine", "STALE_BASELINE": "engine", "WARN": "engine"}


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


def run_bill(instructions: list[Instruction], resolver: Resolver, baseline: Index) -> BillRun:
    """Instructions in bill order -> one Prediction per Code section they reach (text at `baseline` + edits)."""
    ix = resolver.ix
    by_section: "OrderedDict[str, list[tuple[Instruction, list[str], Trace]]]" = OrderedDict()
    traces: list[Trace] = []
    for ins in instructions:
        res = resolver.resolve(ins.target)
        tr = Trace(ins, res)
        traces.append(tr)
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

    # Instructions that reached the Code somewhere (or edit only a table of contents); the rest are unapplied.
    applied = {tr.instruction.id for tr in traces if tr.section is not None or tr.instruction.op == "CONFORM_TOC"
               or tr.resolution.outcome in ("CODIFIED", "NOTE")}
    current_title = [""]
    predictions, workings = [], {}
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
            elif any(f.startswith("delayed effective date") for f in ins.flags):
                # Not executed at the next release point: OLRC sets the amendment out in a note.
                why = next(f for f in ins.flags if f.startswith("delayed effective date"))
                tr.result = Result(ins.id, "WARN", f"not applied: {why}")
            else:
                eng.act_ref = act_refs(ins) if ins.target.kind in ("act", "pl") else None
                tr.result = eng.run(ins, path)
            st = tr.result.status
            if tr.resolution.flags and "needs review" in tr.resolution.flags and st == "CLEAN":
                st = "WARN"
            statuses.append(st)
            if st not in ("CLEAN", "NOT_APPLICABLE") and stage is None:
                stage = STAGE.get(st, "engine") if "needs review" not in tr.resolution.flags else "resolver"
        status = worst(statuses)
        if status == "CLEAN":
            problems = structure_problems(work) + unapplied_mentions(ident, instructions, applied, work)
            if problems:
                status, stage = "WARN", "verify"
                traces.append(Trace(items[0][0], items[0][2].resolution, ident,
                                    Result(items[0][0].id, "WARN", "self-check: " + "; ".join(problems))))
        predictions.append(Prediction(identifier=ident, status="CLEAN" if status == "NOT_APPLICABLE" else status,
                                      text=work.render(), stage=stage, deterministic=deterministic))
    return BillRun(predictions, traces, workings)
