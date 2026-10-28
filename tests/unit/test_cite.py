import pytest

from billmap.data import cite


def test_parse_variants():
    for text in ["49 U.S.C. 24101(a)(2)", "49 USC § 24101(a)(2)", "49 U.S.C. § 24101(a)(2)"]:
        c = cite.parse(text)
        assert c.identifier == "/us/usc/t49/s24101/a/2"


def test_hyphen_becomes_en_dash_and_back():
    c = cite.parse("42 U.S.C. 1395w-22")
    assert c.section_identifier == "/us/usc/t42/s1395w–22"
    assert str(c) == "42 U.S.C. 1395w-22"


def test_appendix_and_round_trip():
    c = cite.from_identifier("/us/usc/t5a/s1/b")
    assert str(c) == "5 App. U.S.C. 1(b)"
    assert cite.parse(str(c)) == c


def test_rejects_non_cites():
    with pytest.raises(cite.CiteError):
        cite.parse("section 301 of the Infrastructure Investment and Jobs Act")
    with pytest.raises(cite.CiteError):
        cite.from_identifier("/us/usc/t18a/pl/91/538/s1")
