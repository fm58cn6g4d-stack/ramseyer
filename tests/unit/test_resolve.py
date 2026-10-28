"""Resolver helpers and decision rules, on synthetic inputs (placeholder text, invented numbers)."""
from billmap.parse.grammar import Ctx, apply_head, lift_quotes
from billmap.resolve.actcode import _date_key, _enacting_segment
from billmap.resolve.cites import designation, parse_designation, parse_parenthetical, prefix_match
from billmap.resolve.popular import identity, norm_name, parse


def test_parenthetical_forms():
    p = parse_parenthetical("Public Law 116–283; 10 U.S.C. 1791 note")
    assert (p.public_law, p.title, p.section, p.note) == ("116-283", "10", "1791", True)
    p = parse_parenthetical("Public Law 112–239; 10 U.S.C. note prec. 3701")
    assert (p.title, p.section, p.preceding, p.note) == ("10", "3701", True, True)
    p = parse_parenthetical("42 U.S.C. 300hh–32(c)")
    assert (p.section, p.path, p.note) == ("300hh–32", ("(c)",), False)
    assert parse_parenthetical("33 U.S.C. 891 et seq.").et_seq


def test_designations_and_prefixes():
    assert designation("divA.titleIII.sec311.b.1") == ("311", ("(b)", "(1)"))
    assert parse_designation('7070(b)(1) "33"') == ("7070", ("(b)", "(1)"))
    assert prefix_match(("(b)",), ("(b)", "(1)")) and not prefix_match(("(c)",), ("(b)",))


def test_enacting_segment_stops_at_as_added():
    raw = "(July 1, 1944, ch. 373, title III, §317U, as added Pub. L. 106–310, §3101; amended Pub. L. 1–2.)"
    assert _enacting_segment(raw) == "July 1, 1944, ch. 373, title III, §317U"
    assert _date_key("Sept.", "8", "1950") == "1950-09-08" and _date_key("July", "1", "1944") == "1944-07-01"


def test_popular_names_entries():
    page = ("<html><body><div class='popular-name-table-entry' release-point='1-1'><p class='popular-name'>Placeholder "
            "Act</p><p class='popular-name-information' content-type='cite' t3searchkey='1944:373' datekey='1944-07-01'>"
            "x</p><p class='popular-name-information' content-type='cite' t3searchkey='107-188' datekey='2002-06-12'>y"
            "</p></div></body></html>")
    table = parse(page)
    assert table[norm_name("the Placeholder Act")][0]["identities"] == ["act:1944-07-01:373", "pl:107-188"]
    assert identity("1944:373", None) is None


def test_heads_with_headers_commas_quotes_and_such_section():
    ctx = Ctx()
    head, quotes, _ = lift_quotes("In general.—Section 5(b) of the Alpha, Beta, and Gamma Act of 1999 "
                                  "(12 U.S.C. 9(b)) is amended—")
    apply_head(head, ctx, quotes)
    assert (ctx.target.kind, ctx.target.act, ctx.target.section) == ("act", "Alpha, Beta, and Gamma Act of 1999", "5")
    ctx.memory["last"] = ctx.target_out()
    sib = Ctx(memory=ctx.memory)
    apply_head("Subsection (d) of such section is amended—", sib)
    assert (sib.target.section, [p for _, p in sib.path]) == ("5", ["(d)"])
    nick = Ctx()
    head, quotes, _ = lift_quotes("Section 9 of the Jane Q. “J” Doe Placeholder Act (Public Law 1–2) is amended—")
    apply_head(head, nick, quotes)
    assert nick.target.act == "Jane Q. “J” Doe Placeholder Act"
