"""The USLM 1.x/2.x seam (uslm.to_v1): each 2.x construct indexes to the same text as its 1.0 form.

Synthetic placeholder text only. The real check is scripts/uslm2_check.py on OLRC's 2.0.12 sample titles.
"""
import sqlite3
import zipfile

from lxml import etree

from ramseyer.data import uslm
from ramseyer.data.indexer import Indexer, text_of

V1 = "http://xml.house.gov/schemas/uslm/1.0"
V2 = "http://schemas.gpo.gov/xml/uslm"
X = "http://www.w3.org/1999/xhtml"


def doc(ns: str, body: str) -> str:
    return (f'<uscDoc xmlns="{ns}" xmlns:xhtml="{X}" identifier="/us/usc/t99"><meta><docPublicationName>Online'
            f'</docPublicationName></meta><main><title identifier="/us/usc/t99"><num value="99">Title 99—</num>'
            f'<heading>PLACEHOLDER</heading><section identifier="/us/usc/t99/s1"><num value="1">§ 1.</num>'
            f'<heading> Alpha</heading>{body}</section></title></main></uscDoc>')


def section_text(xml: str) -> str:
    root = uslm.to_v1(etree.fromstring(xml.encode()))
    return text_of(next(root.iter(f"{{{V1}}}section")))


def test_schema_version():
    assert uslm.schema_version(etree.fromstring(doc(V1, "").encode())) == "1"
    assert uslm.schema_version(etree.fromstring(doc(V2, "").encode())) == "2"
    assert uslm.schema_version(etree.fromstring(b"<uscDoc/>")) is None


def test_v1_is_unchanged():
    root = etree.fromstring(doc(V1, "<content>Lorem.</content>").encode())
    assert uslm.to_v1(root) is root


def test_every_element_moves_to_the_v1_namespace():
    root = uslm.to_v1(etree.fromstring(doc(V2, "<content>Lorem <inline>ipsum</inline>.</content>").encode()))
    names = {etree.QName(e).namespace for e in root.iter() if isinstance(e.tag, str)}
    assert names == {V1}


def test_inline_footnote_is_left_out_like_a_1_0_footnote_note():
    v2 = doc(V2, '<content>Lorem,<ref class="footnoteRef" idref="fn1">1</ref><footnote><num><sup>1</sup></num>'
                 ' So in original.</footnote> ipsum.</content>')
    v1 = doc(V1, '<content>Lorem,<ref class="footnoteRef" idref="fn1">1</ref> ipsum.</content>'
                 '<note type="footnote"><num>1</num> So in original.</note>')
    assert section_text(v2) == section_text(v1)
    assert "So in original" not in section_text(v2)


def test_list_items_become_paragraphs():
    v2 = doc(V2, "<content><p>Lead—</p><list><listItem><listContent>first;</listContent></listItem>"
                 "<listItem><listContent>second.</listContent></listItem></list></content>")
    v1 = doc(V1, '<content><p>Lead—</p><p role="listItem">first;</p><p role="listItem">second.</p></content>')
    assert section_text(v2) == section_text(v1)


def test_loose_heading_and_cross_heading_become_lines():
    v2 = doc(V2, "<content>Described as follows:<heading>alpha meridian</heading><p>Township 1.</p></content>"
                 "<subsection identifier='/us/usc/t99/s1/a'><heading>FORMULA = A + B</heading><num value='a'>(a) "
                 "</num><content>Ipsum.</content></subsection>"
                 "<subsection identifier='/us/usc/t99/s1/b'><num value='b'>(b)</num><content>Dolor"
                 "<crossHeading>beta meridian</crossHeading></content></subsection>")
    text = section_text(v2)
    assert "Described as follows:\nalpha meridian\nTownship 1." in text
    assert "FORMULA = A + B\n(a)" in text
    assert "Dolor\nbeta meridian" in text
    root = uslm.to_v1(etree.fromstring(v2.encode()))
    sub_a = next(e for e in root.iter() if e.get("identifier") == "/us/usc/t99/s1/a")
    assert sub_a.find(f"{{{V1}}}heading") is None            # the formula is not (a)'s heading


def test_unit_heading_after_num_stays_a_heading():
    v2 = doc(V2, "<subsection identifier='/us/usc/t99/s1/a'><num value='a'>(a)</num><heading> In General.—</heading>"
                 "<content>Ipsum.</content></subsection>")
    root = uslm.to_v1(etree.fromstring(v2.encode()))
    sub_a = next(e for e in root.iter() if e.get("identifier") == "/us/usc/t99/s1/a")
    assert sub_a.find(f"{{{V1}}}heading") is not None


def test_table_caption_becomes_a_title_row():
    v2 = doc(V2, f"<content><xhtml:table><xhtml:caption>Schedule</xhtml:caption><xhtml:thead><xhtml:tr><xhtml:th>"
                 f"No.</xhtml:th></xhtml:tr></xhtml:thead><xhtml:tbody><xhtml:tr><xhtml:td>1</xhtml:td></xhtml:tr>"
                 f"</xhtml:tbody></xhtml:table></content>")
    text = section_text(v2)
    assert text.index("Schedule") < text.index("No.") < text.index("\n1")
    root = uslm.to_v1(etree.fromstring(v2.encode()))
    assert not list(root.iter(f"{{{X}}}caption"))


def test_indexer_reads_a_2x_title_and_logs_the_conversion(tmp_path):
    z = tmp_path / "rp.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("usc99.xml", doc(V2, "<content>Lorem ipsum.</content>"))
    ix = Indexer(tmp_path / "t.sqlite")
    rp = ix.load_release_point(z, "1-1", None, "test", log=lambda m: None)
    db = sqlite3.connect(tmp_path / "t.sqlite")
    assert db.execute("SELECT text_plain FROM nodes WHERE identifier='/us/usc/t99/s1'").fetchone()[0].endswith(
        "Lorem ipsum.")
    issues = db.execute("SELECT kind, detail FROM load_issues WHERE rp=?", (rp,)).fetchall()
    assert any(k == "uslm_schema" and "converted to 1.0" in d for k, d in issues)


def test_unknown_namespace_is_reported_not_indexed(tmp_path):
    z = tmp_path / "rp.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("usc99.xml", doc("http://example.org/other", "<content>Lorem.</content>"))
    ix = Indexer(tmp_path / "t.sqlite")
    rp = ix.load_release_point(z, "1-1", None, "test", log=lambda m: None)
    db = sqlite3.connect(tmp_path / "t.sqlite")
    kinds = {k for (k,) in db.execute("SELECT kind FROM load_issues WHERE rp=?", (rp,))}
    assert {"uslm_schema", "no_main"} <= kinds
