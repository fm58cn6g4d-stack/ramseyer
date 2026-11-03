"""M8: the comparative print as one HTML page, rendered from the dry-run (docs/07-comparative-print.md).

Two styles of the same marks:
- "working": struck text struck through, new text underlined, for one's own review;
- "committee": text to be omitted in black brackets, new matter in italics, unchanged law in roman (House Rule XIII,
  clause 3(e), as printed in a current report: records/verify-first.md, M8).

Two displays, chosen per section: an amended section is shown as a redline in context; a section the bill creates is
shown as structure and placement (its units, and the instruction that places it). Every instruction that is not CLEAN
carries a visible marker beside the section it concerns, with its status and reason.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from ramseyer.comparative.redline import Block, Unit, changed, redline

CSS = """
:root { --ink:#1b1b1b; --muted:#5b5b5b; --line:#d8d8d8; --warn:#8a5a00; --bad:#a1260d; --ok:#1d6b35; --paper:#fff; }
@media (prefers-color-scheme: dark) { :root { --ink:#e8e8e8; --muted:#a8a8a8; --line:#3a3a3a; --warn:#e0a948;
  --bad:#ff8a73; --ok:#7fd49a; --paper:#151515; } }
body { font: 16px/1.5 Georgia, 'Times New Roman', serif; color: var(--ink); background: var(--paper); margin: 0 auto;
  max-width: 54rem; padding: 1.5rem 1rem 4rem; }
header, .summary, .marker, .meta { font-family: system-ui, sans-serif; }
header h1 { font-size: 1.4rem; margin: 0 0 .25rem; } .meta { color: var(--muted); font-size: .85rem; }
.summary { border: 1px solid var(--line); border-radius: 6px; padding: .75rem 1rem; margin: 1rem 0 2rem; }
.summary span { margin-right: 1.25rem; } .clean { color: var(--ok); } .warn { color: var(--warn); } .bad { color: var(--bad); }
section.law { border-top: 1px solid var(--line); padding-top: 1rem; margin-top: 2rem; }
section.law h2 { font-size: 1.1rem; margin: 0 0 .5rem; }
.blk { margin: .2rem 0; } .stars { text-align: center; color: var(--muted); letter-spacing: .5rem; }
.working del { text-decoration: line-through; color: var(--bad); } .working ins { text-decoration: underline; color: var(--ok); }
.committee del { text-decoration: none; } .committee b.br { font-weight: bold; }
.committee ins { text-decoration: none; font-style: italic; }
.marker { border-left: 3px solid var(--warn); padding: .25rem .75rem; margin: .5rem 0; font-size: .9rem; }
.marker.bad { border-color: var(--bad); } h2.part { font-family: system-ui, sans-serif; margin-top: 3rem; } .placement { font-family: system-ui, sans-serif; font-size: .9rem; color: var(--muted); }
@media print { .summary { break-inside: avoid; } section.law { break-inside: auto; } }
"""

BROKEN = {"NOT_FOUND", "TARGET_MISSING", "UNPARSED", "NOT_EXECUTED", "CONFLICT", "STALE_BASELINE"}


@dataclass
class SectionView:
    identifier: str
    cite: str
    new: bool                     # created by the bill: shown as structure and placement
    tree: Unit | Block | None     # the redline
    notes: list[tuple[str, str, str]] = field(default_factory=list)   # (status, instruction text, reason)
    placement: str = ""


def cite_of(identifier: str) -> str:
    """"/us/usc/t42/s247b" -> "42 U.S.C. 247b"; anything else as it stands."""
    m = re.match(r"^/us/usc/t(\w+)/s([^/]+)", identifier)
    return f"{m.group(1)} U.S.C. {m.group(2)}" if m else identifier


def _mark(state: str, inner: str, style: str) -> str:
    """Omitted text in literal black brackets (so they survive copying) in the committee style; struck through in the
    working style. New matter in <ins>, set in italics or underlined by the style sheet."""
    if state == "del" and style == "committee":
        return f'<del><b class="br">[</b>{inner}<b class="br">]</b></del>'
    return f"<{state}>{inner}</{state}>"


def _runs(block: Block, style: str, flags: str = "") -> str:
    """A block's text with its marks. A block removed with a whole unit carries no brackets of its own: the unit's
    first line opens "[" and its last line closes "]" (`flags`), as committee reports print a removed unit."""
    if block.state == "del" and style == "committee":
        text = "".join(html.escape(r.text) for r in block.runs)
        o = '<b class="br">[</b>' if "open" in flags else ""
        c = '<b class="br">]</b>' if "close" in flags else ""
        return f"<del>{o}{text}{c}</del>"
    return "".join(html.escape(r.text) if r.state == "same" else _mark(r.state, html.escape(r.text), style)
                   for r in block.runs)


def layout(node, context: int, depth: int = 0, inherited: str = "same"):
    """The print's items in reading order, shared by the HTML and Word renders: (depth, Block) for a block to show;
    (depth, None) for "* * *" where units the bill does not touch are elided beyond `context` neighbours of a changed
    one; (depth, "open") and (depth, "close") around a unit removed whole."""
    if isinstance(node, Block):
        yield depth, node
        return
    if node.state != "same":
        whole = node.state == "del" and inherited != "del"
        if whole:
            yield depth, "open"
        for item in node.items:
            yield from layout(item, context, depth + (0 if isinstance(item, Block) else 1), node.state)
        if whole:
            yield depth, "close"
        return
    kids = node.items
    keep = [False] * len(kids)
    for i, k in enumerate(kids):
        if isinstance(k, Block) and k.kind in ("num", "heading", "text", "chapeau"):
            keep[i] = True
        if changed(k):
            for j in range(max(0, i - context), min(len(kids), i + context + 1)):
                keep[j] = True
    gap = False
    for k, show in zip(kids, keep):
        if show:
            yield from layout(k, context, depth + (0 if isinstance(k, Block) else 1))
            gap = False
        elif not gap:
            yield depth + 1, None
            gap = True


def lines(node, context: int) -> list[tuple[int, list[Block] | None, str]]:
    """`layout` gathered into printed lines: a unit's number, heading and the text that follows them on one line,
    "(a) Heading.—Text", as the Code and committee reports set them; None for "* * *". The third item says whether
    the line opens and/or closes a unit removed whole."""
    out: list[list] = []
    pending = ""
    for depth, b in layout(node, context):
        if b == "open":
            pending = "open"
        elif b == "close":
            if out:
                out[-1][2] += " close"
        elif b is None:
            if not (out and out[-1][1] is None):      # never two "* * *" lines in a row
                out.append([depth, None, ""])
        elif out and out[-1][1] is not None and out[-1][0] == depth and not pending and \
                b.kind in ("heading", "content", "chapeau") and out[-1][1][-1].kind in ("num", "heading") and \
                b.state == out[-1][1][-1].state:
            out[-1][1].append(b)
        else:
            out.append([depth, [b], pending])
            pending = ""
    return [(d, bs, f) for d, bs, f in out]


def _render(node, context: int, style: str = "committee") -> str:
    parts = []
    for depth, bs, flags in lines(node, context):
        if bs is None:
            parts.append('<div class="stars">* * *</div>')
            continue
        texts = [_runs(b, style) for b in bs]
        if style == "committee" and bs[0].state == "del":
            texts = [_runs(b, style, ("open" if i == 0 and "open" in flags else "") +
                           (" close" if i == len(bs) - 1 and "close" in flags else ""))
                     for i, b in enumerate(bs)]
        body = " ".join(t for t in texts if t.strip())
        if body.strip():
            parts.append(f'<div class="blk" style="margin-left:{1.5 * depth:.1f}rem">{body}</div>')
    return "".join(parts)


def views(run) -> list[SectionView]:
    """One view per section the bill touches, from a dry-run (ramseyer.dryrun.predict.BillRun)."""
    notes: dict[str, list] = {}
    for tr in run.traces:
        if tr.section and tr.result is not None and tr.result.status != "CLEAN":
            notes.setdefault(tr.section, []).append((tr.result.status, tr.instruction.source_text.strip(),
                                                     tr.result.detail or ""))
    out = []
    for ident, work in run.working.items():
        new = work.original is None
        tree = redline(work.original, None if work.removed else work.el)
        placement = ""
        if new:
            placing = [tr.instruction.source_text.strip() for tr in run.traces if tr.section == ident]
            placement = placing[0] if placing else ""
        if tree is None and not notes.get(ident):
            continue
        out.append(SectionView(ident, cite_of(ident), new, tree, notes.get(ident, []), placement))
    return sorted(out, key=lambda v: v.identifier)


def _section_html(v, marks: str, context: int, style: str, label: str | None = None) -> str:
    inner = _render(v.tree, context, style) if v.tree is not None else ""
    name = html.escape(label or v.cite)
    if v.new:
        place = f'<div class="placement">New section, placed as the bill directs: {html.escape(v.placement[:400])}' \
                f"</div>" if v.placement else ""
        return f'<section class="law new"><h2>{name} (new)</h2>{place}{marks}{inner}</section>'
    return f'<section class="law"><h2>{name}</h2>{marks}{inner}</section>'


def _marks(notes) -> str:
    return "".join(f'<div class="marker{" bad" if s in BROKEN else ""}"><b>{html.escape(s)}</b>: '
                   f"{html.escape(src[:300])}{' — ' + html.escape(why) if why else ''}</div>" for s, src, why in notes)


def report(run, *, title: str, release_point: str, input_hash: str, generated: str, version: str,
           style: str = "committee", context: int = 0, act=None, unplaced=()) -> str:
    """The comparative print as a standalone HTML page. `context`: unchanged neighbouring units shown beside a
    changed one (0, as committee reports print it: untouched units become "* * *").

    `act` (actside.ActBill): instructions on Act text the Code does not hold, applied to HOLC's compiled text and
    printed in their own part with each compilation's currency (plan contents 5). `unplaced`: (status, instruction,
    reason) for every instruction placed in neither the Code nor a compiled Act, listed at the end so none is
    dropped."""
    secs = views(run)
    statuses = [tr.result.status for tr in run.traces if tr.result is not None]
    clean = sum(s == "CLEAN" for s in statuses)
    broken = sum(s in BROKEN for s in statuses)
    review = len(statuses) - clean - broken
    head = (f"<header><h1>{html.escape(title)}</h1><div class=\"meta\">Checked against release point "
            f"{html.escape(release_point)} · input {html.escape(input_hash[:12])} · {html.escape(generated)} · "
            f"ramseyer {html.escape(version)}</div></header>")
    legend = ("existing law proposed to be omitted is enclosed in black brackets, new matter is printed in italics, "
              "and existing law in which no change is proposed is shown in roman" if style == "committee" else
              "struck text is struck through, new text is underlined")
    summary = (f'<div class="summary"><span class="clean">{clean} clean</span><span class="warn">{review} need '
               f'review</span><span class="bad">{broken} could not be applied</span><div class="meta">'
               f"{html.escape(legend)}</div></div>")
    body = [_section_html(v, _marks(v.notes), context, style) for v in secs]
    if act is not None and act.working:
        body.append('<h2 class="part">Act text not in the Code</h2><div class="meta">From the House Office of the '
                    "Legislative Counsel's compilation of each Act; each section shows the compilation's currency."
                    "</div>")
        for v in views(act):
            cur = "; ".join(act.currency.get(v.identifier, [])) or "currency unknown"
            body.append(_section_html(v, f'<div class="meta">Compilation {html.escape(cur)}</div>' + _marks(v.notes),
                                      context, style, act.labels.get(v.identifier)))
    if unplaced:
        rows = "".join(f'<div class="marker bad"><b>{html.escape(s)}</b>: {html.escape(src[:300])}'
                       f"{' — ' + html.escape(why) if why else ''}</div>" for s, src, why in unplaced)
        body.append(f'<section class="law"><h2>Instructions not placed</h2>{rows}</section>')
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
            f"content=\"width=device-width, initial-scale=1\"><title>Comparative print</title><style>{CSS}</style>"
            f"</head><body class=\"{style}\">{head}{summary}{''.join(body)}</body></html>")
