"""Instruction forms added after the red-team review (records/red-team-2026-10.md, F4) and the M4 quote check.
Each is a drafting form seen in enacted laws; the statute words here are placeholders."""
import pytest

from ramseyer.parse import parse_text

HEAD = "SEC. 2. X.\nSection 1 of title 99, United States Code, is amended—\n"


def one(item: str):
    ins = parse_text(HEAD + item + "\n").instructions
    assert len(ins) >= 1
    return ins


@pytest.mark.parametrize("item,op,find,replace", [
    ("(1) by replacing “alpha” with “beta”.", "STRIKE_INSERT", "alpha", "beta"),
    ("(1) by substituting “beta” for “alpha”.", "STRIKE_INSERT", "alpha", "beta"),
    ("(1) by deleting “alpha”.", "STRIKE", "alpha", None),
    ("(1) In subsection (a), strike “alpha” and insert “beta”.", "STRIKE_INSERT", "alpha", "beta"),
])
def test_nonstandard_verbs_are_read_and_flagged(item, op, find, replace):
    i = one(item)[0]
    assert (i.op, i.find, i.replace) == (op, find, replace)
    assert any(f.startswith("nonstandard verb") for f in i.flags)


def test_amended_with_no_known_verb_is_reported():
    i = one("(1) is amended so as to strike “alpha”.")[0]
    assert i.op == "UNPARSED" and "no instruction verb" in i.reason


@pytest.mark.parametrize("item,find,replace", [
    ("(1) by striking “or” after “alpha,”;", "alpha, or", "alpha,"),
    ("(1) by striking the period after “21”;", "21.", "21"),
    ("(1) by striking “and” after “officers” and inserting a comma;", "officers and", "officers,"),
    ("(1) by striking “and” before “14504”;", "and 14504", "14504"),
])
def test_strikes_anchored_on_neighbouring_words(item, find, replace):
    i = one(item)[0]
    assert (i.op, i.find, i.replace) == ("STRIKE_INSERT", find, replace)


def test_both_places_and_at_each_place():
    assert one("(1) by striking “a” both places it appears and inserting “b”;")[0].occurrence == "each"
    assert one("(1) by striking “a” at each place it appears and inserting “b”;")[0].occurrence == "each"


def test_location_between_the_quote_and_inserting():
    ins = one("(1) by striking “a” in subsections (b)(6)(B), (c)(1), and (e)(3) and inserting “b”;")
    assert [i.target.path for i in ins] == [["(b)", "(6)", "(B)"], ["(c)", "(1)"], ["(e)", "(3)"]]
    h = one("(1) by striking “Alpha” in the heading and inserting “Beta”;")[0]
    assert h.op == "AMEND_HEADING" and h.replace == "Beta"


def test_strike_through_forms():
    a = one("(1) by striking “a” and all that follows through the period and inserting “b.”;")[0]
    assert (a.op, a.through, a.replace) == ("STRIKE_THROUGH", ".", "b.")
    b = one("(1) by striking “a” and all that follows through the end of the paragraph and inserting “b”;")[0]
    assert (b.through, b.replace, b.confidence) == ("the end of the paragraph", "b", 1.0)
    c = one("(1) by striking “a” through “c,” and insert “a”;")[0]
    assert (c.op, c.find, c.through, c.replace) == ("STRIKE_THROUGH", "a", "c,", "a")
    d = one("(1) by striking “a” and all that follows through “c” and inserting the following: “d”;")[0]
    assert d.replace == "d"


def test_inline_quoted_unit_and_replacement_introducing_a_block():
    u = one("(1) by inserting after subparagraph (A) the following new subparagraph: “(B) text.”;")[0]
    assert (u.op, u.unit, u.new_text) == ("ADD_UNIT_AFTER", "subparagraph (A)", "“(B) text.”")
    r = one("(1) by striking “may not be used here” and inserting “may not be used at the following:”\n“(1) Alpha.\n"
            "“(2) Beta.”.")[0]
    assert r.replace.startswith("“may not be used at the following:\n“(1) Alpha.") and r.confidence == 1.0


def test_sentence_replaced_and_ending_punctuation():
    s = one("(1) by striking the second sentence and inserting the following: “The rule applies.”;")[0]
    assert (s.op, s.unit, s.replace) == ("STRIKE", "second sentence", "The rule applies.")
    p = one("(1) in subparagraph (C), by adding at the end before the period the following: “and beyond”;")[0]
    assert (p.op, p.find, p.new_text) == ("INSERT_BEFORE", ".", "and beyond")


def test_rule_of_application_is_not_an_amendment():
    i = parse_text("SEC. 2. X.\nSection 301 of the Placeholder Act (99 U.S.C. 2241) shall be applied by substituting "
                   "“$130” for “$120”.\n").instructions[0]
    assert "rule of application, not an amendment" in i.flags


def test_items_under_an_open_head_are_never_dropped():
    ins = parse_text("SEC. 2. X.\nSubsection (g) of section 2805 of title 99, United States Code, is—\n(1) transferred to "
                     "the end of section 2810 of such title; and\n(2) redesignated as subsection (f) of such section "
                     "2810.\n").instructions
    assert [(i.op, i.target.section, i.target.path) for i in ins] == [("UNPARSED", "2805", ["(g)"])] * 2
