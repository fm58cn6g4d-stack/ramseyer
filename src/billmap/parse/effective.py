"""Delayed effective dates: "The amendments made by subsection (c) shall take effect 180 days after the date of
the enactment of this Act." OLRC does not execute such an amendment at the next release point; it sets it out in an
"Amendment of ..." note (records/milestones.md, M6). The parser flags the instructions it governs.
"""
from __future__ import annotations

import re

from billmap.parse.ir import Instruction, Node
from billmap.parse.segment import walk

RULE = re.compile(r"\b[Tt]he amendments? made by (?P<what>this (?:section|subsection|paragraph|title|subtitle)|"
                  r"(?:sub)?sections? \(\w+\)(?:(?:,| and|, and) \(\w+\))*|paragraphs? \(\w+\)(?:(?:,| and|, and) \(\w+\))*)"
                  r"(?: of this section)? shall take effect (?P<when>[^.]{0,200})")
# A date that falls after the next release point: a period after enactment, or a stated future date.
DELAYED = re.compile(r"\b(?:\d+|one|two|three|four|five|six|\w+-\w+) (?:days?|months?|years?) after|"
                     r"\bon (?:January|February|March|April|May|June|July|August|September|October|November|December) "
                     r"\d{1,2}, \d{4}|\bthe date that is .{0,40}after")
NOT_DELAYED = re.compile(r"\bon the date of (?:the )?enactment|as (?:if|though) enacted|\bapply to\b")


def _scopes(node: Node, what: str) -> list[str]:
    parts = node.loc.split(".")
    sec = next((i for i, p in enumerate(parts) if p.startswith("sec")), None)
    if sec is None:
        return []
    labels = re.findall(r"\((\w+)\)", what)
    if what.startswith("this section"):
        return [".".join(parts[:sec + 1])]
    if what.startswith(("this title", "this subtitle")):
        key = "title" if "title" in what and "subtitle" not in what else "subt"
        i = max((k for k, p in enumerate(parts[:sec]) if p.startswith(key)), default=None)
        return [".".join(parts[:i + 1])] if i is not None else []
    if what.startswith("this subsection"):
        return [".".join(parts[:sec + 2])] if len(parts) > sec + 1 else []
    if what.startswith("this paragraph"):
        return [".".join(parts[:sec + 3])] if len(parts) > sec + 2 else []
    if what.startswith("subsection"):
        return [".".join(parts[:sec + 1] + [lab]) for lab in labels]
    if what.startswith("paragraph"):             # sibling paragraphs of the effective-date provision
        return [".".join(parts[:-1] + [lab]) for lab in labels]
    return []


def flag_delayed(roots: list[Node], instructions: list[Instruction]) -> int:
    """Flag instructions governed by a delayed effective date. Returns how many were flagged."""
    scopes: list[tuple[str, str]] = []
    for n in walk(roots):
        for m in RULE.finditer(n.text or ""):
            # Only the "take effect" part decides: "shall take effect on October 1, 2025, and shall apply to payments
            # ..." is delayed (Pub. L. 118-258 § 117; OLRC left 42 U.S.C. 625 unamended in the 2024 edition).
            when = re.split(r",? and (?:shall )?apply\b", m["when"])[0]
            if DELAYED.search(when) and not NOT_DELAYED.search(when):
                scopes += [(s, m.group(0)[:160]) for s in _scopes(n, m["what"])]
    flagged = 0
    for ins in instructions:
        hit = next((why for s, why in scopes if ins.bill_loc == s or ins.bill_loc.startswith(s + ".")), None)
        if hit:
            ins.flags.append("delayed effective date: " + hit)
            flagged += 1
    return flagged
