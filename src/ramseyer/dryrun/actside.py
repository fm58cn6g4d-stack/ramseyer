"""M8a: run an instruction against the Act's own text (HOLC's Statute Compilation) beside the Code, and say how the two
readings compare (docs/06-dry-run.md, "Act and Code cross-check").

Every instruction gets one reading, with its reason and both sources' currency; nothing is dropped:

| Act side | Code side | Reading |
| --- | --- | --- |
| applies | applies | "both": the strongest result |
| applies | does not | "act only": OLRC's Code form differs from the Act's; both reported |
| does not | applies | "code only": compilation out of date, or the draft follows the Code's form; both currency dates |
| does not | does not | "neither": a drafting error or a stale draft |

An instruction the Act side cannot be run for is reported as such, with why: the target names no Act, the Act has no
compilation, its section is not in the compilation, or files disagree on the section's text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ramseyer.data import comps
from ramseyer.data.index import Index, Node
from ramseyer.dryrun.engine import Engine, Result, Working
from ramseyer.parse.ir import Instruction

# A result that edited the text, or found the edit already made, or found it with a caveat: the quote or unit was there.
APPLIES = {"CLEAN", "WARN", "ALREADY_EXECUTED"}


@dataclass
class ActRun:
    instruction_id: str
    status: str                    # engine status on the Act side, or "UNAVAILABLE"
    reason: str                    # why, in words
    files: list[str]               # compilation files used ("comp838")
    currency: list[str]            # each file's currency, as stored
    identifier: str | None = None  # the compilation section, e.g. /us/sComp/95/617/s5
    result: Result | None = None
    text: str = ""                 # the compilation section's text before the instruction, when one was run


def _sections(ix: Index, titles: list[str], section: str) -> list[Node]:
    """The Act's section `section` in any of `titles`: a section whose identifier ends in /s<section>."""
    want = re.escape(section.strip().rstrip("."))
    rows = ix.db.execute(f"SELECT id, title, identifier FROM nodes WHERE rp=? AND kind='section' AND title IN "
                         f"({','.join('?' * len(titles))})", (ix.rp_id, *titles)).fetchall()
    return [ix._node(i) for i, _, ident in rows if re.search(rf"/s{want}$", ident or "", re.I)]


def locate(ins: Instruction, identities: list[str], ix: Index):
    """The compiled Act section an instruction's target names: (node, files, currency), or an ActRun saying why
    there is none. Never picks among compilations that disagree."""
    t = ins.target
    if not t.section:
        return ActRun(ins.id, "UNAVAILABLE", "the target names no section of an Act", [], [])
    titles = [f for i in identities for f in comps.files_for(ix.db, ix.rp_id, i, t.act)]
    if not identities:
        return ActRun(ins.id, "UNAVAILABLE", "the target names no Act the resolver identifies", [], [])
    if not titles:
        return ActRun(ins.id, "UNAVAILABLE", f"no compilation of {', '.join(identities)}", [], [])
    found = _sections(ix, sorted(set(titles)), t.section)
    currency = {r[0]: r[1] for r in ix.db.execute(
        f"SELECT title, currency FROM titles WHERE rp=? AND title IN ({','.join('?' * len(titles))})",
        (ix.rp_id, *titles))}
    if not found:
        return ActRun(ins.id, "UNAVAILABLE", f"section {t.section} is not in the compilation", sorted(set(titles)),
                      [currency.get(f, "unknown") for f in sorted(set(titles))])
    texts = {n.text for n in found}
    files = sorted({n.title for n in found})
    if len(texts) > 1:
        return ActRun(ins.id, "UNAVAILABLE", f"{len(found)} compilation files hold section {t.section} with different "
                      "text; both reported, neither picked", files, [currency.get(f, "unknown") for f in files])
    return found[0], files, [currency.get(f, "unknown") for f in files]


def run_on_act(ins: Instruction, identities: list[str], ix: Index) -> ActRun:
    """Run one instruction against the compiled Act its target names (identities as the resolver gives them,
    "pl:95-617"), on a fresh copy of the section."""
    where = locate(ins, identities, ix)
    if isinstance(where, ActRun):
        return where
    node, files, currency = where
    work = Working(ix.section_xml(node), node.identifier, positive_law=False)
    res = Engine(work).run(ins, list(ins.target.path))
    return ActRun(ins.id, res.status, res.detail, files, currency, node.identifier, res, node.text)


@dataclass
class ActTrace:
    instruction: Instruction
    section: str | None
    result: Result | None


@dataclass
class ActBill:
    """A bill's instructions on Act text the Code does not hold, applied in bill order to one copy of each compiled
    section (the comparative print's "Act text" part): `working` and `traces` as a BillRun has them, with each
    section's label and currency, and the instructions that could not be placed, with why."""
    working: dict
    traces: list
    labels: dict[str, str]
    currency: dict[str, list[str]]
    unplaced: list[ActRun]


_NUM = r"[0-9]+[A-Za-z]*(?:-[0-9A-Za-z]+)?"
_TAIL = re.compile(r"(?:\s*(?:;|,|\.)?\s*(?:and|or)?\s*)$")


def _numbers(phrase: str) -> list[str] | None:
    """"301, 302, and 305" or "701 through 711" as a list of section numbers; None when the phrase is anything else
    (a range is expanded only between plain integers)."""
    phrase = phrase.strip()
    m = re.fullmatch(rf"({_NUM}) through ({_NUM})", phrase)
    if m:
        a, b = m.groups()
        if not (a.isdigit() and b.isdigit()) or int(b) < int(a):
            return None
        return [str(n) for n in range(int(a), int(b) + 1)]
    parts = [p.strip() for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", phrase) if p.strip()]
    return parts if parts and all(re.fullmatch(_NUM, p) for p in parts) else None


def structural(text: str):
    """An Act-level structural instruction read from its words, or None:
    ("redesignate", kind, [(old, new), ...], after) for "redesignating sections 301 and 302 as sections 201 and 202,
    respectively" (kind "section" or "title"; `after` names the section it is transferred to follow, if any), or
    ("strike", "section", [number, ...]) for "striking section 714 and 723". Deterministic; anything else is None."""
    t = re.sub(r"\s+", " ", text.strip())
    t = re.sub(r"^\(?[0-9A-Za-z]{1,4}\)\s*", "", t)          # a list designation, "(2) "
    t = _TAIL.sub("", t)
    m = re.fullmatch(r"(?:by )?redesignating (sections?|titles?) (.+?) as (?:(?:sections?|titles?) )?(.+?)"
                     r"(?:,? respectively)?(?: and transferring (?:such|those|the) (?:sections?|titles?) so as to "
                     r"appear after (?:section|title) (" + _NUM + r"))?", t, re.I)
    if m:
        kind = "title" if m.group(1).lower().startswith("title") else "section"
        if kind == "title":
            roman = r"[IVXLC]+(?:(?:, (?:and )?| and )[IVXLC]+)*"
            if not (re.fullmatch(roman, m.group(2)) and re.fullmatch(roman, m.group(3))):
                return None                        # joined to anything else ("... and inserting"): not read
            old = re.findall(r"[IVXLC]+", m.group(2))
            new = re.findall(r"[IVXLC]+", m.group(3))
        else:
            old, new = _numbers(m.group(2)), _numbers(m.group(3))
        if old and new and len(old) == len(new):
            return ("redesignate", kind, list(zip(old, new)), m.group(4))
        return None
    m = re.fullmatch(r"(?:by )?striking sections? (.+?)", t, re.I)
    if m:
        nums = _numbers(m.group(1))
        if nums:
            return ("strike", "section", nums)
    return None


def run_bill_on_acts(instructions: list[Instruction], identities_of, ix: Index) -> ActBill:
    """Each instruction in bill order, on its compiled Act section; several instructions on one section edit the same
    copy, as the Code side does. `identities_of(ins)` gives the resolver's identities for its target.

    Act-level structure is followed in bill order: a section the bill redesignates is shown under its new number
    ("formerly section ..."), and a later instruction naming the new number edits that same section; a section the
    bill strikes whole is shown removed. A title's redesignation changes no section's text and is listed with that
    reason."""
    working: dict[str, Working] = {}
    engines: dict[str, Engine] = {}
    traces, labels, currency, unplaced = [], {}, {}, []
    renamed: dict[tuple, dict[str, str]] = {}      # Act -> {current number: number in the compilation}
    gone: dict[tuple, set[str]] = {}                # Act -> compiled numbers redesignated away (not to be reused)

    def open_section(ins, where):
        node, files, cur = where
        ident = node.identifier
        if ident not in working:
            working[ident] = Working(ix.section_xml(node), ident, positive_law=False)
            engines[ident] = Engine(working[ident])
            title = ix.db.execute("SELECT publication FROM titles WHERE rp=? AND title=?",
                                  (ix.rp_id, node.title)).fetchone()
            labels[ident] = f"{(title[0] if title else None) or ins.target.act or 'Act'}, {node.num or ''}".strip(" ,")
            currency[ident] = cur
        return ident

    def find(ins, ids, number):
        t = ins.target.model_copy(update={"section": number})
        return locate(ins.model_copy(update={"target": t}), ids, ix)

    for ins in instructions:
        ids = identities_of(ins)
        # An Act the resolver does not identify is keyed by its drafted name, never shared with other such Acts.
        act = tuple(sorted(ids)) or ("name", ins.target.act or ins.target.public_law or ins.target.cite_raw)
        names = renamed.setdefault(act, {})
        away = gone.setdefault(act, set())
        what = structural(ins.source_text) if not ins.target.section or ins.op in ("UNKNOWN", "UNPARSED") else None
        if what and what[1] == "title":
            unplaced.append(ActRun(ins.id, "UNAVAILABLE", "redesignates a title of the Act: no section's text changes "
                                   "(its sections keep their numbers)", [], []))
            continue
        if what:
            missing = []
            # One instruction's redesignations take effect together ("301 and 302 as 302 and 303"): every number is
            # looked up before any is changed.
            pairs = [(p[0], p[1]) if what[0] == "redesignate" else (p, None) for p in what[2]]
            # A number redesignated away earlier, and not taken since, names no section now (review of #26).
            looked = [(number, new, None if number not in names and number in away else names.get(number, number))
                      for number, new in pairs]
            for number, _new, _c in looked:
                if what[0] == "redesignate":
                    names.pop(number, None)
                    away.add(number)
            done = []
            for number, new, compiled in looked:
                if compiled is None:
                    missing.append(f"section {number}: redesignated earlier in the bill and no section has taken its "
                                   "number")
                    continue
                where = find(ins, ids, compiled)
                if isinstance(where, ActRun):
                    missing.append(f"section {number}: {where.reason}")
                    continue
                ident = open_section(ins, where)
                if working[ident].removed:
                    missing.append(f"section {number}: struck earlier in the bill")
                    continue
                if what[0] == "redesignate":
                    _renumber(working[ident], new)
                    names[new] = compiled
                    away.discard(new)
                    labels[ident] = re.sub(r",[^,]*$", "", labels[ident]) + f", section {new} (formerly section {compiled})"
                    moved = f"; moved to follow section {what[3]} (order not shown)" if what[3] else ""
                    detail = f"section {number} redesignated as section {new}{moved}"
                else:
                    working[ident].removed = True
                    detail = f"section {number} struck"
                done.append(ActTrace(ins, ident, Result(ins.id, "CLEAN", detail)))
            if missing and done:
                # Partly placed: each placed part says what was not, and the instruction is not CLEAN (review of #26).
                for tr in done:
                    tr.result.status = "WARN"
                    tr.result.detail += "; not placed: " + "; ".join(missing)
            elif missing:
                unplaced.append(ActRun(ins.id, "UNAVAILABLE", "; ".join(missing), [], []))
            traces.extend(done)
            continue
        number = ins.target.section
        if number and number not in names and number in away:
            unplaced.append(ActRun(ins.id, "UNAVAILABLE", f"section {number} was redesignated earlier in the bill and no "
                                   "section has taken its number", [], []))
            continue
        where = find(ins, ids, names[number]) if number and number in names else locate(ins, ids, ix)
        if isinstance(where, ActRun):
            unplaced.append(where)
            continue
        ident = open_section(ins, where)
        if working[ident].removed:
            # The bill struck this section earlier: an edit to it is not applied to the removed text (review of #26).
            traces.append(ActTrace(ins, ident, Result(ins.id, "TARGET_MISSING", "the section was struck earlier in "
                                                      "the bill")))
            continue
        res = engines[ident].run(ins, list(ins.target.path))
        traces.append(ActTrace(ins, ident, res))
    return ActBill(working, traces, labels, currency, unplaced)


def _renumber(work: Working, new: str) -> None:
    """Give a compiled section its new number: the <num> text and value."""
    el = work.el
    if el is None:
        return
    num = next((c for c in el if isinstance(c.tag, str) and c.tag.rsplit("}", 1)[-1] == "num"), None)
    if num is None:
        return
    text = "".join(num.itertext())
    old = num.get("value") or (re.search(_NUM, text).group(0) if re.search(_NUM, text) else None)
    for c in list(num):
        num.remove(c)
    num.text = re.sub(re.escape(old), new, text, count=1) if old and old in text else f"SEC. {new}."
    num.set("value", new)


def reading(act: ActRun, code_status: str | None) -> tuple[str, str]:
    """The cross-check reading and its reason (the table above)."""
    if act.status == "UNAVAILABLE":
        return "act unavailable", act.reason
    a, c = act.status in APPLIES, (code_status or "") in APPLIES
    if a and c:
        return "both", "the instruction applies to the Act and to the Code"
    if a:
        return "act only", f"applies to the Act ({act.status}); on the Code {code_status or 'not run'}: OLRC's Code form " \
                            "may differ from the Act's"
    if c:
        return "code only", f"applies to the Code ({code_status}); on the Act {act.status}: the compilation " \
                             f"(current through {'; '.join(act.currency)}) may be out of date, or the draft follows " \
                             "the Code's form"
    return "neither", f"applies to neither (Act {act.status}, Code {code_status or 'not run'}): a drafting error or a " \
                      "stale draft"


MIN_CONFIRM = 20     # characters of inserted text needed before finding it in the Act counts as confirmation


def confirmation(inserted: str | None, act_text: str) -> str:
    """For a compilation that already includes the law: are the law's new words in the Act's section? Words too short
    to stand for this insertion ("2026", "and") are found almost anywhere, so they are reported apart and never count
    as confirmation (review of #20)."""
    new = " ".join((inserted or "").replace("“", "").replace("”", "").split())
    text = " ".join(act_text.split())
    if not new:
        return "the instruction inserts no words to look for"
    if len(new) < MIN_CONFIRM or len(new.split()) < 3:
        return f"its new words are too short to confirm by search (under {MIN_CONFIRM} characters or 3 words)"
    if new[:80] in text:
        return "its new words are in the Act's section"
    return "its new words are not found in the Act's section (later laws may have changed them)"
