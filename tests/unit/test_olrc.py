from pathlib import Path

import pytest

from billmap.data import olrc

FIX = Path(__file__).parent / "fixtures"
BASE = "https://uscode.house.gov/download.html"


def test_release_point_label_date_and_links():
    rp = olrc.parse_release_point((FIX / "olrc_download_excerpt.html").read_text(), BASE)
    assert rp.label == "119-134"
    assert rp.date == "October 20, 2026"
    assert rp.xml_all == "https://uscode.house.gov/download/releasepoints/us/pl/119/134/xml_uscAll@119-134.zip"
    assert set(rp.xml_titles) == {"04", "05a"}
    assert rp.xml_titles["04"].endswith("/119/134/xml_usc04@119-134.zip")


def test_release_point_rejects_links_from_another_release():
    page = (FIX / "olrc_download_excerpt.html").read_text().replace(
        "xml_usc04@119-134", "xml_usc04@119-133")
    with pytest.raises(ValueError, match="does not match release point"):
        olrc.parse_release_point(page, BASE)


def test_release_point_missing_heading_fails_loud():
    with pytest.raises(ValueError, match="heading not found"):
        olrc.parse_release_point("<html><body><p>moved</p></body></html>", BASE)


def test_classification_rows():
    rows = olrc.parse_classification_table((FIX / "olrc_classification_excerpt.html").read_text())
    assert [r.public_law for r in rows] == ["119-70", "119-70", "119-74", "119-75", "119-83", "119-60"]
    assert rows[0] == olrc.ClassificationRow("42", "5301", "nt new", "119-70", "1", "3")
    assert rows[1].description == ""            # amended
    assert rows[2].law_section == ""            # no law section printed
    assert rows[3].law_section == '113(a) "[12]"'
    assert rows[4].stat_page == "762-764"
    assert rows[5].law_section == '7201(c)(1) "Subchapter I"'
    assert rows[5].stat_page == "1677"


def test_classification_unknown_line_fails_loud():
    page = (FIX / "olrc_classification_excerpt.html").read_text().replace(
        "119-70   2 ", "11970    2 ")
    with pytest.raises(ValueError, match="unparsed classification line"):
        olrc.parse_classification_table(page)
