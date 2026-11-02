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


def run_on_act(ins: Instruction, identities: list[str], ix: Index) -> ActRun:
    """Run one instruction against the compiled Act its target names (identities as the resolver gives them,
    "pl:95-617"). Never picks among compilations that disagree."""
    t = ins.target
    if not t.section:
        return ActRun(ins.id, "UNAVAILABLE", "the target names no section of an Act", [], [])
    titles = [f for i in identities for f in comps.files_for(ix.db, ix.rp_id, i)]
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
    node = found[0]
    work = Working(ix.section_xml(node), node.identifier, positive_law=False)
    res = Engine(work).run(ins, list(t.path))
    return ActRun(ins.id, res.status, res.detail, files, [currency.get(f, "unknown") for f in files],
                  node.identifier, res, node.text)


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
