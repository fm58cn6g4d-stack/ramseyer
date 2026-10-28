"""Published bill XML (GPO bill DTD) -> the plain text a staffer would paste, plus an independent count.

`render` emits one line per heading or enumerated unit, inline <quote> as curly quotes (single quotes
inside quoted blocks), and each paragraph of a <quoted-block> opened with “ and the block closed with ”
plus its after-quoted-block text, as bills print. The parser only ever sees that text.

`xml_counts` counts instructions per bill location from the XML markup itself: quote boundaries come
from <quote> and <quoted-block> elements, not from text. Comparing it with the parser's count checks the
parser's segmentation and quote detection against an independent reading.
"""
from __future__ import annotations

from lxml import etree

from billmap.parse.ops import count_ops

HEADINGS = {"division": "DIVISION", "title": "TITLE", "subtitle": "Subtitle", "part": "PART",
            "subpart": "Subpart", "chapter": "CHAPTER", "subchapter": "Subchapter"}
LOC_PREFIX = {"division": "div", "title": "title", "subtitle": "subt", "part": "part", "subpart": "subpart",
              "chapter": "ch", "subchapter": "subch", "section": "sec"}
UNITS = {"subsection", "paragraph", "subparagraph", "clause", "subclause", "item", "subitem", "subsubitem"}
STRUCT = set(HEADINGS) | {"section"} | UNITS
SKIP = {"enum", "header", "toc", "quoted-block", "after-quoted-block", "continuation-text"}


def enum_key(enum: str | None) -> str:
    return (enum or "").strip().strip("().").replace(" ", "") or "_"


def inline(el, quote_open="“", quote_close="”", inner=False) -> str:
    """Text of an inline container: <quote> becomes quotes; nested quoted blocks are not inline."""
    parts = [el.text or ""]
    for c in el:
        if not isinstance(c.tag, str):
            parts.append(c.tail or "")
            continue
        if c.tag == "quote":
            o, cl = ("‘", "’") if inner else (quote_open, quote_close)
            parts.append(o + inline(c, inner=True) + cl)
        elif c.tag in ("quoted-block", "toc"):
            pass
        elif c.tag == "term":            # defined terms print in quotes
            o, cl = ("\u2018", "\u2019") if inner else (quote_open, quote_close)
            parts.append(o + inline(c, inner=True) + cl)
        else:
            parts.append(inline(c, inner=inner))
        parts.append(c.tail or "")
    return " ".join("".join(parts).split())


def _head_line(el) -> str:
    enum = (el.findtext("enum") or "").strip()
    header = " ".join("".join(el.find("header").itertext()).split()) if el.find("header") is not None else ""
    tag = el.tag
    if tag in HEADINGS:
        return f"{HEADINGS[tag]} {enum.rstrip('.')}—{header.upper() if tag in ('division', 'title') else header}"
    if tag == "section":
        return f"SEC. {enum.rstrip('.')}. {header.upper()}." if header else f"SEC. {enum.rstrip('.')}."
    return ""


def _render(el, lines: list[str], in_block: bool) -> None:
    tag = el.tag
    q = in_block
    if tag in STRUCT:
        text_el = el.find("text")
        text = inline(text_el, inner=q) if text_el is not None else ""
        if tag in HEADINGS or tag == "section":
            lines.append(_head_line(el))
            if text:
                lines.append(text)
        else:
            enum = (el.findtext("enum") or "").strip()
            header_el = el.find("header")
            header = " ".join("".join(header_el.itertext()).split()) if header_el is not None else ""
            line = enum
            if header:
                line += f" {header}.—"
                line += text
            elif text:
                line += f" {text}"
            lines.append(line.strip())
    for c in el:
        if not isinstance(c.tag, str):
            continue
        if c.tag in STRUCT:
            _render(c, lines, in_block)
        elif c.tag == "quoted-block":
            _block(c, lines)
        elif c.tag == "toc":
            for e in c.iter("toc-entry"):
                lines.append(" ".join("".join(e.itertext()).split()))
        elif c.tag == "continuation-text":
            lines.append(inline(c, inner=q))
        elif c.tag not in SKIP and tag not in STRUCT:
            _render(c, lines, in_block)


def _block(qb, lines: list[str]) -> None:
    inner: list[str] = []
    for c in qb:
        if not isinstance(c.tag, str) or c.tag == "after-quoted-block":
            continue
        if c.tag in STRUCT:
            _render(c, inner, True)
        elif c.tag == "text":
            inner.append(inline(c, inner=True))
        elif c.tag == "quoted-block":
            _block(c, inner)
        else:
            t = " ".join("".join(c.itertext()).split())
            if t:
                inner.append(t)
    inner = [x for x in inner if x]
    after = qb.find("after-quoted-block")
    after_text = inline(after) if after is not None else ""
    if not inner:
        inner = [""]
    inner = ["“" + x for x in inner]
    inner[-1] += "”" + after_text
    lines.extend(inner)


def render(xml_path) -> str:
    root = etree.parse(str(xml_path)).getroot()
    body = root.find(".//legis-body")
    lines: list[str] = []
    for c in body:
        if isinstance(c.tag, str):
            _render(c, lines, False)
    return "\n".join(line for line in lines if line.strip()) + "\n"


def _loc(el) -> str:
    parts = []
    for a in reversed([el] + list(el.iterancestors())):
        if a.tag in LOC_PREFIX:
            parts.append(LOC_PREFIX[a.tag] + enum_key(a.findtext("enum")))
        elif a.tag in UNITS:
            parts.append(enum_key(a.findtext("enum")))
    return ".".join(parts)


def xml_counts(xml_path) -> dict[str, int]:
    """Instructions per bill location, read from markup: <quote> and <quoted-block> content excluded."""
    root = etree.parse(str(xml_path)).getroot()
    body = root.find(".//legis-body")
    counts: dict[str, int] = {}
    for el in body.iter():
        if not isinstance(el.tag, str) or el.tag not in STRUCT:
            continue
        if any(a.tag == "quoted-block" for a in el.iterancestors()):
            continue
        texts = [t for t in (el.find("text"), *el.findall("continuation-text")) if t is not None]
        if not texts:
            continue
        quote_free = " ".join(inline_without_quotes(t) for t in texts)
        n = count_ops(quote_free)
        if n:
            key = _loc(el)
            counts[key] = counts.get(key, 0) + n
    return counts


def inline_without_quotes(el) -> str:
    parts = [el.text or ""]
    for c in el:
        if isinstance(c.tag, str):
            if c.tag in ("quote", "term"):
                parts.append(" Q ")
            elif c.tag not in ("quoted-block", "toc"):
                parts.append(inline_without_quotes(c))
        parts.append(c.tail or "")
    return " ".join("".join(parts).split())
