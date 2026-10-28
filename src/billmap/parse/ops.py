"""Where instructions start: shared by the parser and the independent XML count (one rule, two readings)."""
from __future__ import annotations

import re

# An instruction starts at an operative verb introduced by "by", at the start of an item under "by—",
# or at "is repealed" / "is amended to read as follows". "striking ... and inserting" is one instruction.
VERB = r"(?:striking|inserting|adding|redesignating|transferring|moving)"
OP_START = re.compile(
    rf"(?:(?<=\bby )|(?<=\band by )|^\s*(?=(?:{VERB})\b)|(?<=—)\s*(?=(?:{VERB})\b))(?P<verb>{VERB})\b"
    r"|(?P<repeal>\b(?:is|are)\s+(?:hereby\s+)?repealed\b)"
    r"|(?P<toread>\b(?:is|are)\s+(?:hereby\s+)?(?:further\s+)?amended\s+to\s+read\s+as\s+follows\b)",
    re.I,
)


def op_starts(quote_free: str) -> list[re.Match]:
    return list(OP_START.finditer(quote_free))


def count_ops(quote_free: str) -> int:
    return len(op_starts(quote_free))
