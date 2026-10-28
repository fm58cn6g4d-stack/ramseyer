"""Stages 4-5: classify units and parse amendatory text into instructions (docs/04-draft-parser.md).

Quoted strings are lifted out first (⟦0⟧, ⟦1⟧, ...) so the grammar only ever reads the drafter's own words.
A unit's text splits into a head (target and location: P1, P12, P14) and one clause per instruction
(ops.OP_START). Each clause either matches a pattern (P2-P11, P13) or becomes UNPARSED with a reason.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from billmap.parse.ir import Instruction, Node, Target
from billmap.parse.ops import op_starts
from billmap.parse.normalize import usc_variants

PH = "⟦{}⟧"                    # ⟦n⟧
PH_RE = re.compile(r"⟦(\d+)⟧")
CONFIDENCE_THRESHOLD = 0.8
UNIT_WORDS = ("subsection", "paragraph", "subparagraph", "clause", "subclause", "item", "subitem")
UNIT_RANK = {u: i for i, u in enumerate(UNIT_WORDS)}
PLURAL = {u + "s": u for u in UNIT_WORDS} | {"sections": "section"}
LABEL = r"\((?:[0-9]+[A-Za-z]?|[a-z]{1,4}|[A-Z]{1,4})\)"
LABELS = rf"(?:{LABEL})+"
UNIT = r"(?:sub)?(?:section|paragraph|clause|item)s?|subparagraphs?|subclauses?|subitems?"
OCC = (r"(?:\s+(?P<occ>each place (?:it|such term|that term|the term|such terms|they|such phrase|such words?) "
       r"appears?(?: in [^,;]*?)?|(?:the|in the) (?P<nth>first|second|third|fourth|last) place (?:it|such term) "
       r"appears?|each place it occurs))?")
PUNCT = {"period": ".", "semicolon": ";", "comma": ",", "colon": ":", "dash": "—", "em dash": "—",
         "close quotation mark": "”", "closing quotation marks": "”", "closing parenthesis": ")",
         "parenthesis": ")", "quotation marks": "”"}
AT_END = r"(?P<atend> at the end(?: (?:thereof|of [\w ]+?(?: \([\w]+\))*))?)?"
DESCR = r"the (?P<punct>period|semicolon|comma|colon|em dash|dash|closing parenthesis|close quotation mark)"


# ---- quotes ------------------------------------------------------------------------------
def lift_quotes(text: str) -> tuple[str, list[str], list[str]]:
    """Replace each top-level “…” with ⟦n⟧. Returns (text, quotes, flags)."""
    out, quotes, flags = [], [], []
    depth, buf = 0, []
    for ch in text:
        if ch == "“":
            if depth == 0:
                buf = []
            else:
                buf.append(ch)
            depth += 1
        elif ch == "”" and depth > 0:
            depth -= 1
            if depth == 0:
                out.append(PH.format(len(quotes)))
                quotes.append("".join(buf))
            else:
                buf.append(ch)
        elif depth > 0:
            buf.append(ch)
        else:
            out.append(ch)
    if depth:
        # An opening quote never closed in the unit's own text: the quoted matter continues in the block
        # that follows (e.g. 'and inserting the following “may not exceed—' in Pub. L. 119-92).
        flags.append("open_quote_continues_in_block")
        out.append(PH.format(len(quotes)))
        quotes.append("".join(buf))
    return "".join(out), quotes, flags


def quote_free(text: str) -> str:
    """The text the instruction counter reads: every quotation replaced by Q (as xmltext does)."""
    lifted, _, _ = lift_quotes(text)
    return PH_RE.sub(" Q ", lifted)


def shape_hash(clause: str) -> str:
    s = PH_RE.sub("Q", clause)
    s = re.sub(LABELS, "E", s)
    s = re.sub(r"\b\d+[\w–-]*\b", "N", s)
    s = re.sub(r"\s+", " ", s.strip().lower())
    return hashlib.sha1(s.encode()).hexdigest()[:12]


# ---- context (scope stack) ------------------------------------------------------------------
@dataclass
class Ctx:
    target: Target = field(default_factory=Target)
    path: list[tuple[int, str]] = field(default_factory=list)     # (rank, "(b)")
    qualifiers: list[str] = field(default_factory=list)
    multi: list[list[tuple[int, str]]] = field(default_factory=list)  # P12 "in each of subsections (a) and (b)"
    toc: bool = False
    is_target_set: bool = False
    memory: dict = field(default_factory=dict)    # shared by every unit of one bill section: the last target named

    def copy(self) -> "Ctx":
        return Ctx(self.target.model_copy(deep=True), list(self.path), list(self.qualifiers),
                   [list(p) for p in self.multi], self.toc, self.is_target_set, self.memory)

    def target_out(self) -> Target:
        t = self.target.model_copy(deep=True)
        t.path = [lab for _, lab in self.path]
        t.qualifiers = list(self.qualifiers)
        if t.kind == "usc" and t.title and t.section:
            t.cite_norm = f"{t.title} U.S.C. {t.section}" + "".join(t.path)
        return t


USC_SECTION = re.compile(rf"\b[Ss]ections? (?P<sec>\d+[\w–-]*)(?P<path>{LABELS})? of title (?P<t>\d+),? United "
                         r"States Code")
USC_UNIT = re.compile(r"\b(?P<chain>(?:[Cc]hapter|[Ss]ubchapter|[Pp]art|[Ss]ubpart|[Ss]ubtitle) [\w]+(?: of (?:chapter|"
                      r"subchapter|subtitle|part|subpart) [\w]+)*) of title (?P<t>\d+),? United States Code")
# An Act's name: words up to "Act" (or Code, Resolution, ...), with an optional year or fiscal-year qualifier and
# short parenthesized words inside it ("William M. (Mac) Thornberry National Defense Authorization Act ...").
ACT_NAME = (r"(?:the )?[A-Z](?:[^()\u27e6;,]|\([A-Z][a-z]{1,12}\)|\u27e6\d+\u27e7|, (?=Jr\.|Sr\.|[A-Z]|and ))*?"
            r"(?:Act|Code|Resolution|Amendments|Law)"
            r"(?: of \d{4}| for (?:the )?Fiscal Years? \d{4}(?: (?:and|through) \d{4})?)?(?:, \d{4})?")
USC_TITLE = re.compile(r"\b[Tt]itle (?P<t>\d+),? United States Code")
ACT_SECTION = re.compile(rf"\b[Ss]ections? (?P<sec>\d+[\w\u2013.-]*)(?P<path>{LABELS})? of (?P<act>{ACT_NAME})"
                         r"(?:\s*\((?P<paren>[^()]*(?:\([^()]*\)[^()]*)*)\))?")
PL_SECTION = re.compile(rf"\b[Ss]ections? (?P<sec>\d+[\w–.-]*)(?P<path>{LABELS})? of Public Law (?P<pl>\d+[–-]\d+)"
                        r"(?:\s*\((?P<paren>[^()]*(?:\([^()]*\)[^()]*)*)\))?")
ACT_UNIT = re.compile(rf"\b(?P<unit>[Tt]itle|[Ss]ubtitle|[Pp]art|[Cc]hapter|[Ss]ubchapter|[Dd]ivision) (?P<x>[\w]+) of "
                      rf"(?P<act>{ACT_NAME})\s*(?:\((?P<paren>[^()]*(?:\([^()]*\)[^()]*)*)\))?")
WHOLE_ACT = re.compile(rf"^(?P<act>{ACT_NAME.replace('(?:the )?', 'The ', 1)})\s*(?:\((?P<paren>[^()]*(?:\([^()]*\)"
                       r"[^()]*)*)\))?,?(?:\s+as amended by [^,]+,)?\s+(?:is|are) (?:further )?amended")
SUCH = re.compile(rf"\b[Ss]ections? (?P<sec>\d+[\w\u2013.-]*)(?P<path>{LABELS})? of such (?P<what>Act|title|Code|law)")
SUCH_SECTION = re.compile(rf"^(?:(?P<unit>[Ss]ubsection|[Pp]aragraph|[Ss]ubparagraph|[Cc]lause)s? (?P<labels>{LABELS}) of )?"
                          r"[Ss]uch section\b")
PAREN_SECTION = re.compile(rf"^[Ss]ection (?P<sec>\d+[\w\u2013.-]*)(?P<path>{LABELS})? \((?P<paren>\d+ U\.S\.C\. [^()]*"
                           r"(?:\([^()]*\)[^()]*)*)\)")
BARE_SECTION = re.compile(rf"^(?:[Ss]ection|[Ii]n section) (?P<sec>\d+[\w–.-]*)(?P<path>{LABELS})?(?=[\s,]|$)")
IN_SECTION = re.compile(rf"\b(?:[Ii]n|for) section (?P<sec>\d+[\w–.-]*)(?P<path>{LABELS})?(?![\w–(])(?! of)")
LOCATION = re.compile(rf"\bin (?:the )?(?P<unit>subsection|paragraph|subparagraph|clause|subclause|item|subitem)s?"
                      rf" (?P<labels>{LABELS}(?:(?:,| and| or|, and) {LABELS})*)")
EACH_OF = re.compile(rf"\bin each of (?P<unit>{UNIT}) (?P<labels>{LABELS}(?:(?:,| and|, and) {LABELS})+)")
QUALIFIERS = [
    (re.compile(rf"\bin the matter (?P<w>preceding|following) (?P<u>{UNIT}) (?P<l>{LABELS})"),
     lambda m: f"matter {m['w']} {PLURAL.get(m['u'], m['u'])} {m['l']}"),
    (re.compile(r"\bin the (?P<n>first|second|third|fourth|last) sentence"), lambda m: f"{m['n']} sentence"),
    (re.compile(r"\bin the (?:(?P<u>section|subsection|paragraph|subparagraph|clause) )?heading"),
     lambda m: "heading" if not m["u"] else f"{m['u']} heading"),
    (re.compile(r"\bin the item relating to (?P<x>[^,;]+?)(?=,|;| by |$)"), lambda m: f"item relating to {m['x']}"),
]
TOC_HEAD = re.compile(r"\b[Tt]he (?:table of (?:sections|contents|chapters)|analysis)\b")


def _labels(s: str) -> list[str]:
    return re.findall(LABEL, s)


def _set_path(ctx: Ctx, unit: str, labels: str) -> None:
    unit = PLURAL.get(unit, unit)
    rank = UNIT_RANK.get(unit, 0)
    labs = _labels(labels)
    ctx.path = [p for p in ctx.path if p[0] < rank]
    for i, lab in enumerate(labs):
        ctx.path.append((rank + i, lab))


def _section_path(ctx: Ctx, path: str | None) -> None:
    ctx.path = [(i, lab) for i, lab in enumerate(_labels(path or ""))]


def _unquote(s: str | None, quotes: list[str] | None) -> str | None:
    if s is None or not quotes:
        return s
    return PH_RE.sub(lambda m: "\u201c" + quotes[int(m.group(1))] + "\u201d", s)


def apply_head(head: str, ctx: Ctx, quotes: list[str] | None = None) -> list[str]:
    """Update ctx from a head phrase (target and location). Returns flags."""
    flags: list[str] = []
    h = usc_variants(head)
    h = re.sub(r"^[^\u201c\u2014]{1,160}?\.\u2014", "", h) if re.match(r"^[A-Z][^.\u2014]{0,160}\.\u2014", h) else h
    if TOC_HEAD.search(h):
        ctx.toc = True
    m = USC_SECTION.search(h)
    if m:
        ctx.target = Target(kind="usc", cite_raw=m.group(0), title=m["t"], section=m["sec"])
        _section_path(ctx, m["path"])
        ctx.qualifiers, ctx.is_target_set = [], True
    elif (m := PL_SECTION.search(h)):
        ctx.target = Target(kind="pl", cite_raw=m.group(0), section=m["sec"], public_law=m["pl"].replace("–", "-"),
                            usc_parenthetical=m["paren"])
        _section_path(ctx, m["path"])
        ctx.qualifiers, ctx.is_target_set = [], True
    elif (m := SUCH.search(h)):
        base = ctx.target if ctx.target.kind != "unknown" else ctx.memory.get("last") or ctx.target
        t = base.model_copy(deep=True)
        t.section, t.cite_raw, t.usc_parenthetical = m["sec"], m.group(0), None
        ctx.target = t
        _section_path(ctx, m["path"])
        ctx.qualifiers, ctx.is_target_set = [], True
    elif (m := ACT_SECTION.search(h)) and "United States Code" not in m.group(0):
        act = _unquote(re.sub(r"^the ", "", m["act"]).strip(), quotes)
        ctx.target = Target(kind="act", cite_raw=m.group(0), section=m["sec"], act=act, usc_parenthetical=m["paren"])
        _section_path(ctx, m["path"])
        ctx.qualifiers, ctx.is_target_set = [], True
    elif (m := USC_UNIT.search(h)):
        ctx.target = Target(kind="usc", cite_raw=m.group(0), title=m["t"])
        ctx.path, ctx.qualifiers, ctx.is_target_set = [], [" of ".join(p.lower() for p in m["chain"].split(" of "))], True
    elif (m := ACT_UNIT.search(h)) and "United States Code" not in m.group(0):
        ctx.target = Target(kind="act", cite_raw=m.group(0), act=_unquote(re.sub(r"^the ", "", m["act"]), quotes),
                            usc_parenthetical=m["paren"])
        ctx.path, ctx.qualifiers, ctx.is_target_set = [], [f"{m['unit'].lower()} {m['x']}"], True
    elif (m := SUCH_SECTION.search(h.strip())) and ctx.memory.get("last") is not None:
        ctx.target = ctx.memory["last"].model_copy(deep=True)
        ctx.path = [(i, lab) for i, lab in enumerate(ctx.target.path)]
        if m["labels"]:
            _set_path(ctx, m["unit"].lower(), m["labels"])
        ctx.qualifiers, ctx.is_target_set = [], True
    elif (m := PAREN_SECTION.search(h.strip())) and ctx.target.kind in ("unknown", "act"):
        # "Section 2(6) (16 U.S.C. 973(6)) is amended": the Act is implied by the enclosing provision.
        act = ctx.target.act if ctx.target.kind == "act" else None
        ctx.target = Target(kind="act", cite_raw=m.group(0), section=m["sec"], act=act, usc_parenthetical=m["paren"])
        _section_path(ctx, m["path"])
        ctx.qualifiers, ctx.is_target_set = [], True
    elif (m := WHOLE_ACT.search(h)):
        ctx.target = Target(kind="act", cite_raw=m.group(0), act=_unquote(re.sub(r"^The ", "", m["act"]), quotes),
                            usc_parenthetical=m["paren"])
        ctx.path, ctx.qualifiers, ctx.is_target_set = [], [], True
    elif (m := USC_TITLE.search(h)) and not ctx.is_target_set:
        ctx.target = Target(kind="usc", cite_raw=m.group(0), title=m["t"])
        ctx.path, ctx.qualifiers, ctx.is_target_set = [], [], True
    elif (m := BARE_SECTION.search(h.strip())) or (m := IN_SECTION.search(h)):
        if ctx.target.kind != "unknown":
            t = ctx.target.model_copy(deep=True)
            t.section, t.cite_raw, t.usc_parenthetical = m["sec"], m.group(0), None
            ctx.target = t
            _section_path(ctx, m["path"])
            ctx.qualifiers = []
        else:
            flags.append("section_without_root")
    m = EACH_OF.search(h)
    if m:
        unit = PLURAL.get(m["unit"], m["unit"])
        rank = UNIT_RANK.get(unit, 0)
        base = [p for p in ctx.path if p[0] < rank]
        ctx.multi = [base + [(rank, lab)] for lab in _labels(m["labels"])]
        flags.append("multi_scope")
    else:
        for m in LOCATION.finditer(h):
            if len(_labels(m["labels"])) > 1 and re.search(r"\)(?:,| and| or)", m["labels"]):
                unit = PLURAL.get(m["unit"], m["unit"])
                rank = UNIT_RANK.get(unit, 0)
                base = [p for p in ctx.path if p[0] < rank]
                ctx.multi = [base + [(rank, lab)] for lab in re.findall(LABEL, m["labels"])]
                flags.append("multi_scope")
            else:
                _set_path(ctx, m["unit"], m["labels"])
    for rx, fmt in QUALIFIERS:
        for m in rx.finditer(h):
            q = fmt(m)
            if q not in ctx.qualifiers:
                ctx.qualifiers.append(q)
    return flags


# ---- operations ----------------------------------------------------------------------------
Q = r"⟦(?P<{}>\d+)⟧"


def q(name: str) -> str:
    return Q.format(name)


LABEL_LIST = rf"{LABELS}(?:(?:,? and|,| through|, and| or) {LABELS})*"
UNIT_LIST = rf"(?:(?:{UNIT}) {LABEL_LIST}(?: of (?:{UNIT}) {LABELS})?(?:(?:,? and|,) (?=(?:{UNIT}) ))?)+"
SECTION_NUM = r"\d+[\w\u2013-]*"
ITEM = (r"(?P<item>the (?:items?|matter) relating to (?:(?:sections?|chapters?|subchapters?|parts?|subtitles?|titles?|"
        r"articles?) [\dIVXL][\w\u2013.-]*(?:(?:,| and|, and| through) [\dIVXL][\w\u2013.-]*)*|\u27e6(?P<itemq>\d+)\u27e7))")
FOLLOWING = r"the following(?: new [a-z ]+)?:?"
PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("P13", re.compile(rf"^striking {q('a')}{OCC} and all that follows through {q('b')}"
                       rf"(?: and inserting (?:{q('c')}|(?P<block>{FOLLOWING})))?"), "STRIKE_THROUGH"),
    ("P13d", re.compile(rf"^striking {q('a')} and all that follows through (?P<toend>the end of (?:the )?[\w ()]+?|"
                        rf"(?:the )?(?:period|semicolon) at the end)(?: and inserting (?:{q('c')}|(?P<block>{FOLLOWING})))?"),
     "STRIKE_THROUGH"),
    ("P13e", re.compile(rf"^striking {q('a')}{OCC} and all that follows(?: through the end(?: of [\w ]+?(?: \([\w]+\))*)?)?"
                        rf"(?: and inserting (?:(?:the following:? ?)?{q('c')}|(?P<block>{FOLLOWING})))?"), "STRIKE_THROUGH"),
    ("P7", re.compile(rf"^striking (?:the )?(?P<unit>{UNIT}) (?P<labels>{LABELS}(?:(?:,| and|, and| through) {LABELS})*)"
                      rf"(?: of [\w ]+? {LABELS})? and inserting (?P<block>{FOLLOWING})"), "REPLACE_UNIT"),
    ("P2", re.compile(rf"^striking {q('a')}{AT_END}{OCC} and inserting (?:(?:the following:? ?)?{q('b')}|(?P<block>{FOLLOWING})|"
                      rf"(?:a|an|the) (?P<punct2>period|semicolon|comma|colon|em dash|dash)){OCC.replace('occ', 'occ2').replace('nth', 'nth2')}"),
     "STRIKE_INSERT"),
    ("P2p", re.compile(rf"^striking {DESCR}(?: at the end(?: (?:thereof|of [\w ]+?(?: \([\w]+\))*))?| after {q('anchor')})?{OCC} "
                       rf"and inserting (?:(?:the following:? ?)?{q('b')}|(?P<block>{FOLLOWING})|"
                       rf"(?:a|an|the) (?P<punct2>period|semicolon|comma|colon|em dash|dash))"), "STRIKE_INSERT"),
    ("P7a", re.compile(rf"^amending (?:the )?(?P<unit>{UNIT}) (?P<labels>{LABELS})(?: of [\w ]+? {LABELS})?"
                       rf"(?:,? as (?:so )?redesignated(?: by [^,]+)?,?)? to read as follows:?"), "REPLACE_UNIT"),
    ("P7b", re.compile(rf"^striking (?:the )?(?P<unit>{UNIT}) (?P<labels>{LABELS}(?:(?:,| and|, and| through) {LABELS})*)"),
     "STRIKE_UNIT"),
    ("P3", re.compile(rf"^striking {q('a')}{AT_END}{OCC}"), "STRIKE"),
    ("P3p", re.compile(rf"^striking {DESCR}(?: at the end(?: of [\w ()]+?)?)?{OCC}"), "STRIKE"),
    ("P3s", re.compile(r"^striking the (?P<sent>first|second|third|last|fourth) sentence"), "STRIKE"),
    ("P11s", re.compile(rf"^striking {ITEM}(?: and inserting (?:(?:the following:? ?)?{q('b')}|(?P<block>{FOLLOWING})))?"),
     "CONFORM_TOC"),
    ("P11i", re.compile(rf"^inserting (?P<where>after|before) {ITEM},? (?:(?:the following:? ?)?{q('b')}|(?P<block>{FOLLOWING}))"),
     "CONFORM_TOC"),
    ("P6s", re.compile(rf"^inserting (?P<where>after|before) (?:the )?section (?P<labels>{SECTION_NUM})(?:,? as so redesignated[^,]*,?)? "
                       rf"(?P<block>{FOLLOWING})"), "ADD_UNIT_"),
    ("P5i", re.compile(rf"^inserting at the end(?: (?:thereof|of [\w ]+?(?: {LABELS})?))?,? (?:{q('b')}|(?P<block>{FOLLOWING}))"),
     "ADD_END"),
    ("P6", re.compile(rf"^inserting (?P<where>after|before) (?:the )?(?P<unit>{UNIT}) (?P<labels>{LABELS})"
                      rf"(?: of [\w ]+? {LABELS})?(?:,? as so redesignated(?: by [^,]+)?,?)? (?P<block>{FOLLOWING})"),
     "ADD_UNIT_"),
    ("P4b", re.compile(rf"^inserting (?P<where>after|before) {q('a')}{OCC} (?P<block>{FOLLOWING})"), "INSERT_"),
    ("P4", re.compile(rf"^inserting {q('b')} (?P<where>after|before) {q('a')}{OCC}"), "INSERT_"),
    ("P4p", re.compile(rf"^inserting {q('b')} (?P<where>after|before) {DESCR}(?: at the end(?: of [\w ()]+?)?)?{OCC}"),
     "INSERT_"),
    ("P4e", re.compile(rf"^inserting {q('b')} (?P<where>after|before) (?:the )?(?P<unit>{UNIT}) (?P<labels>{LABELS})"),
     "INSERT_"),
    ("P5", re.compile(rf"^adding at the end(?: (?:thereof|of [\w ()]+?))?(?:,? the following(?: new [a-z ]+)?:?)?(?: ?{q('b')})?"),
     "ADD_END"),
    ("P8", re.compile(rf"^redesignating (?P<units>{UNIT_LIST})(?:,? as (?:so )?redesignated by [^,]+,)? as "
                      rf"(?P<to>{UNIT_LIST})(?:,? respectively)?"), "REDESIGNATE"),
]


def _occ(m: re.Match) -> str:
    gd = m.groupdict()
    if gd.get("occ") or gd.get("occ2"):
        return "each"
    nth = gd.get("nth") or gd.get("nth2")
    if nth:
        return {"first": "first", "second": "nth:2", "third": "nth:3", "fourth": "nth:4", "last": "last"}[nth]
    return "first"


def _expand(labels_phrase: str) -> list[str]:
    """'(2) through (5)' -> ['(2)','(3)','(4)','(5)'] for numbers and single letters; else the labels named."""
    out = []
    for m in re.finditer(rf"({LABEL})(?: through ({LABEL}))?", labels_phrase):
        a, b = m.group(1), m.group(2)
        if not b:
            out.append(a)
            continue
        x, y = a.strip("()"), b.strip("()")
        if x.isdigit() and y.isdigit():
            out += [f"({i})" for i in range(int(x), int(y) + 1)]
        elif len(x) == 1 and len(y) == 1 and x.isalpha() and y.isalpha():
            out += [f"({chr(c)})" for c in range(ord(x), ord(y) + 1)]
        else:
            out += [a, b]
    return out


def parse_clause(clause: str, quotes: list[str], block: str | None) -> dict | None:
    """One instruction clause (starting at its verb) -> op fields, or None if no pattern matches."""
    c = " ".join(clause.split())          # a quote may start on the next line ("and inserting\n“(D) …”")
    if re.match(r"^(?:is|are)\s+(?:hereby\s+)?repealed", c):
        return {"op": "REPEAL", "pattern": "P9", "rest": c[re.match(r"^\S+\s+(?:hereby\s+)?repealed", c).end():]}
    if re.match(r"^(?:is|are)\s+(?:hereby\s+)?(?:further\s+)?amended\s+to\s+read\s+as\s+follows", c):
        m = re.match(r"^\S+\s+(?:hereby\s+)?(?:further\s+)?amended\s+to\s+read\s+as\s+follows:?", c)
        return {"op": "REPLACE_UNIT", "pattern": "P7r", "new_text": block, "rest": c[m.end():],
                "needs_block": True}
    for pid, rx, op in PATTERNS:
        m = rx.match(c)
        if not m:
            continue
        gd = m.groupdict()
        get = lambda k: quotes[int(gd[k])] if gd.get(k) is not None else None  # noqa: E731
        out = {"pattern": pid, "rest": c[m.end():], "occurrence": _occ(m)}
        uses_block = bool(gd.get("block")) or (pid == "P5" and gd.get("b") is None)
        if pid in ("P13", "P13d", "P13e"):
            out |= {"op": op, "find": get("a"), "through": get("b") or gd.get("toend") or "end of unit",
                    "replace": get("c"),
                    "new_text": block if uses_block else None}
        elif pid in ("P7", "P7a"):
            out |= {"op": op, "unit": f"{gd['unit']} {gd['labels']}", "new_text": block}
        elif pid in ("P2", "P2p"):
            find = get("a") if pid == "P2" else PUNCT[gd["punct"]]
            replace = get("b") if gd.get("b") is not None else (PUNCT[gd["punct2"]] if gd.get("punct2") else None)
            out |= {"op": op, "find": find, "replace": replace, "new_text": block if uses_block else None}
            if pid == "P2p" or gd.get("atend"):
                out["flags"] = ["positional: " + m.group(0).split(" and inserting")[0][len("striking "):]]
        elif pid == "P7b":
            out |= {"op": op, "unit": f"{gd['unit']} {gd['labels']}"}
        elif pid == "P3":
            out |= {"op": op, "find": get("a")}
            if gd.get("atend"):
                out["flags"] = ["positional: " + m.group(0)[len("striking "):]]
        elif pid == "P3p":
            out |= {"op": op, "find": PUNCT[gd["punct"]], "flags": ["positional: " + m.group(0)[len("striking "):]]}
        elif pid == "P3s":
            out |= {"op": op, "unit": f"{gd['sent']} sentence"}
        elif pid in ("P6", "P6s"):
            unit = f"{gd['unit']} {gd['labels']}" if pid == "P6" else f"section {gd['labels']}"
            out |= {"op": op + ("AFTER" if gd["where"] == "after" else "BEFORE"), "unit": unit, "new_text": block}
        elif pid in ("P11s", "P11i"):
            item = gd.get("item") or ""
            if gd.get("itemq") is not None:
                item = "the item " + quotes[int(gd["itemq"])]
            out |= {"op": op, "unit": item, "replace": get("b"), "new_text": block if uses_block else None,
                    "flags": [f"table of contents: {'strike' if pid == 'P11s' else 'insert ' + gd['where']} {item}"]}
        elif pid == "P5i":
            out |= {"op": op, "new_text": get("b") if gd.get("b") is not None else block}
        elif pid == "P4b":
            out |= {"op": op + ("AFTER" if gd["where"] == "after" else "BEFORE"), "find": get("a"), "new_text": block}
        elif pid in ("P4", "P4p", "P4e"):
            anchor = get("a") if pid == "P4" else (PUNCT[gd["punct"]] if pid == "P4p" else f"{gd['unit']} {gd['labels']}")
            out |= {"op": op + ("AFTER" if gd["where"] == "after" else "BEFORE"), "find": anchor, "new_text": get("b")}
            if pid != "P4":
                out["flags"] = [f"anchor is {'positional' if pid == 'P4p' else 'a unit'}: {anchor}"]
        elif pid == "P5":
            out |= {"op": op, "new_text": get("b") if gd.get("b") is not None else block}
        elif pid == "P8":
            src = _expand(gd["units"])
            dst = _expand(gd["to"])
            out |= {"op": op, "unit": gd["units"].strip(" ,"), "redesignate": list(zip(src, dst))}
            if len(src) != len(dst):
                out["flags"] = [f"redesignation counts differ: {len(src)} -> {len(dst)}"]
        out["needs_block"] = uses_block or pid in ("P7", "P7a", "P6", "P6s", "P4b")
        return out
    return None


TRAILING_OK = re.compile(r"^[\s,.;:\u2014]*(?:respectively|and|or)?[\s,.;:\u2014]*(?:and|or)?[\s,.;:\u2014]*$")
TRAILING_LOC = re.compile(rf"^,?\s*(?:in|of) (?:the )?(?:{UNIT}|section) [\w–.-]*(?:{LABELS})?"
                          rf"(?:\s+of\s+(?:such|this|that)\s+\w+)?(?:,? as so redesignated)?")


def parse_unit_text(node: Node, ctx: Ctx, ordinal_base: int = 0) -> tuple[list[Instruction], Ctx]:
    """Instructions in one unit's own text. Returns them and the context its children inherit."""
    lifted, quotes, qflags = lift_quotes(node.text)
    block = node.block
    if "open_quote_continues_in_block" in qflags:
        if block:
            quotes[-1] = "“" + quotes[-1] + "\n" + block
            block = None
        else:
            qflags = ["unbalanced_quotes"]
    starts = op_starts(PH_RE.sub(lambda m: m.group(0), lifted))
    child_ctx = ctx.copy()
    head = lifted[:starts[0].start()] if starts else lifted
    flags = list(qflags) + apply_head(head, child_ctx, quotes)
    if child_ctx.target.kind != "unknown" and child_ctx.target.section:
        child_ctx.memory["last"] = child_ctx.target_out()
    out: list[Instruction] = []
    for i, st in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(lifted)
        clause = lifted[st.start():end]
        ictx = child_ctx.copy()
        parsed = parse_clause(clause, quotes, block)
        base = dict(id=f"{node.loc}#{ordinal_base + i}", bill_loc=node.loc, source_text=node.text, span=node.span,
                    shape_hash=shape_hash(clause))
        if parsed is None:
            out.append(Instruction(**base, target=ictx.target_out(), op="UNPARSED", flags=flags,
                                   confidence=0.0, reason=f"no grammar pattern matches: {PH_RE.sub('“…”', clause)[:160]}"))
            continue
        rest = parsed.pop("rest", "")
        pflags = flags + parsed.pop("flags", [])
        m = TRAILING_LOC.match(rest)
        if m:                                     # "by striking “x” in paragraph (2)"
            apply_head(m.group(0), ictx)
            rest = rest[m.end():]
        conf = 1.0
        if not TRAILING_OK.match(rest):
            conf = 0.6
            pflags.append("unconsumed: " + PH_RE.sub("“…”", rest.strip())[:120])
        needs_block = parsed.pop("needs_block", False)
        if needs_block and not block and parsed.get("new_text") is None:
            conf = min(conf, 0.5)
            pflags.append("expected a quoted block after 'the following' and found none")
        parsed.pop("pattern", None)
        op = parsed.pop("op")
        if ictx.toc and op not in ("REPEAL",):
            pflags.append(f"table of contents edit ({op})")
            op = "CONFORM_TOC"
        elif any(qq.endswith("heading") or qq == "heading" for qq in ictx.qualifiers) and op in (
                "STRIKE_INSERT", "STRIKE", "INSERT_AFTER", "INSERT_BEFORE", "STRIKE_THROUGH"):
            pflags.append(f"heading edit ({op})")
            op = "AMEND_HEADING"
        targets = ictx.multi or [ictx.path]
        for j, path in enumerate(targets):
            tctx = ictx.copy()
            tctx.path = path
            iid = base["id"] if len(targets) == 1 else f"{base['id']}.{j}"
            out.append(Instruction(**{**base, "id": iid}, target=tctx.target_out(), op=op, confidence=conf,
                                   flags=pflags + ([f"one of {len(targets)} scopes"] if len(targets) > 1 else []),
                                   **{k: v for k, v in parsed.items() if v is not None}))
    if not starts:
        child_ctx.multi = child_ctx.multi if child_ctx.multi else []
    return out, child_ctx


FREESTANDING = [
    ("short_title", re.compile(r"\bmay be cited as\b", re.I)),
    ("definitions", re.compile(r"\b(?:In this (?:Act|section|title|subtitle|division|part)[,:]|the term .{1,80} means)")),
    ("authorization", re.compile(r"\b(?:authorized to be appropriated|there (?:is|are) authorized)\b", re.I)),
    ("effective_date", re.compile(r"\b(?:shall take effect|effective date)\b", re.I)),
    ("rule_of_construction", re.compile(r"\bshall (?:not )?be construed\b", re.I)),
    ("sunset", re.compile(r"\b(?:shall (?:terminate|cease to be effective|expire)|sunset)\b", re.I)),
]


def freestanding_type(text: str) -> str:
    return next((name for name, rx in FREESTANDING if rx.search(text)), "other")
