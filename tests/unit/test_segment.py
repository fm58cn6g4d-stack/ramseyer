"""Segmenter and parser on synthetic drafts (placeholder wording; not statute text)."""
from ramseyer.parse import parse_text
from ramseyer.parse.segment import walk

L, R = "“", "”"


def locs(text):
    return [n.loc for n in walk(parse_text(text).nodes)]


def test_ambiguous_i_opens_clause_under_subparagraph():
    text = "\n".join(["SEC. 2. X.", "(h) Alpha.—", "(1) beta", "(A) gamma", "(B) delta—",
                      "(i) first clause", "(ii) second clause", "(C) epsilon"]) + "\n"
    assert "sec2.h.1.B.i" in locs(text) and "sec2.h.1.B.ii" in locs(text) and "sec2.h.1.C" in locs(text)


def test_ambiguous_i_continues_subsections_when_next_is_j():
    text = "\n".join(["SEC. 2. X.", "(h) Alpha.—", "(1) beta", "(i) Iota.—text", "(j) Kappa.—text"]) + "\n"
    assert {"sec2.i", "sec2.j"} <= set(locs(text))


def test_table_of_contents_headings_are_not_structure():
    text = "\n".join(["SEC. 1. SHORT TITLE; TABLE OF CONTENTS.", "(b) Table of contents.—The table of contents "
                      "for this Act is as follows:", "TITLE I—ALPHA", "Sec. 101. Beta.", "TITLE I—ALPHA",
                      "SEC. 101. BETA.", "Section 5 of the Placeholder Act is amended by striking " + L + "a" + R +
                      " and inserting " + L + "b" + R + "."]) + "\n"
    r = parse_text(text)
    assert [i.bill_loc for i in r.instructions] == ["titleI.sec101"]


def test_open_quote_continues_into_block():
    text = "\n".join(["SEC. 2. X.", "Section 5 of the Placeholder Act is amended by striking " + L + "old." + R +
                      " and inserting the following " + L + "new—", L + "(i) one; or", L + "(ii) two." + R + "."]) + "\n"
    i = parse_text(text).instructions[0]
    assert i.op == "STRIKE_INSERT" and i.confidence == 1.0 and "(ii) two." in i.replace
    assert "open_quote_continues_in_block" in i.flags


def test_block_closed_without_space_before_and():
    text = "\n".join(["SEC. 2. X.", "Section 5 of title 99, United States Code, is amended—",
                      "(1) by adding at the end the following:", L + "(c) Gamma." + R + "and",
                      "(2) by striking " + L + "x" + R + "."]) + "\n"
    r = parse_text(text)
    assert [(i.bill_loc, i.op) for i in r.instructions] == [("sec2.1", "ADD_END"), ("sec2.2", "STRIKE")]
    assert r.instructions[1].target.cite_norm == "99 U.S.C. 5"


def test_unmatched_clause_is_reported_never_dropped():
    text = "SEC. 2. X.\nSection 5 of title 99, United States Code, is amended by transferring subsection (c) to " \
           "the end of section 6.\n"
    r = parse_text(text)
    assert len(r.instructions) == 1 and r.instructions[0].op == "UNPARSED"
    assert "transferring" in r.instructions[0].reason and r.instructions[0].source_text
