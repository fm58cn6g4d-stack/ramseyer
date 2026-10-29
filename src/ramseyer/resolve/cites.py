"""Citation helpers for the resolver."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ramseyer.data.cite import normalize_section

LABEL = r"\((?:[0-9]+[A-Za-z]?|[a-z]{1,4}|[A-Z]{1,4})\)"


@dataclass
class Parenthetical:
    """What a drafter wrote in parentheses after an Act reference, e.g. "(Public Law 116–283; 10 U.S.C. 1791 note)"."""
    public_law: str | None = None
    title: str | None = None
    section: str | None = None
    path: tuple[str, ...] = ()
    note: bool = False              # "10 U.S.C. 1791 note"
    preceding: bool = False         # "10 U.S.C. note prec. 3701"
    et_seq: bool = False


PL_RE = re.compile(r"Pub(?:lic|\.)\s*L(?:aw|\.)\s*(\d+)\s*[–-]\s*(\d+)")
USC_RE = re.compile(rf"(\d+)\s+U\.\s?S\.\s?C\.\s+(?:(note prec\.|note preceding)\s+)?(?:§+\s*)?([\dA-Za-z][\w–.-]*)"
                    rf"((?:{LABEL})*)(\s+note)?(\s+et seq\.?)?")


def parse_parenthetical(text: str | None) -> Parenthetical:
    p = Parenthetical()
    if not text:
        return p
    m = PL_RE.search(text)
    if m:
        p.public_law = f"{m.group(1)}-{m.group(2)}"
    m = USC_RE.search(text)
    if m:
        p.title, p.section = m.group(1), normalize_section(m.group(3))
        p.path = tuple(re.findall(LABEL, m.group(4) or ""))
        p.preceding = bool(m.group(2))
        p.note = bool(m.group(5)) or p.preceding
        p.et_seq = bool(m.group(6))
    return p


def designation(bill_loc: str) -> tuple[str, tuple[str, ...]] | None:
    """'divA.titleIII.sec311.b.1' -> ('311', ('(b)', '(1)'))."""
    parts = bill_loc.split(".")
    i = next((k for k, p in enumerate(parts) if p.startswith("sec")), None)
    if i is None:
        return None
    return parts[i][3:], tuple(f"({p})" for p in parts[i + 1:])


def parse_designation(s: str) -> tuple[str, tuple[str, ...]]:
    """Classification-table law section '7070(b)(1) "33"' -> ('7070', ('(b)', '(1)'))."""
    s = re.sub(r'"[^"]*"', "", s).strip()
    m = re.match(r"([\w–.-]+?)((?:\([^)]+\))*)$", s)
    if not m:
        return s, ()
    return m.group(1), tuple(re.findall(r"\([^)]+\)", m.group(2)))


def prefix_match(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    n = min(len(a), len(b))
    return a[:n] == b[:n]
