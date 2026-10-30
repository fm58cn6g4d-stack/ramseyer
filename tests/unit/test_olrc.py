from pathlib import Path

import pytest

from ramseyer.data import olrc

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


def test_classification_table_json_layout():
    # The other layout (118th Congress tables): records in a script array, synthetic values.
    page = ('<html><table id="ctHTMLTable"></table><script>var statVolume = "1";\nvar ctRecords = [\n'
            '{"usctitle": "99", "uscsection": "101", "uscdescription": "", "publiclaw": "118-63", '
            '"publiclawsection": "201(a)", "statutesatlargepage": "1001", "dateofenactment": "05/16/2024"},\n'
            '{"usctitle": "99", "uscsection": "102", "uscdescription": "nt new", "publiclaw": "118-63", '
            '"publiclawsection": "1", "statutesatlargepage": "1000", "dateofenactment": "05/16/2024"}\n];\n'
            'var other = [1];</script></html>')
    rows = olrc.parse_classification_table(page)
    assert [(r.title, r.section, r.description, r.public_law, r.law_section) for r in rows] == [
        ("99", "101", "", "118-63", "201(a)"), ("99", "102", "nt new", "118-63", "1")]


def test_classification_fields_running_into_the_next_column():
    # Older tables (113th-117th Congress) let fields run over, and list several pages (synthetic values).
    page = ("<PRE>\n U. S. Code\nTitle Section      Description      Pub. L.  Sec.                  127 Stat.\n"
            "-------------      -----------      -------------                  ---------\n"
            "99    4016                          113-1   1(a)                     3          \n"
            "99A   105          nt repealed EG Act113-7   1(a)(3)                  438\n"
            "99    1308-3a                       113-79   1605(a)-(e)              707,708\n"
            "99    7181         tr to 99/7971    114-95   4001(a)(4)(A), (B), (C)(ii)1966\n"
            "99    1395m                         119-4    2207(a)-(e)              43, 44\n"
            "99    320101       nt ed chg        119-25                            408\n</PRE>")
    rows = olrc.parse_classification_table(page)
    assert [(r.public_law, r.description, r.law_section, r.stat_page) for r in rows] == [
        ("113-1", "", "1(a)", "3"),
        ("113-7", "nt repealed EG Act", "1(a)(3)", "438"),
        ("113-79", "", "1605(a)-(e)", "707,708"),
        ("114-95", "tr to 99/7971", "4001(a)(4)(A), (B), (C)(ii)", "1966"),
        ("119-4", "", "2207(a)-(e)", "43, 44"),
        ("119-25", "nt ed chg", "", "408")]
