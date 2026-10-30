"""Release-point labels and which public laws each release point incorporates (records/landscape-2026-10.md).

A label does not describe its contents. "119-73not60" incorporates every law of the 119th Congress up to 73
except 60; "116-344not283u1" is a re-issue (u1) of 116-344 still without Pub. L. 116-283, which enters only at
"116-344", below both labels. Following aih/uscode-redesign ADR-0074:

    incorporated(RP, L) = L <= (RP.congress, RP.law) and L not in RP.excluded

where an excluded number above RP's own law belongs to the previous Congress ("118-2not263not328").

and the laws entering between two release points are those the later one incorporates and the earlier does not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

LABEL_RE = re.compile(r"^(\d+)-(\d+)((?:not\d+)*)(?:u(\d+))?$")


@dataclass(frozen=True)
class Label:
    raw: str
    congress: int
    law: int
    excluded: frozenset[int]          # law numbers held back, as printed (see excluded_laws)
    reissue: int                      # the N of a "uN" suffix; 0 for none

    @property
    def excluded_laws(self) -> frozenset[tuple[int, int]]:
        """The held-back laws as (congress, law). A number above the label's own law belongs to the previous
        Congress: "118-2not263not328" holds back 117-263 and 117-328 (the FY2023 NDAA and the 2023 appropriations
        act) at the start of the 118th (scripts/history_govinfo_check.py)."""
        return frozenset((self.congress - 1 if n > self.law else self.congress, n) for n in self.excluded)

    def incorporates(self, congress: int, law: int) -> bool:
        return (congress, law) <= (self.congress, self.law) and (congress, law) not in self.excluded_laws

    @property
    def order(self) -> tuple:
        """Publication order among labels: a release with laws held back precedes the full one at the same law,
        and a re-issue follows its original."""
        return (self.congress, self.law, -len(self.excluded), self.reissue)


def parse(label: str) -> Label:
    m = LABEL_RE.match(label)
    if not m:
        raise ValueError(f"not a release-point label: {label!r}")
    excluded = frozenset(int(x) for x in re.findall(r"not(\d+)", m.group(3)))
    return Label(label, int(m.group(1)), int(m.group(2)), excluded, int(m.group(4) or 0))


def law_number(pl: str) -> tuple[int, int]:
    """'119-60' -> (119, 60)."""
    c, n = pl.split("-")
    return int(c), int(n)


def window(labels, pl: str) -> tuple[str, str] | None:
    """(before, after) for a law: the first release point incorporating it, and the one published just before.

    None when no listed release point incorporates the law yet, or when the first one that does is the earliest
    listed (no release point before it to compare with)."""
    ordered = sorted((parse(l) for l in labels), key=lambda r: r.order)
    congress, law = law_number(pl)
    for i, rp in enumerate(ordered):
        if rp.incorporates(congress, law):
            if i == 0 or ordered[i - 1].incorporates(congress, law):
                return None
            return ordered[i - 1].raw, rp.raw
    return None


def entering(before: str, after: str, laws) -> list[str]:
    """The laws (from `laws`, 'C-N' strings) that `after` incorporates and `before` does not."""
    b, a = parse(before), parse(after)
    return [pl for pl in laws if a.incorporates(*law_number(pl)) and not b.incorporates(*law_number(pl))]
