"""M8: the redline of one section, built from the dry-run engine's own edits.

Before the engine runs, every element of the section is tagged with a stable id (`tag`). The engine keeps the elements
it does not remove, so after it has run the two trees line up by id:

- an element in both trees is the same unit or block, wherever it now sits (a redesignated paragraph keeps its id);
- an element only in the "before" tree was removed by the bill; one only in the "after" tree was added by it.

Only inside one block that is in both trees (a heading, a chapeau, a paragraph's text) are the two texts compared word
by word, and that block is the one an edit touched. So a change is never placed in a unit the bill did not edit, and
stripping the marks gives back each tree's text exactly (`strip`).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from ramseyer.data.indexer import NON_OPERATIVE, local, text_of

from ramseyer.dryrun.ids import ID, tag  # noqa: F401  (tag: re-exported for callers and tests)
# Elements whose whole text is shown as one run of words; everything else is a container whose children are walked.
TEXT_BLOCKS = {"num", "heading", "chapeau", "content", "continuation", "p", "quotedContent", "subheading"}
TOKEN = re.compile(r"\s+|\w+|[^\w\s]")


@dataclass
class Run:
    state: str          # "same", "del" or "ins"
    text: str


@dataclass
class Block:
    kind: str           # the element's local name: "num", "heading", "content", ...
    state: str          # "same" (runs may hold edits), "del" (removed whole) or "ins" (added whole)
    runs: list[Run]


@dataclass
class Unit:
    kind: str           # "section", "subsection", ...
    state: str
    items: list = field(default_factory=list)    # Block | Unit, in reading order


def words(before: str, after: str) -> list[Run]:
    """A word-level comparison of one block's text before and after; joining the "same" and "del" runs gives
    `before` exactly, and the "same" and "ins" runs give `after`."""
    a, b = TOKEN.findall(before), TOKEN.findall(after)
    runs: list[Run] = []

    def add(state, toks):
        if not toks:
            return
        text = "".join(toks)
        if runs and runs[-1].state == state:
            runs[-1].text += text
        else:
            runs.append(Run(state, text))
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            add("same", a[i1:i2])
        else:
            add("del", a[i1:i2])
            add("ins", b[j1:j2])
    return runs


def _children(el) -> list:
    return [c for c in el if isinstance(c.tag, str) and local(c) not in NON_OPERATIVE]


def _whole(el, state: str):
    """An element removed or added whole."""
    name = local(el)
    if name in TEXT_BLOCKS:
        return Block(name, state, [Run(state, text_of(el, frozenset(NON_OPERATIVE)).strip())])
    unit = Unit(name, state)
    if (el.text or "").strip():
        unit.items.append(Block("text", state, [Run(state, el.text.strip())]))
    for c in _children(el):
        unit.items.append(_whole(c, state))
        if (c.tail or "").strip():          # text set after a child unit, inside this one
            unit.items.append(Block("text", state, [Run(state, c.tail.strip())]))
    return unit


def _merge(before_el, after_el):
    """The children of an element in both trees, in reading order, each paired with its other side (or None)."""
    b_kids, a_kids = _children(before_el), _children(after_el)
    b_ids = [c.get(ID) for c in b_kids]
    a_ids = [c.get(ID) for c in a_kids]
    shared = set(b_ids) & set(a_ids)
    by_id_b = {c.get(ID): c for c in b_kids if c.get(ID) in shared}
    seen: set[str] = set()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, b_ids, a_ids, autojunk=False).get_opcodes():
        if op == "equal":
            out += [(b_kids[i], a_kids[j]) for i, j in zip(range(i1, i2), range(j1, j2))]
            seen.update(b_ids[i1:i2])
            continue
        # A unit the bill replaces whole ("amended to read as follows") is new XML, but committee reports compare it
        # with the unit it replaces word by word: a removed and an added child of the same kind and designation are
        # paired, and so are a lone removed and a lone added text block of the same kind (part 2, H.R. 6498).
        removed = [b_kids[i] for i in range(i1, i2) if b_ids[i] not in shared]
        # Pairs keep both orders (each side's text must read back in its own order): a removed child is paired only
        # with a later added one, never across an earlier pairing.
        k = 0
        for j in range(j1, j2):
            ident, a = a_ids[j], a_kids[j]
            if ident in shared and ident not in seen:
                # A child that moved within its parent keeps its id and is paired where it now stands.
                out.append((by_id_b[ident], a))
                seen.add(ident)
                continue
            m = next((x for x in range(k, len(removed)) if _matches(removed[x], a, removed, a_kids[j1:j2])), None)
            if m is None:
                out.append((None, a))
                continue
            out += [(b, None) for b in removed[k:m]]
            out.append((removed[m], a))
            k = m + 1
        out += [(b, None) for b in removed[k:]]
    return out


def _matches(b, a, removed, added) -> bool:
    """A removed child stands for an added one: same kind and designation, or the lone text block of that kind on
    each side."""
    db, da = _designation(b), _designation(a)
    if da[1]:
        return db == da
    if local(a) not in TEXT_BLOCKS or db != da:
        return False
    return sum(_designation(x) == da for x in removed) == 1 and sum(_designation(x) == da for x in added) == 1


def _designation(el) -> tuple[str, str]:
    """(kind, designation): ("subsection", "b") for a unit numbered "(b)"; no designation for a text block."""
    num = el.find(f"{{{el.nsmap.get(None, '')}}}num") if el.nsmap.get(None) else el.find("num")
    text = "".join(num.itertext()).strip().strip("().") if num is not None else ""
    return local(el), text


def _pair(before_el, after_el):
    name = local(after_el)
    if name in TEXT_BLOCKS:
        old = text_of(before_el, frozenset(NON_OPERATIVE)).strip()
        new = text_of(after_el, frozenset(NON_OPERATIVE)).strip()
        return Block(name, "same", words(old, new))
    unit = Unit(name, "same")
    if (before_el.text or "").strip() or (after_el.text or "").strip():
        unit.items.append(Block("text", "same", words((before_el.text or "").strip(), (after_el.text or "").strip())))
    for b, a in _merge(before_el, after_el):
        if b is None:
            unit.items.append(_whole(a, "ins"))
        elif a is None:
            unit.items.append(_whole(b, "del"))
        else:
            unit.items.append(_pair(b, a))
        # Text set after a child, inside this unit (an XML tail): the engine may add a sentence there.
        old, new = ((b.tail or "").strip() if b is not None else ""), ((a.tail or "").strip() if a is not None else "")
        if old or new:
            unit.items.append(Block("text", "same", words(old, new)))
    return unit


def redline(before_el, after_el):
    """The section's redline: removed whole (after_el None), added whole (before_el None), or edited."""
    if before_el is None and after_el is None:
        return None
    if before_el is None:
        return _whole(after_el, "ins")
    if after_el is None:
        return _whole(before_el, "del")
    return _pair(before_el, after_el)


def blocks(node) -> list[Block]:
    """The redline's text blocks in reading order."""
    if isinstance(node, Block):
        return [node]
    return [b for item in node.items for b in blocks(item)]


def strip(node, side: str) -> str:
    """The text of one side ("before" or "after") with the marks taken away: block texts, one per line."""
    drop = "ins" if side == "before" else "del"
    lines = []
    for b in blocks(node):
        if b.state == drop:
            continue
        text = "".join(r.text for r in b.runs if r.state != drop)
        if text.strip():
            lines.append(text.strip())
    return "\n".join(lines)


def changed(node) -> bool:
    return any(b.state != "same" or any(r.state != "same" for r in b.runs) for b in blocks(node))
