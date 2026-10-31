"""OLRC's editorial work, told apart from substantive differences (M6 gate; records/m6e_dev_false_clean.md).

The gate compares a predicted section with the section at R_after. OLRC does more than execute the law's text: it
sets in enactment dates, translates Act references to Code citations, supplies headings in titles that are not
positive law, leaves "Repealed" placeholders and adds or removes footnote markers. Each rule below accepts one such
convention, and only where the evidence can be checked mechanically: a Code citation only when our own resolver maps
the Act citation to that section, a supplied heading only where the title is not positive law and the law does not
amend that heading, a placeholder only when it cites this law. Anything else stays a substantive difference.
"""
from __future__ import annotations

import copy
import difflib
import re
from dataclasses import dataclass, field
from typing import Callable

from lxml import etree

from ramseyer.data.indexer import text_of
from ramseyer.oracle.harness import normalize

DATE_PHRASE = re.compile(
    r"(?:the )?date of (?:the )?enactment of (?:this (?:Act|section|subsection|paragraph|subparagraph|sentence|"
    r"title|subtitle|division|part|chapter)|the (?P<act>[A-Z][\w ,.’'()-]*?Act(?: of \d{4})?(?: for Fiscal Year "
    r"\d{4})?(?:, \d{4})?))")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
# "section 4 of the Indian Self-Determination and Education Assistance Act" -> "section 5304 of title 25"
ACT_REF = re.compile(r"section (\d+[A-Za-z]*(?:[–-]\d+[A-Za-z]*)?)((?:\([^()\s]+\))*) of (the [A-Z][^,;:()\[\]]*?Act"
                     r"(?: of \d{4})?)")
UNIT = ("section", "subsection", "paragraph", "subparagraph", "clause", "subclause", "item", "subitem")


@dataclass
class Context:
    pl: str                                         # the law, "117-81"
    positive_law: bool | None = None                # the section's title at R_after
    heading_amended: bool = False                   # an instruction of the law amends a heading in the section
    new_notes: list[str] = field(default_factory=list)  # notes at R_after not at R_before
    resolve: Callable[[str], str | None] = lambda cite: None  # "Section 4 of the X Act" -> "/us/usc/t25/s5304"
    title: str = ""                                 # the section's title number, "42"
    # The enactment date of an Act named in the text ("CARES Act"), or of this law (None), as "2020-03-27"; None
    # when unknown, and then no date is accepted for the phrase.
    date_of: Callable[[str | None], str | None] = lambda act: None
    inserted: list[str] = field(default_factory=list)   # the law's quoted text inserted in the section

    @property
    def cite(self) -> str:
        return "Pub. L. " + self.pl.replace("-", "–")


def _local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _heading(el):
    return next((c for c in el if _local(c) == "heading"), None)


def _strip_footnotes(el) -> None:
    marks = el.xpath(".//*[local-name()='ref'][@class='footnoteRef'] | .//*[local-name()='note'][@type='footnote']"
                     " | .//*[local-name()='sup'][re:test(., '^\\s*\\d+\\s*$')]",
                     namespaces={"re": "http://exslt.org/regular-expressions"})
    for ref in marks:
        parent, tail = ref.getparent(), ref.tail or ""
        prev = ref.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "").rstrip("   ") + tail
        else:
            parent.text = (parent.text or "").rstrip("   ") + tail
        parent.remove(ref)


def _drop(el) -> None:
    parent, tail = el.getparent(), el.tail or ""
    prev = el.getprevious()
    if prev is not None:
        prev.tail = (prev.tail or "") + " " + tail
    else:
        parent.text = (parent.text or "") + " " + tail
    parent.remove(el)


def _chain(u, root) -> tuple[str, ...]:
    """A unit's numbers from the section down ("b", "1", ...)."""
    out = []
    for e in [u, *u.iterancestors()]:
        if _local(e) in UNIT and e is not root:
            num = next((c for c in e if _local(c) == "num"), None)
            out.append((num.get("value") or "".join(num.itertext()).strip("() .§")) if num is not None else "")
        if e is root:
            break
    return tuple(reversed(out))


def _inserted_without_heading(label: str, inserted: list[str]) -> bool:
    """The law's inserted text gives the unit "(label)" and gives it no heading ("(e) The Director ...", not "(e)
    Policymaking.—The Director ..."): a heading at R_after is then OLRC's, not one the engine lost."""
    lines = [ln.lstrip("“ ") for t in inserted for ln in t.split("\n")]
    mine = [ln for ln in lines if ln.startswith(f"({label})")]
    return bool(mine) and not any(re.match(rf"^\({re.escape(label)}\)\s*[A-Z][^.—]{{0,160}}\.—", ln) for ln in mine)


def texts(pred_el, after_el, ctx: Context | None = None) -> tuple[str, str]:
    """Both sections as comparable text: footnote markers removed, heading case and closing punctuation ("—", ".—")
    set aside, and, in a title that is not positive law, the catchline (unless the law amends a heading) and any
    heading OLRC supplied where the prediction has none."""
    pred_el, after_el = copy.deepcopy(pred_el), copy.deepcopy(after_el)
    for el in (pred_el, after_el):
        _strip_footnotes(el)
    if ctx is not None and ctx.positive_law is False:
        # Units are paired by their chain of numbers from the section: units the engine built from bill text carry
        # no identifier (Pub. L. 116-260 div. Q § 224, 15 U.S.C. 1062(b)).
        pred_units = {_chain(u, pred_el): u for u in pred_el.iter() if _local(u) in UNIT}
        for u in list(after_el.iter()):
            if _local(u) not in UNIT:
                continue
            h = _heading(u)
            if h is None or not "".join(h.itertext()).strip():
                continue
            if _local(u) == "section":
                if not ctx.heading_amended:          # catchlines of such titles are OLRC's
                    _drop(h)
                    ph = _heading(pred_el) if _local(pred_el) == "section" else None
                    if ph is not None:
                        _drop(ph)
                continue
            mine = pred_units.get(_chain(u, after_el))
            mh = _heading(mine) if mine is not None else None
            if mine is not None and (mh is None or not "".join(mh.itertext()).strip()) and \
                    _inserted_without_heading(_chain(u, after_el)[-1], ctx.inserted):
                _drop(h)                             # a heading OLRC supplied: the law's own text has none
    out = []
    for el in (pred_el, after_el):
        for h in list(el.iter("{*}heading")):
            # One text node: the heading's words in lower case, closing punctuation dropped wherever the markup put
            # it ("<inline>Definitions.—</inline>").
            words = re.sub(r"[\s.—–-]+$", "", "".join(h.itertext())).lower()
            for c in list(h):
                h.remove(c)
            h.text = words
        text = re.sub(r"\s+", " ", normalize(text_of(el))).strip()
        # Bracketed Code citations ("(Public Law 93–410) [30 U.S.C. 1101 et seq.]") are OLRC's, never the law's.
        text = re.sub(r"\s?\[[^\[\]]*U\.S\.C\.[^\[\]]*\]", "", text)
        out.append(text)
    return out[0], out[1]


def _pattern(pred: str, ctx: Context | None) -> re.Pattern:
    """pred as a regex in which each enactment-date phrase may also read as a date (OLRC may add a comma after it)
    and each Act reference our resolver codifies may also read as its Code citation."""
    spans: list[tuple[int, int, str]] = []
    for m in DATE_PHRASE.finditer(pred):
        # Only the enactment date of the Act the phrase names (this law's for "this Act"), as OLRC sets it in.
        iso = ctx.date_of(m.group("act")) if ctx is not None else None
        if iso:
            y, mo, d = (int(x) for x in iso.split("-"))
            spans.append((m.start(), m.end(),
                          f"(?:{re.escape(f'{MONTHS[mo - 1]} {d}, {y}')},?|{re.escape(m.group(0))})"))
    if ctx is not None:
        for m in ACT_REF.finditer(pred):
            if any(s < m.end() and m.start() < e for s, e, _ in spans):
                continue
            code = ctx.resolve(f"Section {m.group(1)}{m.group(2)} of {m.group(3)}")
            g = re.match(r"^/us/usc/t(\w+)/s([^/]+)", code or "")   # a subsection resolves too ("…/s1395w–104/o")
            if not g:
                continue
            t, s = g.groups()
            where = f"(?:title {re.escape(t)}" + ("|this title)" if t == ctx.title else ")")
            spans.append((m.start(), m.end(),
                          f"(?:{re.escape(m.group(0))}|section {re.escape(s)}{re.escape(m.group(2))} of {where})"))
    spans.sort()
    rx, at = "", 0
    for s, e, alt in spans:
        if s < at:
            continue
        rx += re.escape(pred[at:s]) + alt
        at = e
    return re.compile(rx + re.escape(pred[at:]))


def _footnote_digits(pred: str, after: str) -> bool:
    """The only differences are runs of one or two digits attached to the preceding character (footnote markers
    OLRC added or removed), never digits that differ at one place."""
    def runs(t):        # position in the digit-free text -> (digits, attached to the preceding character)
        return {len(re.sub(r"\d", "", t[:m.start()])): (m.group(), m.start() > 0 and not t[m.start() - 1].isspace())
                for m in re.finditer(r"\d+", t)}
    if re.sub(r"\d", "", pred) != re.sub(r"\d", "", after):
        return False
    rp, ra = runs(pred), runs(after)
    if any(rp[k][0] != ra[k][0] for k in rp.keys() & ra.keys()):
        return False
    only = [rp[k] for k in rp.keys() - ra.keys()] + [ra[k] for k in ra.keys() - rp.keys()]
    return bool(only) and all(len(d) <= 2 and attached for d, attached in only)


def _probable_intent(pred: str, after: str, ctx: Context) -> bool:
    """OLRC's note says it executed this law "to reflect the probable intent of Congress", and every passage in which
    the prediction differs from R_after is quoted in such a note (“150 percent” for “130 percent”): the note
    explains those differences, and only those."""
    notes = [normalize(n) for n in ctx.new_notes if ctx.cite in n and "probable intent" in n]
    if not notes:
        return False
    a, b = pred.split(), after.split()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        for words in (a[i1:i2], b[j1:j2]):
            piece = " ".join(words).strip(".,;:")
            if piece and not any(piece in n for n in notes):
                return False
    return True


def kind(pred_el, after_xml: str | None, ctx: Context | None = None) -> str | None:
    """Why the prediction differs from R_after only editorially, or None when the difference is substantive."""
    if pred_el is None or after_xml is None:
        return None
    after_el = etree.fromstring(after_xml.encode("utf-8"))
    pred, after = texts(pred_el, after_el, ctx)
    if pred == after:
        return "editorial: headings, footnotes or bracketed citations"
    if ctx is not None and _probable_intent(pred, after, ctx):
        return "editorial: executed to reflect the probable intent of Congress (OLRC note)"
    placeholder = False
    if ctx is not None:                                 # "(f) Repealed. Pub. L. 113–76, ..., 128 Stat. 424"
        # OLRC may set the placeholder as the unit's heading, which texts() lower-cases.
        stripped = re.sub(rf"\((\w+)\) Repealed\. {re.escape(ctx.cite)}\b.{{0,160}}?\d+ Stat\. \d+(?:[–-]\d+)?\.?",
                          "", after, flags=re.I)
        placeholder = stripped != after
        after = re.sub(r"\s+", " ", stripped).strip()
    if _pattern(pred, ctx).fullmatch(after):
        return "editorial: a Repealed placeholder" if placeholder and pred == after else \
            "editorial: enactment date, Code citation or placeholder"
    if re.sub(r"\s", "", pred) == re.sub(r"\s", "", after):
        return "whitespace"
    if _footnote_digits(pred, after):
        return "editorial: footnote markers"
    return None
