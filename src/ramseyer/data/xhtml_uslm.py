"""OLRC's XHTML edition of the Code -> USLM, for Code editions published only as XHTML (GovInfo's annual
U.S. Code editions; records/verify-first.md, M6b).

The XHTML is one `<!-- documentid:... -->` chunk per section with named fields (head, statute, sourcecredit,
notes, footnote). Statute paragraphs carry their depth as a class (`statutory-body`, `statutory-body-1em`, ...),
the same depth USLM records as `indent0`, `indent1`, ...; enumerators give the level names. Headings are inline
small caps in positive-law titles ("(a) <cap-smallcap>Status</cap-smallcap>.—") and `<h4 class="...-head">` lines
in other titles. The output is USLM 1.0 that the indexer loads unchanged; scripts/xhtml_check.py measures it
against the XML edition of the same release point.
"""
from __future__ import annotations

import html as htmlmod
import re
from dataclasses import dataclass, field

from lxml import etree
from lxml import html as lhtml

from ramseyer.data import cite as citemod
from ramseyer.data.indexer import USLM
from ramseyer.parse.segment import is_roman, roman_to_int

NS = f"{{{USLM}}}"
LEVELS = ["subsection", "paragraph", "subparagraph", "clause", "subclause", "item", "subitem", "subsubitem"]
DEPTH_RE = re.compile(r"^statutory-body(?:-(\d+)em)?$")
BLOCK_RE = re.compile(r"^statutory-body-(?:block|flush)")
ENUM_RE = re.compile(r"^(?P<br>\[?)\((?P<e>[0-9]+[A-Za-z]?|[a-z]{1,7}|[A-Z]{1,7})\)\s*")
HEAD_H4 = re.compile(r"^(?:sub)*(?:section|paragraph|clause|item)-head$|^subparagraph-head$")
FN_OPEN, FN_CLOSE = "⟪", "⟫"          # footnote marker placeholder in extracted text
HIER = {"SUBTITLE": ("subtitle", "st"), "PART": ("part", "pt"), "SUBPART": ("subpart", "spt"),
        "CHAPTER": ("chapter", "ch"), "SUBCHAPTER": ("subchapter", "sch"), "DIVISION": ("division", "d"),
        "SUBDIVISION": ("subdivision", "sd"), "ARTICLE": ("article", "a")}


@dataclass
class Chunk:
    doc_id: str
    itempath: str
    fields: dict[str, list[str]] = field(default_factory=dict)


def chunks(page: str) -> list[Chunk]:
    out = []
    for raw in page.split("<!-- documentid:")[1:]:
        doc_id = raw.split(None, 1)[0]
        p = re.search(r"<!-- itempath:([^>]*?) -->", raw)
        c = Chunk(doc_id, p.group(1) if p else "")
        for m in re.finditer(r"<!-- field-start:([\w-]+) -->(.*?)<!-- field-end:\1 -->", raw, re.S):
            c.fields.setdefault(m.group(1), []).append(m.group(2))
        out.append(c)
    return out


# ---- text -------------------------------------------------------------------------------------
def _text(el) -> str:
    """An element's text with footnote anchors replaced by a placeholder; <br> as a space."""
    parts = [el.text or ""]
    for c in el:
        if not isinstance(c.tag, str):
            parts.append(c.tail or "")
            continue
        if c.tag == "sup" and (c.text_content() or "").strip().isdigit():     # footnote marker, linked or not
            parts.append(f"{FN_OPEN}{c.text_content().strip()}{FN_CLOSE}")
        elif c.tag == "br":
            parts.append(" ")
        else:
            parts.append(_text(c))
        parts.append(c.tail or "")
    return "".join(parts)


def _clean(s: str) -> str:
    # The XHTML prints "§52011" and "§§334"; the XML edition "§ 52011" (measured on 119-134 by xhtml_check).
    return re.sub(r"(§+)(?=[\dA-Za-z])", r"\1 ", re.sub(r"[ \t\r\n]+", " ", s))


def _plain(fragment: str) -> str:
    """An HTML fragment's text, read structurally: "§ 1862<i>o</i>–10" stays "§ 1862o–10"."""
    if not fragment.strip():
        return ""
    return _clean(_text(lhtml.fragment_fromstring(fragment, create_parent="div"))).strip()


@dataclass
class Line:
    depth: int
    text: str                 # without the enumerator(s) and heading
    enums: list[str]          # "(b)(1) text" -> ["b", "1"]
    heading: str | None       # as printed: "Status.—" (inline style) or "In general" (h4 style)
    block: bool = False       # quoted or flush text: never structure
    table: etree._Element | None = None


def statute_lines(fragment: str) -> list[Line]:
    root = lhtml.fragment_fromstring(fragment, create_parent="div")
    lines: list[Line] = []
    pending_head: tuple[int, str, list[str]] | None = None     # an h4 heading waiting for its text
    for el in root:
        if not isinstance(el.tag, str):
            continue
        cls = (el.get("class") or "").strip()
        if el.tag == "h4" and HEAD_H4.match(cls):
            t = _clean(_text(el)).strip()
            enums, rest = _enums(t)
            level = cls.rsplit("-", 1)[0]
            depth = LEVELS.index(level) if level in LEVELS else 0
            if pending_head:
                lines.append(Line(pending_head[0], "", pending_head[2], pending_head[1]))
            pending_head = (depth, rest, enums)
            continue
        if el.tag == "table":
            lines.append(Line(lines[-1].depth + 1 if lines else 0, "", [], None, block=True, table=el))
            continue
        if el.tag != "p":
            continue
        t = _clean(_text(el)).strip()
        m = DEPTH_RE.match(cls)
        if pending_head:
            depth, head, enums = pending_head
            pending_head = None
            if not _enums(t)[0] or BLOCK_RE.match(cls):
                lines.append(Line(depth, t, enums, head))
                continue
            # "(c) Exercise of delegated discretion" then "(1) The Administrator ...": the heading's unit has
            # no text of its own; the paragraph is its first child.
            lines.append(Line(depth, "", enums, head))
        if m and not BLOCK_RE.match(cls):
            depth = int(m.group(1) or 0)
            enums, rest = _enums(t)
            head = None
            caps = el.find("cap-smallcap")
            hm = None
            if enums and caps is not None:
                hm = re.match(r"^(?P<h>.{1,400}?\.?—)(?P<r>.*)$", rest, re.S)
            elif enums:
                # "(6) TIP.—The term ...": an acronym heading has no small caps
                hm = re.match(r"^(?P<h>[A-Z][^.—“”]{0,200}?\.—)(?P<r>.*)$", rest, re.S)
            if hm:
                head, rest = hm.group("h").strip(), hm.group("r").strip()
                more, rest2 = _enums(rest)              # "(b) Applicable Laws.—(1) Subtitle IV ..."
                if more:
                    lines.append(Line(depth, "", enums, head))
                    lines.append(Line(depth + 1, rest2, more, None))
                    continue
            lines.append(Line(depth, rest, enums, head))
        else:
            depth = int(re.search(r"(\d+)em", cls).group(1)) if re.search(r"(\d+)em", cls) else 0
            lines.append(Line(depth, t, [], None, block=True))
    if pending_head:
        lines.append(Line(pending_head[0], "", pending_head[2], pending_head[1]))
    return lines


def _enums(t: str) -> tuple[list[str], str]:
    """"(b)(1) The head ..." -> (["b", "1"], "The head ..."); "[(c) Repealed. ...]" -> (["[c"], "Repealed. ...]")."""
    enums = []
    while True:
        m = ENUM_RE.match(t)
        if not m or (m.group("br") and enums):
            return enums, t
        enums.append(m.group("br") + m.group("e"))
        t = t[m.end():]


# ---- levels ---------------------------------------------------------------------------------
def _candidates(e: str) -> list[str]:
    """Levels an enumerator can name: "(i)" is a subsection or a clause, "(I)" a subparagraph or a subclause,
    "(aa)" an item, "(AA)" a subitem."""
    if e[0].isdigit():
        return ["paragraph"]
    doubled = len(e) >= 2 and len(set(e)) == 1 and not is_roman(e)
    if e.islower():
        if doubled:
            return ["item", "subsection"]           # "(aa)": an item, or the subsection after "(z)"
        if len(e) == 1:
            return ["subsection", "clause"] if is_roman(e) else ["subsection"]
        return ["clause"] if is_roman(e) else ["item"]
    if doubled:
        return ["subitem", "subparagraph"]          # "(AA)": a subitem, or the subparagraph after "(Z)"
    if len(e) == 1:
        return ["subparagraph", "subclause"] if is_roman(e) else ["subparagraph"]
    return ["subclause"] if is_roman(e) else ["subitem"]


FIRST = {"subsection": "a", "paragraph": "1", "subparagraph": "A", "clause": "i", "subclause": "I",
         "item": "aa", "subitem": "AA", "subsubitem": "aaa"}


def _ordinal(level: str, e: str) -> int:
    e = e.lstrip("[")
    if level == "paragraph":
        m = re.match(r"\d+", e)
        return int(m.group(0)) * 10 + (ord(e[-1].lower()) - 96 if e[-1].isalpha() else 0)
    if level in ("clause", "subclause"):
        return roman_to_int(e) * 10 if is_roman(e) else -1
    if level in ("item", "subitem", "subsubitem"):
        return ((ord(e[0].lower()) - 96) + 26 * (len(e) - 2)) * 10
    return (ord(e[0].lower()) - 96 + 26 * (len(e) - 1)) * 10


def _place(e: str, stack: list["Unit"], depth: int) -> tuple[int, str]:
    """Where an enumerator goes: (number of stack entries to keep, level). A later label of an open unit's
    level continues it (gaps of up to 3 allow for omitted units); a first label starts a child of the top. An
    ambiguous letter ("(i)" after "(h)", "(I)" after "(H)") continues only a unit printed at its depth or deeper:
    a deeper-indented "(i)" is a clause."""
    cands = _candidates(e.lstrip("["))
    for i in range(len(stack) - 1, -1, -1):
        u = stack[i]
        if u.level in cands:
            a, b = _ordinal(u.level, u.enum), _ordinal(u.level, e)
            if 0 < b - a <= 30 and (len(cands) == 1 or depth <= u.depth):
                return i, u.level
    top = stack[-1].level if stack else None
    floor = LEVELS.index(top) if top in LEVELS else -1
    firsts = [c for c in cands if FIRST[c] == e.lstrip("[") and LEVELS.index(c) > floor]
    if firsts:
        return len(stack), min(firsts, key=LEVELS.index)
    deeper = [c for c in cands if LEVELS.index(c) > floor]
    if deeper:
        return len(stack), min(deeper, key=LEVELS.index)
    # shallower than the top and no open unit to continue: a sibling at the nearest open level above it
    lvl = min(cands, key=LEVELS.index)
    keep = len(stack)
    while keep and LEVELS.index(stack[keep - 1].level) >= LEVELS.index(lvl):
        keep -= 1
    return keep, lvl


# ---- elements ---------------------------------------------------------------------------------
def _put_text(parent: etree._Element, text: str, tag: str, notes: dict[str, str]) -> etree._Element:
    """A text element whose footnote placeholders become USLM footnote refs (with their note inline)."""
    el = etree.SubElement(parent, NS + tag)
    parts = re.split(f"{FN_OPEN}(\\d+){FN_CLOSE}", text)
    el.text = parts[0]
    last = None
    for i in range(1, len(parts), 2):
        n = parts[i]
        ref = etree.SubElement(el, NS + "ref", {"class": "footnoteRef", "idref": f"fn{n}"})
        ref.text = n
        last = ref
        if n in notes:
            note = etree.SubElement(el, NS + "note", type="footnote", id=f"fn{n}")
            num = etree.SubElement(note, NS + "num")
            num.text = n
            num.tail = " " + notes[n]
            last = note
        last.tail = parts[i + 1]
    return el


def _table(el) -> etree._Element:
    """A statute table as USLM's XHTML table module would carry it: plain rows and cells."""
    t = etree.Element("{http://www.w3.org/1999/xhtml}table")
    for row in el.iter("tr"):
        r = etree.SubElement(t, "{http://www.w3.org/1999/xhtml}tr")
        for cell in row:
            if isinstance(cell.tag, str) and cell.tag in ("td", "th"):
                c = etree.SubElement(r, "{http://www.w3.org/1999/xhtml}" + cell.tag)
                c.text = _clean(cell.text_content()).strip()
    return t


@dataclass
class Unit:
    level: str
    enum: str
    depth: int
    heading: str | None
    texts: list[tuple[str, object]] = field(default_factory=list)   # ("text", str) | ("table", el) | ("block", str)
    children: list["Unit"] = field(default_factory=list)
    after: list[tuple[str, object]] = field(default_factory=list)   # text after the children (continuation)


def build_tree(lines: list[Line]) -> tuple[list[tuple[str, object]], list[Unit], list[tuple[str, object]]]:
    """Section-level text before units, the units, and section-level text after them."""
    top: list[Unit] = []
    lead: list[tuple[str, object]] = []
    tail: list[tuple[str, object]] = []
    stack: list[Unit] = []

    def add_text(item, depth):
        # Attach to the deepest open unit shallower than (or, for flush text, at) this depth.
        while stack and stack[-1].depth > depth:
            stack.pop()
        if not stack:
            (tail if top else lead).append(item)
            return
        u = stack[-1]
        (u.after if u.children else u.texts).append(item)

    for ln in lines:
        if ln.table is not None:
            add_text(("table", ln.table), ln.depth)
            continue
        if not ln.enums:
            add_text(("block" if ln.block else "text", ln.text), ln.depth)
            continue
        for k, e in enumerate(ln.enums):
            keep, level = _place(e, stack, ln.depth + k)
            del stack[keep:]
            parent = stack[-1] if stack else None
            # A unit chained on its parent's line ("(a)(1) ...") is printed at that line's depth.
            u = Unit(level, e, ln.depth, ln.heading if k == 0 else None)
            (parent.children if parent else top).append(u)
            stack.append(u)
        if ln.text:
            stack[-1].texts.append(("text", ln.text))
    return lead, top, tail


def _emit_items(el, items, tag, notes):
    for kind, val in items:
        if kind == "table":
            _put_text(el, "", tag, notes).append(_table(val))
        elif kind == "block":
            _put_text(_put_text(el, "", tag, notes), val, "quotedContent", notes)
        else:
            _put_text(el, " " + val if tag == "content" else val, tag, notes)


def _unit_el(parent, u: Unit, base_ident: str, notes):
    label = u.enum.lstrip("[")
    ident = f"{base_ident}/{label}"
    el = etree.SubElement(parent, NS + u.level, {"class": f"indent{u.depth}", "identifier": ident})
    num = etree.SubElement(el, NS + "num", value=label)
    num.text = f"{'[' if u.enum.startswith('[') else ''}({label})"
    if u.heading:
        _put_text(el, " " + u.heading, "heading", notes)
    if u.children:
        if u.texts:
            _emit_items(el, u.texts, "chapeau", notes)
        for c in u.children:
            _unit_el(el, c, ident, notes)
        if u.after:
            _emit_items(el, u.after, "continuation", notes)
    elif u.texts:
        _emit_items(el, u.texts, "content", notes)
    return el


SEC_HEAD = re.compile(r"^\[?§+\s*(?P<num>[^.\s][^.]*?)\.(?:\s+|$)(?P<head>.*?)\]?$")


def section_element(chunk: Chunk, title: str) -> etree._Element | None:
    """One XHTML section chunk -> a USLM <section> (None for chunks that are not sections)."""
    leaf = chunk.itempath.rsplit("/", 1)[-1]
    if not re.match(r"^\[?Secs?\.\s", leaf):
        return None
    heads = [k for k in chunk.fields if k.endswith("head") and k != "structuralhead"]   # head, repealedhead, omittedhead
    head = _plain((chunk.fields.get("head") or chunk.fields[heads[0]] if heads else [""])[0])
    m = SEC_HEAD.match(head)
    first = re.sub(r"_\d+$", "", re.split(r",\s*| to ", re.sub(r"^\[?Secs?\.\s+", "", leaf).rstrip("]"))[0])
    num_value = citemod.normalize_section(first)
    sec = etree.Element(NS + "section", identifier=f"/us/usc/t{title}/s{num_value}")
    num = etree.SubElement(sec, NS + "num", value=num_value)
    bracket = head.startswith("[")             # "[§ 111. Repealed. ...]": the XML keeps the brackets
    num.text = (("[" if bracket else "") + head[:m.start("head")].strip().lstrip("[")) if m else head.split(" ", 1)[0]
    if "head" not in chunk.fields and heads:
        sec.set("status", heads[0][:-len("head")] or "unknown")      # repealed, omitted, ...
    notes = {}
    for fn in chunk.fields.get("footnote", []):
        fm = re.search(r"<sup>(\d+)</sup>(.*?)</a>", fn, re.S)
        if fm:
            notes[fm.group(1)] = _clean(htmlmod.unescape(re.sub(r"<[^>]+>", " ", fm.group(2)))).strip()
    head_text = " " + ((m.group("head") + ("]" if bracket and head.endswith("]") else "")) if m else head)
    _put_text(sec, head_text, "heading", notes)
    statute = "".join(chunk.fields.get("statute", []))
    if statute.strip():
        lead, units, tail = build_tree(statute_lines(statute))
        if units:
            if lead:
                _emit_items(sec, lead, "chapeau", notes)
            for u in units:
                _unit_el(sec, u, sec.get("identifier"), notes)
            if tail:
                _emit_items(sec, tail, "continuation", notes)
        elif lead or tail:
            _emit_items(sec, lead + tail, "content", notes)
    for credit in chunk.fields.get("sourcecredit", []):
        sc = etree.SubElement(sec, NS + "sourceCredit")
        sc.text = _plain(credit)
    note_fields = [(k, v) for k, vs in chunk.fields.items() if k.endswith("-note") for v in vs]
    if note_fields:
        ns = etree.SubElement(sec, NS + "notes", type="uscNote")
        for k, v in note_fields:
            frag = lhtml.fragment_fromstring(v, create_parent="div")
            hd = frag.find(".//h4")
            note = etree.SubElement(ns, NS + "note", topic=k.replace("-note", ""))
            if hd is not None:
                nh = etree.SubElement(note, NS + "heading")
                nh.text = _clean(hd.text_content()).strip()
            for para in frag.iter("p"):
                p = etree.SubElement(note, NS + "p")
                p.text = _clean(para.text_content()).strip()
    return sec


def title_document(chunks_: list[Chunk], title: str, name: str, positive: bool,
                   only: set[str] | None = None) -> bytes:
    """A USLM title document holding the sections (optionally only those in `only`) under their hierarchy."""
    doc = etree.Element(NS + "uscDoc", nsmap={None: USLM}, identifier=f"/us/usc/t{title}")
    meta = etree.SubElement(doc, NS + "meta")
    etree.SubElement(meta, "{http://purl.org/dc/elements/1.1/}title").text = f"Title {title}"
    pub = etree.SubElement(meta, NS + "docPublicationName")
    pub.text = name
    prop = etree.SubElement(meta, NS + "property", role="is-positive-law")
    prop.text = "yes" if positive else "no"
    main = etree.SubElement(doc, NS + "main")
    t = etree.SubElement(main, NS + "title", identifier=f"/us/usc/t{title}")
    etree.SubElement(t, NS + "num", value=title).text = f"Title {title}—"
    levels: dict[str, etree._Element] = {}
    for c in chunks_:
        sec = section_element(c, title)
        if sec is None or (only is not None and sec.get("identifier") not in only):
            continue
        parent, ident = t, f"/us/usc/t{title}"
        for step in c.itempath.strip("/").split("/")[1:-1]:
            m = re.match(r"^(\w+)\s+(.+)$", step)
            if not m or m.group(1).upper() not in HIER:
                continue
            kind, prefix = HIER[m.group(1).upper()]
            ident = f"{ident}/{prefix}{m.group(2)}"
            if ident not in levels:
                lv = etree.SubElement(parent, NS + kind, identifier=ident)
                etree.SubElement(lv, NS + "num", value=m.group(2)).text = f"{m.group(1)} {m.group(2)}—"
                levels[ident] = lv
            parent = levels[ident]
        parent.append(sec)
    return etree.tostring(doc, xml_declaration=True, encoding="utf-8")
