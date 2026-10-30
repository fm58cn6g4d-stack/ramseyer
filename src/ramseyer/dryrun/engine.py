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
from typing import Callable, Literal

from lxml import etree

from ramseyer.data.indexer import NON_OPERATIVE, SUB, USLM, local, text_of
from ramseyer.parse.ir import Instruction
from ramseyer.parse.normalize import normalize
from ramseyer.parse.segment import Segmenter, walk

# NOT_EXECUTED: the instruction reached no section text (a note, uncodified Act text, an unresolved target); it is
# reported with the reason, never dropped. ALREADY_EXECUTED: current law already reads as the instruction would
# leave it at the place it names (an insertion already next to its anchor, or a replacement that contains the old
# text already around it); the text is left as it is.
Status = Literal["CLEAN", "WARN", "AMBIGUOUS", "NOT_FOUND", "TARGET_MISSING", "STALE_BASELINE", "CONFLICT",
                 "UNPARSED", "NOT_APPLICABLE", "NOT_EXECUTED", "ALREADY_EXECUTED"]
SEVERITY = ["CLEAN", "NOT_APPLICABLE", "WARN", "ALREADY_EXECUTED", "AMBIGUOUS", "STALE_BASELINE", "CONFLICT",
            "NOT_FOUND", "TARGET_MISSING", "NOT_EXECUTED", "UNPARSED"]
# Why an instruction could not be carried out, in the House Comparative Print Suite's four notification categories
# (records/landscape-2026-10.md): an error in drafting, in the current-law data, or in the system (an instruction
# ramseyer does not execute), or the amendment is already executed into current law. The category is the likely
# cause for the status; the detail line says what was seen.
CATEGORY = {
    "AMBIGUOUS": "drafting", "NOT_FOUND": "drafting", "TARGET_MISSING": "drafting", "CONFLICT": "drafting",
    "STALE_BASELINE": "current-law data",
    "UNPARSED": "system", "NOT_EXECUTED": "system",
    "ALREADY_EXECUTED": "already executed",
}
MIN_EXECUTED = 4          # non-space characters an insertion needs before its presence counts as already executed


def category(status: str) -> str | None:
    """The failure category of a status; None for CLEAN, WARN and NOT_APPLICABLE (carried out, or nothing to do)."""
    return CATEGORY.get(status)


def _squash(text: str) -> str:
    return "".join(text.split())
NS = f"{{{USLM}}}"
STRUCTURAL = re.compile(r"^\u201c?\(\w{1,6}\)\s|\u2014\u201c?\(\w{1,6}\)|\.\u2014")
ACT_REF = re.compile(r"\b(?:[Ss]ection|[Tt]itle|[Ss]ubtitle|[Cc]hapter|[Ss]ubchapter|[Pp]art) (?:\d+[A-Za-z]?|[IVXL]+|[A-Z])"
                     r"(?:\([\w]+\))*(?![\w\u2013-])(?! of (?:title \d+|this title|this chapter|such title))"
                     r"(?! of the )(?!,? United States Code)(?! of Public Law)(?! \()"
                     r"|\bthis (?:title|Act|subtitle)\b")
ABBREV = re.compile(r"(?:\b(?:U\.S|U\.S\.C|Sec|Secs|No|Nos|Stat|Pub|Mr|Mrs|Ms|Dr|St|Co|Inc|Corp|Jr|Sr|seq|al|etc|"
                    r"Ph\.D|i\.e|e\.g|Jan|Feb|Mar|Apr|Aug|Sept|Oct|Nov|Dec|ch|subch|pt|div|tit)|(?<![\w.])[A-Z])\.$")
MARGINS = re.compile(r",? and (?:by )?(?:adjusting|moving) the (?:margins|indentation)[^;.]*(?:[;.]|; and)?")
ORDER = ["subsection", "paragraph", "subparagraph", "clause", "subclause", "item", "subitem"]
LEVEL_TAGS = set(ORDER)


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
    """Bills quote inside quotes with ‘ ’; the Code prints those as “ ”. Apostrophes (applicant’s) stay.

    A quotation closes at the first ’ not followed by a letter, except that a plural possessive (“Victims’ ” followed
    by a space) is skipped when a later ’ before the next ‘ is followed by closing punctuation: ‘Special Victims’
    Counsel’) is one quotation (Pub. L. 113-66 § 1716), while ‘State’ includes the Indians’ lands is not."""
    out, i = [], 0
    for m in re.finditer(r"(?<![\w])‘", s):
        if m.start() < i:
            continue
        rest = s[m.end():]
        nxt = rest.find("‘")
        span = rest if nxt < 0 else rest[:nxt]
        closes = [c.start() for c in re.finditer(r"’(?!\w)", span)]
        if not closes:
            continue
        end = closes[0]
        if span[end - 1:end] == "s" and span[end + 1:end + 2] == " ":
            later = [c for c in closes[1:] if re.match(r"’(?:[)\].,;:”—]|$)", span[c:])]
            end = later[0] if later else end
        out.append(s[i:m.start()] + "“" + span[:end] + "”")
        i = m.end() + end + 1
    return "".join(out) + s[i:]


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
                      r"(?:Act|Code)(?: of \d{4})?|Act of (?:January|February|March|April|May|June|July|August|"
                      r"September|October|November|December) \d{1,2}, \d{4}(?:, ch\. \d+)?) "
                      r"\((?P<t>\d+) U\.S\.C\. (?P<z>[\w\u2013.-]+?(?:\([\w]+\))*)\)")


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

    def _heading_style(self, root=None) -> bool:
        """Whether unit headings under `root` (default: the section) print with ".—". OLRC follows the existing
        style of the unit being amended (the Toxic Substances Control Act in title 15 keeps ".—" in subsection
        (b) of 15 U.S.C. 2625 and not elsewhere); with no unit headings, the section's or the title's default."""
        root = self.el if root is None else root
        if root is None:
            return self.positive_law
        heads = [text_of(h).strip() for h in root.iter(NS + "heading") if local(h.getparent()) in LEVEL_TAGS
                 and h.getparent() is not root]
        heads = [h for h in heads if h]
        if not heads:
            return self.positive_law if root is self.el else self.dash
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


def _remove_keep_tail(el) -> None:
    parent, tail, prev = el.getparent(), el.tail or "", el.getprevious()
    if prev is not None:
        prev.tail = (prev.tail or "").rstrip("\u202f ") + tail
    else:
        parent.text = (parent.text or "").rstrip("\u202f ") + tail
    parent.remove(el)


def drop_footnote_after(segs: list[Seg], b: int) -> None:
    """A footnote attached to words the amendment replaces goes with them: OLRC removed "section 2334 [1]"'s
    References-in-Text footnote when 10 U.S.C. 139a was amended to read "section 3221"."""
    for s in segs:
        txt = getattr(s.node, s.attr) or ""
        if s.start < b <= s.start + len(txt) and not txt[b - s.start:].strip("\u202f "):
            nxt = (s.node[0] if len(s.node) else None) if s.attr == "text" else s.node.getnext()
            if nxt is not None and local(nxt) == "sup" and (nxt.text or "").strip().isdigit():
                _remove_keep_tail(nxt)                  # the other footnote marker form: "\u202f<sup>1</sup>"
            elif nxt is not None and local(nxt) == "ref" and nxt.get("class") == "footnoteRef":
                note = nxt.getnext()
                if note is not None and local(note) == "note" and note.get("id") == nxt.get("idref"):
                    _remove_keep_tail(note)
                _remove_keep_tail(nxt)
            return


def find_all(hay: str, needle: str, allowed: list[tuple[int, int]]) -> tuple[list[tuple[int, int]], str]:
    """All matches of needle in hay inside allowed ranges: exact, then folded, then folded case-insensitive."""
    def inside(a, b):
        return any(lo <= a and b <= hi for lo, hi in allowed)

    starts, ends = {lo for lo, _ in allowed}, {hi for _, hi in allowed}

    def bounded(a, b):
        # A quoted word matches whole words only: "term" is not found inside "determines". The edge of an
        # allowed range is a boundary too: the linear view joins a heading and its text with no space ("UseOf").
        lead = a not in starts and hay[a:a + 1].isalnum() and a > 0 and hay[a - 1].isalnum()
        trail = b not in ends and hay[b - 1:b].isalnum() and b < len(hay) and hay[b].isalnum()
        # A number continues across "," or "." followed by a digit: "$1,000" is not found in "$1,000,000" or
        # "1.5" in "21.5" (red team F8; a stale amount must come back NOT_FOUND).
        num_trail = hay[b - 1:b].isdigit() and re.match(r"[,.]\d", hay[b:b + 2]) is not None
        num_lead = hay[a:a + 1].isdigit() and (hay[a - 1:a].isdigit() or re.search(r"\d[,.]$", hay[max(0, a - 2):a])
                                                is not None)
        return not (lead or trail or num_trail or num_lead)

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
BARE_ACT_REF = re.compile(r"\bsection (?P<sec>\d+[A-Za-z]{0,3}(?:[\u2013-]\d+)?)(?P<path>(?:\(\w+\))*)(?![\w\u2013-])"
                          r"(?! of )(?!,? United States Code)(?! \()")
STRAY_SPACE = re.compile(r"(?<=\w) +([,;:])")
SECTION_LINE = re.compile(r"^(?:§+|SEC\.|Sec\.)\s*([\w–-]+(?:\.\d+)?)\.\s*(.*)$")
TOC_LINE = re.compile(r"^(?:Sec\.|\d+[\w\u2013-]*\.\s+\S.*)$")
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
        # Struck text that began or ended with punctuation leaves two words touching: "fishing" + ". In particular
        # ..." replaced by "and in accordance" is "fishing and in accordance" (16 U.S.C. 973k, Pub. L. 119-60).
        if new and a > 0 and hay[a - 1].isalnum() and new[0].isalnum():
            new = " " + new
        if new and b < len(hay) and hay[b].isalnum() and new[-1].isalnum():
            new = new + " "
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
        if new and left and not new[0].isspace() and not left[-1].isspace() and WORD_START.match(new) \
                and WORD_END.search(left[-1]):
            new = " " + new                     # "subparagraph (A)" + "and shall ..." -> "(A) and shall"
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
        elif new == "\u2014" and left.endswith(" ") and not hay[a:a + 1].isspace():
            a -= 1                              # "striking “as follows:” and inserting an em dash": "made—"
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
    # Inner quotation marks are ‘ ’ in a bill, so a ” still unmatched on a line closes the block a second time: a
    # drafting slip OLRC drops (“... Hawaii.”.” in the middle of a block, Pub. L. 116-315 § 7002; “... general.”;”;”,
    # Pub. L. 117-263 § 502).
    for i, x in enumerate(lines):
        while x.count("”") > x.count("“") and re.search(r"”[\s.;,:]*$", x):
            x = re.sub(r"”[\s.;,:]*$", "", x).rstrip()
        lines[i] = x
    return [nested_to_double(x) for x in lines if x]


PLACEHOLDER = "zzcontextzz"     # text of the synthetic context lines build_units sets before a block


def _predecessor(level: str, enum: str) -> str | None:
    """The label before `enum` at `level` ("ii" -> "i", "C" -> "B", "3" -> "2"), or None for a first label."""
    from ramseyer.parse.segment import FIRST, int_to_roman, roman_to_int
    if enum == FIRST.get(level):
        return None
    if enum[:1].isdigit():
        n = int(re.match(r"\d+", enum).group())
        return str(n - 1) if n > 1 else None
    if level in ("clause", "subclause"):
        n = roman_to_int(enum)
        return (int_to_roman(n - 1) if level == "clause" else int_to_roman(n - 1).upper()) if n > 1 else None
    if len(enum) == 2 and enum[0] == enum[1]:
        return enum[0] if enum[0] not in "aA" else None
    return chr(ord(enum[-1]) - 1) if enum[-1] not in "aA" else None


def build_units(block: str, positive_law: bool = False, dash: bool | None = None,
                case: dict[str, str | None] | None = None, level: str | None = None
                ) -> tuple[list[etree._Element], list[str]]:
    """Quoted block -> USLM unit (or section) elements. Returns (elements, plain text lines that had no unit).
    `level` sets the level of the block's first unit where its label alone is ambiguous ("(i)": subsection or
    clause): synthetic ancestor lines (and the label before it) are set ahead of the block and dropped after."""
    lines = [nested_to_double(x) for x in block_lines(block)]
    sec_re = SECTION_LINE
    starts = [i for i, x in enumerate(lines) if sec_re.match(x)]
    if starts and (starts[0] == 0 or all(DIVISION_LINE.match(x) or TOC_LINE.match(x) for x in lines[:starts[0]])):
        if len(starts) > 1 or starts[0] > 0:
            # Several new sections (perhaps under a new subchapter heading): one element per section.
            out = []
            for a, b in zip(starts, starts[1:] + [len(lines)]):
                chunk = [x for x in lines[a:b] if not DIVISION_LINE.match(x)]
                while len(chunk) > 1 and TOC_LINE.match(chunk[-1]):      # the next chapter's table of sections
                    chunk.pop()
                out += build_units("\n".join("\u201c" + x for x in chunk) + "\u201d", positive_law, dash, case)[0]
            return out, []
        m = sec_re.match(lines[0])
        sec = etree.Element(NS + "section")
        num = etree.SubElement(sec, NS + "num", value=m.group(1))
        num.text = f"§ {m.group(1)}."
        h = etree.SubElement(sec, NS + "heading")
        # "§ 15735. Mid-Atlantic Regional Commission." is printed with the law's period (and a "So in original"
        # footnote, 40 U.S.C. 15735); the period after a rendered "SEC. N. Header." is the renderer's.
        h.text = " " + (m.group(2) if lines[0].startswith("§") else m.group(2).rstrip("."))
        units, loose = build_units("\n".join("\u201c" + x for x in lines[1:]) + "\u201d", positive_law, dash, case) \
            if len(lines) > 1 else ([], [])
        if loose:
            c = etree.SubElement(sec, NS + ("chapeau" if units else "content"))
            c.text = " " + " ".join(loose)
        for u in units:
            sec.append(u)
        return [sec], []
    if not lines or not re.match(r"^\(", lines[0]):
        # Lead-in text ("In this subchapter:") before the first unit: returned as loose lines, units after it.
        first = next((i for i, x in enumerate(lines) if re.match(r"^\(\w+\) ", x)), None)
        if not first:
            return [], lines
        units, _ = build_units("\n".join("\u201c" + x for x in lines[first:]) + "\u201d", positive_law, dash, case)
        return units, lines[:first]
    prefix = []
    if level in ORDER:
        from ramseyer.parse.segment import FIRST
        prefix = [f"({FIRST[lv]}) {PLACEHOLDER}" for lv in ORDER[:ORDER.index(level)]]
        m = re.match(r"^\((\w+)\)", lines[0])
        pred = _predecessor(level, m.group(1)) if m else None
        if pred:
            prefix.append(f"({pred}) {PLACEHOLDER}")
    text = "SEC. 0. X.\n" + "\n".join(prefix + lines) + "\n"
    nodes = Segmenter(normalize(text)).run()
    section = next((n for n in walk(nodes) if n.level == "section"), None)
    if section is None:
        return [], lines
    if prefix:
        holder = section            # descend through the synthetic lines to the parent of the block's units
        while not any(c.text.strip() != PLACEHOLDER for c in holder.children) and holder.children:
            holder = holder.children[-1]
        real = [c for c in holder.children if c.text.strip() != PLACEHOLDER]
        if not real or real[0].level != level:
            return [], lines
        section = holder.model_copy(update={"children": real})

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
    # Act section label -> (Code section, " of this title" | " of title N"), for the Act being amended; or None.
    act_ref: Callable[[str], tuple[str, str, bool] | None] | None = None
    weak_refs: set[str] = field(default_factory=set)     # Act references translated on one witness

    def run(self, ins: Instruction, path: list[str]) -> Result:
        self.weak_refs = set()
        r = self._run(ins, path)
        if r.status == "CLEAN":
            r.status, r.detail = self._review(ins, r)
        if r.status == "CLEAN":
            loose = [f for f in ins.flags if f.startswith(("expected a quoted block", "nonstandard verb")) or
                     (f.startswith("unconsumed") and not MARGINS.fullmatch(f[len("unconsumed: "):].strip()))]
            if loose:
                # The parser left part of the instruction unread, or read an unusual verb as a usual one: a clean
                # edit may be an incomplete or misread one.
                r.status, r.detail = "WARN", "; ".join(x for x in (r.detail, "read with caution: " +
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
        if text_op and added and (STRUCTURAL.search(added) or "\n" in added.strip()) \
                and not r.detail.startswith("split"):
            why = "the inserted text adds an enumerated unit or heading, which the Code sets as structure"
        elif added and not self.work.positive_law and ACT_REF.search(self._tr(nested_to_double(added))):
            why = ("the inserted text refers to a provision of the Act; the Code sets such references in Code form, "
                   "which needs the Act-to-Code map")
        elif ins.op == "STRIKE_UNIT" and "repealed unit" in ins.flags:
            why = "the Code sets out a repealed unit as a “[Repealed. …]” stub citing the enacted law"
        elif ins.op == "REPEAL" and r.detail == "section repealed":
            why = "a repealed section is removed or set out as a stub in the Code"
        if not why and self.weak_refs:
            why = ("Act references translated on one witness (source credits): " + "; ".join(sorted(self.weak_refs)))
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
        if "each place, headings included" in ins.flags:
            kinds.add("heading")
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
        # A period ends a sentence unless it closes an abbreviation ("U.S. Government", "Pub. L.", "No. 5").
        bounds = [0] + [m.end() for m in re.finditer(r"(?<=[.])\s+(?=[A-Z(“\"])", body)
                        if not ABBREV.search(body[:m.start()])] + [len(body)]
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
        term = next((q[len("defining "):] for q in ins.target.qualifiers if q.startswith("defining ")), None)
        if term is not None and scope is not None:
            # "in the paragraph defining the term “State”": the one unit whose text opens with that definition.
            want = fold(f'The term "{nested_to_double(term)}"', True)[0]
            hits = [e for e in scope.iter() if local(e) in LEVEL_TAGS and
                    fold(" ".join(text_of(c) for c in e if local(c) in ("content", "chapeau")), True)[0]
                    .lstrip().startswith(want)]
            if len(hits) != 1:
                return Result(rid, "AMBIGUOUS" if hits else "TARGET_MISSING",
                              f"{len(hits)} units define the term “{term}”")
            scope = hits[0]
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
        allowed = self._ranges(ins, segs, hay, find)
        hits, how = find_all(hay, find, allowed)
        if positional and hits:
            end = max(b for _, b in allowed) if allowed else len(hay)
            tail_ok = [h for h in hits if not hay[h[1]:end].strip(" \n\t")]
            hits = tail_ok[-1:] if tail_ok else []
        return segs, hay, hits, how, None

    def _ranges(self, ins, segs, hay, find):
        """The ranges of the unit's text an instruction may edit: its part (heading, matter preceding ...) and sentence."""
        allowed = self._allowed(segs, ins, find)
        # "in the second sentence" (a target qualifier), or "the period at the end of the first sentence" (a
        # positional flag on the operation, Pub. L. 116-136 § 19006(a)).
        named = [m.group(1) for q in ins.target.qualifiers if (m := re.match(r"(first|second|third|fourth|last) "
                                                                              r"sentence", q))]
        named += [m.group(1) for f in ins.flags if f.startswith(("positional", "anchor is positional"))
                  and (m := re.search(r"\b(first|second|third|fourth|last) sentence\b", f))]
        for n in named[:1]:
            allowed = self._sentence_range(hay, n, allowed)
        return allowed

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

    @staticmethod
    def _is_marker(seg, footnoted: bool) -> bool:
        """A footnote marker: <ref class="footnoteRef">, or a one- or two-digit <sup> in a section that has footnotes
        (a <sup> elsewhere may be an exponent)."""
        node = seg.node
        if seg.attr != "text" or not isinstance(node.tag, str):
            return False
        if local(node) == "ref":
            return "footnoteRef" in (node.get("class") or "")
        t = (node.text or "").strip()
        return footnoted and local(node) == "sup" and t.isdigit() and len(t) <= 2

    def _clear_markers_in(self, ins, scope, find, positional=False) -> bool:
        """If `find` occurs, once footnote markers are skipped, in the part of the unit the instruction may edit,
        remove the markers inside the occurrence it edits (and their footnote notes). Only when that occurrence is
        unambiguous: one occurrence (or "each place"), and no "second place" or later. Returns True when any marker
        was removed; nothing outside the edited occurrence is touched."""
        if scope is None or not find:
            return False
        if ins.occurrence.startswith("nth:") and ins.occurrence != "nth:1":
            return False
        target_scope, _ = self._qualified_scope(scope, ins)
        if target_scope is None:
            return False
        segs = Working.segments(target_scope)
        allowed = self._ranges(ins, segs, linear(segs), find)
        root = self.work.el
        footnoted = root is not None and any(n.get("type") == "footnote" or n.get("topic") == "footnote"
                                             for n in root.iter(NS + "note"))
        kept, index = [], []
        for sg in segs:
            txt = getattr(sg.node, sg.attr) or ""
            if self._is_marker(sg, footnoted):
                while kept and kept[-1] in "\u202f ":       # the thin space set before a marker goes with it
                    kept.pop()
                    index.pop()
                continue
            kept.extend(txt)
            index.extend(range(sg.start, sg.start + len(txt)))
        hay2 = "".join(kept)
        hits, _ = find_all(hay2, find, [(0, len(hay2))])
        if not hits:
            return False
        spans = [(index[a], index[b - 1] + 1) for a, b in hits if b > a]
        spans = [(lo, hi) for lo, hi in spans if any(a <= lo and hi <= b for a, b in allowed)]
        if positional and spans:
            # "the period at the end": as in _locate, the occurrence must end the allowed text; markers and
            # whitespace may follow it ("end.¹").
            end = max(b for _, b in allowed) if allowed else len(index)
            marked = [(sg.start, sg.start + len(getattr(sg.node, sg.attr) or "")) for sg in segs
                      if self._is_marker(sg, footnoted)]
            hay = linear(segs)
            def rest_is_blank(hi):
                rest = "".join(ch for i, ch in enumerate(hay[hi:end], hi)
                               if not any(m0 <= i < m1 for m0, m1 in marked))
                return not rest.strip(" \n\t\u202f")
            spans = [sp for sp in spans if rest_is_blank(sp[1])][-1:]
        if not spans or (len(spans) > 1 and ins.occurrence != "each"):
            return False
        removed = False
        for sg in segs:
            if self._is_marker(sg, footnoted) and any(lo <= sg.start <= hi for lo, hi in spans):
                ref = sg.node
                if local(ref) == "ref":
                    note = ref.getnext()
                    if note is not None and local(note) == "note" and note.get("id") == ref.get("idref"):
                        _remove_keep_tail(note)
                _remove_keep_tail(ref)
                removed = True
        return removed

    def _baseline_hay(self, path) -> str:
        """The unit's text as it stood before this bill (the working copy carries the bill's earlier edits)."""
        root = self.work.original if self.work.original is not None else self.work.el
        unit = self.work.unit(path, root=root) if path else root
        return linear(Working.segments(unit)) if unit is not None else ""

    def _already_there(self, ins, scope, path, find, new_text):
        """A note for NOT_FOUND when the struck text is absent but its replacement already occurs in the unit.

        Not ALREADY_EXECUTED: with the struck text gone there is no place to check, and the replacement occurs by
        chance far too often (a deletion's replacement is part of the struck text, "and $13,300,000" -> "$13,300,000";
        a common word, "contract"). Measured on the drafting-error benchmark (records/milestones.md, M6d)."""
        if len(_squash(new_text)) < MIN_EXECUTED:
            return None
        _, _, hits, _, err = self._locate(ins, scope, new_text)
        if err or not hits:
            return None
        return Result(ins.id, "NOT_FOUND", f"quoted text is absent from the target: “{find[:80]}”; its replacement "
                      f"“{new_text[:60]}” already occurs in the unit (an earlier execution, or chance)",
                      matches=len(hits))

    @staticmethod
    def _in_place(hay, a, b, piece, join):
        """True when the edit at hay[a:b] would leave the text as it already reads: an insertion already next to its
        anchor, or a replacement whose new text, containing the old, already surrounds the match."""
        # Compared with whitespace collapsed, and only as whole words: "program" is not in place before "programming".
        def flat(t):
            return " ".join(t.split())
        old = hay[a:b]
        if join == "after":
            added = flat(piece[len(old):])
            tail = flat(hay[b:b + len(added) + 40])
            return len(_squash(added)) >= MIN_EXECUTED and tail.startswith(added) and \
                (len(tail) == len(added) or not tail[len(added)].isalnum())
        if join == "before":
            added = flat(piece[:len(piece) - len(old)])
            head = flat(hay[max(0, a - len(added) - 40):a])
            return len(_squash(added)) >= MIN_EXECUTED and head.endswith(added) and \
                (len(head) == len(added) or not head[-len(added) - 1].isalnum())
        k = piece.find(old) if old else -1
        if k < 0 or len(_squash(piece)) - len(_squash(old)) < MIN_EXECUTED:
            return False
        lo, hi = a - k, a - k + len(piece)
        if lo < 0 or hi > len(hay) or flat(hay[lo:hi]) != flat(piece):
            return False
        return (lo == 0 or not hay[lo - 1].isalnum()) and (hi == len(hay) or not hay[hi].isalnum())

    def _status_for_missing(self, ins, find, path):
        """NOT_FOUND, or CONFLICT when the text existed at the baseline and an earlier instruction removed it."""
        cur = self.work.unit(path) if path else self.work.el
        if ins.target.qualifiers and cur is not None and find_all(text_of(cur), find, [(0, 10 ** 9)])[0]:
            # In the unit, but not in the part the qualifier names (a sentence, the matter preceding ...).
            return "NOT_FOUND", f"present in the unit but not in the {', '.join(ins.target.qualifiers)}"
        if self.work.original is not None:
            orig = self.work.unit(path, root=self.work.original) if path else self.work.original
            if orig is not None:
                h, _ = find_all(text_of(orig), find, [(0, 10 ** 9)])
                if h:
                    return "CONFLICT", "present at the baseline; an earlier instruction in this bill changed it"
        return "NOT_FOUND", "quoted text is absent from the target"

    def _tr(self, text: str) -> str:
        text = STRAY_SPACE.sub(r"\1", text)      # "rifle , or" in the bill is printed "rifle, or" (36 U.S.C. 40732)
        if self.work.positive_law:
            return text
        text = code_form(text, self.work.title)
        if self.act_ref is not None:
            # "section 407(d)(6)" of the Act being amended is printed "section 1107(d)(6) of this title".
            def sub(m):
                code = self.act_ref(m["sec"])
                if code and code[2]:
                    self.weak_refs.add(f"section {m['sec']} -> section {code[0]}{code[1]}")
                return f"section {code[0]}{m['path']}{code[1]}" if code else m.group(0)
            text = BARE_ACT_REF.sub(sub, text)
        return text

    def _edit(self, ins, scope, path, find, make_new, positional=False, label="", join="replace"):
        if any(q.endswith(" sentence") for q in ins.target.qualifiers) and scope is not None and \
                any(local(c) in SUB for c in scope):
            return Result(ins.id, "AMBIGUOUS", "a sentence of a unit that has subunits: no single sentence order")
        segs, hay, hits, how, err = self._locate(ins, scope, find, positional)
        if err:
            return Result(ins.id, "TARGET_MISSING", err)
        if not hits and self._tr(find) != find:
            segs, hay, hits, how, err = self._locate(ins, scope, self._tr(find), positional)
            how = "with Act cross-references in Code form"
        if not hits and "this Act" in find and not self.work.positive_law:
            # The Code prints the Act's "this Act" as the unit it is classified to ("this chapter"); the form that
            # occurs in the section is used for the struck and the inserted text alike (16 U.S.C. 6801).
            for unit in ("chapter", "subchapter", "part", "title"):
                f2 = find.replace("this Act", f"this {unit}")
                segs2, hay2, hits2, how2, err2 = self._locate(ins, scope, f2, positional)
                if hits2:
                    segs, hay, hits, how = segs2, hay2, hits2, f"with “this Act” as “this {unit}”"
                    make_new = (lambda mk, u: lambda old: mk(old).replace("this Act", f"this {u}"))(make_new, unit)
                    break
        if not hits and self._clear_markers_in(ins, scope, find, positional):
            # The quote runs across a footnote marker (OLRC's "So in original" on the words a correction fixes:
            # "the the¹ Secretary", 10 U.S.C. 14504(b)); the marker goes with the words, as OLRC removes it.
            segs, hay, hits, how, err = self._locate(ins, scope, find, positional)
            how = "across a footnote marker, removed with the words"
        if not hits:
            st, why = self._status_for_missing(ins, find, path)
            done = self._already_there(ins, scope, path, find, make_new(find)) if join == "replace" and \
                st == "NOT_FOUND" else None
            return done or Result(ins.id, st, f"{why}: “{find[:80]}”")
        chosen, warn = self._choose(ins, hits)
        if not chosen:
            return Result(ins.id, "NOT_FOUND", warn or "occurrence not found", matches=len(hits))
        if all(self._in_place(hay, a, b, make_new(hay[a:b]), join) for a, b in chosen):
            old = hay[chosen[0][0]:chosen[0][1]]
            piece = make_new(old)
            shown = piece[len(old):] if join == "after" else piece[:len(piece) - len(old)] if join == "before" else piece
            if _squash(piece) in _squash(self._baseline_hay(path)):
                return Result(ins.id, "ALREADY_EXECUTED", f"current law already reads as amended here: "
                              f"“{shown.strip()[:80]}”", matches=len(hits))
            return Result(ins.id, "CONFLICT", f"an earlier instruction in this bill already made this change: "
                          f"“{shown.strip()[:80]}”", matches=len(hits))
        before = hay[chosen[0][0]:chosen[0][1]]
        for a, b in sorted(chosen, reverse=True):
            if join == "replace":
                drop_footnote_after(segs, b)
            piece = make_new(hay[a:b])
            if join != "replace":
                piece = piece[b - a:] if join == "after" else piece[:len(piece) - (b - a)]
            a2, b2, piece = tidy(hay, a, b, piece, join)
            replace_span(segs, a2, b2, piece)
        after_hay = linear(Working.segments(scope))
        ev_at = max(0, chosen[0][0] - 80)
        status = "AMBIGUOUS" if warn else ("WARN" if how in ("case-insensitive", "with Act cross-references in Code form")
                                           or how.startswith("with “this Act”") else "CLEAN")
        detail = "; ".join(x for x in (label, warn, f"matched {how}" if how != "exact" else "") if x)
        return Result(ins.id, status, detail, evidence=after_hay[ev_at:ev_at + 200], before_span=before,
                      after_span=make_new(before), matches=len(hits))

    def _split(self, ins, scope):
        """A text edit whose replacement starts new enumerated units restructures the text (42 U.S.C. 284g(a)(1),
        Pub. L. 118-180 § 2(a); 40 U.S.C. 15702(c)(3), Pub. L. 118-272 § 2250(c)):
        - "striking “to a county” and inserting “to—“(A) a county”": the text up to the match plus the lead line
          ("to—") becomes a lead-in (chapeau) over the new units, which are children of the unit;
        - "striking “toxicology, and interventions” and inserting “toxicology ...; and“(ii) on interventions”": the
          lead line ends the unit's text and the new units follow as siblings, of the unit or of the ancestor at
          their level ("disorder; and“(B) ensure ...—“(i) investigates");
        - "striking “In determining” and inserting “(1) In general.—In determining”" at the start of the text: the
          whole text moves into the new unit.
        The rest of the original text continues the last new unit. Returns None when the edit is not of one of these
        shapes (or later units would have to move), so the literal text edit applies instead."""
        raw = ins.replace if ins.replace is not None else ins.new_text
        if not raw or scope is None:
            return None
        lines = block_lines(raw)
        k = next((i for i, x in enumerate(lines) if re.match(r"^\(\w{1,6}\) ", x)), None)
        if k is None or k > 1:
            return None
        find = nested_to_double(ins.find or "")
        found = []
        for u in [scope] + [e for e in scope.iter() if local(e) in LEVEL_TAGS and e is not scope]:
            c = u.find(NS + "content")
            if c is not None:
                segs = Working.segments(c)
                hay = linear(segs)
                found += [(u, c, segs, hay, h) for h in find_all(hay, find, [(0, len(hay))])[0]
                          if hay[h[0]:h[1]] == find]
        if len(found) != 1:
            return None
        host, content, segs, hay, (a, b) = found[0]
        from ramseyer.parse.segment import candidates
        lead = self._tr(lines[0]) if k == 1 else ""
        host_level = local(host)
        cands = [c for c in candidates(re.match(r"^\((\w+)\)", lines[k]).group(1)) if c in ORDER]
        deeper = [c for c in cands if host_level == "section" or ORDER.index(c) > ORDER.index(host_level)]
        anchor = None
        if k == 0 or lead.rstrip().endswith(("\u2014", ":")):
            if (k == 0 and hay[:a].strip()) or not deeper or any(local(c) in SUB for c in host):
                return None             # an enumerated unit starting mid-sentence is not this shape
            mode, level = ("push" if k == 0 else "children"), deeper[0]
        else:
            # Siblings: of the host, or of the ancestor at the new units' level. No unit may follow anywhere on that
            # chain, or it would have to move (and its label could collide with a new one).
            mode, anchor = "siblings", host
            while True:
                if anchor is None or anchor is self.work.el or any(local(x) in SUB for x in anchor.itersiblings()):
                    return None
                if local(anchor) in cands:
                    break
                anchor = anchor.getparent()
            level = local(anchor)
        units, loose = build_units("\n".join("\u201c" + x for x in lines[k:]) + "\u201d", self.work.positive_law,
                                   self.work._heading_style(host), self.work.case, level=level)
        last = [e for e in units[-1].iter(NS + "content")][-1:] if units else []
        if not units or loose or not last or local(units[0]) != level:
            return None
        if not self.work.positive_law:
            for u in units:
                for t in u.iter():
                    if t.text:
                        t.text = self._tr(t.text)
        rest = copy.deepcopy(content)
        replace_span(Working.segments(rest), 0, b, "")
        a2, _, lead = tidy(hay, a, b, lead, "replace") if lead else (a, b, lead)
        replace_span(segs, a2, len(hay), lead.rstrip())
        if mode == "push":
            host.remove(content)
        elif mode == "children":
            content.tag = NS + "chapeau"
        dst = last[0]
        holder, attr = (dst[-1], "tail") if len(dst) else (dst, "text")
        end, piece = (getattr(holder, attr) or ""), (rest.text or "")
        if piece.strip() or len(rest):
            # One space between the new unit's words and the rest of the old text, none before closing punctuation.
            piece = piece.lstrip()
            end = end.rstrip() + ("" if piece[:1] and piece[0] in CLOSE_PUNCT else " ")
        setattr(holder, attr, end + piece)
        for c in list(rest):
            dst.append(c)
        if mode == "siblings":
            parent, idx = anchor.getparent(), anchor.getparent().index(anchor) + 1
        else:
            parent = host
            idx = (host.index(content) + 1 if mode == "children" else
                   next((i for i, c in enumerate(host) if local(c) in ("continuation", "notes", "sourceCredit")),
                        len(host)))
        for j, u in enumerate(units):
            parent.insert(idx + j, u)
        return Result(ins.id, "CLEAN", f"split ({mode}): {len(units)} new unit(s) from the replacement text",
                      before_span=hay[a:b], after_span=" / ".join(lines))

    def _op_strike_insert(self, ins, scope, path):
        split = self._split(ins, scope) if not ins.target.qualifiers and ins.find else None
        if split is not None:
            return split
        new = self._tr(nested_to_double(ins.replace if ins.replace is not None else
                                        "\n".join(block_lines(ins.new_text or ""))))
        positional = any(f.startswith("positional") for f in ins.flags)
        return self._edit(ins, scope, path, nested_to_double(ins.find or ""), lambda old: new, positional)

    def _heading_append(self, ins, scope):
        """"in the section heading, by adding at the end the following: “; medical surge program”"."""
        h = scope.find(NS + "heading") if scope is not None else None
        if h is None or not ins.new_text or "\n" in ins.new_text.strip():
            return Result(ins.id, "TARGET_MISSING" if h is None else "AMBIGUOUS", "no heading text to add to")
        new = self._tr(nested_to_double(ins.new_text))
        holder, attr = (h, "text") if len(h) == 0 else (h[-1], "tail")
        old = getattr(holder, attr) or ""
        dash = ".\u2014" if old.rstrip().endswith(".\u2014") else ""
        body = old.rstrip()[:-2] if dash else old.rstrip().rstrip(".")
        setattr(holder, attr, body + new + dash)
        return Result(ins.id, "CLEAN", "added at the end of the heading", after_span=new)

    def _heading_replace(self, ins, scope):
        """"striking the heading and inserting “…”" / "amending the section heading to read as follows: “…”": the
        whole heading, set the way the unit's heading is set now (".—" kept or not; the title's heading case)."""
        whole_section = (ins.unit or "").startswith("section")
        unit = self.work.el if whole_section else scope
        h = unit.find(NS + "heading") if unit is not None else None
        if h is None or not ins.replace:
            return Result(ins.id, "TARGET_MISSING", "the unit has no heading to replace")
        new = self._tr(nested_to_double(ins.replace)).strip()
        if local(unit) == "section":
            text = " " + new.rstrip(".")
        else:
            old = text_of(h).strip()
            text = " " + heading_form(new, local(unit), self.work.positive_law, old.endswith(".\u2014"),
                                      self.work.case.get(local(unit)))
        for c in list(h):
            h.remove(c)
        h.text = text
        return Result(ins.id, "CLEAN", "heading replaced", after_span=text.strip())

    def _op_amend_heading(self, ins, scope, path):
        """A heading edit: the parser records the underlying op ("heading edit (INSERT_AFTER)"); the scope is
        limited to the heading by _allowed."""
        if "heading replaced" in ins.flags:
            return self._heading_replace(ins, scope)
        if "heading struck" in ins.flags:
            unit = self.work.el if (ins.unit or "").startswith("section") else scope
            h = unit.find(NS + "heading") if unit is not None else None
            if h is None:
                return Result(ins.id, "TARGET_MISSING", "the unit has no heading to strike")
            _remove_keep_tail(h)
            return Result(ins.id, "CLEAN", "heading struck")
        m = next((re.search(r"heading edit \((\w+)\)", f) for f in ins.flags if "heading edit" in f), None)
        op = m.group(1).lower() if m else "strike_insert"
        if op == "add_end":
            return self._heading_append(ins, scope)
        handler = getattr(self, "_op_" + op, None)
        if handler is None:
            return Result(ins.id, "AMBIGUOUS", f"heading edit with op {op} not supported")
        return handler(ins, scope, path)

    def _op_strike(self, ins, scope, path):
        if ins.unit and ins.unit.endswith("sentence") and any(local(c) in SUB for c in scope):
            # Sentences are counted in a unit's own text; a unit with subunits has no single sentence order.
            return Result(ins.id, "AMBIGUOUS", f"the {ins.unit} of a unit that has subunits")
        if ins.unit and ins.unit.endswith("sentence"):
            segs = Working.segments(scope)
            hay = linear(segs)
            rng = self._sentence_range(hay, ins.unit.split()[0], self._allowed(segs, ins, None))
            if not rng:
                return Result(ins.id, "NOT_FOUND", f"no {ins.unit}")
            a, b = rng[0]
            new = ""
            if ins.replace:                    # "striking the second sentence and inserting “…”"
                new = self._tr(nested_to_double(" ".join(block_lines(ins.replace)) if "\n" in ins.replace
                                                else ins.replace)).strip()
                new += " " if hay[a:b] != hay[a:b].rstrip() else ""
            replace_span(segs, a, b, new)
            return Result(ins.id, "CLEAN", f"{'replaced' if new else 'struck'} the {ins.unit}")
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
        if through in (".", ";", ":"):
            # "and all that follows through the period": the next one after the start.
            nxt = hay.find(through, start + len(ins.find or ""), allowed_end)
            if nxt < 0:
                return Result(ins.id, "NOT_FOUND", f"no “{through}” after the start")
            end = nxt + 1
        elif through.startswith("end") or through.startswith("the end") or "at the end" in through:
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
        # Units whose number falls inside the struck span are swallowed: what is left of the last one (".")
        # joins the replacement and the emptied units are removed (30 U.S.C. 191(d)(3), Pub. L. 119-134).
        swallowed = [s.node.getparent() for s in segs if s.kind == "num" and start <= s.start < end]
        swallowed = [u for u in swallowed if not any(a in swallowed for a in u.iterancestors())]
        if swallowed:
            last_end = max(s.start + len(getattr(s.node, s.attr) or "") for s in segs
                           if (s.node is swallowed[-1] or swallowed[-1] in s.node.iterancestors())
                           and not (s.node is swallowed[-1] and s.attr == "tail"))
            new, end = new + hay[end:last_end], max(end, last_end)
        a, b, piece = tidy(hay, start, end, new, "replace")
        replace_span(segs, a, b, piece)
        for u in swallowed:
            if not text_of(u).strip() and u.getparent() is not None:
                _remove_keep_tail(u)
        status = "AMBIGUOUS" if len(hits) > 1 else ("WARN" if swallowed else "CLEAN")
        return Result(ins.id, status, "struck through" + (f"; {len(hits)} start matches" if len(hits) > 1 else "")
                      + (f"; the strike runs across {len(swallowed)} unit(s), merged into the text" if swallowed else ""),
                      before_span=hay[start:end], after_span=new, matches=len(hits))

    # unit edits -------------------------------------------------------------------------------
    def _children_named(self, scope, unit_phrase: str) -> list:
        if " of " in unit_phrase:                  # "paragraph (2) of subsection (b)": descend to the parent first
            unit_phrase, parent = unit_phrase.split(" of ", 1)
            if scope is not None:
                scope = self.work.unit([f"({x})" for x in re.findall(r"\((\w+)\)", parent)], root=scope)
        labels = re.findall(r"\((\w+)\)", unit_phrase)
        if " through " in unit_phrase and len(labels) == 2:
            from ramseyer.parse.grammar import _expand
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

    def _new_units(self, ins, scope=None):
        if not ins.new_text:
            return None, None, Result(ins.id, "NOT_FOUND", "no quoted block to insert")
        dash = self.work._heading_style(scope) if scope is not None and self.work.el is not None else self.work.dash
        units, loose = build_units(ins.new_text, self.work.positive_law, dash, self.work.case)
        if not self.work.positive_law:
            for u in units:
                for t in u.iter():
                    if t.text:
                        t.text = self._tr(t.text)
        return units, loose, None

    def _op_replace_unit(self, ins, scope, path):
        units, loose, err = self._new_units(ins, scope)
        if err:
            return err
        if ins.unit:                                   # "striking paragraph (2) and inserting the following"
            old = self._children_named(scope, ins.unit)
            if not old or old[0] is None:
                return Result(ins.id, "TARGET_MISSING", f"{ins.unit} not found")
            parent, idx = old[0].getparent(), old[0].getparent().index(old[0])
            old_labels = [_num(o) for o in old if o is not None]
            new_labels = [_num(u) for u in units]
            for o in old:
                if o is not None and o.getparent() is parent:
                    parent.remove(o)
            for k, u in enumerate(units):
                parent.insert(idx + k, u)
            if units and new_labels[:1] != old_labels[:1]:
                # "striking subsection (b) and inserting “(c) …”": a label that does not continue the sequence.
                return Result(ins.id, "WARN", f"replaced {ins.unit} with a unit labelled ({new_labels[0]}), not "
                              f"({old_labels[0]})")
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
        units, loose, err = self._new_units(ins, scope)
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
                if loose:
                    # "adding at the end the following: “Whenever ..., the Chairperson shall—“(i) ...”": the lead-in
                    # ends the unit's text and introduces the new units (Pub. L. 113-76 div. G § 416, 20 U.S.C. 954).
                    segs = Working.segments(scope)
                    replace_span(segs, len(linear(segs).rstrip()), len(linear(segs)), " " + " ".join(loose))
                    loose = []
                # The unit had only content: it becomes a chapeau over the new units.
                content = scope.find(NS + "content")
                if content is not None:
                    content.tag = NS + "chapeau"
                idx = len(scope)
                for i, c in enumerate(scope):
                    if local(c) in ("continuation", "notes", "sourceCredit"):
                        idx = i
                        break
        existing = {_num(c) for c in parent if local(c) in SUB}
        dup = [_num(u) for u in units if local(u) in SUB and _num(u) in existing]
        for k, u in enumerate(units):
            parent.insert(idx + k, u)
        if dup:
            return Result(ins.id, "WARN", f"the added unit's label ({dup[0]}) already exists in the unit")
        gap = _sequence_gap(parent, units[0]) if units and local(units[0]) in SUB else None
        if gap:
            # "(d)" added after a last "(b)": a wrong section or unit is the likelier explanation (M6c benchmark).
            return Result(ins.id, "WARN", gap)
        warn = None
        if loose:
            warn = f"lead-in text before the new units not placed: “{' '.join(loose)[:80]}”"
        prev = parent[idx - 1] if idx > 0 else None
        if prev is not None and local(prev) in SUB and units and local(units[0]) in SUB:
            tail = text_of(prev).rstrip()
            if tail.endswith(".") and not tail.endswith("”.") and warn is None:
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
        nested = False
        for old, new in moves:
            u = self.work.unit([old], root=scope)
            if u is None and scope is not None:
                # "redesignating clauses (i) and (ii)" of a paragraph whose clauses sit under a subparagraph:
                # a unique descendant with that number.
                want = old.strip("()")
                hits = [e for e in scope.iter() if local(e) in LEVEL_TAGS and e is not scope
                        and (e.find(NS + "num") is not None and e.find(NS + "num").get("value") == want)]
                if len(hits) > 1:
                    return Result(ins.id, "AMBIGUOUS", f"{old} occurs {len(hits)} times below the unit")
                u, nested = (hits[0], True) if hits else (None, nested)
            if u is None:
                return self._redesignate_inline(ins, scope, moves) or \
                    Result(ins.id, "TARGET_MISSING", f"{old} not found for redesignation")
            found.append((u, new))
        for u, new in found:                      # all at once: (2)->(3) and (3)->(4) never collide
            num = u.find(NS + "num")
            num.set("value", new.strip("()"))
            num.text = new
        flags = [f for f in ins.flags if f.startswith("redesignation counts differ")]
        if nested:
            flags.append("units found below the named unit, not directly in it")
        # A "[(d) Repealed ...]" stub that the redesignation leaves out of order goes (49 U.S.C. 308, Pub. L.
        # 118-63 § 218: (e) became (c) past the (d) stub, and the Code dropped the stub).
        parent = found[0][0].getparent() if found else None
        if parent is not None:
            units = [c for c in parent if local(c) in LEVEL_TAGS and c.find(NS + "num") is not None]
            for i, c in enumerate(units):
                num = c.find(NS + "num")
                later = [u.find(NS + "num").get("value") or "" for u in units[i + 1:]
                         if not (u.find(NS + "num").text or "").startswith("[")]
                if (num.text or "").startswith("[") and later and _label_key(later[0]) <= _label_key(num.get("value") or ""):
                    _remove_keep_tail(c)
                    flags.append(f"dropped the repeal stub {num.text.rstrip()} left out of order")
        # Cross-references in the section to a moved unit by its old label may need conforming (docs/06-dry-run.md).
        word = (ins.unit or "").split(" ")[0].rstrip("s") or "paragraph"
        text = text_of(self.work.el) if self.work.el is not None else ""
        stale = [old for old, _ in moves if re.search(rf"\b{word} {re.escape(old)}(?![\w(])", text)]
        if stale:
            flags.append(f"the section still refers to {word} {', '.join(stale)}; references may need conforming")
        return Result(ins.id, "WARN" if flags else "CLEAN", "; ".join(flags) or f"redesignated {len(found)} unit(s)")

    def _redesignate_inline(self, ins, scope, moves):
        """Enumerators set inline in running text ("means (A) in the case of ... either (i) ... or (ii) ...", 29 U.S.C.
        1002(18)) are redesignated in the text, when each old label occurs exactly once."""
        if scope is None:
            return None
        segs = Working.segments(scope)
        hay = linear(segs)
        allowed = self._allowed(segs, ins, None)
        spans = []
        for old, new in moves:
            hits = [h for h in find_all(hay, old, allowed)[0] if hay[h[0]:h[1]] == old]
            if len(hits) != 1:
                return None
            spans.append((hits[0], new))
        for (a, b), new in sorted(spans, reverse=True):
            replace_span(segs, a, b, new)
        return Result(ins.id, "WARN", f"redesignated {len(spans)} enumerator(s) set inline in the text")

    def _op_repeal(self, ins, scope, path):
        if scope is self.work.el:
            self.work.removed = True
            return Result(ins.id, "CLEAN", "section repealed")
        scope.getparent().remove(scope)
        return Result(ins.id, "CLEAN", f"{''.join(path)} repealed")


def _sequence_gap(parent, unit) -> str | None:
    """The label of an added unit should follow the one before it ("(c)" after "(b)"); None when it does, or when
    there is nothing to compare with (first unit, repeal stubs, labels of other kinds)."""
    from ramseyer.parse.segment import successor
    sibs = [c for c in parent if local(c) in SUB]
    i = sibs.index(unit)
    if i == 0:
        return None
    prev, new = _num(sibs[i - 1]), _num(unit)
    level = local(unit)
    if not prev or not new or local(sibs[i - 1]) != level:
        return None
    try:
        nxt = successor(level, prev)
    except (ValueError, KeyError):
        return None
    if new != nxt and not (new[:-1] == prev and new[-1:].isalpha()):     # "(2A)" after "(2)" is an inserted unit
        return f"the added unit ({new}) does not follow ({prev}); expected ({nxt})"
    return None


def _num(el) -> str:
    n = el.find(NS + "num")
    return (n.get("value") or "").strip("[]()") if n is not None else ""


def _label_key(label: str) -> tuple:
    """Order of unit labels: (2) < (10); (b) < (c) < (aa); (iii) < (iv)."""
    from ramseyer.parse.segment import is_roman, roman_to_int
    if label[:1].isdigit():
        m = re.match(r"\d+", label)
        return (0, int(m.group(0)), label[m.end():])
    if len(label) > 1 and is_roman(label):
        return (1, roman_to_int(label), "")
    return (2, len(label), label.lower())


def worst(statuses) -> str:
    return max(statuses, key=SEVERITY.index) if statuses else "CLEAN"
