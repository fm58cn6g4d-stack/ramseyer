"""U.S. Code citations <-> USLM identifiers.

Identifier format verified in M0/M1 (records/verify-first.md): /us/usc/t{title}/s{section}/{sub}/...
Section numbers in identifiers use an en dash ("136a–2"), never an ASCII hyphen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

EN_DASH = "–"

# 49 U.S.C. 24101(a)(2) | 49 USC § 24101 | 49 U.S.C.A. 24101 | 5 App. U.S.C. 5
_CITE_RE = re.compile(
    r"^\s*(?P<title>\d+)(?P<app>\s*(?:a|A|App\.?))?\s*U\.?\s*S\.?\s*C\.?(?:\s*A\.?)?\s*"
    r"(?:§§?|sec\.|section)?\s*(?P<section>[0-9A-Za-z][0-9A-Za-z.\-‐‑‒–—]*)"
    r"(?P<path>(?:\([0-9A-Za-z]+\))*)\s*$",
    re.I,
)
_PATH_RE = re.compile(r"\(([0-9A-Za-z]+)\)")
_ID_RE = re.compile(r"^/us/usc/t(?P<title>\d+a?)/s(?P<section>[^/\s]+)(?P<rest>(?:/[^/\s]+)*)$")


class CiteError(ValueError):
    """A citation string that does not have a recognized U.S. Code shape."""


@dataclass(frozen=True)
class UscCite:
    title: str            # "49", or "5a" for an appendix
    section: str          # as in the identifier, en dash form
    path: tuple[str, ...] = ()

    @property
    def section_identifier(self) -> str:
        return f"/us/usc/t{self.title}/s{self.section}"

    @property
    def identifier(self) -> str:
        return self.section_identifier + "".join(f"/{p}" for p in self.path)

    def __str__(self) -> str:
        title = f"{self.title[:-1]} App." if self.title.endswith("a") else self.title
        section = self.section.replace(EN_DASH, "-")
        return f"{title} U.S.C. {section}" + "".join(f"({p})" for p in self.path)


def normalize_section(s: str) -> str:
    return re.sub(r"[\-‐‑‒—]", EN_DASH, s.strip().rstrip("."))


def parse(text: str) -> UscCite:
    m = _CITE_RE.match(text.replace(" ", " ").replace(" ", " "))
    if not m:
        raise CiteError(f"not a U.S. Code citation: {text!r}")
    title = m.group("title") + ("a" if m.group("app") else "")
    return UscCite(title, normalize_section(m.group("section")), tuple(_PATH_RE.findall(m.group("path"))))


def from_identifier(identifier: str) -> UscCite:
    m = _ID_RE.match(identifier)
    if not m:
        raise CiteError(f"not a U.S. Code section identifier: {identifier!r}")
    rest = tuple(p for p in m.group("rest").split("/") if p)
    return UscCite(m.group("title"), m.group("section"), rest)
