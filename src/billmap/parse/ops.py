"""Where instructions start: shared by the parser and the independent XML count (one rule, two readings)."""
from __future__ import annotations

import re

# An instruction starts at an operative verb introduced by "by", at the start of an item under "by—",
# or at "is repealed" / "is amended to read as follows". "striking ... and inserting" is one instruction;
# "by amending paragraph (3) to read as follows" is one too. "redesignating (c) and (d) as (d) and (e), respectively,
# and inserting after subsection (b) the following" is two.
VERB = (r"(?:striking|inserting|adding|redesignating|transferring|moving|repealing|deleting|replacing|substituting|"
        r"amending(?=[^\u201c\u27e6.;:]*?\bto read as follows))")
# Imperative drafting ("(1) In subsection (a), strike “A” and insert “B”."): the verb starts the clause or follows a
# comma or dash, and a quotation or a unit follows it. "and insert" after "strike" stays in the same instruction.
IMPERATIVE = (r"(?:strike|insert|add|redesignate)(?=\s+(?:Q\b|\u27e6|the\s|(?:sub)?(?:section|paragraph|clause|item)s?\b|"
              r"subparagraphs?\b|subclauses?\b|at the end\b|after\b|before\b))")
OP_START = re.compile(
    rf"(?:(?<=\bby )|(?<=\band by )|(?<=\brespectively, and )|(?<=\brespectively and )|^\s*(?=(?:{VERB})\b)"
    rf"|(?<=—)\s*(?=(?:{VERB})\b))(?P<verb>{VERB})\b"
    rf"|(?:(?<=^)|(?<=, )|(?<=—)|(?<=; and )|(?<=; ))(?P<imperative>{IMPERATIVE})\b"
    r"|(?P<repeal>\b(?:is|are)\s+(?:hereby\s+)?repealed\b)"
    r"|(?P<toread>\b(?:is|are)\s+(?:hereby\s+)?(?:further\s+)?amended\s+to\s+read\s+as\s+follows\b)",
    re.I,
)


# A unit that says "is amended" / "is repealed" yet holds no instruction verb counts as one (unparsed) instruction.
AMENDED = re.compile(r"\b(?:is|are) (?:hereby )?(?:further )?(?:amended|repealed)\b")
# A head that hands its verb to the items below it: "Subsection (g) of section 2805 ... is—" / "(1) transferred to
# the end of section 2810 ...". An item under it with no known verb counts as one (unparsed) instruction.
OPEN_HEAD = re.compile(r"\b(?:is|are)(?: hereby)?(?: further)?(?: amended)?\s*\u2014\s*$")


def op_starts(quote_free: str) -> list[re.Match]:
    return list(OP_START.finditer(quote_free))


def count_ops(quote_free: str) -> int:
    return len(op_starts(quote_free))
