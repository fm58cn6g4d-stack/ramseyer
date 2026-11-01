"""OLRC editorial conventions (oracle/editorial.py) on synthetic sections (placeholder text)."""
from lxml import etree

from ramseyer.oracle import editorial
from ramseyer.oracle.editorial import Context

NS = "http://xml.house.gov/schemas/uslm/1.0"


def sec(body: str, heading: str = "Placeholder rule") -> str:
    return (f'<section xmlns="{NS}" identifier="/us/usc/t99/s1"><num value="1">§ 1.</num><heading> {heading}</heading>'
            f'{body}</section>')


def sub(letter: str, text: str, heading: str | None = None) -> str:
    h = f"<heading> {heading}.—</heading>" if heading else ""
    return (f'<subsection identifier="/us/usc/t99/s1/{letter}"><num value="{letter}">({letter})</num>{h}'
            f"<content>{text}</content></subsection>")


def kind(pred: str, after: str, ctx: Context | None = None):
    return editorial.kind(etree.fromstring(pred), after, ctx)


def test_an_enactment_date_set_in_with_a_comma():
    pred = sec(sub("a", "Not later than 90 days after the date of enactment of this sentence the Secretary shall act."))
    after = sec(sub("a", "Not later than 90 days after December 23, 2022, the Secretary shall act."))
    this_law = Context(pl="1-2", date_of=lambda act: "2022-12-23" if act is None else None)
    assert kind(pred, after, this_law) .startswith("editorial")
    wrong = sec(sub("a", "Not later than 60 days after December 23, 2022, the Secretary shall act."))
    assert kind(pred, wrong, this_law) is None
    assert kind(pred, after, Context(pl="1-2")) is None                       # no known date: not accepted


def test_only_the_named_act_s_own_enactment_date_counts():
    # Review of #10: an unexecuted "strike ‘the date of enactment of this Act’ and insert ‘October 1, 2031’" must not
    # pass as OLRC setting in the date; and a named Act's date is that Act's, not this law's.
    pred = sec(sub("a", "beginning on the date of enactment of this Act, the Secretary shall act."))
    later = sec(sub("a", "beginning on October 1, 2031, the Secretary shall act."))
    ctx = Context(pl="1-2", date_of=lambda act: "2022-12-23" if act is None else "2020-03-27")
    assert kind(pred, later, ctx) is None
    named = sec(sub("a", "Not later than 4 years after the date of enactment of the Placeholder Relief Act, act."))
    assert kind(named, sec(sub("a", "Not later than 4 years after March 27, 2020, act.")), ctx) .startswith("editorial")
    assert kind(named, sec(sub("a", "Not later than 4 years after December 23, 2022, act.")), ctx) is None


def test_an_act_reference_counts_only_as_the_code_section_the_resolver_finds():
    pred = sec(sub("a", "as defined in section 4 of the Placeholder Act), and other entities"))
    after = sec(sub("a", "as defined in section 5304 of title 25), and other entities"))
    right = Context(pl="1-2", title="99", resolve=lambda cite: "/us/usc/t25/s5304")
    assert kind(pred, after, right) .startswith("editorial")
    assert kind(pred, after, Context(pl="1-2", title="99", resolve=lambda cite: "/us/usc/t25/s5305")) is None
    assert kind(pred, after, Context(pl="1-2", title="99")) is None            # unresolved: not accepted
    here = sec(sub("a", "as defined in section 5304 of this title), and other entities"))
    assert kind(pred, here, Context(pl="1-2", title="25", resolve=lambda cite: "/us/usc/t25/s5304")) .startswith("editorial")


def test_a_heading_olrc_supplied_counts_only_outside_positive_law():
    pred = sec(sub("e", "The Director shall act."))
    after = sec(sub("e", "The Director shall act.", heading="Policymaking"))
    law = [([], "“(e) The Director shall act.”")]                               # the law's text has no heading
    assert kind(pred, after, Context(pl="1-2", positive_law=False, inserted=law)) .startswith("editorial")
    assert kind(pred, after, Context(pl="1-2", positive_law=True, inserted=law)) is None
    assert kind(pred, after, Context(pl="1-2", inserted=law)) is None          # not known: not accepted
    renamed = sec(sub("e", "The Director shall act.", heading="Other"))
    assert kind(sec(sub("e", "The Director shall act.", heading="Policy")), renamed,
                Context(pl="1-2", positive_law=False, inserted=law)) is None   # a heading the law has, changed


def test_a_heading_the_engine_lost_is_not_excused():
    # Review of #10: the prediction lacks a heading the law's own text gives; R_after has it. Not OLRC's work.
    pred = sec(sub("e", "The Director shall act."))
    after = sec(sub("e", "The Director shall act.", heading="Policymaking"))
    law = [([], "“(e) Policymaking.—The Director shall act.”")]
    assert kind(pred, after, Context(pl="1-2", positive_law=False, inserted=law)) is None
    assert kind(pred, after, Context(pl="1-2", positive_law=False)) is None   # the unit is not in the law's text


def test_a_supplied_heading_is_matched_on_the_units_own_place():
    # Review of #10: text inserted elsewhere in the section that happens to have an "(e)" says nothing of this (e).
    pred = sec(sub("e", "The Director shall act."))
    after = sec(sub("e", "The Director shall act.", heading="Policymaking"))
    elsewhere = [(["(c)"], "“(e) The Director shall act.”")]
    assert kind(pred, after, Context(pl="1-2", positive_law=False, inserted=elsewhere)) is None
    assert kind(pred, after, Context(pl="1-2", positive_law=False, inserted=[(["(e)"], "“(1) Text.”")])) is None


def test_a_catchline_counts_as_olrc_s_unless_the_law_amends_a_heading():
    pred, after = sec(sub("a", "Text."), "Control of plant growths"), sec(sub("a", "Text."), "Control of plant growths "
                                                                                     "and invasive species")
    assert kind(pred, after, Context(pl="1-2", positive_law=False)) .startswith("editorial")
    assert kind(pred, after, Context(pl="1-2", positive_law=False, heading_amended=True)) is None


def test_heading_case_and_closing_punctuation_are_style():
    pred = sec(sub("c", "Text.", heading="Period of validity"))
    after = sec(sub("c", "Text.", heading="Period of Validity").replace(".—</heading>", "</heading>"))
    assert kind(pred, after) .startswith("editorial")


def test_a_repealed_placeholder_counts_only_when_it_cites_this_law():
    pred = sec(sub("e", "Text."))
    after = sec(sub("e", "Text.") + '<subsection identifier="/us/usc/t99/s1/f"><num value="f">(f)</num>'
                '<content>Repealed. Pub. L. 1–2, § 3(b), Jan. 17, 2014, 128 Stat. 424.</content></subsection>')
    assert kind(pred, after, Context(pl="1-2")) .startswith("editorial")
    assert kind(pred, after, Context(pl="1-3")) is None


def test_footnote_digits_attached_to_a_word_count_but_numbers_do_not():
    pred = sec(sub("a", "under section 3024),2 the Director"))
    assert kind(pred, sec(sub("a", "under section 3024), the Director")), Context(pl="1-2")) == \
        "editorial: footnote markers"
    assert kind(sec(sub("a", "under section 2 the Director")), sec(sub("a", "under section the Director")),
                Context(pl="1-2")) is None                                     # a number dropped after a space
    assert kind(sec(sub("a", "subject to paragraph (4), the")), sec(sub("a", "subject to paragraph (5), the")),
                Context(pl="1-2")) is None                                     # different digits at one place


def test_whitespace_only_differences_are_reported_as_such():
    pred = sec(sub("a", "to carry out this section$41,304,000 for each year"))
    after = sec(sub("a", "to carry out this section $41,304,000 for each year"))
    assert kind(pred, after) == "whitespace"


def test_an_olrc_probable_intent_execution_of_this_law():
    pred, after = sec(sub("a", "130 percent")), sec(sub("a", "150 percent"))
    note = ("Amendments 2022—Pub. L. 1–2, which directed substitution of “150 percent” for “130 percent” both places, "
            "was executed in the one place to reflect the probable intent of Congress.")
    assert kind(pred, after, Context(pl="1-2", new_notes=[note])).startswith("editorial: executed")
    assert kind(pred, after, Context(pl="1-3", new_notes=[note])) is None


def test_a_probable_intent_note_excuses_only_the_differences_it_quotes():
    note = ("Amendments 2022—Pub. L. 1–2, which directed substitution of “150 percent” for “130 percent” both places, "
            "was executed in the one place to reflect the probable intent of Congress.")
    pred = sec(sub("a", "130 percent of the amount") + sub("b", "The board shall act."))
    after = sec(sub("a", "150 percent of the amount") + sub("b", "The board may act."))
    assert kind(pred, after, Context(pl="1-2", new_notes=[note])) is None


def test_a_supplied_heading_is_found_on_a_unit_the_engine_built_without_an_identifier():
    # Units built from bill text carry no identifier (Pub. L. 116-260 div. Q § 224, 15 U.S.C. 1062(b)).
    pred = sec('<subsection><num value="b">(b)</num><content>The applicant shall reply.</content></subsection>')
    after = sec(sub("b", "The applicant shall reply.", heading="Refusal of registration"))
    law = [([], "“(b)\n“(1) If the applicant ..."), ([], "“(b) The applicant shall reply.”")]
    assert kind(pred, after, Context(pl="1-2", positive_law=False, inserted=law)) .startswith("editorial")


def test_bracketed_code_citations_are_olrc_s():
    # OLRC adds and drops "[30 U.S.C. 1101 et seq.]" after an Act's public law number (42 U.S.C. 5905).
    pred = sec(sub("a", "the Placeholder Act (Public Law 93–410) [30 U.S.C. 1101 et seq.], to accelerate"))
    after = sec(sub("a", "the Placeholder Act (Public Law 93–410), to accelerate"))
    assert kind(pred, after, Context(pl="1-2")) .startswith("editorial")


def test_an_act_reference_resolving_to_a_subsection():
    # "section 1860D–4(o) of the Social Security Act" resolves to …/s1395w–104/o (42 U.S.C. 300jj).
    pred = sec(sub("a", "of paragraph (2)(B) of section 1860D–4(o) of the Placeholder Act at a time"))
    after = sec(sub("a", "of paragraph (2)(B) of section 1395w–104(o) of this title at a time"))
    ctx = Context(pl="1-2", title="42", resolve=lambda cite: "/us/usc/t42/s1395w–104/o")
    assert kind(pred, after, ctx) .startswith("editorial")


def test_a_supplied_heading_on_a_unit_the_law_replaces_whole():
    # Pub. L. 116-260 div. Q § 224 (15 U.S.C. 1062): "striking subsection (b) and inserting “(b)\n“(1) ...": the
    # inserted text is the unit itself, set at its parent's level, and gives (b) no heading.
    pred = sec('<subsection><num value="b">(b)</num><content>The applicant shall reply.</content></subsection>')
    after = sec(sub("b", "The applicant shall reply.", heading="Refusal of registration"))
    law = [(["(b)"], "“(b) The applicant shall reply.”")]
    assert kind(pred, after, Context(pl="1-2", positive_law=False, inserted=law)) .startswith("editorial")
    lost = [(["(b)"], "“(b) Refusal of registration.—The applicant shall reply.”")]
    assert kind(pred, after, Context(pl="1-2", positive_law=False, inserted=lost)) is None


def test_a_bracketed_repealed_placeholder_and_this_clause():
    # 10 U.S.C. 652: "[(5) Repealed. Pub. L. 114–92, ...]"; 33 U.S.C. 2263: "the date of enactment of this clause".
    pred = sec(sub("a", "Alpha.") + sub("b", "Beta."))
    after = sec(sub("a", "Alpha.") + sub("b", "Beta.") +
                "<p>[(5) Repealed. Pub. L. 1–2, div. A, title V, § 524(a)(2), Nov. 25, 2015, 129 Stat. 818.]</p>")
    assert kind(pred, after, Context(pl="1-2")) is not None
    after2 = sec(sub("a", "carried out after June 10, 2014, or later"))
    pred2 = sec(sub("a", "carried out after the date of enactment of this clause, or later"))
    assert kind(pred2, after2, Context(pl="1-2", date_of=lambda act: "2014-06-10" if act is None else None)) is not None


def test_an_act_reference_with_its_own_code_citation():
    # 38 U.S.C. 2021, 7 U.S.C. 3195, 4 U.S.C. 7 (dev 2): the law prints the Code citation; OLRC sets it in place.
    pred = sec(sub("a", "pursuant to section 8(o)(19) of the Alpha Act of 1937 (42 U.S.C. 1437f(o)(19)) or the"))
    after = sec(sub("a", "pursuant to section 1437f(o)(19) of title 42 or the"))
    assert kind(pred, after, Context(pl="1-2", title="38")) is not None
    assert kind(pred, sec(sub("a", "pursuant to section 1437g(o)(19) of title 42 or the")),
                Context(pl="1-2", title="38")) is None                    # another section: not the law's citation
    pred = sec(sub("a", "employees subject to the Act of March 4, 1940 (7 U.S.C. 331);"))
    assert kind(pred, sec(sub("a", "employees subject to section 331 of this title;")),
                Context(pl="1-2", title="7")) is not None
