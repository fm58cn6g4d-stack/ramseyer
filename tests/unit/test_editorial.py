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
    assert kind(pred, after, Context(pl="1-2")) == "editorial"
    wrong = sec(sub("a", "Not later than 60 days after December 23, 2022, the Secretary shall act."))
    assert kind(pred, wrong, Context(pl="1-2")) is None


def test_an_act_reference_counts_only_as_the_code_section_the_resolver_finds():
    pred = sec(sub("a", "as defined in section 4 of the Placeholder Act), and other entities"))
    after = sec(sub("a", "as defined in section 5304 of title 25), and other entities"))
    right = Context(pl="1-2", title="99", resolve=lambda cite: "/us/usc/t25/s5304")
    assert kind(pred, after, right) == "editorial"
    assert kind(pred, after, Context(pl="1-2", title="99", resolve=lambda cite: "/us/usc/t25/s5305")) is None
    assert kind(pred, after, Context(pl="1-2", title="99")) is None            # unresolved: not accepted
    here = sec(sub("a", "as defined in section 5304 of this title), and other entities"))
    assert kind(pred, here, Context(pl="1-2", title="25", resolve=lambda cite: "/us/usc/t25/s5304")) == "editorial"


def test_a_heading_olrc_supplied_counts_only_outside_positive_law():
    pred = sec(sub("e", "The Director shall act."))
    after = sec(sub("e", "The Director shall act.", heading="Policymaking"))
    assert kind(pred, after, Context(pl="1-2", positive_law=False)) == "editorial"
    assert kind(pred, after, Context(pl="1-2", positive_law=True)) is None
    assert kind(pred, after, Context(pl="1-2")) is None                        # not known: not accepted
    renamed = sec(sub("e", "The Director shall act.", heading="Other"))
    assert kind(sec(sub("e", "The Director shall act.", heading="Policy")), renamed,
                Context(pl="1-2", positive_law=False)) is None                # a heading the law has, changed


def test_a_catchline_counts_as_olrc_s_unless_the_law_amends_a_heading():
    pred, after = sec(sub("a", "Text."), "Control of plant growths"), sec(sub("a", "Text."), "Control of plant growths "
                                                                                     "and invasive species")
    assert kind(pred, after, Context(pl="1-2", positive_law=False)) == "editorial"
    assert kind(pred, after, Context(pl="1-2", positive_law=False, heading_amended=True)) is None


def test_heading_case_and_closing_punctuation_are_style():
    pred = sec(sub("c", "Text.", heading="Period of validity"))
    after = sec(sub("c", "Text.", heading="Period of Validity").replace(".—</heading>", "</heading>"))
    assert kind(pred, after) == "editorial"


def test_a_repealed_placeholder_counts_only_when_it_cites_this_law():
    pred = sec(sub("e", "Text."))
    after = sec(sub("e", "Text.") + '<subsection identifier="/us/usc/t99/s1/f"><num value="f">(f)</num>'
                '<content>Repealed. Pub. L. 1–2, § 3(b), Jan. 17, 2014, 128 Stat. 424.</content></subsection>')
    assert kind(pred, after, Context(pl="1-2")) == "editorial"
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
