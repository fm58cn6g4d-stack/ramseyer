"""Draft parser: text -> IR (docs/04-draft-parser.md)."""
from __future__ import annotations

import re

from ramseyer.parse.effective import flag_delayed
from ramseyer.parse.grammar import (CONFIDENCE_THRESHOLD, REFERENCES_CLAUSE, Ctx, freestanding_type, parse_unit_text,
                                   quote_free)
from ramseyer.parse.ir import Instruction, Node, ParseResult
from ramseyer.parse.normalize import normalize
from ramseyer.parse.ops import AMENDED, OPEN_HEAD, count_ops
from ramseyer.parse.segment import LEVEL_PREFIX, Segmenter

AMEND_WORDS = re.compile(r"\b(?:amended|amending|repealed)\b")


def references_clauses(roots: list[Node]) -> list[tuple[str, str]]:
    """(scope prefix, Act or "title N") for each references clause: "wherever in this title an amendment ... is expressed in
    terms of an amendment to ... a section ..., the reference shall be considered to be made to ... of the Social
    Security Act" covers the bill title that holds it ("titleI."); "this Act" covers the whole bill ("")."""
    out = []

    def walk(n: Node) -> None:
        m = REFERENCES_CLAUSE.search(lift_free(n.text))
        if m:
            scope, parts = m["scope"].lower(), n.loc.split(".")
            prefix = ""
            if scope != "act":
                lead = LEVEL_PREFIX.get(scope, "sec" if scope == "section" else scope)
                k = next((i for i, p in enumerate(parts) if p.startswith(lead) and p[len(lead):][:1].isalnum()), None)
                if k is None:
                    return
                prefix = ".".join(parts[:k + 1]) + "."
            out.append((prefix, f"title {m['title']}" if m["title"] else re.sub(r"^the ", "", m["act"]).strip()))
        for c in n.children:
            walk(c)

    for r in roots:
        walk(r)
    return out


def default_act(defaults: list[tuple[str, str]], loc: str) -> str | None:
    """The Act of the narrowest references clause covering a bill location."""
    hits = [(len(p), act) for p, act in defaults if (loc + ".").startswith(p)]
    return max(hits)[1] if hits else None


def lift_free(text: str) -> str:
    return text if "\u201c" not in text else quote_free(text)


def parse_text(text: str) -> ParseResult:
    norm = normalize(text)
    roots = Segmenter(norm).run()
    instructions: list[Instruction] = []
    counts: dict[str, int] = {}
    defaults = references_clauses(roots)

    bill_memory: dict = {}      # the Code unit named last, for "Such subchapter is further amended" in a later section

    def visit(node: Node, ctx: Ctx | None, parent_text: str = "") -> None:
        if node.level == "section":
            ctx = Ctx()
            if bill_memory.get("usc") is not None:
                ctx.memory["prior_usc"] = bill_memory["usc"]
            act = default_act(defaults, node.loc)
            if act:
                ctx.memory["default_act"] = act
        child_ctx = ctx
        if node.cls != "TABLE_OF_CONTENTS" and node.text and ctx is not None:
            qf = quote_free(node.text)
            n = count_ops(qf)
            if n:
                counts[node.loc] = counts.get(node.loc, 0) + n
            ops, child_ctx = parse_unit_text(node, ctx)
            if not ops and not node.children and (AMENDED.search(qf) or OPEN_HEAD.search(quote_free(parent_text))):
                # "is amended so as to strike …", or an item under "… is—" ("(1) transferred to the end of section
                # 2810"), with no verb the grammar knows: reported, with its text, rather than dropped.
                ops = [Instruction(id=f"{node.loc}#0", bill_loc=node.loc, source_text=node.text, span=node.span,
                                   # under "… is—" the subject is the head's target, not a place the item names
                                   target=(child_ctx if AMENDED.search(qf) else ctx).target_out(), op="UNPARSED",
                                   confidence=0.0,
                                   reason="amendatory wording with no instruction verb the grammar knows: "
                                          + node.text[:160])]
            instructions.extend(ops)
            if n or AMEND_WORDS.search(qf):
                node.cls = "AMENDATORY"
            elif node.cls != "STRUCTURAL" or node.text:
                node.cls = "FREESTANDING"
                node.freestanding_type = freestanding_type(node.text)
        for c in node.children:
            visit(c, child_ctx, node.text)
        if node.level == "section" and ctx is not None and ctx.memory.get("usc") is not None:
            bill_memory["usc"] = ctx.memory["usc"]

    for r in roots:
        visit(r, None)
    flag_delayed(roots, instructions)
    total = len(instructions)
    parsed = sum(1 for i in instructions if i.op != "UNPARSED" and i.confidence >= CONFIDENCE_THRESHOLD)
    return ParseResult(instructions=instructions, nodes=roots, counts=counts,
                       coverage=round(parsed / total, 4) if total else 1.0)
