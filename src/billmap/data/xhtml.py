"""OLRC's XHTML edition of a release point, used as an independent cross-check of the XML.

Verified 2026-10-28 (records/verify-first.md): one `<!-- documentid:... -->` chunk per section, with an
`<!-- itempath:/.../Sec. N -->` comment ("Secs. 3, 4", "[Sec. 2" when repealed, "130g_2" for a duplicate
number) and the operative text between `<!-- field-start:statute -->` and `<!-- field-end:statute -->`.
"""
from __future__ import annotations

import html
import re
import unicodedata
import zipfile
from pathlib import Path

from billmap.data import cite as citemod

SEC_LEAF = re.compile(r"^\[?Secs?\.\s+(.+?)\]?$")
FILE_RE = re.compile(r"^PRELIMusc(\d+)([aA]?)\.htm$")
QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
FRACTIONS = {"⅓": "1/3", "⅔": "2/3", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8", "¼": "1/4", "½": "1/2",
             "¾": "3/4", "⅒": "1/10", "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5", "⅙": "1/6", "⅚": "5/6",
             "⅐": "1/7", "⅑": "1/9", "⁄": "/"}


def listing(zip_path: Path) -> dict[str, list[tuple[str, list[str] | None]]]:
    """Per title code: [(first section number, statute words or None)] in document order."""
    out: dict[str, list] = {}
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            m = FILE_RE.match(name)
            if not m:
                continue
            code = str(int(m.group(1))) + ("a" if m.group(2) else "")
            entries, last = [], None
            # Three files carry GPO locator escapes (b"\xffAE1") that are not UTF-8; they sit in note text.
            for chunk in zf.read(name).decode("utf-8", errors="replace").split("<!-- documentid:")[1:]:
                doc_id = chunk.split(None, 1)[0]
                p = re.search(r"<!-- itempath:([^>]*?) -->", chunk)
                leaf = SEC_LEAF.match(p.group(1).rsplit("/", 1)[-1]) if p else None
                if not leaf:
                    continue
                first = re.sub(r"_\d+$", "", re.split(r",\s*| to ", leaf.group(1))[0])
                body = re.search(r"<!-- field-start:statute -->(.*?)<!-- field-end:statute -->", chunk, re.S)
                words = html.unescape(re.sub(r"<[^>]+>", " ", body.group(1))).split() if body else None
                key = (doc_id, leaf.group(1))      # duplicates differ in the leaf: "130g" vs "130g_2"
                if key == last and entries:        # one section split over two documents (18a § 2)
                    num, prev = entries[-1]
                    entries[-1] = (num, (prev or []) + (words or []) or None)
                    continue
                last = key
                entries.append((citemod.normalize_section(first), words))
            out[code] = entries
    return out


def first_number(identifier: str) -> str:
    """'/us/usc/t2/s1001...1004' -> '1001'; '/us/usc/t2/s3' -> '3'."""
    return identifier.rsplit("/s", 1)[1].split("...", 1)[0]


def comparable(words: list[str]) -> str:
    """Whitespace and curly/straight quote style are rendering choices; every other character must match."""
    return "".join(words).translate(QUOTES)


def rendering_normalized(s: str) -> str:
    """Also discount presentation-only differences: fractions, Unicode composition, joiners, dot leaders,
    blank-line lengths, GPO escapes. What survives this is a content difference between the editions."""
    s = unicodedata.normalize("NFC", s)
    for k, v in FRACTIONS.items():
        s = s.replace(k, v)
    s = re.sub(r"[⁠​﻿̅]", "", s).replace("ʻ", "'").replace("″", "′′")
    s = re.sub(r"\.{3,}", "", s)
    s = re.sub(r"_+", "_", s)
    return re.sub(r"�AE\d", "", s)


def body_words(text_plain: str) -> list[str]:
    """Index text minus its first line (num and heading), which the XHTML keeps outside the statute field."""
    return text_plain.split("\n", 1)[1].split() if "\n" in text_plain else []


def compare(mine: list[str], theirs: list[str]) -> tuple[str, str | None]:
    """('equal' | 'rendering' | 'content', first-difference snippet)."""
    a, b = comparable(mine), comparable(theirs)
    if a == b:
        return "equal", None
    a2, b2 = rendering_normalized(a), rendering_normalized(b)
    kind = "rendering" if a2 == b2 else "content"
    x, y = (a, b) if kind == "rendering" else (a2, b2)
    i = next((k for k, (p, q) in enumerate(zip(x, y)) if p != q), min(len(x), len(y)))
    return kind, f"XML …{x[max(0, i - 30):i + 40]}… | XHTML …{y[max(0, i - 30):i + 40]}…"
