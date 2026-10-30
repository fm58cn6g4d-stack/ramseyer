"""Bill XML rendering (parse/xmltext.py) on synthetic documents (placeholder text)."""
import pytest

from ramseyer.parse.xmltext import render, xml_counts

SECTION = ('<section><enum>1.</enum><header>Amendment</header><text>Section 1 of title 99, United States Code, is '
           'amended by striking <quote>alpha</quote> and inserting <quote>beta</quote>.</text></section>')


def test_a_joint_resolution_renders_like_a_bill(tmp_path):
    # Joint resolutions use <resolution>/<resolution-body> (H.J. Res. 124, 113th Congress).
    bill = tmp_path / "bill.xml"
    bill.write_text(f"<bill><legis-body>{SECTION}</legis-body></bill>")
    res = tmp_path / "res.xml"
    res.write_text(f"<resolution><resolution-body>{SECTION}</resolution-body></resolution>")
    assert render(res) == render(bill)
    assert "striking “alpha” and inserting “beta”" in render(res)
    assert xml_counts(res) == xml_counts(bill)


def test_a_document_with_no_body_is_an_error(tmp_path):
    p = tmp_path / "x.xml"
    p.write_text("<bill><form/></bill>")
    with pytest.raises(ValueError, match="no <legis-body> or <resolution-body>"):
        render(p)
