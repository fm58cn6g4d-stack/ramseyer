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


def test_an_instruction_runs_on_the_act_and_the_reading_compares_it_with_the_code(tmp_path):
    from ramseyer.dryrun.actside import reading, run_on_act
    from ramseyer.parse import parse_text
    build(tmp_path, {
        "COMPS-1.xml": comp("1", "<dc:title>Placeholder Act</dc:title><citableAs>Public Law 99–1</citableAs>"
                                 "<currentThroughPublicLaw>118–5</currentThroughPublicLaw>", "", SEC)})
    ix = Index(tmp_path / "c.sqlite", "comps")
    ins = parse_text("SEC. 2. AMENDMENT.\nSection 2(a) of the Placeholder Act (Public Law 99–1) is amended by "
                     "striking “beta” and inserting “delta”.\n").instructions[0]
    run = run_on_act(ins, ["pl:99-1"], ix)
    assert (run.status, run.identifier, run.currency) == ("CLEAN", "/us/sComp/99/1/s2", ["currentThroughPublicLaw: 118–5"])
    assert reading(run, "CLEAN")[0] == "both"
    assert reading(run, "NOT_FOUND")[0] == "act only"
    missing = parse_text("SEC. 2. AMENDMENT.\nSection 2(a) of the Placeholder Act (Public Law 99–1) is amended by "
                         "striking “omega” and inserting “delta”.\n").instructions[0]
    gone = run_on_act(missing, ["pl:99-1"], ix)
    assert gone.status == "NOT_FOUND" and reading(gone, "NOT_FOUND")[0] == "neither"
    assert reading(gone, "CLEAN")[0] == "code only" and "118–5" in reading(gone, "CLEAN")[1]
    nothing = run_on_act(ins, ["pl:99-7"], ix)
    assert nothing.status == "UNAVAILABLE" and "no compilation" in nothing.reason


def test_an_act_before_public_law_numbers_is_found_by_its_approval_date_and_chapter(tmp_path):
    from ramseyer.data.comps import files_for
    pre = '<citationNote>[<citableAs>Public Law 93–406</citableAs>]</citationNote>'
    ix, rp = build(tmp_path, {
        "COMPS-5.xml": comp("5", "<dc:title>Five</dc:title><approvedDate>1944-07-01</approvedDate>", "",
                            SEC.replace("/99/1/", "/78/410/")),
        "COMPS-6.xml": comp("6", "<dc:title>Six</dc:title><approvedDate>1944-07-01</approvedDate>"
                                 "<citableAs>Chapter 999 of the 78th Congress</citableAs>", "", SEC.replace("/99/1/", "/78/9/")),
        "COMPS-7.xml": comp("7", "<dc:title>Seven</dc:title>", pre, SEC.replace("/99/1/", "/93/406/"))})
    assert files_for(ix.db, rp, "act:1944-07-01:373", "Five") == ["comp5"]  # no chapter stated, name matches
    assert files_for(ix.db, rp, "act:1944-07-01:373", "Placeholder Health Act") == []   # a same-day Act: never taken
    assert files_for(ix.db, rp, "act:1944-07-01:373") == []                # no chapter and no name: not matched
    assert files_for(ix.db, rp, "act:1944-07-01:999") == ["comp6"]         # the chapter decides
    assert files_for(ix.db, rp, "pl:93-406") == ["comp7"]                 # citableAs only in the preface


def test_short_new_words_never_confirm_an_amendment():
    from ramseyer.dryrun.actside import confirmation
    text = "The Secretary shall act by 2026 and report on the placeholder program each year."
    assert confirmation("2026", text).startswith("its new words are too short")
    assert confirmation("“report on the placeholder program”", text) == "its new words are in the Act's section"
    assert confirmation("report on the other program", text).startswith("its new words are not found")
    assert confirmation(None, text) == "the instruction inserts no words to look for"
