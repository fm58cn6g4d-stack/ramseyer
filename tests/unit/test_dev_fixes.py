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


def test_a_closing_quotation_mark_repeated_by_the_drafter_is_dropped():
    # Pub. L. 116-315 § 7002 closes a quoted block twice in its middle (“... Hawaii.”.” then “(6) ...”); Pub. L.
    # 117-263 § 502 ends one “... general.”;”;”. OLRC drops the extra marks.
    text, _ = run("Section 1 of title 99, United States Code, is amended by adding at the end the following:\n"
                  "“(c) Definitions.—In this section:\n“(1) The term ‘alpha’ means the alpha of the State.”.\n"
                  "“(2) The term ‘beta’ means beta.”;”;")
    assert "the alpha of the State. (2) The term “beta” means beta." in text and "”" not in text.split("(c)")[1] \
        .replace("“alpha”", "").replace("“beta”", "")


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
