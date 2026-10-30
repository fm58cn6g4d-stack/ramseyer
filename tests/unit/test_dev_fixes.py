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
