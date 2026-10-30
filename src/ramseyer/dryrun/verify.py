"""Independent checks on an amended section (docs/06-dry-run.md): a CLEAN prediction is lowered to WARN when the
result shows a sign that an edit went wrong or that the bill does more to the section than was applied. None of
these checks reads R_after; each looks only at the bill and the amended working copy."""
from __future__ import annotations

import re

from ramseyer.data.indexer import local, text_of
from ramseyer.dryrun.engine import LEVEL_TAGS, NS, _label_key, fold
from ramseyer.parse.segment import is_roman, roman_to_int
from ramseyer.parse.ir import Instruction

# An enumerator with a heading left inside running text: "... c. Application reviews.—" or "... (2) Fees.—".
INLINE_UNIT = re.compile(r"(?:^|[\s—])(?:[a-z]{1,2}\.|\(\w{1,5}\)) [A-Z][\w’' ,-]{0,80}\.—")
SECTION_MENTION = re.compile(r"\b[Ss]ections? (\d+[A-Za-z]{0,3}(?:[\u2013-]\d+[A-Za-z]?)?)\b")


def _in_order(labels: list[str]) -> bool:
    """Labels increase, read as numbers, as roman numerals ("i", "ii", ... "v": "v" is also a letter) or as letters."""
    def increasing(keys):
        return all(a < b for a, b in zip(keys, keys[1:]))
    if all(is_roman(x) or len(x) == 1 and x.lower() in "ivxl" for x in labels) and \
            increasing([roman_to_int(x) for x in labels]):
        return True
    return increasing([_label_key(x) if not is_roman(x) or x[0].isdigit() else (2, len(x), x.lower())
                       for x in labels])


def _children(el) -> list:
    return [c for c in el if local(c) in LEVEL_TAGS and c.find(NS + "num") is not None]


def _labels(el) -> list[str]:
    return [(c.find(NS + "num").get("value") or "").strip("[]()") for c in _children(el)]


def structure_problems(work) -> list[str]:
    """Signs of a bad edit in the amended section, relative to the baseline copy."""
    if work.el is None or work.removed:
        return []
    out = []
    before = {text_of(e) for e in work.original.iter()} if work.original is not None else set()
    for e in work.el.iter(NS + "content", NS + "chapeau", NS + "continuation"):
        t = text_of(e)
        if t not in before and INLINE_UNIT.search(t):
            out.append(f"enumerated text left inside a unit's text: “{INLINE_UNIT.search(t).group(0).strip()[:60]}”")
            break
    orig_seq = {}
    if work.original is not None:
        for e in work.original.iter():
            if e is work.original or local(e) in LEVEL_TAGS:
                orig_seq[e.get("identifier")] = _labels(e)
    for e in [work.el] + [x for x in work.el.iter() if local(x) in LEVEL_TAGS]:
        labs = _labels(e)
        if len(labs) < 2 or orig_seq.get(e.get("identifier")) == labs:
            continue
        if len(set(labs)) != len(labs) or not _in_order([x for x in labs if x]):
            out.append(f"unit labels out of order after the edits: {' '.join('(' + x + ')' for x in labs[:12])}")
            break
    return out


def unapplied_mentions(ident: str, instructions: list[Instruction], applied: set[str], work=None) -> list[str]:
    """Instructions of the bill that were not applied anywhere (unparsed or unresolved) and either name this
    section's number in their own text or, amending "each covered law" (a blanket target) or striking words "each
    place it appears", strike words this section contains: the bill may amend the section in a way the prediction
    lacks."""
    title, num = ident.split("/")[3][1:], ident.rsplit("/s", 1)[1]
    here = fold(text_of(work.el), True)[0] if work is not None and work.el is not None and not work.removed else ""
    out = []
    for ins in instructions:
        if ins.id in applied:
            continue
        text = (ins.source_text or "").replace("-", "\u2013")
        named = ins.target.kind == "usc" and ins.target.title == title and \
            any(m.group(1) == num for m in SECTION_MENTION.finditer(text))
        cited = re.search(rf"\b{title} U\.S\.C\. {re.escape(num)}(?![\w\u2013])(?! note)|\bsection {re.escape(num)}"
                          rf"(?![\w\u2013])(?:\([\w]+\))*,? of (?:the )?title {title}\b", text)
        if named or cited:
            out.append(f"instruction {ins.id} was not applied and names section {num}: “{text[:100]}”")
        elif here and ins.find and (any(q.startswith("blanket") for q in ins.target.qualifiers) or
                                    ins.occurrence == "each" and len(ins.find.split()) >= 2) and \
                fold(ins.find, True)[0] in here:
            # "each covered defense law ... is amended by striking the term “program executive officer” ...": an
            # instruction with no single target whose struck words are in this section (10 U.S.C. 4025). So too an
            # unresolved one striking words "each place it appears" ("Part E of title III is amended by striking
            # “this subpart” each place it appears", Pub. L. 114-144 § 4(m), 42 U.S.C. 3030s-1).
            out.append(f"instruction {ins.id} was not applied and strikes “{ins.find[:60]}”, which this section "
                       "contains")
    return out
