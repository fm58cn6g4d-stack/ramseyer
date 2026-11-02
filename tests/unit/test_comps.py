"""M8a: Statute Compilations indexed as a second current-law source (synthetic files: structure only, placeholder text)."""
import zipfile

from ramseyer.data.comps import load_compilations
from ramseyer.data.index import Index
from ramseyer.data.indexer import Indexer

NS = "http://schemas.gpo.gov/xml/uslm"


def comp(file_id: str, meta: str, preface: str, body: str) -> str:
    return (f'<statuteCompilation xmlns="{NS}" xmlns:dc="http://purl.org/dc/elements/1.1/"><meta>{meta}</meta>'
            f'<preface>{preface}</preface><main>{body}</main></statuteCompilation>')


SEC = ('<section identifier="/us/sComp/99/1/s2"><num value="2">SEC. 2. </num><heading>PLACEHOLDER RULE.</heading>'
       '<subsection identifier="/us/sComp/99/1/s2/a"><num value="a">(a) </num><content>Alpha beta gamma.</content>'
       '</subsection></section>')


def build(tmp_path, files: dict[str, str]):
    z = tmp_path / "COMPS.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for name, xml in files.items():
            zf.writestr(name, xml)
    ix = Indexer(tmp_path / "c.sqlite")
    rp = load_compilations(ix, z, log=lambda s: None)
    ix.mark_complete(rp)
    return ix, rp


def test_a_compilation_section_is_found_by_its_own_identifier_with_its_currency(tmp_path):
    ix, rp = build(tmp_path, {
        "COMPS-1.xml": comp("1", "<dc:title>Placeholder Act</dc:title><citableAs>Public Law 99–1</citableAs>"
                                 "<currentThroughPublicLaw>118–5</currentThroughPublicLaw>", "", SEC)})
    node = Index(tmp_path / "c.sqlite", "comps").by_identifier("/us/sComp/99/1/s2/a")
    assert "Alpha beta gamma." in node.text
    assert ix.db.execute("SELECT currency FROM titles WHERE rp=?", (rp,)).fetchone()[0] == \
        "currentThroughPublicLaw: 118–5"


def test_currency_is_read_from_the_edition_note_or_reported_unknown(tmp_path):
    note = '<editionNote role="x">[As Amended Through P.L. 115–141, Enacted March 23, 2018]</editionNote>'
    ix, rp = build(tmp_path, {
        "COMPS-2.xml": comp("2", "<dc:title>Two</dc:title>", note, SEC.replace("/99/1/", "/99/2/")),
        "COMPS-3.xml": comp("3", "<dc:title>Three</dc:title>",
                            "<editionNote>[This law has not been amended]</editionNote>", SEC.replace("/99/1/", "/99/3/")),
        "COMPS-4.xml": comp("4", "<dc:title>Four</dc:title>", "", SEC.replace("/99/1/", "/99/4/"))})
    cur = dict(ix.db.execute("SELECT title, currency FROM titles WHERE rp=?", (rp,)).fetchall())
    assert cur == {"comp2": "edition note: P.L. 115–141, Enacted March 23, 2018",
                   "comp3": "unamended: the Act as enacted", "comp4": "unknown"}
