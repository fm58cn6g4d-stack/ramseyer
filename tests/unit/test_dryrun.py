"""Dry-run engine (M6) on a synthetic section: placeholder statute text, real USLM structure."""
from billmap.dryrun.engine import Engine, Working, find_all, sentence_case, tidy, title_case
from billmap.parse import parse_text
from billmap.parse.grammar import _expand

NS = "http://xml.house.gov/schemas/uslm/1.0"
XML = f"""<section xmlns="{NS}" identifier="/us/usc/t99/s1"><num value="1">§ 1.</num><heading> Placeholder</heading>
<subsection identifier="/us/usc/t99/s1/a"><num value="a">(a)</num><heading> Alpha Rule.—</heading>
<content>The determiner shall review each term of the alpha program.</content></subsection>
<subsection identifier="/us/usc/t99/s1/b"><num value="b">(b)</num><heading> Beta Rule.—</heading>
<chapeau>The determiner shall—</chapeau>
<paragraph identifier="/us/usc/t99/s1/b/1"><num value="1">(1)</num><content> file a report;</content></paragraph>
<paragraph identifier="/us/usc/t99/s1/b/2"><num value="2">(2)</num><content> keep a record; and</content></paragraph>
<paragraph identifier="/us/usc/t99/s1/b/3"><num value="3">(3)</num><content> notify the board.</content></paragraph>
</subsection></section>"""


def run(draft: str):
    ins = parse_text("SEC. 2. AMENDMENTS.\n" + draft + "\n").instructions
    work = Working(XML, "/us/usc/t99/s1", positive_law=True)
    eng = Engine(work)
    results = [eng.run(i, list(i.target.path)) for i in ins]
    return work.render(), results


def test_word_bounded_match():
    text, res = run("Section 1 of title 99, United States Code, is amended in subsection (a) by striking “term” "
                    "and inserting “tenure”.")
    assert res[0].status == "CLEAN"
    assert "each tenure of" in text and "determiner" in text      # not "detenureiner"


def test_insert_spacing():
    text, res = run("Section 1 of title 99, United States Code, is amended in subsection (a) by inserting “and "
                    "beta” after “alpha”.")
    assert "alpha and beta program" in text


def test_strike_leaves_no_space_before_punctuation():
    text, _ = run("Section 1 of title 99, United States Code, is amended in subsection (b)(1) by striking “a report”.")
    assert "file;" in text and "file ;" not in text


def test_partially_parsed_instruction_is_not_clean():
    _, res = run("Section 1 of title 99, United States Code, is amended in subsection (a) by inserting after “alpha” "
                 "the following:")
    assert res[0].status != "CLEAN"


def test_replace_unit_keeps_section_heading_style():
    text, res = run("Section 1 of title 99, United States Code, is amended by amending paragraph (2) of subsection (b) "
                    "to read as follows:\n“(2) Record keeping.—keep a ledger; and”.")
    assert res[0].status == "CLEAN", res[0].detail
    assert "(2) Record keeping.—\nkeep a ledger; and\n(3)" in text


def test_find_all_requires_word_boundaries():
    hits, _ = find_all("the determiner and the term", "term", [(0, 100)])
    assert hits == [(23, 27)]


def test_tidy_drops_double_space_on_strike():
    hay = "one two three"
    assert tidy(hay, 4, 7, "", "replace") == (4, 8, "")


def test_heading_case():
    assert title_case("Prohibition on contracting with certain retailers") == \
        "Prohibition on Contracting With Certain Retailers"
    assert title_case("Life-cycle sustainment plan") == "Life-cycle Sustainment Plan"
    assert sentence_case("Members of the House of Representatives") == "Members of the house of representatives"


def test_roman_ranges():
    assert _expand("(i) through (iii)") == ["(i)", "(ii)", "(iii)"]
    assert _expand("(a) through (c)") == ["(a)", "(b)", "(c)"]


def test_listed_provisions_fan_out():
    ins = parse_text("SEC. 2. AMENDMENTS.\n(a) Extensions.—The following sections of title 99, United States Code, "
                     "are amended by striking “2025” and inserting “2026”:\n(1) Section 1(a), relating to alpha.\n"
                     "(2) Section 7(b), relating to beta.\n").instructions
    assert [(i.target.section, i.target.path) for i in ins] == [("1", ["(a)"]), ("7", ["(b)"])]


def test_delayed_effective_date_is_flagged():
    ins = parse_text("SEC. 2. AMENDMENTS.\n(a) In general.—Section 1 of title 99, United States Code, is amended by "
                     "striking “alpha” and inserting “beta”.\n(b) Effective date.—The amendment made by subsection (a) "
                     "shall take effect 180 days after the date of the enactment of this Act.\n").instructions
    assert any(f.startswith("delayed effective date") for f in ins[0].flags)
