"""M8: the comparative print as a Word document (python-docx), with real formatting so it can be pasted into a
committee document: in the committee style, omitted text in bold black brackets and new matter in italics; in the
working style, struck-through and underlined text. Built from the same lines as the HTML (html.lines)."""
from __future__ import annotations

import io

from docx import Document
from docx.shared import Pt

from ramseyer.comparative.html import BROKEN, lines, views


def _add_runs(par, block, style: str) -> None:
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
             style: str = "committee", context: int = 1) -> bytes:
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
    for v in views(run):
        doc.add_heading(v.cite + (" (new)" if v.new else ""), level=2)
        if v.new and v.placement:
            doc.add_paragraph(f"New section, placed as the bill directs: {v.placement[:400]}")
        for status, src, why in v.notes:
            doc.add_paragraph(f"{status}: {src[:300]}" + (f" — {why}" if why else ""))
        if v.tree is None:
            continue
        for depth, bs in lines(v.tree, context):
            par = doc.add_paragraph()
            par.paragraph_format.left_indent = Pt(18 * depth)
            if bs is None:
                par.add_run("*       *       *")
                continue
            for i, b in enumerate(bs):
                if i:
                    par.add_run(" ")
                _add_runs(par, b, style)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
