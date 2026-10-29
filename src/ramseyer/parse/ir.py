"""The parser's intermediate representation (docs/04-draft-parser.md, IR schema)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Op = Literal["STRIKE_INSERT", "STRIKE", "INSERT_AFTER", "INSERT_BEFORE", "ADD_END", "ADD_UNIT_AFTER",
             "ADD_UNIT_BEFORE", "REPLACE_UNIT", "STRIKE_UNIT", "REDESIGNATE", "REPEAL", "AMEND_HEADING",
             "CONFORM_TOC", "STRIKE_THROUGH", "UNPARSED"]
Kind = Literal["usc", "act", "pl", "unknown"]
NodeClass = Literal["AMENDATORY", "FREESTANDING", "STRUCTURAL", "TABLE_OF_CONTENTS", "QUOTED"]


class Span(BaseModel):
    start: int                         # character offsets into the original (pre-normalization) text
    end: int


class Target(BaseModel):
    kind: Kind = "unknown"
    cite_raw: str = ""                 # the target phrase as drafted, e.g. "Section 317U of the Public Health ..."
    cite_norm: str | None = None       # "42 U.S.C. 247b–23(b)" when the draft states a Code citation
    title: str | None = None           # Code title, when the target is in the Code
    section: str | None = None         # section number within the title or the Act
    act: str | None = None             # named Act, e.g. "Public Health Service Act"
    public_law: str | None = None      # "117-58"
    usc_parenthetical: str | None = None   # "(42 U.S.C. 247b–23)" as drafted next to an Act reference
    path: list[str] = Field(default_factory=list)        # ["(b)", "(2)"]
    qualifiers: list[str] = Field(default_factory=list)  # ["matter preceding paragraph (1)", "heading"]


class Instruction(BaseModel):
    id: str                            # stable: bill location + op index, e.g. "sec2.a.1#0"
    bill_loc: str                      # "sec2.a.1"
    source_text: str                   # exact original text of the node holding the instruction
    span: Span
    target: Target
    op: Op
    find: str | None = None            # quoted text to strike, or the anchor for INSERT_AFTER/BEFORE
    replace: str | None = None         # quoted text inserted in place of `find` (STRIKE_INSERT)
    through: str | None = None         # STRIKE_THROUGH end anchor
    new_text: str | None = None        # quoted text or quoted block to add
    unit: str | None = None            # unit named by the op: "subsection (c)", "paragraphs (2) through (5)"
    redesignate: list[tuple[str, str]] | None = None   # [("(2)", "(3)"), ...]
    occurrence: str = "first"          # first (none given) | each | last | nth:<n> (drafted ordinal)
    confidence: float = 1.0
    shape_hash: str = ""
    flags: list[str] = Field(default_factory=list)
    reason: str | None = None          # why UNPARSED or low confidence


class Node(BaseModel):
    """A segment of the bill: a heading, an enumerated unit, or a quoted block attached to its parent."""
    loc: str
    level: str                         # division, title, subtitle, part, chapter, section, subsection, ...
    enum: str | None = None
    header: str | None = None
    text: str = ""                     # the node's own text (normalized), quoted blocks excluded
    span: Span
    cls: NodeClass = "FREESTANDING"
    block: str | None = None           # quoted block that follows this node's text, normalized
    freestanding_type: str | None = None
    children: list["Node"] = Field(default_factory=list)


class ParseResult(BaseModel):
    instructions: list[Instruction]
    nodes: list[Node]
    counts: dict[str, int]             # per bill_loc: instructions detected in the source
    coverage: float                    # share of instructions parsed deterministically (not UNPARSED)
