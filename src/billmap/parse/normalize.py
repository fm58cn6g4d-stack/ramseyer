"""Normalization with an offset map back to the original text (docs/04-draft-parser.md, stage 2)."""
from __future__ import annotations

import re
from dataclasses import dataclass

# Single-character replacements keep offsets aligned; multi-character ones are recorded in the map.
CHAR_MAP = {
    " ": " ", " ": " ", " ": " ", " ": " ", "​": "", "⁠": "", "­": "",
    "‐": "-", "‑": "-", "‒": "-",
    "‟": "“", "„": "“", "″": "”", "‘": "‘", "’": "’",
}
MULTI = [("``", "“"), ("''", "”"), ("§§", "§§")]


@dataclass
class Normalized:
    text: str
    offsets: list[int]          # offsets[i] = original index of normalized char i; len = len(text) + 1

    def original_span(self, start: int, end: int) -> tuple[int, int]:
        return self.offsets[start], self.offsets[end]


def normalize(original: str) -> Normalized:
    """Quote, dash and space variants to one form. Straight double quotes become curly by pairing."""
    out: list[str] = []
    offs: list[int] = []
    i = 0
    n = len(original)
    while i < n:
        two = original[i:i + 2]
        hit = next((rep for src, rep in MULTI if two == src and src != rep), None)
        if hit:
            out.append(hit)
            offs.append(i)
            i += 2
            continue
        c = CHAR_MAP.get(original[i], original[i])
        for ch in c:
            out.append(ch)
            offs.append(i)
        i += 1
    offs.append(n)
    text = "".join(out)
    if '"' in text:                     # pair straight quotes per line: odd -> open, even -> close
        chars = list(text)
        for m in re.finditer(r"[^\n]+", text):
            k = 0
            for j in range(m.start(), m.end()):
                if chars[j] == '"':
                    chars[j] = "“" if k % 2 == 0 else "”"
                    k += 1
        text = "".join(chars)
    return Normalized(text, offs)


def usc_variants(s: str) -> str:
    """'U. S. C.', 'USC', 'U.S.C.A.' -> 'U.S.C.' (used on cite text only, not on whole drafts)."""
    return re.sub(r"\bU\.?\s?S\.?\s?C\.?(?:\s?A\.?)?(?=[\s)§,;]|$)", "U.S.C.", s)
