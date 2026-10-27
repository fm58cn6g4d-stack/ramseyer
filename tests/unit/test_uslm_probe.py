import zipfile

import pytest

from billmap.data import uslm

# Synthetic structure only: placeholder text, no statute content.
DOC = """<?xml version="1.0" encoding="UTF-8"?>
<uscDoc xmlns="http://xml.house.gov/schemas/uslm/1.0" identifier="/us/usc/t99">
<meta><docPublicationName>Online@0-0</docPublicationName></meta>
<main><title identifier="/us/usc/t99">
<section identifier="/us/usc/t99/s1"><num>x</num></section>
<section identifier="/us/usc/t99/s2a-1"><num>x</num></section>
{extra}
</title></main></uscDoc>"""


def _zip(tmp_path, body):
    p = tmp_path / "t.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("usc99.xml", body)
    return p


def test_summary(tmp_path):
    s = uslm.summarize_title_zip(_zip(tmp_path, DOC.format(extra="")))
    assert (s.root_tag, s.title_identifier, s.publication, s.sections) == (
        "uscDoc", "/us/usc/t99", "Online@0-0", 2)
    assert s.malformed_ids == []


def test_malformed_identifier_reported(tmp_path):
    bad = '<section identifier="/us/usc/t99/ch1"><num>x</num></section>'
    s = uslm.summarize_title_zip(_zip(tmp_path, DOC.format(extra=bad)))
    assert s.malformed_ids == ["/us/usc/t99/ch1"]


def test_multiple_members_rejected(tmp_path):
    p = tmp_path / "t.zip"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("a.xml", DOC.format(extra=""))
        zf.writestr("b.xml", DOC.format(extra=""))
    with pytest.raises(ValueError, match="expected one XML member"):
        uslm.summarize_title_zip(p)
