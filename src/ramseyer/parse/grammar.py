"""Stages 4-5: classify units and parse amendatory text into instructions (docs/04-draft-parser.md).

Quoted strings are lifted out first (⟦0⟧, ⟦1⟧, ...) so the grammar only ever reads the drafter's own words.
A unit's text splits into a head (target and location: P1, P12, P14) and one clause per instruction
(ops.OP_START). Each clause either matches a pattern (P2-P11, P13) or becomes UNPARSED with a reason.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from ramseyer.parse.ir import Instruction, Node, Target
from ramseyer.parse.ops import op_starts
from ramseyer.parse.normalize import usc_variants
from ramseyer.parse.segment import int_to_roman, is_roman, roman_to_int

PH = "⟦{}⟧"                    # ⟦n⟧
PH_RE = re.compile(r"⟦(\d+)⟧")
CONFIDENCE_THRESHOLD = 0.8
UNIT_WORDS = ("subsection", "paragraph", "subparagraph", "clause", "subclause", "item", "subitem")
UNIT_RANK = {u: i for i, u in enumerate(UNIT_WORDS)}
PLURAL = {u + "s": u for u in UNIT_WORDS} | {"sections": "section"}
LABEL = r"\((?:[0-9]+[A-Za-z]?|[a-z]{1,4}|[A-Z]{1,4})\)"
LABELS = rf"(?:{LABEL})+"
SECTION_NUM = r"\d+[\w\u2013-]*"
UNIT = r"(?:sub)?(?:section|paragraph|clause|item)s?|subparagraphs?|subclauses?|subitems?"
# "each place it appears" (occ) and "the second place it appears" (nth) are separate groups: an ordinal is never "each".
OCC = (r"(?:\s+(?:in )?(?:(?P<occ>(?:at )?each place (?:it|such term|that term|the term|such terms|they|such phrase|such "
       r"words?) appears?(?: in (?:the )?text (?:and|or) (?:section |subsection )?headings?| in [^,;]*?)?|each place it occurs|"
       r"both places (?:it|such term|the term|they) appears?)|"
       r"(?:the|in the) (?P<nth>first|second|third|fourth|fifth|last) place (?:it|such term|that term|the term) "
       r"appears?))?")
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
DATE = (r"(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, "
        r"\d{4}")
# An Act known by its date ("the Act of March 3, 1899 (chapter 425; 30 Stat. 1152)") or by its long title ("the Act
# entitled “An Act to establish ...”, approved June 3, 1976").
DATED_ACT = rf"(?:the )?Act (?:of {DATE}|entitled,? \u27e6\d+\u27e7,? approved {DATE})"
NAMED_ACT = (r"(?:the )?[A-Z](?:[^()\u27e6;,]|\([A-Z][a-z]{1,12}\)|\u27e6\d+\u27e7|, (?=Jr\.|Sr\.|[A-Z]|and ))*?"
             r"(?:Act|Code|Resolution|Amendments(?! Act\b)|Law(?! (?:Act|Code)\b))"
             r"(?: [Oo]f \d{4}| for (?:the )?Fiscal Years? \d{4}(?: (?:and|through) \d{4})?)?(?:, \d{4})?")
ACT_NAME = rf"(?:{DATED_ACT}|{NAMED_ACT})"
# "Section 1701 of title I of the Omnibus Crime Control and Safe Streets Act of 1968"
ACT_PART = r"(?:(?:title|subtitle|part|chapter|division) [\w]+ of )*"
USC_TITLE = re.compile(r"\b[Tt]itle (?P<t>\d+),? United States Code")
ACT_SECTION = re.compile(rf"\b[Ss]ections? (?P<sec>\d+[\w\u2013.-]*)(?P<path>{LABELS})? of {ACT_PART}(?P<act>{ACT_NAME})"
                         r"(?:\s*\((?P<paren>[^()]*(?:\([^()]*\)[^()]*)*)\))?")
PL_SECTION = re.compile(rf"\b[Ss]ections? (?P<sec>\d+[\w–.-]*)(?P<path>{LABELS})? of Public Law (?P<pl>\d+[–-]\d+)"
                        r"(?:\s*\((?P<paren>[^()]*(?:\([^()]*\)[^()]*)*)\))?")
ACT_UNIT = re.compile(rf"\b(?P<unit>[Tt]itle|[Ss]ubtitle|[Pp]art|[Cc]hapter|[Ss]ubchapter|[Dd]ivision) (?P<x>[\w]+) of "
                      rf"(?P<act>{ACT_NAME})\s*(?:\((?P<paren>[^()]*(?:\([^()]*\)[^()]*)*)\))?")
WHOLE_ACT = re.compile(rf"^(?P<act>The Act of {DATE}|{NAMED_ACT.replace('(?:the )?', 'The ', 1)})\s*(?:\((?P<paren>[^()]*(?:\([^()]*\)"
                       r"[^()]*)*)\))?,?(?:\s+as amended by [^,]+,)?\s+(?:is|are) (?:further )?amended")
SUCH = re.compile(rf"\b[Ss]ections? (?P<sec>\d+[\w\u2013.-]*)(?P<path>{LABELS})? of such (?P<what>Act|title|Code|law)"
                  r"(?:\s*\((?P<paren>\d+ U\.S\.C\. [^()]*(?:\([^()]*\)[^()]*)*)\))?")
SUCH_UNIT_OF = rf"(?P<unit>[Ss]ubsection|[Pp]aragraph|[Ss]ubparagraph|[Cc]lause|[Ss]ubclause)s? (?P<labels>{LABELS}) of "
# "Subsection (d) of such section", "Paragraph (1) of subsection (c) of such section"
SUCH_SECTION = re.compile(rf"^(?P<chain>(?:{SUCH_UNIT_OF.replace('?P<unit>', '').replace('?P<labels>', '')})*)"
                          rf"[Ss]uch section(?: (?P<num>{SECTION_NUM}))?\b")
SUCH_SECTION_NUM = re.compile(rf"\b[Ss]uch section (?P<num>\d+[\w\u2013.-]*?)(?=[,\s]|$)")
PAREN_SECTION = re.compile(rf"^[Ss]ection (?P<sec>\d+[\w\u2013.-]*)(?P<path>{LABELS})? \((?P<paren>\d+ U\.S\.C\. [^()]*"
                           r"(?:\([^()]*\)[^()]*)*)\)")
# Not "Section 3(c) of <a law the grammar does not know>": a root from context would pick the wrong law.
BARE_SECTION = re.compile(rf"^(?:[Ss]ection|[Ii]n section) (?P<sec>\d+[\w–.-]*)(?P<path>{LABELS})?(?=[\s,]|$)(?! of\b)")
IN_SECTION = re.compile(rf"\b(?:[Ii]n|for|of) section (?P<sec>\d+[\w–.-]*)(?P<path>{LABELS})?(?![\w–(])(?! of)")
LOCATION = re.compile(rf"\b[Ii]n (?:the )?(?P<unit>subsection|paragraph|subparagraph|clause|subclause|item|subitem)s?"
                      rf" (?P<labels>{LABELS}(?:(?:,| and| or|, and) {LABELS})*)")
EACH_OF = re.compile(rf"\bin each of (?P<unit>{UNIT}) (?P<labels>{LABELS}(?:(?:,| and|, and) {LABELS})+)")
DEFINING = re.compile(r"\b[Ii]n (?:the )?(?:paragraph|subsection|subparagraph|clause|subclause|item|provision) "
                      r"defining (?:the )?(?:terms? )?⟦(?P<q>\d+)⟧")
HEADING_QUAL = re.compile(rf"(?:\b[Ii]n |^)[Tt]he (?:(?P<u>section|subsection|paragraph|subparagraph|clause) )?heading"
                          rf"(?! of the \w+ column)(?: (?:for|of) (?P<fu>subsection|paragraph|subparagraph|clause) "
                          rf"(?P<fl>{LABELS}))?")
QUALIFIERS = [
    (re.compile(rf"\bin the matter (?P<w>preceding|following) (?P<u>{UNIT}) (?P<l>{LABELS})"),
     lambda m: f"matter {m['w']} {PLURAL.get(m['u'], m['u'])} {m['l']}"),
    (re.compile(r"\bin the (?P<n>first|second|third|fourth|last) sentence"), lambda m: f"{m['n']} sentence"),
    # "in the heading", "In the section heading for section 430c", "The heading for section 723 of title 10 is amended",
    # "In the subsection heading for subsection (c) of section 3072"; not "in the heading of the second column".
    (HEADING_QUAL, lambda m: "heading" if not m["u"] else f"{m['u']} heading"),
    (re.compile(r"\bin the item relating to (?P<x>[^,;]+?)(?=,|;| by |$)"), lambda m: f"item relating to {m['x']}"),
]
LEAD_UNITS = re.compile(rf"^(?:{UNIT}) (?P<labels>{LABELS}(?:(?:,| and|, and) {LABELS})*) of (?:such )?section ",
                        re.I)
_SN = r"\d[\w\u2013-]*+"           # possessive: no backtracking between the digits and the suffix
SECTION_LIST = re.compile(rf"\b[Ss]ections (?P<list>{_SN}(?:{LABELS})?(?:(?:,| and|, and) {_SN}(?:{LABELS})?)+)"
                          r" of (?:such title|this title|title \d+,? United States Code)\b")
# "(1) in each of sections 46101(a)(1), 46102(a), and 46110(a) by striking ...", under "Chapter 461 is amended—":
# the title is the one in context (Pub. L. 115-254 div. K § 1991(f)).
# A comma the drafter left out between two entries ("46102(a) 46103(a)", § 1991(f)(3)) still separates them.
EACH_SECTIONS = re.compile(rf"^\s*[Ii]n (?:each of )?sections (?P<list>{_SN}(?:{LABELS})?(?:(?:,| and|, and|) "
                           rf"{_SN}(?:{LABELS})?)+),?\s*(?:by\s*)?$")
# "Except as otherwise expressly provided, wherever in this title an amendment or repeal is expressed in terms of an
# amendment to, or repeal of, a section or other provision, the reference shall be considered to be made to that
# section or other provision of the Social Security Act."
REFERENCES_CLAUSE = re.compile(
    r"\b(?:wherever|whenever) in this (?P<scope>Act|division|title|subtitle|part|chapter|section|subsection)\b"
    r"[^.]{0,200}?"
    r"expressed in terms of an amendment[^.]{0,160}?references? shall be considered to be made to (?:a|that|the) (?:section or "
    rf"other provision|section|provision) of (?:title (?P<title>\d+),? United States Code|(?P<act>{ACT_NAME}))")
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


# "Such subchapter is further amended" (no number): the Code unit named last, in this bill section or an earlier one.
SUCH_BARE_UNIT = re.compile(r"^[Ss]uch (?P<u>chapter|subchapter|part|subpart|subtitle) (?:is|are) (?:further )?amended")
# "Such subsection is further amended" after "Subsection (a) of section 1562 of title 38 ... is amended": the
# section's own unit named last (Pub. L. 116-315 § 2003(b)(1)).
SUCH_OWN_UNIT = re.compile(r"^[Ss]uch (?P<u>subsection|paragraph|subparagraph|clause) (?:is|are) (?:further )?amended")
OWN_LABEL = {"subsection": r"\([a-z]+\)", "paragraph": r"\(\d+[A-Za-z]?\)", "subparagraph": r"\([A-Z]+\)",
             "clause": r"\([ivxl]+\)"}
SUCH_UNIT = re.compile(r"(?:\b[Ss]uch (?P<u1>chapter|subchapter|part|subpart) (?P<x1>[\w]+)|"
                       r"\b(?P<u2>[Cc]hapter|[Ss]ubchapter|[Pp]art|[Ss]ubpart) (?P<x2>[\w]+) of (?:such|this) title)")


def _usc_base(ctx: Ctx) -> Target | None:
    for t in (ctx.target, ctx.memory.get("last"), ctx.memory.get("usc")):
        if t is not None and t.kind == "usc" and t.title:
            return t
    return None


def _named_unit(ctx: Ctx, unit: str) -> Target | None:
    """The Code unit target named last whose innermost unit is `unit` ("subchapter ii of chapter 17")."""
    for t in (ctx.memory.get("usc"), ctx.memory.get("prior_usc")):
        if t is not None and t.kind == "usc" and t.qualifiers and t.qualifiers[0].split()[0] == unit:
            return t
    return None


def apply_head(head: str, ctx: Ctx, quotes: list[str] | None = None) -> list[str]:
    """Update ctx from a head phrase (target and location). Returns flags."""
    flags: list[str] = []
    h = usc_variants(head)
    # "Section 505–1(h)(21 U.S.C. 355–1(h)) is amended": no space before the Code parenthetical (Pub. L. 114-255
    # § 3101(a)(2)(C)); it is not a label.
    h = re.sub(r"\)\((\d+ U\.S\.C\. )", r") (\1", h)
    h = re.sub(r"^[^\u201c\u2014]{1,160}?\.\u2014", "", h) if re.match(r"^[A-Z][^.\u2014]{0,160}\.\u2014", h) else h
    # Neither "Except as provided in paragraph (2)," nor "(as defined in section 102 of title 10 ...)" names the target.
    h = re.sub(r"^\s*[Ee]xcept as (?:otherwise )?(?:expressly )?provided in [^,]+,\s*", "", h)
    h = re.sub(r"\(as defined in [^()]*(?:\([^()]*\)[^()]*)*\)", "", h)
    # "Subsection (b) and subsection (d) of section 311103 ... are amended" is "Subsections (b) and (d) of ..." (Pub. L.
    # 114-289 § 501(d)); read as the last unit alone, the edit fell on the whole section.
    h = re.sub(r"\b([Ss]ubsection|[Pp]aragraph|[Ss]ubparagraph|[Cc]lause|[Ss]ubclause|[Ii]tem) ((?:\([\w.-]+\))+) and "
               r"(?i:\1) ((?:\([\w.-]+\))+)", lambda m: f"{m.group(1)}s {m.group(2)} and {m.group(3)}", h)
    # "The second sentence of paragraph (1) of section 3(a) of the ... Act is amended": the target is the paragraph,
    # restricted to that sentence (Pub. L. 114-94 § 78001(a)).
    sentence = re.match(r"^\s*[Tt]he (?P<n>first|second|third|fourth|last) sentence of ", h)
    if sentence:
        h = h[sentence.end():]
        h = h[:1].upper() + h[1:]
    if TOC_HEAD.search(h):
        ctx.toc = True
    m = USC_SECTION.search(h)
    if (b := BLANKET.search(h)):
        # "each covered defense law ... is amended by striking the term “…” in each place it appears": no single
        # target; reported, and the self-checks look for the struck words in every predicted section.
        ctx.target = Target(kind="unknown", cite_raw=b.group(0))
        ctx.path, ctx.qualifiers, ctx.is_target_set = [], [f"blanket: {b['what']}"], True
    elif m:
        ctx.target = Target(kind="usc", cite_raw=m.group(0), title=m["t"], section=m["sec"])
        _section_path(ctx, m["path"])
        ctx.qualifiers, ctx.is_target_set = [], True
    elif (m := PL_SECTION.search(h)):
        ctx.target = Target(kind="pl", cite_raw=m.group(0), section=m["sec"], public_law=m["pl"].replace("–", "-"),
                            usc_parenthetical=m["paren"])
        _section_path(ctx, m["path"])
        ctx.qualifiers, ctx.is_target_set = [], True
    elif (m := SECTION_LIST.search(h)) or (m := EACH_SECTIONS.search(h)) and _usc_base(ctx) is not None:
        # "Sections 351(a), 352(a), and 353(b) of such title": the first here; parse_unit_text fans out the rest.
        tm = re.search(r"title (\d+)", m.group(0))
        base = (Target(kind="usc", title=tm.group(1)) if tm else
                Target(kind="usc", title=_usc_base(ctx).title) if m.re is EACH_SECTIONS else
                ctx.target if ctx.target.kind != "unknown" else ctx.memory.get("last") or ctx.target)
        t = base.model_copy(deep=True)
        first = re.match(rf"(?P<sec>{SECTION_NUM}?)(?P<path>{LABELS})?", m["list"])
        t.section, t.cite_raw, t.usc_parenthetical = first["sec"], m.group(0), None
        ctx.target = t
        _section_path(ctx, first["path"])
        ctx.qualifiers, ctx.is_target_set = [], True
    elif (m := SUCH.search(h)):
        base = ctx.target if ctx.target.kind != "unknown" else ctx.memory.get("last") or ctx.target
        is_act = m["what"] != "title"
        if is_act and ctx.target.kind not in ("act", "pl") and ctx.memory.get("act") is not None:
            base = ctx.memory["act"]              # "Section 401 of such Act": the Act named last in this section
        elif not is_act and base.kind != "usc":
            base = _usc_base(ctx) or base         # "Section 3763 of such title" after "Subchapter V of ... title 38"
        t = base.model_copy(deep=True)
        t.section, t.cite_raw, t.usc_parenthetical = m["sec"], m.group(0), m["paren"] if is_act else None
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
        # "such section" is the whole section, not the unit the last instruction reached (10 U.S.C. 129a, Pub. L.
        # 119-60 § 1107(c): "Such section 129a is amended by adding at the end" after an edit in subsection (b)).
        ctx.target = ctx.memory["last"].model_copy(deep=True)
        ctx.target.path, ctx.path = [], []
        if m["num"]:
            ctx.target.section = m["num"]
        for u in reversed(list(re.finditer(SUCH_UNIT_OF, m["chain"]))):     # outermost unit is named last
            _set_path(ctx, u["unit"].lower(), u["labels"])
        ctx.qualifiers, ctx.is_target_set = [], True
    elif (m := SUCH_SECTION_NUM.search(h)) and (ctx.memory.get("last") is not None or _usc_base(ctx) is not None):
        # "In subsection (a)(2) of such section 710a, as so redesignated—": the section named in the title in context.
        base = ctx.memory.get("last") if ctx.memory.get("last") is not None else _usc_base(ctx)
        ctx.target = base.model_copy(deep=True)
        ctx.target.section, ctx.target.cite_raw, ctx.target.path, ctx.target.qualifiers = m["num"], m.group(0), [], []
        ctx.path, ctx.qualifiers, ctx.is_target_set = [], [], True
    elif (m := PAREN_SECTION.search(h.strip())) and ctx.target.kind in ("unknown", "act"):
        # "Section 2(6) (16 U.S.C. 973(6)) is amended": the Act is implied by the enclosing provision, or by the
        # bill's references clause ("... shall be considered to be made to ... the Social Security Act").
        act = ctx.target.act if ctx.target.kind == "act" else None
        if act is None and ctx.memory.get("default_act") and not ctx.memory["default_act"].startswith("title "):
            act = ctx.memory["default_act"]
            flags.append(f"Act from the references clause: {act}")
        ctx.target = Target(kind="act", cite_raw=m.group(0), section=m["sec"], act=act, usc_parenthetical=m["paren"])
        _section_path(ctx, m["path"])
        ctx.qualifiers, ctx.is_target_set = [], True
    elif (m := WHOLE_ACT.search(h)):
        ctx.target = Target(kind="act", cite_raw=m.group(0), act=_unquote(re.sub(r"^The ", "", m["act"]), quotes),
                            usc_parenthetical=m["paren"])
        ctx.path, ctx.qualifiers, ctx.is_target_set = [], [], True
    elif (m := SUCH_OWN_UNIT.match(h.strip())) and (last := ctx.memory.get("last")) is not None and \
            last.section and (depth := ["subsection", "paragraph", "subparagraph", "clause"].index(m["u"])) < \
            len(last.path) and re.fullmatch(OWN_LABEL[m["u"]], last.path[depth]):
        ctx.target = last.model_copy(deep=True)
        ctx.target.path = []
        ctx.path = [(i, lab) for i, lab in enumerate(last.path[:depth + 1])]
        ctx.qualifiers, ctx.is_target_set = [], True
        flags.append(f"such {m['u']}: {last.cite_raw}")
    elif (m := SUCH_BARE_UNIT.match(h.strip())) and (prior := _named_unit(ctx, m["u"])) is not None:
        ctx.target = prior.model_copy(deep=True)
        ctx.path, ctx.qualifiers, ctx.is_target_set = [], list(prior.qualifiers), True
        flags.append(f"such {m['u']}: {prior.cite_raw}")
    elif (m := SUCH_UNIT.search(h)) and _usc_base(ctx) is not None:
        # "Chapter 2003 of such title", "Such chapter 908": a unit of the title in context.
        unit, x = (m["u1"] or m["u2"]).lower(), m["x1"] or m["x2"]
        ctx.target = Target(kind="usc", cite_raw=m.group(0), title=_usc_base(ctx).title)
        ctx.path, ctx.qualifiers, ctx.is_target_set = [], [f"{unit} {x}"], True
    elif (m := USC_TITLE.search(h)) and not ctx.is_target_set:
        ctx.target = Target(kind="usc", cite_raw=m.group(0), title=m["t"])
        ctx.path, ctx.qualifiers, ctx.is_target_set = [], [], True
    elif (m := BARE_SECTION.search(h.strip())) or (m := IN_SECTION.search(h)):
        base = ctx.target if ctx.target.kind != "unknown" else ctx.memory.get("last")
        if base is not None:
            # "(2) Notice.—Section 41731(a)(1)(D)(ii) is amended ..." after "(1) ... Section 41731(a)(1)(C) of
            # title 49, United States Code, is amended": the root comes from the bill section's last citation.
            if ctx.target.kind == "unknown":
                flags.append(f"root from context: {base.cite_raw}")
            t = base.model_copy(deep=True)
            t.section, t.cite_raw, t.usc_parenthetical, t.path = m["sec"], m.group(0), None, []
            ctx.target = t
            _section_path(ctx, m["path"])
            ctx.qualifiers = []
        elif ctx.memory.get("default_act"):
            act = ctx.memory["default_act"]
            flags.append(f"root from the references clause: {act}")
            t = re.fullmatch(r"title (\d+)", act)
            ctx.target = (Target(kind="usc", cite_raw=m.group(0), title=t.group(1), section=m["sec"]) if t else
                          Target(kind="act", cite_raw=m.group(0), section=m["sec"], act=act))
            _section_path(ctx, m["path"])
            ctx.qualifiers, ctx.is_target_set = [], True
        else:
            flags.append("section_without_root")
    m = LEAD_UNITS.match(h.strip())
    if m and ctx.is_target_set:
        chains = re.findall(LABELS, m["labels"])
        if len(chains) == 1:
            _section_path(ctx, chains[0])
        else:
            ctx.multi = [[(i, lab) for i, lab in enumerate(_labels(c))] for c in chains]
            flags.append("multi_scope")
    m = EACH_OF.search(h)
    if m:
        unit = PLURAL.get(m["unit"], m["unit"])
        rank = UNIT_RANK.get(unit, 0)
        base = [p for p in ctx.path if p[0] < rank]
        # "in each of paragraphs (1)(A) and (2)(C)": chains, not single labels
        ctx.multi = [base + [(rank + i, lab) for i, lab in enumerate(_labels(chain))]
                     for chain in re.findall(LABELS, m["labels"])]
        flags.append("multi_scope")
    else:
        for m in LOCATION.finditer(h):
            if len(_labels(m["labels"])) > 1 and re.search(r"\)(?:,| and| or)", m["labels"]):
                unit = PLURAL.get(m["unit"], m["unit"])
                rank = UNIT_RANK.get(unit, 0)
                base = [p for p in ctx.path if p[0] < rank]
                ctx.multi = [base + [(rank + i, lab) for i, lab in enumerate(_labels(chain))]
                             for chain in re.findall(LABELS, m["labels"])]
                flags.append("multi_scope")
            else:
                _set_path(ctx, m["unit"], m["labels"])
    for rx, fmt in QUALIFIERS:
        for m in rx.finditer(h):
            q = fmt(m)
            if q not in ctx.qualifiers:
                ctx.qualifiers.append(q)
            if rx is HEADING_QUAL and m["fu"]:          # "the subsection heading for subsection (c)"
                _set_path(ctx, m["fu"], m["fl"])
    if sentence and f"{sentence['n']} sentence" not in ctx.qualifiers:
        ctx.qualifiers.append(f"{sentence['n']} sentence")
    for m in DEFINING.finditer(h):
        # "in the paragraph defining the term “State”": the engine finds the unit that defines the term.
        term = quotes[int(m["q"])] if quotes and int(m["q"]) < len(quotes) else None
        if term and f"defining {term}" not in ctx.qualifiers:
            ctx.qualifiers.append(f"defining {term}")
    return flags


# ---- operations ----------------------------------------------------------------------------
Q = r"⟦(?P<{}>\d+)⟧"


def q(name: str) -> str:
    return Q.format(name)


LABEL_LIST = rf"{LABELS}(?:(?:,? and|,| through|, and| or) {LABELS})*"
UNIT_LIST = rf"(?:(?:{UNIT}) {LABEL_LIST}(?: of (?:{UNIT}) {LABELS})?(?:(?:,? and|,) (?=(?:{UNIT}) ))?)+"
ITEM = (r"(?P<item>the (?:items?|matter) relating to (?:(?:sections?|chapters?|subchapters?|parts?|subtitles?|titles?|"
        r"articles?) [\dIVXL][\w\u2013.-]*(?:(?:,| and|, and| through) [\dIVXL][\w\u2013.-]*)*|\u27e6(?P<itemq>\d+)\u27e7))")
FOLLOWING = r"the following(?: new [a-z ]+)?:?"
TERM = r"(?:the (?:terms?|phrases?|words?|figures?) )?"       # "striking the term “program executive officer”"
AS_REDESIGNATED = r"(?:,? \(?as (?:so )?redesignated(?: by [^,()]+)?\)?,?)?"
PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("P13", re.compile(rf"^striking {q('a')}{OCC} and all that follows through {q('b')}"
                       rf"(?: and inserting (?:(?:the following:? ?)?{q('c')}|(?P<block>{FOLLOWING})))?"), "STRIKE_THROUGH"),
    ("P13t", re.compile(rf"^striking {q('a')} through {q('b')}"
                        rf"(?: and inserting (?:(?:the following:? ?)?{q('c')}|(?P<block>{FOLLOWING})))?"), "STRIKE_THROUGH"),
    ("P13d", re.compile(rf"^striking {q('a')} and all that follows through (?P<toend>the end of (?:the )?(?:section|"
                        rf"subsection|paragraph|subparagraph|clause|subclause|item|subitem|sentence)(?: \(\w+\))*|"
                        rf"(?:the )?(?P<tpunct>period|semicolon|colon)(?P<tend> at the end)?)(?: and inserting (?:(?:the following:? ?)?{q('c')}|"
                        rf"(?P<block>{FOLLOWING})))?"),
     "STRIKE_THROUGH"),
    ("P13e", re.compile(rf"^striking {q('a')}{OCC} and all that follows(?: through the end(?: of [\w ]+?(?: \([\w]+\))*)?)?"
                        rf"(?: and inserting (?:(?:the following:? ?)?{q('c')}|(?P<block>{FOLLOWING})))?"), "STRIKE_THROUGH"),
    ("P7s", re.compile(rf"^striking (?:the )?section (?P<labels>{SECTION_NUM})(?: \([^()]*(?:\([^()]*\)[^()]*)*\))? "
                       rf"and inserting (?P<block>{FOLLOWING})"), "REPLACE_UNIT"),
    ("P7", re.compile(rf"^striking (?:the )?(?P<unit>{UNIT}) (?P<labels>{LABELS}(?:(?:,| and|, and| through) {LABELS})*)"
                      rf"(?P<of> of [\w ]+? {LABELS})? and inserting (?P<block>{FOLLOWING})"), "REPLACE_UNIT"),
    # "striking “or” after “military installation resilience,”", "striking the period after “21”", "striking “and”
    # before “14504”": the struck words are found next to the anchor words.
    ("P3a", re.compile(rf"^striking (?:{q('a')}|the (?P<punct>period|semicolon|comma|colon|em dash|dash)(?: that appears)?)"
                       rf" (?P<where>after|before) {q('x')}(?: and inserting (?:{q('c')}|(?:a|an|the) (?P<punct2>period|"
                       rf"semicolon|comma|colon|em dash|dash)))?"), "STRIKE_INSERT"),
    ("P2", re.compile(rf"^striking {TERM}{q('a')}{AT_END}{OCC} and inserting (?:(?:the following:? ?)?{q('b')}|(?P<block>{FOLLOWING})|"
                      rf"(?:a|an|the) (?P<punct2>period|semicolon|comma|colon|em dash|dash)){OCC.replace('occ', 'occ2').replace('nth', 'nth2')}"),
     "STRIKE_INSERT"),
    ("P2p", re.compile(rf"^striking {DESCR}(?: at the end(?: (?:thereof|of [\w ]+?(?: \([\w]+\))*))?| after {q('anchor')})?{OCC} "
                       rf"and inserting (?:(?:the following:? ?)?{q('b')}|(?P<block>{FOLLOWING})|"
                       rf"(?:a|an|the) (?P<punct2>period|semicolon|comma|colon|em dash|dash))"), "STRIKE_INSERT"),
    ("P10h", re.compile(rf"^(?:striking the (?:(?P<u>section|subsection|paragraph|subparagraph|clause|subclause) )?heading"
                        rf" and inserting|amending the (?:(?P<u2>section|subsection|paragraph|subparagraph|clause|"
                        rf"subclause) )?heading to read as follows:?) (?:the following:? ?)?{q('b')}"), "AMEND_HEADING"),
    ("P7a", re.compile(rf"^amending (?:the )?(?P<unit>{UNIT}) (?P<labels>{LABELS}(?:(?:,| and|, and) {LABELS})*)"
                       rf"(?P<of> of [\w ]+? {LABELS})?"
                       rf"(?:,? as (?:so )?redesignated(?: by [^,]+)?,?)? to read as follows:?"), "REPLACE_UNIT"),
    ("P9u", re.compile(rf"^repealing (?:the )?(?P<unit>{UNIT}) (?P<labels>{LABELS}(?:(?:,| and|, and| through) {LABELS})*)"),
     "STRIKE_UNIT"),
    ("P7b", re.compile(rf"^striking (?:the )?(?P<unit>{UNIT}) (?P<labels>{LABELS}(?:(?:,| and|, and| through) {LABELS})*)"),
     "STRIKE_UNIT"),
    ("P3", re.compile(rf"^striking {TERM}{q('a')}{AT_END}{OCC}"), "STRIKE"),
    ("P10x", re.compile(r"^striking the (?:(?P<u>section|subsection|paragraph|subparagraph|clause|subclause) )?heading"
                        r"(?! and)"), "AMEND_HEADING"),
    ("P3p", re.compile(rf"^striking {DESCR}(?: at the end(?: of [\w ()]+?)?)?{OCC}"), "STRIKE"),
    ("P3s", re.compile(rf"^striking the (?P<sent>first|second|third|last|fourth) sentence(?: and inserting (?:(?:the "
                       rf"following:? ?)?{q('b')}|(?P<block>{FOLLOWING})))?"), "STRIKE"),
    ("P11s", re.compile(rf"^striking {ITEM}(?: and inserting (?:(?:the following:? ?)?{q('b')}|(?P<block>{FOLLOWING})))?"),
     "CONFORM_TOC"),
    ("P11i", re.compile(rf"^inserting (?P<where>after|before) {ITEM},? (?:(?:the following:? ?)?{q('b')}|(?P<block>{FOLLOWING}))"),
     "CONFORM_TOC"),
    ("P6s", re.compile(rf"^inserting (?P<where>after|before) (?:the )?section (?P<labels>{SECTION_NUM})"
                       r"(?: \([^()]*(?:\([^()]*\)[^()]*)*\))?(?:,? as so redesignated[^,]*,?)? "
                       rf"(?P<block>{FOLLOWING})"), "ADD_UNIT_"),
    ("P5i", re.compile(rf"^inserting at the end(?: (?:thereof|of [\w ]+?(?: {LABELS})?))?,? (?:{q('b')}|(?P<block>{FOLLOWING}))"),
     "ADD_END"),
    ("P6", re.compile(rf"^inserting (?P<where>after|before) (?:the )?(?P<unit>{UNIT}) (?P<labels>{LABELS})"
                      rf"(?: of [\w ]+? {LABELS})?{AS_REDESIGNATED},? (?P<block>{FOLLOWING})(?: ?{q('b')})?"),
     "ADD_UNIT_"),
    ("P4b", re.compile(rf"^inserting (?P<where>after|before) {q('a')}{OCC},? (?P<block>{FOLLOWING})(?: ?{q('b')})?"),
     "INSERT_"),
    # "inserting the following before the period at the end: “…”", "inserting before the semicolon the following:"
    ("P4pb", re.compile(rf"^(?:inserting|adding at the end) (?:the following:? )?(?P<where>after|before) {DESCR}(?P<atend2> at the end(?: of "
                        rf"[\w ()]+?)?)?(?:,? (?P<block>{FOLLOWING}))?:?(?: ?{q('b')})?"), "INSERT_"),
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
        return {"first": "nth:1", "second": "nth:2", "third": "nth:3", "fourth": "nth:4", "fifth": "nth:5",
                "last": "last"}[nth]
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
        elif is_roman(x) and is_roman(y) and max(len(x), len(y)) > 1 and roman_to_int(x) < roman_to_int(y):
            # "(i) through (iii)": a roman range (a range of single letters is read as letters below)
            out += [f"({r if x.islower() else r.upper()})" for r in
                    (int_to_roman(i) for i in range(roman_to_int(x), roman_to_int(y) + 1))]
        elif len(x) == 1 and len(y) == 1 and x.isalpha() and y.isalpha():
            out += [f"({chr(c)})" for c in range(ord(x), ord(y) + 1)]
        else:
            out += [a, b]
    return out


MID_LOC = re.compile(r"^(?P<head>striking (?:the (?:terms?|phrases?|words?) )?⟦\d+⟧(?: (?:at )?(?:each|both) places? [^⟦,;]*?"
                     r"appears?)?),? (?P<loc>in (?:the )?(?:(?:sub)?sections?|paragraphs?|subparagraphs?|clauses?|"
                     r"subclauses?|(?:\w+ )?heading|first sentence|second sentence|third sentence|last sentence)\b[^⟦]*?),?"
                     r" (?P<tail>and inserting\b.*)$")
NONSTANDARD = [   # (pattern, standard form): read as the usual verbs; the instruction is flagged and stays WARN
    (re.compile(r"^replacing (⟦\d+⟧)(.*?) with (⟦\d+⟧)"), r"striking \1\2 and inserting \3"),
    (re.compile(r"^substituting (⟦\d+⟧) for (⟦\d+⟧)"), r"striking \2 and inserting \1"),
    (re.compile(r"^deleting\b"), "striking"),
    (re.compile(r"^strike\b"), "striking"),
    (re.compile(r"^insert\b"), "inserting"),
    (re.compile(r"^add\b"), "adding"),
    (re.compile(r"^redesignate\b"), "redesignating"),
]


def parse_clause(clause: str, quotes: list[str], block: str | None) -> dict | None:
    """One instruction clause (starting at its verb) -> op fields, or None if no pattern matches."""
    c = " ".join(clause.split())          # a quote may start on the next line ("and inserting\n“(D) …”")
    nonstandard, loc = None, None
    if re.search(r"\band insert\b", c):
        c, nonstandard = re.sub(r"\band insert\b", "and inserting", c), "insert"
    m = MID_LOC.match(c)
    if m:   # "striking “A” in subsections (b)(6)(B), (c)(1), and (e)(3) and inserting “B”"
        c, loc = f"{m['head']} {m['tail']}", m["loc"]
    for rx, std in NONSTANDARD:
        if rx.match(c):
            nonstandard = c.split()[0]
            c = rx.sub(std, c, count=1)
            c = re.sub(r"\band insert\b", "and inserting", c)     # imperative "strike “A” and insert “B”"
            break
    out = _parse_clause(c, quotes, block)
    if out is not None and nonstandard:
        out["flags"] = out.get("flags", []) + [f"nonstandard verb: {nonstandard}"]
    if out is not None and loc:
        out["loc"] = loc
    return out


def _parse_clause(c: str, quotes: list[str], block: str | None) -> dict | None:
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
        if pid in ("P13", "P13d", "P13e", "P13t"):
            through = get("b") or gd.get("toend") or "end of unit"
            if gd.get("tpunct") and not gd.get("tend"):
                through = PUNCT[gd["tpunct"]]       # "through the period": the next period after the start
            out |= {"op": op, "find": get("a"), "through": through,
                    "replace": get("c"),
                    "new_text": block if uses_block else None}
        elif pid == "P7s":            # "Chapter 1009 ... is amended by striking section 100905 and inserting"
            out |= {"op": op, "new_text": block, "section": gd["labels"]}
        elif pid == "P10x":           # "by striking the subsection heading"
            u = gd.get("u")
            out |= {"op": op, "replace": "", "unit": f"{u} heading" if u else "heading", "flags": ["heading struck"]}
        elif pid == "P10h":
            u = gd.get("u") or gd.get("u2")
            out |= {"op": op, "replace": get("b"), "unit": f"{u} heading" if u else "heading",
                    "flags": ["heading replaced"]}
        elif pid in ("P7", "P7a"):
            out |= {"op": op, "unit": f"{gd['unit']} {gd['labels']}{gd.get('of') or ''}", "new_text": block}
        elif pid == "P3a":
            a = get("a") if gd.get("a") is not None else PUNCT[gd["punct"]]
            c = get("c") if gd.get("c") is not None else (PUNCT[gd["punct2"]] if gd.get("punct2") else None)
            x = get("x")

            def join(left, right):
                return left + right if right in PUNCT.values() else left + " " + right
            if gd["where"] == "after":
                find, replace = join(x, a), (join(x, c) if c else x)
            else:
                find, replace = join(a, x), (join(c, x) if c else x)
            out |= {"op": op, "find": find, "replace": replace, "flags": [f"anchored {gd['where']} “{x[:40]}”"]}
        elif pid in ("P2", "P2p"):
            find = get("a") if pid == "P2" else PUNCT[gd["punct"]]
            replace = get("b") if gd.get("b") is not None else (PUNCT[gd["punct2"]] if gd.get("punct2") else None)
            if replace and block and re.search(r"[:\u2014]\s*$", replace) and not gd.get("block"):
                # "inserting “may not be used at the following:”" and then the block of new units it introduces.
                replace = "\u201c" + replace + "\n" + block
            out |= {"op": op, "find": find, "replace": replace, "new_text": block if uses_block else None}
            if pid == "P2p" or gd.get("atend"):
                out["flags"] = ["positional: " + m.group(0).split(" and inserting")[0][len("striking "):]]
        elif pid == "P7b":
            out |= {"op": op, "unit": f"{gd['unit']} {gd['labels']}"}
        elif pid == "P9u":
            out |= {"op": op, "unit": f"{gd['unit']} {gd['labels']}", "flags": ["repealed unit"]}
        elif pid == "P3":
            out |= {"op": op, "find": get("a")}
            if gd.get("atend"):
                out["flags"] = ["positional: " + m.group(0)[len("striking "):]]
        elif pid == "P3p":
            out |= {"op": op, "find": PUNCT[gd["punct"]], "flags": ["positional: " + m.group(0)[len("striking "):]]}
        elif pid == "P3s":
            rep = get("b") if gd.get("b") is not None else (block if gd.get("block") else None)
            out |= {"op": op, "unit": f"{gd['sent']} sentence", "replace": rep}
        elif pid in ("P6", "P6s"):
            unit = f"{gd['unit']} {gd['labels']}" if pid == "P6" else f"section {gd['labels']}"
            inline = "\u201c" + get("b") + "\u201d" if gd.get("b") is not None else None   # “(B) …” quoted inline
            out |= {"op": op + ("AFTER" if gd["where"] == "after" else "BEFORE"), "unit": unit,
                    "new_text": inline or block}
        elif pid in ("P11s", "P11i"):
            item = gd.get("item") or ""
            if gd.get("itemq") is not None:
                item = "the item " + quotes[int(gd["itemq"])]
            out |= {"op": op, "unit": item, "replace": get("b"), "new_text": block if uses_block else None,
                    "flags": [f"table of contents: {'strike' if pid == 'P11s' else 'insert ' + gd['where']} {item}"]}
        elif pid == "P5i":
            out |= {"op": op, "new_text": get("b") if gd.get("b") is not None else block}
        elif pid == "P4b":
            out |= {"op": op + ("AFTER" if gd["where"] == "after" else "BEFORE"), "find": get("a"),
                    "new_text": get("b") if gd.get("b") is not None else block}
        elif pid == "P4pb":
            if gd.get("b") is None and not gd.get("block") and not block:
                continue
            out |= {"op": op + ("AFTER" if gd["where"] == "after" else "BEFORE"), "find": PUNCT[gd["punct"]],
                    "new_text": get("b") if gd.get("b") is not None else block,
                    "flags": [f"anchor is positional: {PUNCT[gd['punct']]}"]}
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
        if "heading" in (gd.get("occ") or "") + (gd.get("occ2") or ""):    # "each place it appears in text or headings"
            out["flags"] = out.get("flags", []) + ["each place, headings included"]
        out["needs_block"] = uses_block or pid in ("P7", "P7a", "P6", "P6s", "P4b")
        return out
    return None


HEAD_WHERE = re.compile(rf"\b(?P<where>after|before) (?:the )?(?P<unit>{UNIT}) (?P<labels>{LABELS})"
                        r"(?:\s*\(as (?:so )?redesignated[^()]*\))?,?\s*(?:by\s*)?$")
BLANKET = re.compile(r"\b(?:[Ee]ach|[Aa]ny|[Aa]ll) (?P<what>(?:covered |applicable |other )?[\w ]{0,40}?(?:laws?|Acts?|"
                     r"statutes?|provisions? of (?:Federal )?law))\s*,?\s*(?:is|are) (?:hereby )?amended\b")
APPLIED_AS = re.compile(r"\bshall (?:be applied|apply)\b[^.]{0,80}?\b(?:by|as if)\b\s*$|\bshall be applied\b")
CONFORMING = re.compile(r"\s*\(and conforming the table of (?:sections|contents|chapters)[^()]*\)")
TRAILING_OK = re.compile(r"^[\s,.;:\u2014]*(?:respectively|and|or)?[\s,.;:\u2014]*(?:and|or)?[\s,.;:\u2014]*$")
TRAILING_LOC = re.compile(rf"^,?\s*(?:in|of) (?:the )?(?:{UNIT}|section) [\w–.-]*(?:{LABELS})?"
                          rf"(?:\s+of\s+(?:such|this|that)\s+\w+)?(?:,? as so redesignated)?")


DISTRIBUTED = re.compile(r"\b[Tt]he following (?:sections|provisions|paragraphs|subsections)\b[^\u27e6]*?\b(?:is|are) "
                         r"(?:each )?(?:further )?amended(?: by)?\s*$")


# "The following provisions of title 10, United States Code, are hereby repealed: (1) Chapter 345. (2) Section 3070."
DISTRIBUTED_REPEAL = re.compile(r"\b[Tt]he following (?:sections|provisions|chapters)\b[^\u27e6]*?\s*$")
LISTED_UNIT = re.compile(r"^(?P<unit>[Cc]hapter|[Ss]ubchapter|[Pp]art|[Ss]ubpart) (?P<x>[\w]+)$")


def _distributed(node: Node, ctx: Ctx) -> list[Ctx]:
    """"The following sections of title 10 ... are amended by striking X and inserting Y: (1) Section 2130a(a)(1),
    relating to ...; (2) ...": one target per listed item. Empty unless every item names a provision."""
    out = []
    for c in node.children:
        text, quotes, _ = lift_quotes(c.text)
        text = re.sub(r"(?:,\s*relating to .*)?[.;]?(?:\s*and)?\s*$", "", text.strip())
        d = ctx.copy()
        d.is_target_set, d.multi = False, []
        apply_head(text, d, quotes)
        unit = LISTED_UNIT.match(text)
        if unit and d.target == ctx.target and _usc_base(ctx) is not None:      # "(1) Chapter 345."
            d.target = Target(kind="usc", cite_raw=text, title=_usc_base(ctx).title)
            d.path, d.qualifiers = [], [f"{unit['unit'].lower()} {unit['x']}"]
        elif d.target.kind == "unknown" or not d.target.section or d.target == ctx.target:
            # An item naming no single provision (a whole Act, "Sections 3116 and 3141 of ..."): its own
            # instruction with an unknown target, reported with its text rather than guessed.
            d.target, d.path, d.qualifiers = Target(kind="unknown", cite_raw=text), [], []
        out.append(d)
    return out if any(d.target.kind != "unknown" for d in out) else []


def _section_list(head: str, ctx: Ctx) -> list[Ctx]:
    """"Sections 351(a), 352(a), 353(a), and 353(b) of such title are amended by ...": one target per section."""
    m = SECTION_LIST.search(head) or EACH_SECTIONS.search(head)
    if not m or ctx.target.kind != "usc":
        return []
    out = []
    for sm in re.finditer(rf"(?P<sec>{SECTION_NUM}?)(?P<path>{LABELS})?(?=,| and| \d|$)", m["list"]):
        if not sm["sec"]:
            continue
        d = ctx.copy()
        d.target = ctx.target.model_copy(deep=True)
        d.target.section, d.target.cite_raw = sm["sec"], m.group(0)
        _section_path(d, sm["path"])
        d.multi = []
        out.append(d)
    return out if len(out) > 1 else []


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
    if child_ctx.target.kind == "usc" and child_ctx.target.title:
        child_ctx.memory["usc"] = child_ctx.target_out()      # for "such chapter 908" later in the section
    if child_ctx.target.kind == "act" and child_ctx.target.act:
        child_ctx.memory["act"] = child_ctx.target_out()      # for "section 401 of such Act"
    out: list[Instruction] = []
    listed = (_distributed(node, child_ctx) if starts and node.children and
              (DISTRIBUTED.search(head) or DISTRIBUTED_REPEAL.search(head) and starts[0]["repeal"]) else [])
    listed = listed or (_section_list(head, child_ctx) if starts else [])
    for i, st in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(lifted)
        clause = lifted[st.start():end]
        if i == 0 and (w := HEAD_WHERE.search(head)) and clause.startswith("inserting the following"):
            # "after subclause (III), by inserting the following:" -> "inserting after subclause (III) the following:"
            clause = f"inserting {w['where']} {w['unit']} {w['labels']} " + clause[len("inserting "):]
        ictx = child_ctx.copy()
        parsed = parse_clause(clause, quotes, block)
        base = dict(id=f"{node.loc}#{ordinal_base + i}", bill_loc=node.loc, source_text=node.text, span=node.span,
                    shape_hash=shape_hash(clause))
        if parsed is None:
            out.append(Instruction(**base, target=ictx.target_out(), op="UNPARSED", flags=flags,
                                   confidence=0.0, reason=f"no grammar pattern matches: {PH_RE.sub('“…”', clause)[:160]}"))
            continue
        rest = CONFORMING.sub("", parsed.pop("rest", ""))
        loc_flags = apply_head(parsed.pop("loc"), ictx) if parsed.get("loc") else []   # location set mid-clause
        if (sec := parsed.pop("section", None)) and ictx.target.kind != "unknown":
            ictx.target = ictx.target.model_copy(deep=True)
            ictx.target.section, ictx.path, ictx.qualifiers = sec, [], []
        pflags = flags + loc_flags + parsed.pop("flags", [])
        if APPLIED_AS.search(head):
            # "Section 301 ... shall be applied by substituting “$130,000,000” for “$120,000,000”": a rule of
            # application, not an amendment; the Code text is unchanged (OLRC sets it out in a note).
            pflags.append("rule of application, not an amendment")
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
                "STRIKE_INSERT", "STRIKE", "INSERT_AFTER", "INSERT_BEFORE", "STRIKE_THROUGH", "ADD_END"):
            pflags.append(f"heading edit ({op})")
            op = "AMEND_HEADING"
        elif op == "REPLACE_UNIT" and any(qq.endswith("heading") or qq == "heading" for qq in ictx.qualifiers) and \
                parsed.get("new_text") and "\n" not in parsed["new_text"].strip():
            # "The heading of such section 1005 is amended to read as follows: “§ 1005. Army, ...”." (Pub. L.
            # 116-283 § 925(k)(1)(B)): the heading alone, never the whole unit. A section's number is not its heading.
            line = re.sub(r"^“|”[.;]?$", "", parsed.pop("new_text").strip()).strip()
            parsed["replace"] = re.sub(r"^§+\s*[\w.\u2013-]+\.\s*", "", line)
            parsed["unit"] = "heading" if ictx.path else "section heading"
            pflags.append("heading replaced")
            op = "AMEND_HEADING"
        if listed and TRAILING_OK.match(rest.rstrip(":")):
            for j, d in enumerate(listed):
                out.append(Instruction(**{**base, "id": f"{base['id']}.{j}"}, target=d.target_out(), op=op,
                                       confidence=conf, flags=pflags + [f"one of {len(listed)} listed provisions"],
                                       **{k: v for k, v in parsed.items() if v is not None}))
            continue
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
