"""Stage 3: lines -> a tree of bill units (docs/04-draft-parser.md). Quoted blocks attach to the unit
whose text introduces them; they are never segmented as bill structure."""
from __future__ import annotations

import re

from billmap.parse.ir import Node, Span
from billmap.parse.normalize import Normalized

HEADING_RE = re.compile(r"^(DIVISION|TITLE|Subtitle|SUBTITLE|PART|Part|Subpart|SUBPART|CHAPTER|Chapter|Subchapter|"
                        r"SUBCHAPTER)\s+([A-Z0-9]+)\s*[—–-]+\s*(.*)$")
SECTION_RE = re.compile(r"^(?:SEC\.|SECTION)\s+(\d+[A-Za-z]*(?:[–-]\d+)?)\.\s*(.*)$")
ENUM_RE = re.compile(r"^\(([0-9]+[A-Za-z]?|[ivxl]{1,7}|[IVXL]{1,7}|[a-z]{1,3}|[A-Z]{1,3})\)\s*(.*)$", re.S)
HEADER_RE = re.compile(r"^([^“”—]{1,240}?)\.—(.*)$", re.S)
BLOCK_CLOSE_RE = re.compile(r"”(?:\s*[.;,:]?\s*(?:and|or)?|\.”)?\s*$")
TOC_ENTRY_RE = re.compile(r"^(?:Sec\.|Sections?\s|Subtitle|Part|Chapter|TITLE|DIVISION|Division|Title)\b")
LEVEL_PREFIX = {"division": "div", "title": "title", "subtitle": "subt", "part": "part", "subpart": "subpart",
                "chapter": "ch", "subchapter": "subch"}
HEAD_LEVELS = ["division", "title", "subtitle", "part", "subpart", "chapter", "subchapter"]
UNIT_LEVELS = ["subsection", "paragraph", "subparagraph", "clause", "subclause", "item", "subitem"]
FIRST = {"subsection": "a", "paragraph": "1", "subparagraph": "A", "clause": "i", "subclause": "I", "item": "aa",
         "subitem": "AA"}
ROMAN = re.compile(r"^(?=[ivxl]+$)m{0,0}(x{0,3})(ix|iv|v?i{0,3})$|^(l?x{0,3})(ix|iv|v?i{0,3})$", re.I)


def is_roman(s: str) -> bool:
    return bool(s) and bool(ROMAN.match(s)) and set(s.lower()) <= set("ivxl")


def roman_to_int(s: str) -> int:
    vals = {"i": 1, "v": 5, "x": 10, "l": 50}
    s = s.lower()
    total = 0
    for i, c in enumerate(s):
        v = vals[c]
        total += -v if i + 1 < len(s) and vals[s[i + 1]] > v else v
    return total


def int_to_roman(n: int) -> str:
    out = ""
    for v, r in ((50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out, n = out + r, n - v
    return out


def candidates(enum: str) -> list[str]:
    if enum[0].isdigit():
        return ["paragraph"]
    if enum.islower():
        if len(enum) == 2 and enum[0] == enum[1] and not is_roman(enum):
            return ["item"]
        return (["subsection", "clause"] if is_roman(enum) else ["subsection"]) + (["item"] if len(enum) == 2 else [])
    if len(enum) == 2 and enum[0] == enum[1] and not is_roman(enum):
        return ["subitem"]
    return ["subparagraph", "subclause"] if is_roman(enum) else ["subparagraph"]


def successor(level: str, enum: str) -> str:
    if enum[0].isdigit():
        return str(int(re.match(r"\d+", enum).group()) + 1)
    if level in ("clause", "subclause"):
        nxt = int_to_roman(roman_to_int(enum) + 1)
        return nxt if level == "clause" else nxt.upper()
    if len(enum) == 2 and enum[0] == enum[1]:
        c = chr(ord(enum[0]) + 1)
        return c + c
    if enum[-1] in "zZ":
        return enum + enum[-1]
    return enum[:-1] + chr(ord(enum[-1]) + 1)


class Segmenter:
    def __init__(self, norm: Normalized):
        self.norm = norm
        self.roots: list[Node] = []
        self.heads: dict[str, Node] = {}      # level -> current heading node
        self.section: Node | None = None
        self.units: list[Node] = []           # stack of enumerated units within the section
        self.current: Node | None = None
        self.block_lines: list[str] | None = None
        self.block_owner: Node | None = None
        self.toc = False

    # ---- helpers -------------------------------------------------------------------
    def _loc(self, level: str, key: str) -> str:
        """Bill location key, the same shape xmltext._loc builds from XML: "titleI.sec2.a.1"."""
        if level in LEVEL_PREFIX:
            idx = HEAD_LEVELS.index(level)
            parts = [LEVEL_PREFIX[lv] + self.heads[lv].enum for lv in HEAD_LEVELS[:idx] if lv in self.heads]
            return ".".join(parts + [LEVEL_PREFIX[level] + key])
        parts = [LEVEL_PREFIX[lv] + self.heads[lv].enum for lv in HEAD_LEVELS if lv in self.heads]
        if level == "section":
            return ".".join(parts + ["sec" + key])
        if self.section is not None:
            parts.append("sec" + self.section.enum)
        return ".".join(parts + [u.enum for u in self.units] + [key])

    def _attach(self, node: Node, parent: Node | None) -> None:
        (parent.children if parent is not None else self.roots).append(node)

    def _close_block(self) -> None:
        if self.block_lines is not None and self.block_owner is not None:
            text = "\n".join(self.block_lines)
            self.block_owner.block = (self.block_owner.block + "\n" + text) if self.block_owner.block else text
        self.block_lines, self.block_owner = None, None

    # ---- main ----------------------------------------------------------------------
    def run(self) -> list[Node]:
        pos = 0
        raws = self.norm.text.split("\n")
        for k, raw in enumerate(raws):
            start, end = pos, pos + len(raw)
            pos = end + 1
            line = raw.strip()
            self.next_line = next((r.strip() for r in raws[k + 1:] if r.strip()), "")
            self.raws, self.k = raws, k
            if not line:
                continue
            span = Span(start=self.norm.offsets[start], end=self.norm.offsets[end])
            if self.block_lines is not None and not line.startswith("“"):
                # Every paragraph of a quoted block opens with “; a line that does not ends an unterminated block.
                if self.block_owner is not None:
                    self.block_owner.freestanding_type = "unterminated_quoted_block"
                self._close_block()
            if self.block_lines is not None:
                self.block_lines.append(line)
                if BLOCK_CLOSE_RE.search(line):
                    self._close_block()
                continue
            if line.startswith("\u201c") and self.current is not None and (
                    self.current.text.rstrip().endswith((":", ":\u201d", "\u2014\u201d")) or
                    self.current.text.count("\u201c") > self.current.text.count("\u201d")):
                # A quoted block follows text ending "the following:" / "as follows:". Each paragraph of the
                # block opens with “; the block ends at the line that closes with ” (inner quotes are ‘ ’).
                self.block_lines, self.block_owner = [line], self.current
                if BLOCK_CLOSE_RE.search(line):
                    self._close_block()
                continue
            self._line(line, span)
        self._close_block()
        return self.roots

    def _line(self, line: str, span: Span) -> None:
        m = HEADING_RE.match(line)
        if m:
            level = {"DIVISION": "division", "TITLE": "title", "SUBTITLE": "subtitle", "Subtitle": "subtitle",
                     "PART": "part", "Part": "part", "SUBPART": "subpart", "Subpart": "subpart",
                     "CHAPTER": "chapter", "Chapter": "chapter", "SUBCHAPTER": "subchapter",
                     "Subchapter": "subchapter"}[m.group(1)]
            if self.toc and not SECTION_RE.match(self.next_line) and not HEADING_RE.match(self.next_line):
                self._toc_line(line, span)
                return
            self.toc = False
            node = Node(loc="", level=level, enum=m.group(2), header=m.group(3).strip(), span=span, cls="STRUCTURAL")
            idx = HEAD_LEVELS.index(level)
            for lv in HEAD_LEVELS[idx:]:
                self.heads.pop(lv, None)
            node.loc = self._loc(level, m.group(2))
            parent = next((self.heads[lv] for lv in reversed(HEAD_LEVELS[:idx]) if lv in self.heads), None)
            self._attach(node, parent)
            self.heads[level] = node
            self.section, self.units, self.current = None, [], node
            return
        m = SECTION_RE.match(line)
        if m:
            self.toc = False
            enum = m.group(1)
            node = Node(loc="", level="section", enum=enum, header=m.group(2).rstrip(".").strip() or None, span=span,
                        cls="STRUCTURAL")
            parent = next((self.heads[lv] for lv in reversed(HEAD_LEVELS) if lv in self.heads), None)
            self.section, self.units = None, []
            node.loc = self._loc("section", enum)
            self._attach(node, parent)
            self.section, self.current = node, node
            if node.header and "TABLE OF CONTENTS" in node.header.upper():
                self.toc = True
            return
        if self.toc and (TOC_ENTRY_RE.match(line) or (self.section and not ENUM_RE.match(line)
                                                        and "is as follows" not in line)):
            self._toc_line(line, span)
            return
        m = ENUM_RE.match(line)
        if m and self.section is not None:
            self._unit(m.group(1), m.group(2), span)
            return
        # Unenumerated text: the section's own text, or continuation text of the current unit.
        target = self.current if self.current is not None else None
        if target is None:
            node = Node(loc="pre", level="text", text=line, span=span)
            self.roots.append(node)
            self.current = node
            return
        target.text = (target.text + "\n" + line) if target.text else line
        target.span = Span(start=target.span.start, end=span.end)
        if "table of contents" in line.lower() and "is as follows" in line.lower():
            self.toc = True

    def decide(self, child: str, enum: str, cont: Node) -> str:
        """Ambiguous "(i)"/"(I)": read ahead to the first enumerator that follows on from an open unit.
        Its successor at the child level ("(ii)") or at a unit below `cont` ("(F)" after "(E)") means the
        enumerator opened a child level; the successor of `cont` itself ("(j)" after "(h)"), or of a unit above
        it, means it continued that sequence."""
        child_next = successor(child, enum)
        below = {successor(u.level, u.enum) for u in self.units[self.units.index(cont) + 1:]}
        above = {successor(u.level, u.enum) for u in self.units[:self.units.index(cont)]}
        cont_next = successor(cont.level, enum)
        in_block = False
        for raw in self.raws[self.k + 1:]:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("\u201c") or in_block:
                in_block = not BLOCK_CLOSE_RE.search(line)
                continue
            if SECTION_RE.match(line) or HEADING_RE.match(line):
                return "child"
            m = ENUM_RE.match(line)
            if not m:
                continue
            e = m.group(1)
            if e == child_next or e in below:
                return "child"
            if e == cont_next or e in above:
                return "continue"
        return "child"

    def _toc_line(self, line: str, span: Span) -> None:
        owner = self.section or self.current
        node = Node(loc=(owner.loc if owner else "toc") + ".toc", level="toc", text=line, span=span,
                    cls="TABLE_OF_CONTENTS")
        if owner is not None:
            owner.children.append(node)
        else:
            self.roots.append(node)

    def _unit(self, enum: str, rest: str, span: Span) -> None:
        cands = candidates(enum)
        level = None
        deepest = UNIT_LEVELS.index(self.units[-1].level) if self.units else -1
        child = UNIT_LEVELS[deepest + 1] if deepest + 1 < len(UNIT_LEVELS) else None
        # "(i)" under a subparagraph, "(I)" under a clause: the first value of the next level down opens it,
        # rather than continuing "(h)" or "(H)" higher up.
        if child in cands and enum == FIRST.get(child):
            level = child
            cont = next((u for u in reversed(self.units) if u.level in cands and successor(u.level, u.enum) == enum),
                        None)
            if cont is not None:
                # Both readings fit ("(I)" after "(H)" with a clause open). The next enumerator decides:
                # "(II)" means a new deeper level; anything else means the sequence continues.
                if self.decide(child, enum, cont) == "continue":
                    level = None
        # Otherwise continue an open level whose next expected enumerator is this one (pop deeper levels).
        for i in range(len(self.units) - 1, -1, -1) if level is None else ():
            u = self.units[i]
            if u.level in cands and successor(u.level, u.enum) == enum:
                level = u.level
                self.units = self.units[:i]
                break
        if level is None:
            deepest = UNIT_LEVELS.index(self.units[-1].level) if self.units else -1
            deeper = [c for c in cands if UNIT_LEVELS.index(c) > deepest]
            level = min(deeper, key=UNIT_LEVELS.index) if deeper else cands[0]
            while self.units and UNIT_LEVELS.index(self.units[-1].level) >= UNIT_LEVELS.index(level):
                self.units.pop()
        header, text = None, rest
        h = HEADER_RE.match(rest)
        # A header ends with ".—" ("In general.—"); lowercase starts are instruction text, never headers.
        if h and not h.group(1).strip().startswith(("in ", "by ")) and len(h.group(1).split()) <= 32:
            header, text = h.group(1).strip(), h.group(2).strip()
        node = Node(loc=self._loc(level, enum), level=level, enum=enum, header=header, text=text, span=span)
        parent = self.units[-1] if self.units else self.section
        self._attach(node, parent)
        self.units.append(node)
        self.current = node
        nested = ENUM_RE.match(text)       # "(a) In general.—(1) ..." or "(4)(A) ..."
        if nested and text.startswith("(") and header is not None:
            node.text = ""
            self._unit(nested.group(1), nested.group(2), span)


def walk(nodes: list[Node]):
    for n in nodes:
        yield n
        yield from walk(n.children)
