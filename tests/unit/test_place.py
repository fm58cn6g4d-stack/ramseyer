"""Every instruction gets exactly one place in the print: a Code section, the Act-text part, or "Instructions not
placed" (review of #25). Act-side statuses stay distinct from Code-side ones."""
from types import SimpleNamespace as NS

from ramseyer.analyze import place


def _tr(iid, section, status):
    return NS(instruction=NS(id=iid), section=section, result=None if status is None else NS(status=status))


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
