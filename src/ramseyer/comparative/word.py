"""M8: the comparative print as a Word document (python-docx), with real formatting so it can be pasted into a
committee document: in the committee style, omitted text in bold black brackets and new matter in italics; in the
working style, struck-through and underlined text. Built from the same lines as the HTML (html.lines)."""
from __future__ import annotations

import io

from docx import Document
from docx.shared import Pt

from ramseyer.comparative.html import BROKEN, act_parts, lines, views


def _add_runs(par, block, style: str, flags: str = "") -> None:
    if block.state == "del" and style == "committee":
        if "open" in flags:
            par.add_run("[").bold = True
        par.add_run("".join(r.text for r in block.runs))
        if "close" in flags:
            par.add_run("]").bold = True
        return
    for r in block.runs:
        if r.state == "same":
            par.add_run(r.text)
        elif r.state == "del" and style == "committee":
            par.add_run("[").bold = True
            par.add_run(r.text)
            par.add_run("]").bold = True
        elif r.state == "del":
            par.add_run(r.text).font.strike = True
        elif style == "committee":
            par.add_run(r.text).italic = True
        else:
            par.add_run(r.text).underline = True


def document(run, *, title: str, release_point: str, input_hash: str, generated: str, version: str,
             style: str = "committee", context: int = 0, act=None, unplaced=()) -> bytes:
    doc = Document()
    doc.styles["Normal"].font.name = "Times New Roman"
    doc.styles["Normal"].font.size = Pt(12)
    doc.add_heading(title, level=1)
    doc.add_paragraph(f"Checked against release point {release_point} · input {input_hash[:12]} · {generated} · "
                      f"ramseyer {version}")
    statuses = [tr.result.status for tr in run.traces if tr.result is not None]
    clean = sum(s == "CLEAN" for s in statuses)
    broken = sum(s in BROKEN for s in statuses)
    doc.add_paragraph(f"{clean} clean · {len(statuses) - clean - broken} need review · {broken} could not be applied")
    doc.add_paragraph("Existing law proposed to be omitted is enclosed in black brackets, new matter is printed in "
                      "italics, and existing law in which no change is proposed is shown in roman." if style ==
                      "committee" else "Struck text is struck through; new text is underlined.")
    def section(v, label=None, currency=None):
        doc.add_heading((label or v.cite) + (" (new)" if v.new else ""), level=2)
        if currency is not None:
            doc.add_paragraph(currency)
        if v.new and v.placement:
            doc.add_paragraph(f"New section, placed as the bill directs: {v.placement[:400]}")
        for status, src, why in v.notes:
            doc.add_paragraph(f"{status}: {src[:300]}" + (f" — {why}" if why else ""))
        if v.tree is None:
            return
        for depth, bs, flags in lines(v.tree, context):
            par = doc.add_paragraph()
            par.paragraph_format.left_indent = Pt(18 * depth)
            if bs is None:
                par.add_run("*       *       *")
                continue
            for i, b in enumerate(bs):
                if i:
                    par.add_run(" ")
                _add_runs(par, b, style, ("open" if i == 0 and "open" in flags else "") +
                          (" close" if i == len(bs) - 1 and "close" in flags else ""))
    for v in views(run):
        section(v)
    for part, intro, vs in act_parts(act):
        doc.add_heading(part, level=1)
        doc.add_paragraph(intro)
        for v in vs:
            cur = "; ".join(act.currency.get(v.identifier, [])) or "currency unknown"
            where = act.notes.get(v.identifier)
            section(v, act.labels.get(v.identifier),
                    (f"Set out as a note under {where.removesuffix(' note')}; compilation " if where else "Compilation ")
                    + cur)
    if unplaced:
        doc.add_heading("Instructions not placed", level=1)
        for status, src, why in unplaced:
            doc.add_paragraph(f"{status}: {src[:300]}" + (f" — {why}" if why else ""))
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
