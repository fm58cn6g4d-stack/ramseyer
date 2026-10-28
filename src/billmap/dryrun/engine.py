"""Dry-run engine (docs/06-dry-run.md): apply instructions to a working copy of real section XML, in bill order.

The working copy is the section's USLM element at the baseline release point; the stored statute is never
touched. Text edits operate on a linear view of the scope's text (with a map back to the XML text nodes), so
a match may cross inline markup. New units from quoted blocks are built as USLM elements, so the result
renders with the same extractor the index uses (indexer.text_of) and compares like for like.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Literal

from lxml import etree

from billmap.data.indexer import NON_OPERATIVE, SUB, USLM, local, text_of
from billmap.parse.ir import Instruction
from billmap.parse.normalize import normalize
from billmap.parse.segment import Segmenter, walk

Status = Literal["CLEAN", "WARN", "AMBIGUOUS", "NOT_FOUND", "TARGET_MISSING", "STALE_BASELINE", "CONFLICT",
                 "UNPARSED", "NOT_APPLICABLE"]
SEVERITY = ["CLEAN", "NOT_APPLICABLE", "WARN", "AMBIGUOUS", "STALE_BASELINE", "CONFLICT", "NOT_FOUND",
            "TARGET_MISSING", "UNPARSED"]
NS = f"{{{USLM}}}"
STRUCTURAL = re.compile(r"^\u201c?\(\w{1,6}\)\s|\u2014\u201c?\(\w{1,6}\)|\.\u2014")
ACT_REF = re.compile(r"\b(?:[Ss]ection|[Tt]itle|[Ss]ubtitle|[Cc]hapter|[Ss]ubchapter|[Pp]art) (?:\d+[A-Za-z]?|[IVXL]+)"
                     r"(?:\([\w]+\))*(?![\w\u2013-])(?! of (?:title \d+|this title|this chapter|such title))"
                     r"(?! of the )(?!,? United States Code)(?! of Public Law)(?! \()"
                     r"|\bthis (?:title|Act|subtitle)\b")
MARGINS = re.compile(r",? and (?:by )?(?:adjusting|moving) the (?:margins|indentation)[^;.]*(?:[;.]|; and)?")
LEVEL_TAGS = {"subsection", "paragraph", "subparagraph", "clause", "subclause", "item", "subitem"}


@dataclass
class Result:
    instruction_id: str
    status: Status
    detail: str = ""
    evidence: str = ""                 # ~200 characters around the edit (after applying), for the report
    before_span: str | None = None
    after_span: str | None = None
    matches: int = 0


@dataclass
class Seg:
    node: etree._Element
    attr: str                          # "text" or "tail"
    kind: str                          # body, num, heading
    start: int = 0


# ---- quotes --------------------------------------------------------------------------------
def nested_to_double(s: str) -> str:
    """Bills quote inside quotes with ‘ ’; the Code prints those as “ ”. Apostrophes (applicant’s) stay."""
    return re.sub(r"(?<![\w])‘([^‘’]*?)’(?![\w])", "“\\1”", s)


def fold(s: str, case: bool = False) -> tuple[str, list[int]]:
    """Whitespace collapsed and quotes folded, with a map from folded index to original index."""
    out, idx = [], []
    prev_space = False
    for i, ch in enumerate(s):
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            idx.append(i)
            prev_space = True
            continue
        prev_space = False
        ch = {"“": '"', "”": '"', "‘": "'", "’": "'"}.get(ch, ch)
        out.append(ch.lower() if case else ch)
        idx.append(i)
    idx.append(len(s))
    return "".join(out), idx


# ---- OLRC's editorial form of Act cross-references ------------------------------------------
ACT_XREF = re.compile(r"section (?P<sec>[\w\u2013.-]+?(?:\([\w]+\))*) of (?:the )?(?P<act>[A-Z][^()\u201c\u201d]*?"
                      r"(?:Act|Code)(?: of \d{4})?) \((?P<t>\d+) U\.S\.C\. (?P<z>[\w\u2013.-]+?(?:\([\w]+\))*)\)")


# Measured on the subsection headings of titles 10, 14 and 46 (records/milestones.md, M6): these stay lowercase;
# "with", "from", "under", "upon" and other prepositions are capitalized.
SMALL = {"a", "an", "and", "as", "at", "but", "by", "for", "if", "in", "nor", "of", "on", "or", "the", "to", "via"}


def title_case(s: str) -> str:
    """OLRC's subsection-heading case in positive-law titles: every word capitalized except the SMALL words after
    the first; the part of a hyphenated compound after the hyphen is left as drafted (measured: lowercase in 210
    of 378 subsection headings of titles 10, 14 and 46)."""
    def cap(w):
        return w if w.isupper() and len(w) > 1 else w[:1].upper() + w[1:]
    out = []
    for i, w in enumerate(s.split(" ")):
        if i > 0 and w.lower() in SMALL:
            out.append(w.lower())
        else:
            head, sep, rest = w.partition("-")
            out.append(cap(head) + sep + rest)          # after a hyphen, as drafted ("Life-cycle", "Safe-to-Report")
    return " ".join(out)


def sentence_case(s: str) -> str:
    """OLRC's heading case below the subsection in positive-law titles: the bill's small-caps heading set in
    lowercase after the first letter ("Senior leader of the coast guard"); all-capital acronyms are kept."""
    words = s.split(" ")
    return " ".join(w if (w.isupper() and len(w) > 1) or i == 0 else w.lower() for i, w in enumerate(words))


def heading_case(heads: list[str]) -> str | None:
    """"title" or "sentence": the case style of existing headings, judged by their capitalizable words."""
    up = low = 0
    for h in heads:
        for w in h.split(" ")[1:]:
            if w.isalpha() and w.lower() not in SMALL and not w.isupper():
                up, low = up + w[0].isupper(), low + w[0].islower()
    if up + low == 0:
        return None
    return "title" if up > low else "sentence"


def heading_form(text: str, level: str, positive_law: bool, dash: bool | None = None,
                 case: str | None = None) -> str:
    """How OLRC prints an inserted unit's heading (measured on the corpus, records/milestones.md M6):
    positive-law titles title-case subsection headings; ".—" follows the section's existing style (`dash`),
    by default kept in positive-law titles and dropped in others."""
    text = text.strip().rstrip(".\u2014").strip()
    dash = positive_law if dash is None else dash
    if positive_law and case is None:
        case = "title" if level in ("subsection", "section") else "sentence"
    if case == "title":
        text = title_case(text)
    elif case == "sentence":
        text = sentence_case(text)
    return text + (".\u2014" if dash else "")


def code_form(text: str, title: str) -> str:
    """In a non-positive-law title the Code prints "section 2062 of the 21st Century Cures Act (42 U.S.C. 284s)"
    as "section 284s of this title" (or "of title N" for another title). Verified on 42 U.S.C. 247b-23(b)."""
    def sub(m):
        z = m.group("z").replace("-", "\u2013")
        return f"section {z} of this title" if m.group("t") == title else f"section {z} of title {m.group('t')}"
    text = ACT_XREF.sub(sub, text)
    # "title 49, United States Code" is printed "title 49" in non-positive-law titles.
    return re.sub(r"\b(title \d+), United States Code\b", r"\1", text)


# ---- the working copy -----------------------------------------------------------------------
class Working:
    def __init__(self, xml: str | None, identifier: str, positive_law: bool = True):
        self.identifier = identifier
        self.title = identifier.split("/")[3][1:]
        self.positive_law = positive_law
        self.el = etree.fromstring(xml.encode("utf-8")) if xml is not None else None
        self.original = copy.deepcopy(self.el) if self.el is not None else None
        self.removed = False
        self.dash = self._heading_style()
        self.case: dict[str, str | None] = {}
        if self.el is not None and positive_law:
            # The case style of existing headings at each level, which OLRC follows for inserted units.
            by_level: dict[str, list[str]] = {}
            for h in self.el.iter(NS + "heading"):
                lvl = local(h.getparent())
                if lvl in LEVEL_TAGS:
                    by_level.setdefault(lvl, []).append(text_of(h).strip().rstrip(".\u2014"))
            self.case = {lvl: heading_case(hs) for lvl, hs in by_level.items()}

    def _heading_style(self) -> bool:
        """Whether this section prints unit headings with ".—". OLRC follows the section's existing style (the
        Toxic Substances Control Act in title 15 keeps ".—" though the title is not positive law); a section
        with no unit headings gets the title's default."""
        if self.el is None:
            return self.positive_law
        heads = [text_of(h).strip() for h in self.el.iter(NS + "heading") if local(h.getparent()) in LEVEL_TAGS]
        heads = [h for h in heads if h]
        if not heads:
            return self.positive_law
        return sum(h.endswith(".\u2014") for h in heads) * 2 >= len(heads)

    def render(self) -> str | None:
        if self.removed or self.el is None:
            return None
        return text_of(self.el)

    # units ---------------------------------------------------------------------------------
    def unit(self, path: list[str], root=None):
        el = root if root is not None else self.el
        for lab in path:
            want = lab.strip("()")
            nxt = None
            for c in el:
                if local(c) in SUB or local(c) in ("section",):
                    num = c.find(NS + "num")
                    if num is not None and (num.get("value") == want or
                                            "".join(num.itertext()).strip().strip("().") == want):
                        nxt = c
                        break
            if nxt is None:
                return None
            el = nxt
        return el

    @staticmethod
    def segments(scope, include_children=True) -> list[Seg]:
        segs: list[Seg] = []

        def walk_el(e, kind):
            name = local(e)
            if name in NON_OPERATIVE:
                return
            k = "num" if name == "num" else ("heading" if name == "heading" else kind)
            if e.text:
                segs.append(Seg(e, "text", k))
            for c in e:
                if local(c) in NON_OPERATIVE:
                    if c.tail:
                        segs.append(Seg(c, "tail", kind))
                    continue
                if not include_children and local(c) in SUB:
                    if c.tail:
                        segs.append(Seg(c, "tail", kind))
                    continue
                walk_el(c, k)
                if c.tail:
                    segs.append(Seg(c, "tail", kind))
        walk_el(scope, "body")
        pos = 0
        for s in segs:
            s.start = pos
            pos += len(getattr(s.node, s.attr) or "")
        return segs


def linear(segs: list[Seg]) -> str:
    return "".join(getattr(s.node, s.attr) or "" for s in segs)


def replace_span(segs: list[Seg], start: int, end: int, new: str) -> None:
    """Replace linear [start, end) with `new`, editing the XML text nodes it covers."""
    placed = False
    for s in segs:
        txt = getattr(s.node, s.attr) or ""
        s_end = s.start + len(txt)
        if s_end < start or s.start > end or (s_end == start and (placed or end > start)):
            continue
        a, b = max(start, s.start) - s.start, min(end, s_end) - s.start
        if a > len(txt) or b < 0:
            continue
        piece = new if not placed else ""
        if not placed and (s_end >= start):
            placed = True
        setattr(s.node, s.attr, txt[:a] + piece + txt[b:])
    if not placed and segs:
        s = segs[-1]
        setattr(s.node, s.attr, (getattr(s.node, s.attr) or "") + new)


def find_all(hay: str, needle: str, allowed: list[tuple[int, int]]) -> tuple[list[tuple[int, int]], str]:
    """All matches of needle in hay inside allowed ranges: exact, then folded, then folded case-insensitive."""
    def inside(a, b):
        return any(lo <= a and b <= hi for lo, hi in allowed)

    def bounded(a, b):
        # A quoted word matches whole words only: "term" is not found inside "determines".
        lead = hay[a:a + 1].isalnum() and a > 0 and hay[a - 1].isalnum()
        trail = hay[b - 1:b].isalnum() and b < len(hay) and hay[b].isalnum()
        return not (lead or trail)

    hits = [(m.start(), m.start() + len(needle)) for m in re.finditer(re.escape(needle), hay)]
    hits = [h for h in hits if inside(*h) and bounded(*h)]
    if hits:
        return hits, "exact"
    for case, how in ((False, "normalized"), (True, "case-insensitive")):
        fh, fmap = fold(hay, case)
        fn, _ = fold(needle.strip(), case)
        if not fn:
            return [], how
        out = []
        for m in re.finditer(re.escape(fn), fh):
            a, b = fmap[m.start()], fmap[m.end() - 1] + 1
            if inside(a, b) and bounded(a, b):
                out.append((a, b))
        if out:
            return out, how
    return [], "none"


# ---- spacing at edit boundaries ----------------------------------------------------------------
WORD_END = re.compile(r"[\w).,;:\u201d\"'%]$")
WORD_START = re.compile(r"^[\w(\u201c$]")
CLOSE_PUNCT = ".,;:)"
SECTION_LINE = re.compile(r"^(?:§+|SEC\.|Sec\.)\s*([\w–-]+(?:\.\d+)?)\.\s*(.*)$")
DIVISION_LINE = re.compile(r"^(?:SUBCHAPTER|Subchapter|CHAPTER|Chapter|PART|Part|SUBPART|Subpart) [\w–-]+\s*[\u2014-]")
EDITORIAL_CITE = re.compile(r" \[\d+ U\.S\.C\. [^\]]*\]")


def tidy(hay: str, a: int, b: int, new: str, join: str) -> tuple[int, int, str]:
    """Spacing the way the Code sets an amended text: an insertion is separated from the words around it by
    one space, and a strike does not leave a double space or a space before closing punctuation.

    join: "after" (new follows the anchor hay[a:b]), "before" (new precedes it) or "replace".
    Returns the span to replace and the replacement, adjusted.
    """
    if join == "replace":
        old = hay[a:b]
        # The bracketed Code cite OLRC sets after an Act's name goes with the name when the name is struck.
        m = EDITORIAL_CITE.match(hay, b)
        if m and re.search(r"\bAct(?: of \d{4})?$", old):
            b = m.end()
        if new and old[:1].isspace() and not new[:1].isspace():
            new = old[:1] + new
        if new and old[-1:].isspace() and not new[-1:].isspace():
            new = new + old[-1:]
    left, right = hay[:a], hay[b:]
    if join == "after":
        old = hay[a:b]
        if new and old and not new[0].isspace() and WORD_END.search(old) and WORD_START.match(new):
            new = old + " " + new
        else:
            new = old + new
        if new and right and not new[-1].isspace() and not right[0].isspace() and new[-1].isalnum() \
                and right[0].isalnum():
            new += " "
    elif join == "before":
        old = hay[a:b]
        if new and old and not new[-1].isspace() and WORD_START.match(old) and WORD_END.search(new):
            new = new + " " + old
        else:
            new = new + old
        if new and left and not new[0].isspace() and not left[-1].isspace() and new[0].isalnum() \
                and left[-1].isalnum():
            new = " " + new
    lc = left[-1:] if not new or not new[0].isspace() else " "
    rc = right[:1]
    if not new or new.isspace():
        new = ""
        if lc == " " and rc == " ":
            b += 1
        elif lc == " " and rc and rc in CLOSE_PUNCT:
            a -= 1
        elif lc == " " and not rc:
            a -= 1
    else:
        if new[0] == " " and left.endswith(" "):
            new = new[1:]
        if new[0] in CLOSE_PUNCT and left.endswith(" ") and not hay[a:a + 1].isspace():
            a -= 1
        if new.endswith(" ") and right.startswith(" "):
            new = new[:-1]
        if new.endswith(" ") and rc and rc in CLOSE_PUNCT:
            new = new[:-1]
    return a, b, new


# ---- new units from quoted blocks -------------------------------------------------------------
def block_lines(block: str) -> list[str]:
    lines = []
    for raw in block.split("\n"):
        s = raw.strip()
        if s.startswith("“"):
            s = s[1:]
        lines.append(s)
    if lines:
        lines[-1] = re.sub(r"”[\s.;,:]*(?:and|or)?[\s.;,:]*$", "", lines[-1])
    return [nested_to_double(x) for x in lines if x]


def build_units(block: str, positive_law: bool = False, dash: bool | None = None,
                case: dict[str, str | None] | None = None) -> tuple[list[etree._Element], list[str]]:
    """Quoted block -> USLM unit (or section) elements. Returns (elements, plain text lines that had no unit)."""
    lines = block_lines(block)
    sec_re = SECTION_LINE
    starts = [i for i, x in enumerate(lines) if sec_re.match(x)]
    if starts and (starts[0] == 0 or all(DIVISION_LINE.match(x) for x in lines[:starts[0]])):
        if len(starts) > 1 or starts[0] > 0:
            # Several new sections (perhaps under a new subchapter heading): one element per section.
            out = []
            for a, b in zip(starts, starts[1:] + [len(lines)]):
                chunk = [x for x in lines[a:b] if not DIVISION_LINE.match(x)]
                out += build_units("\n".join("\u201c" + x for x in chunk) + "\u201d", positive_law, dash, case)[0]
            return out, []
        m = sec_re.match(lines[0])
        sec = etree.Element(NS + "section")
        num = etree.SubElement(sec, NS + "num", value=m.group(1))
        num.text = f"§ {m.group(1)}."
        h = etree.SubElement(sec, NS + "heading")
        h.text = " " + m.group(2).rstrip(".")
        units, loose = build_units("\n".join("\u201c" + x for x in lines[1:]) + "\u201d", positive_law, dash, case) \
            if len(lines) > 1 else ([], [])
        if loose:
            c = etree.SubElement(sec, NS + "content")
            c.text = " " + " ".join(loose)
        for u in units:
            sec.append(u)
        return [sec], []
    if not lines or not re.match(r"^\(", lines[0]):
        return [], lines
    text = "SEC. 0. X.\n" + "\n".join(lines) + "\n"
    nodes = Segmenter(normalize(text)).run()
    section = next((n for n in walk(nodes) if n.level == "section"), None)
    if section is None:
        return [], lines

    def make(node) -> etree._Element:
        tag = node.level if node.level in LEVEL_TAGS else "paragraph"
        el = etree.Element(NS + tag)
        num = etree.SubElement(el, NS + "num", value=node.enum)
        num.text = f"({node.enum})"
        if node.header:
            h = etree.SubElement(el, NS + "heading")
            h.text = " " + heading_form(node.header, tag, positive_law, dash, (case or {}).get(tag))
        body = node.text.split("\n")
        first, rest = body[0], body[1:]
        if node.children:
            if first:
                ch = etree.SubElement(el, NS + "chapeau")
                ch.text = first
            for c in node.children:
                el.append(make(c))
            for r in rest:
                cont = etree.SubElement(el, NS + "continuation")
                cont.text = r
        elif first or rest:
            ct = etree.SubElement(el, NS + "content")
            ct.text = " " + " ".join(x for x in [first] + rest if x)
        return el

    return [make(c) for c in section.children], []


# ---- the engine ------------------------------------------------------------------------------
@dataclass
class Engine:
    work: Working
    results: list[Result] = field(default_factory=list)

    def run(self, ins: Instruction, path: list[str]) -> Result:
        r = self._run(ins, path)
        if r.status == "CLEAN":
            r.status, r.detail = self._review(ins, r)
        if r.status == "CLEAN":
            loose = [f for f in ins.flags if f.startswith("expected a quoted block") or
                     (f.startswith("unconsumed") and not MARGINS.fullmatch(f[len("unconsumed: "):].strip()))]
            if loose:
                # The parser left part of the instruction unread, so a clean edit may be an incomplete one.
                r.status, r.detail = "WARN", "; ".join(x for x in (r.detail, "parser left text unread: " +
                                                                    loose[0][:120]) if x)
        self.results.append(r)
        return r

    def _review(self, ins: Instruction, r: Result) -> tuple[str, str]:
        """Downgrade a clean edit to WARN where the Code is known to set the result differently from the literal
        text: a text edit that adds an enumerated unit or heading (set as structure), Act references in inserted
        text in a non-positive-law title (set in Code form by OLRC), and a whole-section repeal (removed or set
        out as a stub)."""
        why = None
        added = ins.replace if ins.replace is not None else ins.new_text
        text_op = ins.op in ("STRIKE_INSERT", "INSERT_AFTER", "INSERT_BEFORE", "STRIKE_THROUGH", "AMEND_HEADING")
        if text_op and added and (STRUCTURAL.search(added) or "\n" in added.strip()):
            why = "the inserted text adds an enumerated unit or heading, which the Code sets as structure"
        elif added and not self.work.positive_law and ACT_REF.search(self._tr(nested_to_double(added))):
            why = ("the inserted text refers to a provision of the Act; the Code sets such references in Code form, "
                   "which needs the Act-to-Code map")
        elif ins.op == "REPEAL" and r.detail == "section repealed":
            why = "a repealed section is removed or set out as a stub in the Code"
        if why:
            return "WARN", "; ".join(x for x in (r.detail, why) if x)
        return r.status, r.detail

    def _scope(self, path: list[str]):
        if self.work.el is None:
            return None
        return self.work.unit(path)

    def _allowed(self, segs, ins: Instruction, find: str | None):
        quals = ins.target.qualifiers
        kinds = {"body"}
        if ins.op == "AMEND_HEADING" or any(q.endswith("heading") for q in quals):
            kinds = {"heading"}
        if find and re.match(r"^\(\w+\)", find):
            kinds.add("num")
        ranges = [(s.start, s.start + len(getattr(s.node, s.attr) or "")) for s in segs if s.kind in kinds]
        merged: list[tuple[int, int]] = []
        for a, b in ranges:
            if merged and merged[-1][1] == a:
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        return merged

    def _qualified_scope(self, scope, ins: Instruction):
        """Matter preceding/following a unit narrows the scope to the chapeau or continuation."""
        for q in ins.target.qualifiers:
            m = re.match(r"matter (preceding|following) \w+ (\(\w+\))", q)
            if m:
                tag = "chapeau" if m.group(1) == "preceding" else "continuation"
                el = scope.find(NS + tag)
                return el, f"{q}"
        return scope, None

    def _sentence_range(self, hay: str, which: str, allowed):
        lo = allowed[0][0] if allowed else 0
        hi = allowed[-1][1] if allowed else len(hay)
        body = hay[lo:hi]
        bounds = [0] + [m.end() for m in re.finditer(r"(?<=[.])\s+(?=[A-Z(“])", body)] + [len(body)]
        spans = [(lo + bounds[i], lo + bounds[i + 1]) for i in range(len(bounds) - 1)]
        idx = {"first": 0, "second": 1, "third": 2, "fourth": 3, "last": -1}[which]
        try:
            return [spans[idx]]
        except IndexError:
            return []

    def _run(self, ins: Instruction, path: list[str]) -> Result:
        rid = ins.id
        if ins.op == "UNPARSED":
            return Result(rid, "UNPARSED", ins.reason or "")
        if ins.op == "CONFORM_TOC":
            return Result(rid, "NOT_APPLICABLE", "table of contents edit; section text unaffected")
        if self.work.el is None and ins.op not in ("REPLACE_UNIT",):
            return Result(rid, "TARGET_MISSING", f"{self.work.identifier} does not exist at the baseline")
        if ins.op == "REPEAL" and not path:
            self.work.removed = True
            return Result(rid, "CLEAN", "section repealed")
        scope = self._scope(path) if self.work.el is not None else None
        if scope is None and not (ins.op == "REPLACE_UNIT" and not path and self.work.el is None):
            return Result(rid, "TARGET_MISSING", f"no unit {''.join(path)} in {self.work.identifier}")
        handler = getattr(self, "_op_" + ins.op.lower(), None)
        if handler is None:
            return Result(rid, "AMBIGUOUS", f"op {ins.op} not supported by the engine")
        return handler(ins, scope, path)

    # text edits -------------------------------------------------------------------------------
    def _locate(self, ins, scope, find, positional=False):
        target_scope, qnote = self._qualified_scope(scope, ins)
        if target_scope is None:
            return None, None, [], "TARGET_MISSING", f"no {qnote} in the unit"
        segs = Working.segments(target_scope)
        hay = linear(segs)
        allowed = self._allowed(segs, ins, find)
        for q in ins.target.qualifiers:
            m = re.match(r"(first|second|third|fourth|last) sentence", q)
            if m:
                allowed = self._sentence_range(hay, m.group(1), allowed)
        hits, how = find_all(hay, find, allowed)
        if positional and hits:
            end = max(b for _, b in allowed) if allowed else len(hay)
            tail_ok = [h for h in hits if not hay[h[1]:end].strip(" \n\t")]
            hits = tail_ok[-1:] if tail_ok else []
        return segs, hay, hits, how, None

    def _choose(self, ins, hits):
        if ins.occurrence == "each":
            return hits, None
        if ins.occurrence.startswith("nth:"):
            n = int(ins.occurrence[4:])
            return (hits[n - 1:n], None) if len(hits) >= n else ([], f"only {len(hits)} occurrences")
        if ins.occurrence == "last":
            return hits[-1:], None
        if len(hits) > 1:
            return hits[:1], f"{len(hits)} occurrences and no 'each place it appears'; applied to the first"
        return hits, None

    def _status_for_missing(self, ins, find, path):
        """NOT_FOUND, or CONFLICT when the text existed at the baseline and an earlier instruction removed it."""
        if self.work.original is not None:
            orig = self.work.unit(path, root=self.work.original) if path else self.work.original
            if orig is not None:
                h, _ = find_all(text_of(orig), find, [(0, 10 ** 9)])
                if h:
                    return "CONFLICT", "present at the baseline; an earlier instruction in this bill changed it"
        return "NOT_FOUND", "quoted text is absent from the target"

    def _tr(self, text: str) -> str:
        return text if self.work.positive_law else code_form(text, self.work.title)

    def _edit(self, ins, scope, path, find, make_new, positional=False, label="", join="replace"):
        segs, hay, hits, how, err = self._locate(ins, scope, find, positional)
        if err:
            return Result(ins.id, "TARGET_MISSING", err)
        if not hits and self._tr(find) != find:
            segs, hay, hits, how, err = self._locate(ins, scope, self._tr(find), positional)
            how = "with Act cross-references in Code form"
        if not hits:
            st, why = self._status_for_missing(ins, find, path)
            return Result(ins.id, st, f"{why}: “{find[:80]}”")
        chosen, warn = self._choose(ins, hits)
        if not chosen:
            return Result(ins.id, "NOT_FOUND", warn or "occurrence not found", matches=len(hits))
        before = hay[chosen[0][0]:chosen[0][1]]
        for a, b in sorted(chosen, reverse=True):
            piece = make_new(hay[a:b])
            if join != "replace":
                piece = piece[b - a:] if join == "after" else piece[:len(piece) - (b - a)]
            a2, b2, piece = tidy(hay, a, b, piece, join)
            replace_span(segs, a2, b2, piece)
        after_hay = linear(Working.segments(scope))
        ev_at = max(0, chosen[0][0] - 80)
        status = "AMBIGUOUS" if warn else ("WARN" if how in ("case-insensitive",
                                                              "with Act cross-references in Code form") else "CLEAN")
        detail = "; ".join(x for x in (label, warn, f"matched {how}" if how != "exact" else "") if x)
        return Result(ins.id, status, detail, evidence=after_hay[ev_at:ev_at + 200], before_span=before,
                      after_span=make_new(before), matches=len(hits))

    def _op_strike_insert(self, ins, scope, path):
        new = self._tr(nested_to_double(ins.replace if ins.replace is not None else
                                        "\n".join(block_lines(ins.new_text or ""))))
        positional = any(f.startswith("positional") for f in ins.flags)
        return self._edit(ins, scope, path, nested_to_double(ins.find or ""), lambda old: new, positional)

    def _op_amend_heading(self, ins, scope, path):
        """A heading edit: the parser records the underlying op ("heading edit (INSERT_AFTER)"); the scope is
        limited to the heading by _allowed."""
        m = next((re.search(r"heading edit \((\w+)\)", f) for f in ins.flags if "heading edit" in f), None)
        op = m.group(1).lower() if m else "strike_insert"
        handler = getattr(self, "_op_" + op, None)
        if handler is None:
            return Result(ins.id, "AMBIGUOUS", f"heading edit with op {op} not supported")
        return handler(ins, scope, path)

    def _op_strike(self, ins, scope, path):
        if ins.unit and ins.unit.endswith("sentence"):
            segs = Working.segments(scope)
            hay = linear(segs)
            rng = self._sentence_range(hay, ins.unit.split()[0], self._allowed(segs, ins, None))
            if not rng:
                return Result(ins.id, "NOT_FOUND", f"no {ins.unit}")
            a, b = rng[0]
            replace_span(segs, a, b, "")
            return Result(ins.id, "CLEAN", f"struck the {ins.unit}")
        positional = any(f.startswith("positional") for f in ins.flags)
        return self._edit(ins, scope, path, nested_to_double(ins.find or ""), lambda old: "", positional)

    def _insert(self, ins, scope, path, after: bool):
        if ins.find is None or any(f.startswith("anchor is a unit") for f in ins.flags):
            return Result(ins.id, "AMBIGUOUS", f"insertion anchored on {ins.find!r}: not a quoted anchor the "
                          "engine applies")
        if ins.new_text is None:
            return Result(ins.id, "UNPARSED", "insertion with no quoted text to insert")
        new = nested_to_double(ins.new_text)
        if "\n" in new or new.startswith("\u201c"):
            new = " ".join(block_lines(new))
        new = self._tr(new)
        positional = any(f.startswith("anchor is positional") for f in ins.flags)
        return self._edit(ins, scope, path, nested_to_double(ins.find), (lambda old: old + new) if after else
                          (lambda old: new + old), positional, join="after" if after else "before")

    def _op_insert_after(self, ins, scope, path):
        return self._insert(ins, scope, path, True)

    def _op_insert_before(self, ins, scope, path):
        return self._insert(ins, scope, path, False)

    def _op_strike_through(self, ins, scope, path):
        segs, hay, hits, how, err = self._locate(ins, scope, nested_to_double(ins.find or ""))
        if err:
            return Result(ins.id, "TARGET_MISSING", err)
        if not hits:
            st, why = self._status_for_missing(ins, nested_to_double(ins.find or ""), path)
            return Result(ins.id, st, f"{why}: start “{(ins.find or '')[:60]}”")
        start = hits[0][0]
        allowed_end = max(b for _, b in self._allowed(segs, ins, ins.find)) if segs else len(hay)
        through = ins.through or "end of unit"
        if through.startswith("end") or through.startswith("the end") or "at the end" in through:
            end = allowed_end
            # keep the unit's terminal punctuation when the strike runs "through the end"
        else:
            th, _ = find_all(hay, nested_to_double(through), [(start, allowed_end)])
            if not th:
                return Result(ins.id, "NOT_FOUND", f"end anchor “{through[:60]}” not found after the start")
            end = th[0][1]
        new = ins.replace if ins.replace is not None else (ins.new_text or "")
        if "\n" in new or new.startswith("\u201c"):
            new = " ".join(block_lines(new))
        new = self._tr(nested_to_double(new))
        a, b, piece = tidy(hay, start, end, new, "replace")
        replace_span(segs, a, b, piece)
        status = "AMBIGUOUS" if len(hits) > 1 else "CLEAN"
        return Result(ins.id, status, "struck through" + (f"; {len(hits)} start matches" if len(hits) > 1 else ""),
                      before_span=hay[start:end], after_span=new, matches=len(hits))

    # unit edits -------------------------------------------------------------------------------
    def _children_named(self, scope, unit_phrase: str) -> list:
        labels = re.findall(r"\((\w+)\)", unit_phrase)
        if " through " in unit_phrase and len(labels) == 2:
            from billmap.parse.grammar import _expand
            labels = [x.strip("()") for x in _expand(unit_phrase)]
        if scope is None:
            return []
        if len(labels) > 1 and re.fullmatch(r"[a-z]+ (?:\(\w+\))+", unit_phrase.strip()):
            return [self.work.unit([f"({lab})" for lab in labels], root=scope)]     # "subparagraph (B)(v)(I)"
        return [self.work.unit([f"({lab})"], root=scope) for lab in labels]

    def _op_strike_unit(self, ins, scope, path):
        units = self._children_named(scope, ins.unit or "")
        if not units or any(u is None for u in units):
            return Result(ins.id, "TARGET_MISSING", f"{ins.unit} not found in {''.join(path) or 'the section'}")
        for u in units:
            u.getparent().remove(u)
        return Result(ins.id, "CLEAN", f"struck {ins.unit}")

    def _new_units(self, ins):
        if not ins.new_text:
            return None, None, Result(ins.id, "NOT_FOUND", "no quoted block to insert")
        units, loose = build_units(ins.new_text, self.work.positive_law, self.work.dash, self.work.case)
        if not self.work.positive_law:
            for u in units:
                for t in u.iter():
                    if t.text:
                        t.text = code_form(t.text, self.work.title)
        return units, loose, None

    def _op_replace_unit(self, ins, scope, path):
        units, loose, err = self._new_units(ins)
        if err:
            return err
        if ins.unit:                                   # "striking paragraph (2) and inserting the following"
            old = self._children_named(scope, ins.unit)
            if not old or old[0] is None:
                return Result(ins.id, "TARGET_MISSING", f"{ins.unit} not found")
            parent, idx = old[0].getparent(), old[0].getparent().index(old[0])
            for o in old:
                if o is not None and o.getparent() is parent:
                    parent.remove(o)
            for k, u in enumerate(units):
                parent.insert(idx + k, u)
            return Result(ins.id, "CLEAN" if units else "AMBIGUOUS", f"replaced {ins.unit}")
        # "is amended to read as follows": the whole target unit (or section).
        if not units:
            return Result(ins.id, "AMBIGUOUS", "replacement text is not a unit")
        new = units[0]
        if scope is None or scope is self.work.el:
            if local(new) == "section":
                # An Act section replaced in full keeps its Code section number.
                new.set("identifier", self.work.identifier)
                code_num = self.work.identifier.rsplit("/s", 1)[1]
                num = new.find(NS + "num")
                num.set("value", code_num)
                num.text = f"\u00a7 {code_num}."
                self.work.el, self.work.removed = new, False
                return Result(ins.id, "CLEAN", "section replaced")
            return Result(ins.id, "AMBIGUOUS", "section-level replacement is not a section")
        parent = scope.getparent()
        parent.replace(scope, new)
        return Result(ins.id, "CLEAN", f"replaced {''.join(path)}")

    def _append(self, ins, scope, after_el=None, before_el=None):
        units, loose, err = self._new_units(ins)
        if err:
            return err
        if loose and not units:
            # A sentence added at the end of the unit's own text.
            segs = Working.segments(scope)
            text = " ".join(loose)
            replace_span(segs, len(linear(segs).rstrip()), len(linear(segs)), " " + text)
            return Result(ins.id, "CLEAN", "text added at the end")
        if after_el is not None:
            parent, idx = after_el.getparent(), after_el.getparent().index(after_el) + 1
        elif before_el is not None:
            parent, idx = before_el.getparent(), before_el.getparent().index(before_el)
        else:
            parent = scope
            kids = [c for c in scope if local(c) in SUB or local(c) == "section"]
            if kids:
                idx = scope.index(kids[-1]) + 1
            else:
                # The unit had only content: it becomes a chapeau over the new units.
                content = scope.find(NS + "content")
                if content is not None:
                    content.tag = NS + "chapeau"
                idx = len(scope)
                for i, c in enumerate(scope):
                    if local(c) in ("continuation", "notes", "sourceCredit"):
                        idx = i
                        break
        for k, u in enumerate(units):
            parent.insert(idx + k, u)
        warn = None
        prev = parent[idx - 1] if idx > 0 else None
        if prev is not None and local(prev) in SUB and units and local(units[0]) in SUB:
            tail = text_of(prev).rstrip()
            if tail.endswith(".") and not tail.endswith("”."):
                warn = "the preceding unit ends with a period; a conjunction or semicolon amendment may be missing"
        return Result(ins.id, "WARN" if warn else "CLEAN", warn or f"added {len(units)} unit(s)")

    def _op_add_end(self, ins, scope, path):
        return self._append(ins, scope)

    def _op_add_unit_after(self, ins, scope, path):
        anchor = self._children_named(scope, ins.unit or "")
        if not anchor or anchor[0] is None:
            return Result(ins.id, "TARGET_MISSING", f"{ins.unit} not found")
        return self._append(ins, scope, after_el=anchor[-1])

    def _op_add_unit_before(self, ins, scope, path):
        anchor = self._children_named(scope, ins.unit or "")
        if not anchor or anchor[0] is None:
            return Result(ins.id, "TARGET_MISSING", f"{ins.unit} not found")
        return self._append(ins, scope, before_el=anchor[0])

    def _op_redesignate(self, ins, scope, path):
        moves = ins.redesignate or []
        found = []
        for old, new in moves:
            u = self.work.unit([old], root=scope)
            if u is None:
                return Result(ins.id, "TARGET_MISSING", f"{old} not found for redesignation")
            found.append((u, new))
        for u, new in found:                      # all at once: (2)->(3) and (3)->(4) never collide
            num = u.find(NS + "num")
            num.set("value", new.strip("()"))
            num.text = new
        flags = [f for f in ins.flags if f.startswith("redesignation counts differ")]
        return Result(ins.id, "WARN" if flags else "CLEAN", "; ".join(flags) or f"redesignated {len(found)} unit(s)")

    def _op_repeal(self, ins, scope, path):
        if scope is self.work.el:
            self.work.removed = True
            return Result(ins.id, "CLEAN", "section repealed")
        scope.getparent().remove(scope)
        return Result(ins.id, "CLEAN", f"{''.join(path)} repealed")


def worst(statuses) -> str:
    return max(statuses, key=SEVERITY.index) if statuses else "CLEAN"
