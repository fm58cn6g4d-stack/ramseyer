"""Fixes from the M6e dev set's false-clean cases (records/m6e_dev_false_clean.md), on a synthetic section
(placeholder text, real USLM structure)."""
from ramseyer.dryrun.engine import Engine, Working
from ramseyer.parse import parse_text

NS = "http://xml.house.gov/schemas/uslm/1.0"
XML = f"""<section xmlns="{NS}" identifier="/us/usc/t99/s1"><num value="1">§ 1.</num><heading> Placeholder</heading>
<subsection identifier="/us/usc/t99/s1/a"><num value="a">(a)</num><heading> Alpha Rule.—</heading>
<content>The determiner shall review each term. Reviews shall be made at least annually. The board shall keep records.
</content></subsection>
<subsection identifier="/us/usc/t99/s1/b"><num value="b">(b)</num><content>The board may issue rules to carry out this
chapter.</content></subsection></section>"""


def run(draft: str, xml: str = XML):
    ins = parse_text("SEC. 2. AMENDMENTS.\n" + draft + "\n").instructions
    work = Working(xml, "/us/usc/t99/s1", positive_law=True)
    eng = Engine(work)
    results = [eng.run(i, list(i.target.path)) for i in ins]
    return " ".join(work.render().split()), results


def test_the_nth_sentence_of_a_unit_named_as_the_target():
    # Pub. L. 114-94 § 78001(a): "The second sentence of paragraph (1) of section 3(a) ... is amended by inserting
    # before the period at the end the following: ..." (42 U.S.C. 1437a). The target was lost and the text went to
    # the end of the section.
    text, res = run("The second sentence of subsection (a) of section 1 of title 99, United States Code, is amended by "
                    "inserting before the period at the end the following: “; except as provided”.")
    assert res[0].status == "CLEAN"
    assert "made at least annually; except as provided. The board shall keep records." in text


def test_the_period_at_the_end_of_the_first_sentence():
    # Pub. L. 116-136 § 19006(a) (39 U.S.C. 3210): the period of the last sentence was replaced instead.
    text, res = run("Section 1(a) of title 99, United States Code, is amended by striking the period at the end of the "
                    "first sentence and inserting the following: “, or semiannually.”.")
    assert res[0].status == "CLEAN"
    assert "review each term, or semiannually. Reviews shall" in text and "keep records." in text


def test_a_plural_possessive_inside_a_nested_quotation():
    # Pub. L. 113-66 § 1716 (10 U.S.C. 1044e): “(to be known as ‘Special Victims’ Counsel’)” became
    # “Special Victims” Counsel’).
    from ramseyer.dryrun.engine import nested_to_double
    assert nested_to_double("(to be known as ‘Special Victims’ Counsel’) for") == \
        "(to be known as “Special Victims’ Counsel”) for"
    assert nested_to_double("the term ‘State’ includes the Indians’ lands") == \
        "the term “State” includes the Indians’ lands"


def test_a_stray_closing_mark_inside_a_block_is_kept_and_a_repeated_close_dropped():
    # A ” the law leaves in the middle of a block is its own text and is kept (38 U.S.C. 119, Pub. L. 116-171; Espen,
    # 2026-10-31: literal marks). A close the law repeats at the block's end is the block's close (“... general.”;”;”,
    # Pub. L. 117-263 § 502).
    text, _ = run("Section 1 of title 99, United States Code, is amended by adding at the end the following:\n"
                  "“(c) Definitions.—In this section:\n“(1) The term ‘alpha’ means the alpha of the State.”.\n"
                  "“(2) The term ‘beta’ means beta.”;”;")
    assert "the alpha of the State.”. (2) The term “beta” means beta." in text
    assert not text.rstrip().endswith("”;")


def test_an_inserted_em_dash_takes_no_space_before_it():
    # Pub. L. 117-263 § 502(1)(A): “by striking ‘as follows:’ and inserting an em dash” (10 U.S.C. 525): “made—”.
    text, res = run("Section 1(a) of title 99, United States Code, is amended by striking “shall review” and inserting "
                    "an em dash.")
    assert "The determiner— each term" in text


def test_such_subsection_is_the_subsection_named_last():
    # Pub. L. 116-315 § 2003(b)(1) (38 U.S.C. 1562): "Such subsection is further amended—(A) by inserting “(1)”
    # after “(a)”; and (B) by adding at the end ..." had no target, and the section stayed CLEAN without them.
    text, res = run("Subsection (b) of section 1 of title 99, United States Code, is amended by striking “rules” and "
                    "inserting “orders”.\n(b) Spouses.—\n(1) Benefit.—Such subsection is further amended—\n"
                    "(A) by inserting “(1)” after “(b)”; and\n(B) by adding at the end the following new paragraph:\n"
                    "“(2) The board shall pay.”.")
    assert [r.status for r in res] == ["CLEAN", "CLEAN", "CLEAN"]
    assert text.endswith("(b) (1) The board may issue orders to carry out this chapter. (2) The board shall pay.")


def test_an_unapplied_each_place_strike_keeps_a_section_with_those_words_from_clean():
    # Pub. L. 114-144 § 4(m): "Part E of title III is amended by striking “this subpart” each place it appears"
    # (the Older Americans Act, named only earlier in the section) resolves nowhere; 42 U.S.C. 3030s-1 holds the words.
    from ramseyer.dryrun.verify import unapplied_mentions
    ins = parse_text("SEC. 4. X.\n(m) Conforming.—Part E of title III is amended by striking “this subpart” each place "
                     "it appears and inserting “this part”.\n").instructions
    work = Working(XML.replace("this\nchapter", "this subpart"), "/us/usc/t99/s1", positive_law=True)
    assert unapplied_mentions("/us/usc/t99/s1", ins, set(), work)
    assert not unapplied_mentions("/us/usc/t99/s1", ins, set(), Working(XML, "/us/usc/t99/s1", positive_law=True))


def test_lead_in_text_before_new_units_is_kept():
    # Pub. L. 113-76 div. G § 416 (20 U.S.C. 954): "by adding at the end the following: “Whenever a State agency
    # requests ..., the Chairperson shall—“(i) ...; and “(ii) ...”" lost its lead-in, CLEAN.
    text, res = run("Section 1(a) of title 99, United States Code, is amended by adding at the end the following: "
                    "“Whenever a member so requests, the board shall—\n“(1) give consideration to the request; and\n"
                    "“(2) ensure that it is not repeated.”.")
    assert res[0].status == "CLEAN"
    assert "keep records. Whenever a member so requests, the board shall— (1) give consideration" in text


def test_the_section_heading_is_not_a_subsection_heading():
    # Pub. L. 114-255 § 9010 (42 U.S.C. 290bb-41): "in the section heading, by inserting “mental health awareness”
    # before “training”" went into subsection (b)'s heading, which already held "training".
    xml = (f'<section xmlns="{NS}" identifier="/us/usc/t99/s1"><num value="1">§ 1.</num><heading> Training grants'
           '</heading><subsection identifier="/us/usc/t99/s1/b"><num value="b">(b)</num><heading> Mental illness '
           'awareness training grants</heading><content>Text b.</content></subsection></section>')
    text, res = run("Section 1 of title 99, United States Code, is amended—\n(1) in the section heading, by inserting "
                    "“mental health awareness” before “training”; and\n(2) in subsection (b)—\n(A) in the subsection "
                    "heading, by striking “illness” and inserting “health”.", xml)
    assert "(b) Mental health awareness training grants Text b." in text
    assert text.startswith("§ 1. mental health awareness Training grants") and res[0].status == "WARN"


def test_a_unit_added_at_the_end_of_a_unit_of_its_own_level_follows_its_siblings():
    # Pub. L. 116-136 § 19002(a) (2 U.S.C. 2062): "Section 312(d)(3)(A) ... is amended— ... (2) by adding at the end
    # the following new subparagraph: “(C) ...”" put (C) inside (A); OLRC put it after (B). WARN: drafted defectively.
    xml = (f'<section xmlns="{NS}" identifier="/us/usc/t99/s1"><num value="1">§ 1.</num><heading> H</heading>'
           '<subsection identifier="/us/usc/t99/s1/d"><num value="d">(d)</num><chapeau>The fund shall pay—</chapeau>'
           '<paragraph identifier="/us/usc/t99/s1/d/1"><num value="1">(1)</num><content>salaries.</content></paragraph>'
           '<paragraph identifier="/us/usc/t99/s1/d/2"><num value="2">(2)</num><content>reimbursements.</content>'
           '</paragraph></subsection></section>')
    text, res = run("Section 1(d)(1) of title 99, United States Code, is amended—\n(1) by striking the period at the end "
                    "and inserting “, and other costs.”; and\n(2) by adding at the end the following new paragraph:\n"
                    "“(3) Emergency expenses.”.", xml)
    assert text.endswith("(1) salaries, and other costs. (2) reimbursements. (3) Emergency expenses.")
    assert res[1].status == "WARN"


def test_an_identical_edit_made_twice_by_one_bill_is_a_conflict():
    # Pub. L. 115-254 div. B § 539(l) and div. K § 1991(f)(9)(C) both strike “(18 U.S.C. App.)” in 49 U.S.C.
    # 46111(g)(2)(A) and insert “(18 U.S.C. App.))”; the second applied it again (“App.)))”), CLEAN.
    xml = (f'<section xmlns="{NS}" identifier="/us/usc/t99/s1"><num value="1">§ 1.</num><heading> H</heading>'
           '<subsection identifier="/us/usc/t99/s1/g"><num value="g">(g)</num><content>A notice (as defined in '
           'section 1(a) of the Classified Act (18 U.S.C. App.), as applicable.</content></subsection></section>')
    text, res = run("Section 1(g) of title 99, United States Code, is amended by striking “(18 U.S.C. App.)” and "
                    "inserting “(18 U.S.C. App.))”.\nSEC. 3. MORE.\nSection 1 of title 99, United States Code, is "
                    "amended in subsection (g) by striking “(18 U.S.C. App.)” and inserting “(18 U.S.C. App.))”.", xml)
    assert [r.status for r in res] == ["CLEAN", "CONFLICT"]
    assert "(18 U.S.C. App.)), as applicable." in text


def test_in_each_of_sections_takes_the_title_in_context():
    # Pub. L. 115-254 div. K § 1991(f): "Chapter 461 is amended—(1) in each of sections 46101(a)(1), 46102(a), ...
    # by striking ..." had no target; 49 U.S.C. 46102 and 46105 stayed CLEAN without the edits.
    ins = parse_text("SEC. 2. X.\n(a) One.—Section 1 of title 99, United States Code, is amended by striking “a” and "
                     "inserting “b”.\n(b) Chapter 1 amendments.—Chapter 1 is amended—\n(1) in each of sections 1(a), 2, "
                     "and 3(b) by striking “Under Secretary,” each place it appears and inserting “Administrator,”;\n"
                     "(2) in section 2, by striking “the Board” and inserting “the Council”.\n").instructions
    listed = [i for i in ins if i.id.startswith("sec2.b.1")]
    assert [(i.target.title, i.target.section, i.target.path) for i in listed] == \
        [("99", "1", ["(a)"]), ("99", "2", []), ("99", "3", ["(b)"])]
    assert all(i.occurrence == "each" for i in listed)
    # § 1991(f)(3) leaves out a comma: "46101(a)(1), 46102(a) 46103(a), ...".
    gap = parse_text("SEC. 2. X.\n(a) One.—Section 1 of title 99, United States Code, is amended by striking “a” and "
                     "inserting “b”.\n(b) Chapter 1.—Chapter 1 is amended—\n(3) in each of sections 1(a)(1), 2(a) "
                     "3(a), and 10(a) by striking “x” and inserting “y”;\n").instructions
    assert [(i.target.section, i.target.path) for i in gap if i.id.startswith("sec2.b.3")] == \
        [("1", ["(a)", "(1)"]), ("2", ["(a)"]), ("3", ["(a)"]), ("10", ["(a)"])]


def test_a_code_parenthetical_without_a_space_is_not_a_label():
    # Pub. L. 114-255 § 3101(a)(2)(C): "Section 505–1(h)(21 U.S.C. 355–1(h)) is amended—" had no target, so 21 U.S.C.
    # 355-1 stayed CLEAN without its edits.
    ins = parse_text("SEC. 2. X.\nSection 505–1(h)(21 U.S.C. 355–1(h)) of the Placeholder Act is amended in "
                     "paragraph (8) by striking “and (7).” and inserting “and (7)”.\n").instructions
    assert (ins[0].target.section, ins[0].target.usc_parenthetical, ins[0].target.path) == \
        ("505–1", "21 U.S.C. 355–1(h)", ["(h)", "(8)"])


def test_a_table_in_quoted_text_keeps_the_instruction_from_clean(tmp_path):
    # Pub. L. 113-67 § 402(b)(2) (22 U.S.C. 4071e): “(C) ... shall be as follows:” and a one-row table; the table
    # was dropped by the renderer and the section came out CLEAN without it.
    from ramseyer.parse.xmltext import render
    bill = tmp_path / "bill.xml"
    bill.write_text(
        "<bill><legis-body><section><enum>2.</enum><header>Amendment</header><text>Section 1(b) of title 99, United "
        "States Code, is amended by adding at the end the following:</text><quoted-block><paragraph><enum>(2)</enum>"
        "<text>The applicable percentage shall be as follows:</text><table><tgroup cols=\"2\"><tbody><row><entry>"
        "11.15</entry><entry>After a placeholder date.</entry></row></tbody></tgroup></table></paragraph>"
        "<after-quoted-block>.</after-quoted-block></quoted-block></section></legis-body></bill>")
    rendered = render(bill)
    assert "[table omitted from the dry run: 1 row]" in rendered
    ins = parse_text(rendered).instructions
    work = Working(XML, "/us/usc/t99/s1", positive_law=True)
    res = Engine(work).run(ins[0], list(ins[0].target.path))
    assert res.status == "WARN" and "table" in res.detail
    assert "table omitted" not in work.render()


def test_a_references_clause_scoped_to_a_subsection():
    # Pub. L. 114-255 § 3101(a)(1): "whenever in this subsection an amendment is expressed in terms of an amendment to
    # a section ..., the reference shall be considered to be made to ... the Federal Food, Drug, and Cosmetic Act":
    # every § 3101(a) instruction resolved to UNKNOWN (21 U.S.C. 355-1 stayed CLEAN without its edits).
    ins = parse_text("SEC. 3101. CORRECTIONS.\n(a) One.—\n(1) References.—Except as otherwise expressly provided, "
                     "whenever in this subsection an amendment is expressed in terms of an amendment to a section or "
                     "other provision, the reference shall be considered to be made to that section or other provision "
                     "of the Placeholder Act (99 U.S.C. 301 et seq.).\n(2) Amendments.—Section 505–1(h)(99 U.S.C. "
                     "355–1(h)) is amended in paragraph (8) by striking “x” and inserting “y”.\n(b) Two.—Section 351 "
                     "(98 U.S.C. 262) is amended by striking “a” and inserting “b”.\n").instructions
    assert [(i.id, i.target.act) for i in ins] == [("sec3101.a.2#0", "Placeholder Act"), ("sec3101.b#0", None)]


def test_nested_quotation_keeps_the_laws_own_marks():
    # Pub. L. 114-153 § 2 (18 U.S.C. 1839): a quotation the law opens inside another keeps its single marks, and the
    # outer one the law never closes is still set as double. Synthetic placeholder text.
    from ramseyer.dryrun.engine import nested_to_double
    s = "the Act entitled ‘An Act to foo, (referred to as the ‘Alpha Act’ or the ‘Beta Act’)"
    want = "the Act entitled “An Act to foo, (referred to as the ‘Alpha Act’ or the ‘Beta Act’)"
    assert nested_to_double(s) == want
    assert nested_to_double(want) == want
    assert nested_to_double("the term ‘State’ includes the Indians’ lands") == \
        "the term “State” includes the Indians’ lands"


def test_an_apostrophe_inside_a_word_is_the_codes():
    # Pub. L. 116-283 § 505 (10 U.S.C. 628a): "person's" in the enrolled text, "person’s" in the Code.
    from ramseyer.parse.normalize import normalize
    n = normalize("the alpha's beta, ``gamma'' and 'delta'")
    assert n.text == "the alpha’s beta, “gamma” and 'delta'" and len(n.offsets) == len(n.text) + 1


def test_a_space_at_a_defined_terms_edge_goes_outside_its_marks():
    # Pub. L. 116-283 § 505: "<term>promotion board </term>means". Synthetic placeholder text.
    from lxml import etree
    from ramseyer.parse.xmltext import inline
    el = etree.fromstring("<text>the term <term>alpha beta </term>means gamma</text>")
    assert inline(el) == "the term “alpha beta” means gamma"
    assert inline(etree.fromstring("<text>striking <quote> and beta</quote></text>")) == "striking “ and beta”"


def test_the_heading_of_a_section_amended_to_read_replaces_the_heading_only():
    # Pub. L. 116-283 § 925(k)(1)(B) (37 U.S.C. 1005): read as a whole-section replacement, the text was lost.
    text, res = run("(a) In general.—Section 1 of title 99, United States Code, is amended by striking “review each "
                    "term” and inserting “review every term”.\n(b) Heading.—The heading of such section 1 is amended "
                    "to read as follows:\n“§ 1. Alpha rule”.")
    assert [r.status for r in res] == ["CLEAN", "CLEAN"]
    assert "Alpha rule" in text and "review every term" in text
