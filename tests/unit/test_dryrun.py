"""Dry-run engine (M6) on a synthetic section: placeholder statute text, real USLM structure."""
from ramseyer.dryrun.engine import Engine, Working, find_all, sentence_case, tidy, title_case
from ramseyer.parse import parse_text
from ramseyer.parse.grammar import _expand

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


def test_future_date_with_application_clause_is_delayed():
    ins = parse_text("TITLE I—ALPHA\nSEC. 101. AMENDMENT.\nSection 1 of title 99, United States Code, is amended by "
                     "striking “alpha” and inserting “beta”.\nSEC. 102. EFFECTIVE DATE.\nThe amendments made by this "
                     "title shall take effect on October 1, 2025, and shall apply to payments for quarters beginning on "
                     "or after such date.\n").instructions
    assert any(f.startswith("delayed effective date") for f in ins[0].flags)


def test_listed_repeals_fan_out_with_unknown_items_kept():
    ins = parse_text("SEC. 2. REPEALS.\n(a) Title 99.—The following provisions of title 99, United States Code, are hereby "
                     "repealed:\n(1) Chapter 5.\n(2) Section 7.\n(3) The Placeholder Act (99 U.S.C. 1 et seq.).\n").instructions
    assert [i.op for i in ins] == ["REPEAL"] * 3
    assert ins[0].target.qualifiers == ["chapter 5"] and ins[1].target.section == "7"
    assert ins[2].target.kind == "unknown" and "Placeholder Act" in ins[2].target.cite_raw


def test_structural_redesignation():
    text, res = run("Section 1 of title 99, United States Code, is amended in subsection (b) by redesignating "
                    "paragraphs (1) and (2) as paragraphs (4) and (5), respectively.")
    assert res[0].status == "CLEAN" and "(4)\nfile a report;" in text


def test_strike_at_start_of_text_after_heading():
    text, res = run("Section 1 of title 99, United States Code, is amended in subsection (a) by striking “The determiner” "
                    "and inserting “The reviewer”.")
    assert res[0].status == "CLEAN" and "The reviewer shall review" in text


def test_split_into_lead_in_and_new_units():
    # "by striking “x” and inserting “y—“(A) x”": the unit's text becomes a chapeau, the rest continues (A).
    text, res = run("Section 1 of title 99, United States Code, is amended in subsection (a)—\n"
                    "(1) by striking “review each” and inserting the following: “review—\n“(A) each”; and\n"
                    "(2) by adding at the end the following:\n“(B) the beta program.”.")
    assert res[0].status == "CLEAN" and res[0].detail.startswith("split")
    assert "shall review— (A) each term of the alpha program. (B) the beta program." in " ".join(text.split())


def test_text_moves_into_a_new_first_unit():
    # "by striking “The determiner” and inserting “(1) In general.—The determiner”" at the start of the text.
    text, res = run("Section 1 of title 99, United States Code, is amended in subsection (a)—\n"
                    "(1) by striking “The determiner” and inserting “(1) In general.—The determiner”; and\n"
                    "(2) by adding at the end the following:\n“(2) Beta.—The beta program.”.")
    assert res[0].status == "CLEAN" and res[0].detail.startswith("split")
    assert "Rule.— (1) In general.— The determiner shall review each term" in " ".join(text.split())


def test_split_continues_as_siblings_at_their_level():
    # (b)(1) "file a report;" -> "(1) file a report—(A) ...; and(B) ..." then a sibling (2) at the paragraph level.
    text, res = run("Section 1 of title 99, United States Code, is amended in subsection (b)(1)—\n"
                    "(1) by striking “file a report” and inserting “file—\n“(A) a report”; and\n"
                    "(2) by striking “a report;” and inserting “a report; and\n“(B) a plan;”.")
    assert [r.detail.split(":")[0] for r in res] == ["split (children)", "split (siblings)"]
    assert "shall— (1) file— (A) a report; and (B) a plan; (2) keep a record;" in " ".join(text.split())


def test_replacing_text_that_starts_with_punctuation_keeps_words_apart():
    hay = "available for fishing. In particular, the boom shall be lowered."
    a = hay.index(". In")
    a2, b2, new = tidy(hay, a, len(hay), "and in accordance with the rules.", "replace")
    assert (hay[:a2] + new + hay[b2:]).endswith("for fishing and in accordance with the rules.")


def test_self_check_flags_enumerated_text_left_inline_and_unapplied_mentions():
    from ramseyer.dryrun.verify import structure_problems, unapplied_mentions
    work = Working(XML, "/us/usc/t99/s1", positive_law=True)
    eng = Engine(work)
    ins = parse_text("SEC. 2. AMENDMENTS.\nSection 1 of title 99, United States Code, is amended in subsection (a) by "
                     "inserting “ c. Gamma review.—The board may act.” after “program.”.\n").instructions
    eng.run(ins[0], list(ins[0].target.path))
    assert structure_problems(work) and "enumerated text" in structure_problems(work)[0]
    other = parse_text("SEC. 3. MORE.\nSection 1 of the Placeholder Act (99 U.S.C. 1) is amended by "
                       "striking the matter that relates to beta.\n").instructions
    assert unapplied_mentions("/us/usc/t99/s1", other, set()) and not unapplied_mentions("/us/usc/t99/s1", other,
                                                                                          {other[0].id})


def test_label_order_reads_roman_and_letters():
    from ramseyer.dryrun.verify import _in_order
    assert _in_order(["i", "ii", "iii", "iv", "v"]) and _in_order(["h", "i", "j"]) and _in_order(["1", "2", "10"])
    assert _in_order(["A", "B", "C"]) and not _in_order(["i", "iii", "ii"]) and not _in_order(["b", "a"])


def test_sentence_edits_on_units_with_subunits_are_not_clean():
    _, res = run("Section 1 of title 99, United States Code, is amended in subsection (b) by striking the second "
                 "sentence and inserting “Another.”.")
    assert res[0].status == "AMBIGUOUS"


def test_unit_found_by_the_term_it_defines():
    xml = XML.replace("<content>The determiner shall review each term of the alpha program.</content>",
                      '<content>The term "alpha" means the first program. It runs yearly.</content>')
    ins = parse_text("SEC. 2. X.\nSection 1 of title 99, United States Code, is amended, in the subsection defining "
                     "the term “alpha”, by striking the second sentence and inserting “It runs monthly.”.\n").instructions
    work = Working(xml, "/us/usc/t99/s1", positive_law=True)
    r = Engine(work).run(ins[0], list(ins[0].target.path))
    assert r.status == "CLEAN" and "It runs monthly." in work.render() and "yearly" not in work.render()


# ---- already executed (M6d): current law already reads as the instruction would leave it ----

def test_a_missing_quote_whose_replacement_occurs_stays_not_found():
    # No place to check once the struck text is gone; the replacement's presence is only noted.
    text, res = run("Section 1 of title 99, United States Code, is amended in subsection (a) by striking “each term "
                    "of the omega program” and inserting “each term of the alpha program”.")
    assert res[0].status == "NOT_FOUND", res[0].detail
    assert "already occurs in the unit" in res[0].detail
    assert "each term of the alpha program" in text


def test_replacement_containing_the_old_text_is_not_applied_twice():
    # Striking "alpha" and inserting "alpha program" where the text already reads "alpha program": applying it
    # again would print "alpha program program".
    text, res = run("Section 1 of title 99, United States Code, is amended in subsection (a) by striking “alpha” "
                    "and inserting “alpha program”.")
    assert res[0].status == "ALREADY_EXECUTED", res[0].detail
    assert "program program" not in text


def test_insert_after_already_in_place():
    text, res = run("Section 1 of title 99, United States Code, is amended in subsection (a) by inserting “of the "
                    "alpha” after “each term”.")
    assert res[0].status == "ALREADY_EXECUTED", res[0].detail
    assert text.count("of the alpha") == 1


def test_insert_before_already_in_place():
    _, res = run("Section 1 of title 99, United States Code, is amended in subsection (a) by inserting “shall "
                 "review” before “each term”.")
    assert res[0].status == "ALREADY_EXECUTED", res[0].detail


def test_a_real_insertion_and_a_missing_quote_are_unchanged():
    _, res = run("Section 1 of title 99, United States Code, is amended in subsection (a) by inserting “and "
                 "beta” after “alpha”.")
    assert res[0].status == "CLEAN"
    _, res = run("Section 1 of title 99, United States Code, is amended in subsection (a) by striking “omega” "
                 "and inserting “zeta rule”.")
    assert res[0].status == "NOT_FOUND"


def test_short_insertions_never_count_as_executed():
    # "of" is too short to tell an earlier execution from coincidence.
    _, res = run("Section 1 of title 99, United States Code, is amended in subsection (a) by striking “omega” "
                 "and inserting “of”.")
    assert res[0].status == "NOT_FOUND"


def test_categories():
    from ramseyer.dryrun.engine import category
    assert category("ALREADY_EXECUTED") == "already executed"
    assert category("NOT_FOUND") == "drafting" and category("TARGET_MISSING") == "drafting"
    assert category("STALE_BASELINE") == "current-law data"
    assert category("UNPARSED") == "system" and category("NOT_EXECUTED") == "system"
    assert category("CLEAN") is None and category("WARN") is None


def test_a_change_made_earlier_in_the_same_bill_is_a_conflict_not_already_executed():
    text, res = run("(a) Section 1 of title 99, United States Code, is amended in subsection (a) by inserting “and "
                    "beta” after “alpha”.\n(b) Section 1 of title 99, United States Code, is amended in subsection "
                    "(a) by inserting “and beta” after “alpha”.")
    assert [r.status for r in res] == ["CLEAN", "CONFLICT"], [r.detail for r in res]
    assert text.count("and beta") == 1


def test_a_correction_matches_across_a_footnote_marker_and_removes_it():
    # OLRC prints the words a correction fixes with a "So in original" footnote: "the the¹ board".
    xml = XML.replace("notify the board.", 'notify the the<ref class="footnoteRef" idref="fn1">1</ref> board.'
                      '<note type="footnote" id="fn1">So in original.</note>')
    ins = parse_text("SEC. 2. AMENDMENTS.\nSection 1 of title 99, United States Code, is amended in subsection "
                     "(b)(3) by striking “the the board” and inserting “the board”.\n").instructions
    work = Working(xml, "/us/usc/t99/s1", positive_law=True)
    res = Engine(work).run(ins[0], list(ins[0].target.path))
    assert res.status == "CLEAN", res.detail
    assert "notify the board." in work.render() and "So in original" not in work.render()


def test_a_longer_word_is_not_an_insertion_in_place():
    # Inserting "program" after "alpha" in "alpha programming" is a real insertion (Codex, PR #3).
    xml = XML.replace("the alpha program.", "the alpha programming.")
    ins = parse_text("SEC. 2. AMENDMENTS.\nSection 1 of title 99, United States Code, is amended in subsection "
                     "(a) by inserting “program” after “alpha”.\n").instructions
    work = Working(xml, "/us/usc/t99/s1", positive_law=True)
    res = Engine(work).run(ins[0], list(ins[0].target.path))
    assert res.status == "CLEAN", res.detail
    assert "alpha program programming" in work.render()


def test_markers_are_removed_only_in_the_edited_occurrence():
    # Two footnoted occurrences and an edit of the first: the second keeps its marker; "the second place" is not
    # matched across markers at all (Codex, PR #3).
    fn = '<ref class="footnoteRef" idref="fn{n}">{n}</ref>'
    xml = XML.replace("file a report;", f"file a the{fn.format(n=1)} report;").replace(
        "keep a record; and", f"keep a the{fn.format(n=2)} report; and")
    def go(draft):
        ins = parse_text("SEC. 2. AMENDMENTS.\n" + draft + "\n").instructions
        work = Working(xml, "/us/usc/t99/s1", positive_law=True)
        return Engine(work).run(ins[0], list(ins[0].target.path)), work
    res, work = go("Section 1 of title 99, United States Code, is amended in subsection (b)(1) by striking “a the "
                   "report” and inserting “a report”.")
    assert res.status == "CLEAN", res.detail
    assert work.el.find(".//{*}ref[@idref='fn2']") is not None and work.el.find(".//{*}ref[@idref='fn1']") is None
    res, work = go("Section 1 of title 99, United States Code, is amended in subsection (b) by striking “a the "
                   "report” the second place it appears and inserting “a report”.")
    assert res.status != "CLEAN"
    assert work.el.find(".//{*}ref[@idref='fn1']") is not None and work.el.find(".//{*}ref[@idref='fn2']") is not None


def test_the_period_at_the_end_matches_before_a_footnote_marker():
    # "striking the period at the end": only the final period, though a marker follows it (Pub. L. 119-60
    # § 8431(b)(1)(B) on 43 U.S.C. 1474d). An earlier footnoted period is untouched (review of PR #3).
    xml = XML.replace("notify the board.", 'notify the board.<ref class="footnoteRef" idref="fn1">1</ref>'
                      '<note type="footnote" id="fn1">So in original.</note>').replace(
        "keep a record; and", 'keep a record.<ref class="footnoteRef" idref="fn2">2</ref> and')
    ins = parse_text("SEC. 2. AMENDMENTS.\nSection 1 of title 99, United States Code, is amended in subsection "
                     "(b)(3) by striking the period at the end and inserting “; and”.\n").instructions
    work = Working(xml, "/us/usc/t99/s1", positive_law=True)
    res = Engine(work).run(ins[0], list(ins[0].target.path))
    assert res.status == "CLEAN", res.detail
    assert "notify the board; and" in work.render()
    assert work.el.find(".//{*}ref[@idref='fn2']") is not None


def test_an_exponent_is_not_a_footnote_marker_without_footnotes():
    # A digit <sup> counts as a marker only in a section that has footnotes; "10<sup>3</sup>" may be an exponent.
    xml = XML.replace("file a report;", "file a report of 10<sup>3</sup> pages;")
    ins = parse_text("SEC. 2. AMENDMENTS.\nSection 1 of title 99, United States Code, is amended in subsection "
                     "(b)(1) by striking “10 pages” and inserting “ten pages”.\n").instructions
    work = Working(xml, "/us/usc/t99/s1", positive_law=True)
    res = Engine(work).run(ins[0], list(ins[0].target.path))
    assert res.status == "NOT_FOUND", res.detail
    assert work.el.find(".//{*}sup") is not None
