"""Draft parser: text -> IR (docs/04-draft-parser.md)."""
from __future__ import annotations

import re

from billmap.parse.effective import flag_delayed
from billmap.parse.grammar import CONFIDENCE_THRESHOLD, Ctx, freestanding_type, parse_unit_text, quote_free
from billmap.parse.ir import Instruction, Node, ParseResult
from billmap.parse.normalize import normalize
from billmap.parse.ops import count_ops
from billmap.parse.segment import Segmenter

AMEND_WORDS = re.compile(r"\b(?:amended|amending|repealed)\b")


def parse_text(text: str) -> ParseResult:
    norm = normalize(text)
    roots = Segmenter(norm).run()
    instructions: list[Instruction] = []
    counts: dict[str, int] = {}

    def visit(node: Node, ctx: Ctx | None) -> None:
        if node.level == "section":
            ctx = Ctx()
        child_ctx = ctx
        if node.cls != "TABLE_OF_CONTENTS" and node.text and ctx is not None:
            qf = quote_free(node.text)
            n = count_ops(qf)
            if n:
                counts[node.loc] = counts.get(node.loc, 0) + n
            ops, child_ctx = parse_unit_text(node, ctx)
            instructions.extend(ops)
            if n or AMEND_WORDS.search(qf):
                node.cls = "AMENDATORY"
            elif node.cls != "STRUCTURAL" or node.text:
                node.cls = "FREESTANDING"
                node.freestanding_type = freestanding_type(node.text)
        for c in node.children:
            visit(c, child_ctx)

    for r in roots:
        visit(r, None)
    flag_delayed(roots, instructions)
    total = len(instructions)
    parsed = sum(1 for i in instructions if i.op != "UNPARSED" and i.confidence >= CONFIDENCE_THRESHOLD)
    return ParseResult(instructions=instructions, nodes=roots, counts=counts,
                       coverage=round(parsed / total, 4) if total else 1.0)
