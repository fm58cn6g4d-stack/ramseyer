"""M8: run the pipeline on one draft and write its report: parse, resolve against the pinned release point, dry-run,
and render the comparative print (HTML in both styles, and Word). Used by `ramseyer analyze` and the local app.
Drafts never leave the machine."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from ramseyer import config
from ramseyer.comparative import html as print_html
from ramseyer.comparative import word as print_word


@dataclass
class Analysis:
    title: str
    release_point: str
    input_hash: str
    generated: str
    version: str
    counts: dict[str, int]          # status -> instructions
    committee_html: str
    working_html: str
    docx: bytes
    instructions: list[dict]        # one row per instruction: id, status, target, source, detail
    run: object = None              # the dry-run itself (BillRun), for callers that read the print's marks
    act: object = None              # instructions on Act text outside the Code, run on HOLC's compilations (ActBill)


def draft_text(name: str, data: bytes) -> str:
    """A draft's text: published bill XML (.xml) is rendered to text; .txt and .md are read as they are. Word
    drafts come with M7."""
    if name.lower().endswith(".xml"):
        import tempfile

        from ramseyer.parse.xmltext import render
        with tempfile.NamedTemporaryFile(suffix=".xml") as fh:
            fh.write(data)
            fh.flush()
            return render(Path(fh.name))
    if name.lower().endswith((".txt", ".md")):
        return data.decode("utf-8", errors="replace")
    raise ValueError("ramseyer reads .txt, .md and bill .xml drafts for now; Word drafts come with M7")


_resolver = None


def resolver():
    """The resolver against the pinned release point, built once per process (the app reuses it)."""
    global _resolver
    if _resolver is None:
        from ramseyer.data.http import Fetcher
        from ramseyer.data.index import Index
        from ramseyer.resolve import popular
        from ramseyer.resolve.actcode import classification_map
        from ramseyer.resolve.resolver import Resolver, classification_rows
        cfg = config.load()
        f = Fetcher(cfg)
        _resolver = Resolver(Index(cfg.index_path, cfg.release_pin), popular.load(),
                             classification_map(classification_rows(f, cfg.olrc_base)))
    return _resolver


def analyze(name: str, data: bytes) -> Analysis:
    from importlib.metadata import PackageNotFoundError, version

    from ramseyer.dryrun.predict import run_bill
    from ramseyer.parse import parse_text
    text = draft_text(name, data)
    r = resolver()
    instructions = parse_text(text).instructions
    run = run_bill(instructions, r, r.ix)
    try:
        ver = version("ramseyer")
    except PackageNotFoundError:
        ver = "dev"
    meta = dict(title=Path(name).name, release_point=r.ix.release_point, input_hash=hashlib.sha256(data).hexdigest(),
                generated=time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), version=ver)
    status = {}
    for tr in run.traces:
        if tr.result is not None:
            prev = status.get(tr.instruction.id)
            status[tr.instruction.id] = tr.result.status if prev in (None, "CLEAN") else prev
    rows = [{"id": i.id, "status": status.get(i.id, "UNPARSED" if i.op == "UNPARSED" else "NOT_EXECUTED"),
             "target": i.target.cite_raw, "source": i.source_text.strip()[:400],
             "detail": next((tr.result.detail for tr in run.traces if tr.instruction.id == i.id and tr.result), "")
             or i.reason or ""} for i in instructions]
    act = act_side(instructions, status, r)
    unplaced = place(rows, run, act)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    extra = dict(act=act, unplaced=unplaced)
    return Analysis(counts=counts, instructions=rows, run=run, act=act,
                    committee_html=print_html.report(run, style="committee", **meta, **extra),
                    working_html=print_html.report(run, style="working", **meta, **extra),
                    docx=print_word.document(run, style="committee", **meta, **extra), **meta)


def place(rows: list[dict], run, act) -> list[tuple[str, str, str]]:
    """Give each instruction row its place in the print and return the ones placed nowhere.

    `row["placed"]` is "code" (shown in a Code section), "act" (in the part "Act text not in the Code") or "none"
    (listed under "Instructions not placed", with its reason). An instruction the Code side could not execute and the
    Act side ran keeps that fact in its status: "ACT:<status>", checked against HOLC's compilation of the Act (its
    currency in the detail), not against the pinned release point and without the Code side's checks (review of
    #25). Every row gets exactly one place, so none is dropped."""
    code = {tr.instruction.id for tr in run.traces if tr.section and tr.result is not None}
    act_status: dict[str, str] = {}
    act_cur: dict[str, str] = {}
    if act is not None:
        for tr in act.traces:
            if tr.result is None:
                continue
            prev = act_status.get(tr.instruction.id)
            act_status[tr.instruction.id] = tr.result.status if prev in (None, "CLEAN") else prev
            act_cur[tr.instruction.id] = "; ".join(act.currency.get(tr.section, [])) or "currency unknown"
    reasons = {u.instruction_id: u.reason for u in (act.unplaced if act is not None else [])}
    unplaced = []
    for row in rows:
        if row["status"] == "NOT_EXECUTED" and row["id"] in act_status:
            row["status"] = "ACT:" + act_status[row["id"]]
            row["detail"] = f"on HOLC's compiled text of the Act (not in the Code), compilation {act_cur[row['id']]}"
            row["placed"] = "act"
        elif row["id"] in code:
            row["placed"] = "code"
        else:
            row["placed"] = "none"
            row["detail"] = reasons.get(row["id"], row["detail"])
            unplaced.append((row["status"], row["source"], row["detail"]))
    return unplaced


def act_side(instructions, status: dict, r):
    """The instructions the Code side could not execute that name an Act, run on HOLC's compiled text of that Act
    (M8a), or None when the compilations are not loaded (var/comps/comps.sqlite)."""
    from ramseyer.data.index import Index
    from ramseyer.dryrun.actside import run_bill_on_acts
    from ramseyer.resolve.cites import parse_parenthetical
    db = config.load().var / "comps" / "comps.sqlite"
    if not db.exists():
        return None
    todo = [i for i in instructions if status.get(i.id, "NOT_EXECUTED") == "NOT_EXECUTED"
            and (i.target.act or i.target.public_law) and i.op != "UNPARSED"]
    if not todo:
        return None
    return run_bill_on_acts(todo, lambda i: r._identities(i.target, parse_parenthetical(i.target.usc_parenthetical))[0],
                            Index(db, "comps"))


def write_report(a: Analysis, out: Path) -> list[Path]:
    """The report folder (docs/11-packaging.md): comparative prints, Word file, instruction list and run record."""
    out.mkdir(parents=True, exist_ok=True)
    files = {"comparative.html": a.committee_html, "comparative-working.html": a.working_html}
    for name, body in files.items():
        (out / name).write_text(body, encoding="utf-8")
    (out / "comparative.docx").write_bytes(a.docx)
    (out / "instructions.json").write_text(json.dumps(a.instructions, indent=1, ensure_ascii=False))
    (out / "run.json").write_text(json.dumps({"title": a.title, "release_point": a.release_point,
                                              "input_hash": a.input_hash, "generated": a.generated,
                                              "counts": a.counts}, indent=1))
    return sorted(out.iterdir())
