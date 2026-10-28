"""Parse -> resolve -> dry-run for one bill, producing per-section predictions for the oracle harness."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from billmap.data.index import Index, LookupError_
from billmap.dryrun.engine import NS, Engine, Result, Working, build_units, worst
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
            continue
        if res.section_id is not None:
            ident = ix._node(res.section_id).identifier
            by_section.setdefault(ident, []).append((ins, list(res.path), tr))
            tr.section = ident
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
    predictions, workings = [], {}
    for ident, items in by_section.items():
        try:
            node = baseline.by_identifier(ident)
            xml = baseline.section_xml(node)
        except LookupError_:
            xml = None
        work = Working(xml, ident, positive_law=ident.split("/")[3][1:] in resolver.positive)
        workings[ident] = work
        eng = Engine(work)
        statuses, stage, deterministic = [], None, True
        for ins, path, tr in items:
            if path == ["NEW"]:
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
                    else:
                        tr.result = Result(ins.id, "CLEAN", "new section added")
                else:
                    tr.result = Result(ins.id, "TARGET_MISSING", "section to add already exists at the baseline")
            elif any(f.startswith("delayed effective date") for f in ins.flags):
                # Not executed at the next release point: OLRC sets the amendment out in a note.
                why = next(f for f in ins.flags if f.startswith("delayed effective date"))
                tr.result = Result(ins.id, "WARN", f"not applied: {why}")
            else:
                tr.result = eng.run(ins, path)
            st = tr.result.status
            if tr.resolution.flags and "needs review" in tr.resolution.flags and st == "CLEAN":
                st = "WARN"
            statuses.append(st)
            if st not in ("CLEAN", "NOT_APPLICABLE") and stage is None:
                stage = STAGE.get(st, "engine") if "needs review" not in tr.resolution.flags else "resolver"
        status = worst(statuses)
        predictions.append(Prediction(identifier=ident, status="CLEAN" if status == "NOT_APPLICABLE" else status,
                                      text=work.render(), stage=stage, deterministic=deterministic))
    return BillRun(predictions, traces, workings)
