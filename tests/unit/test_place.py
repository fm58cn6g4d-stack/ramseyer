"""Every instruction gets exactly one place in the print: a Code section, the Act-text part, or "Instructions not
placed" (review of #25). Act-side statuses stay distinct from Code-side ones."""
from types import SimpleNamespace as NS

from ramseyer.analyze import place


def _tr(iid, section, status):
    return NS(instruction=NS(id=iid), section=section, result=None if status is None else NS(status=status, detail=""))


def _row(iid, status):
    return {"id": iid, "status": status, "target": "", "source": f"instruction {iid}", "detail": ""}


def test_every_instruction_has_exactly_one_place():
    rows = [_row("1", "CLEAN"), _row("2", "NOT_EXECUTED"), _row("3", "NOT_EXECUTED"), _row("4", "UNPARSED"),
            _row("5", "NOT_EXECUTED"), _row("6", "CONFLICT")]
    run = NS(traces=[_tr("1", "/us/usc/t1/s1", "CLEAN"), _tr("5", "/us/usc/t1/s2", None),
                     _tr("6", "/us/usc/t1/s1", "CONFLICT")])
    act = NS(traces=[_tr("2", "/us/comp/9/s3", "CLEAN")], currency={"/us/comp/9/s3": ["through P.L. 118-1"]},
             unplaced=[NS(instruction_id="3", reason="the target names no section of an Act")])
    unplaced = place(rows, run, act)
    by_id = {r["id"]: r for r in rows}
    assert {r["placed"] for r in rows} <= {"code", "act", "none"}
    assert [by_id[i]["placed"] for i in "123456"] == ["code", "act", "none", "none", "none", "code"]
    # The unplaced list is exactly the rows placed nowhere, with their reasons: nothing dropped, nothing doubled.
    assert [u[1] for u in unplaced] == [by_id[i]["source"] for i in "345"]
    assert unplaced[0][2] == "the target names no section of an Act"


def test_act_status_is_kept_apart_from_code_status():
    rows = [_row("2", "NOT_EXECUTED")]
    act = NS(traces=[_tr("2", "/us/comp/9/s3", "CLEAN")], currency={"/us/comp/9/s3": ["through P.L. 118-1"]},
             unplaced=[])
    place(rows, NS(traces=[]), act)
    assert rows[0]["status"] == "ACT:CLEAN"
    assert "through P.L. 118-1" in rows[0]["detail"]


def test_without_compilations_every_unrun_instruction_is_listed():
    rows = [_row("1", "NOT_EXECUTED"), _row("2", "UNPARSED")]
    assert len(place(rows, NS(traces=[]), None)) == 2
    assert all(r["placed"] == "none" for r in rows)


def test_act_side_reason_is_kept_in_the_instruction_list():
    rows = [_row("2", "NOT_EXECUTED")]
    tr = _tr("2", "/us/comp/9/s3", "WARN")
    tr.result.detail = "section 3 struck; not placed: section 9: section 9 is not in the compilation"
    place(rows, NS(traces=[]), NS(traces=[tr], currency={}, unplaced=[]))
    assert rows[0]["status"] == "ACT:WARN" and "not placed: section 9" in rows[0]["detail"]


def test_only_confirmed_notes_are_printed_as_notes_and_every_place_is_named():
    """Review of #28: a NOTE read from the drafted parenthetical alone (no note_id) is not printed as a note."""
    from ramseyer.analyze import note_places
    from ramseyer.comparative.html import note_place

    def code(iid, cite, note_id):
        return NS(instruction=NS(id=iid), resolution=NS(outcome="NOTE", cite=cite, note_id=note_id))
    run = NS(traces=[code("a", "42 U.S.C. 1 note", 7), code("b", "15 U.S.C. 6701(a)", None),
                     code("c", "42 U.S.C. note prec. 1", 8)])
    act = NS(traces=[NS(instruction=NS(id=i), section=s) for i, s in (("a", "s1"), ("b", "s2"), ("c", "s1"))])
    assert note_places(run, act) == {"s1": "42 U.S.C. 1 note; 42 U.S.C. note prec. 1"}
    assert note_place("42 U.S.C. 1 note; 42 U.S.C. note prec. 1") == \
        "Set out as a note under 42 U.S.C. 1 and as a note preceding 42 U.S.C. 1"
