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


def test_act_level_structure_is_followed_in_bill_order(tmp_path):
    """Redesignations take effect together, a later instruction naming the new number edits the renumbered section,
    a struck section is shown removed, and an old number no section has taken is reported, never guessed."""
    from ramseyer.comparative.redline import strip
    from ramseyer.comparative.html import views
    from ramseyer.dryrun.actside import run_bill_on_acts, structural
    from ramseyer.parse import parse_text
    secs = "".join(SEC.replace("s2", f"s{n}").replace('value="2">SEC. 2.', f'value="{n}">SEC. {n}.') for n in (2, 3, 5))
    build(tmp_path, {"COMPS-1.xml": comp("1", "<dc:title>Placeholder Act</dc:title><citableAs>Public Law 99–1"
                                              "</citableAs>", "", secs)})
    ix = Index(tmp_path / "c.sqlite", "comps")
    edit = parse_text("SEC. 2. AMENDMENT.\nSection 3(a) of the Placeholder Act (Public Law 99–1) is amended by "
                      "striking “beta” and inserting “delta”.\n").instructions[0]
    base = edit.target.model_copy(update={"section": None, "path": []})

    def struct(i, words):
        return edit.model_copy(update={"id": f"s{i}", "op": "UNPARSED", "source_text": words, "target": base})
    bill = [struct(1, "by redesignating sections 2 and 3 as sections 3 and 4, respectively;"),
            edit,                                                  # section 3 is now the old section 2
            struct(2, "by striking section 5; and"),
            edit.model_copy(update={"id": "late", "target": edit.target.model_copy(update={"section": "2"})})]
    assert structural(bill[0].source_text) == ("redesignate", "section", [("2", "3"), ("3", "4")], None)
    act = run_bill_on_acts(bill, lambda i: ["pl:99-1"], ix)
    by = {tr.instruction.id: tr for tr in act.traces if tr.instruction.id != "s1"}
    assert by[edit.id].section == "/us/sComp/99/1/s2" and by[edit.id].result.status == "CLEAN"
    assert act.working["/us/sComp/99/1/s5"].removed
    assert "formerly section 2" in act.labels["/us/sComp/99/1/s2"]
    assert [u.instruction_id for u in act.unplaced] == ["late"] and "redesignated earlier" in act.unplaced[0].reason
    v = {x.identifier: x for x in views(act)}["/us/sComp/99/1/s2"]
    assert "SEC. 3." in strip(v.tree, "after") and "SEC. 2." in strip(v.tree, "before")
    assert "delta" in strip(v.tree, "after")


def test_structural_reads_only_whole_section_and_title_changes():
    from ramseyer.dryrun.actside import structural
    assert structural("by redesignating sections 701 through 703 as sections 301 through 303, respectively;") == \
        ("redesignate", "section", [("701", "301"), ("702", "302"), ("703", "303")], None)
    assert structural("by redesignating section 107 as section 204 and transferring such section so as to appear "
                      "after section 303; and") == ("redesignate", "section", [("107", "204")], "303")
    assert structural("by redesignating title VII as title III;") == ("redesignate", "title", [("VII", "III")], None)
    assert structural("striking section 714 and 723;") == ("strike", "section", ["714", "723"])
    assert structural("by striking section 3 and inserting the following:") is None
    assert structural("by redesignating sections 2 and 3 as section 4;") is None       # counts differ: not guessed
    assert structural("by redesignating sections 2A through 2C as sections 3A through 3C") is None


def test_structure_regressions_from_review_of_26(tmp_path):
    """(1) a number redesignated away is not struck under its old name; (2) a partly placed structural instruction is
    not CLEAN and says what was not placed; (3) an edit to a struck section is not applied."""
    from ramseyer.dryrun.actside import run_bill_on_acts, structural
    from ramseyer.parse import parse_text
    secs = "".join(SEC.replace("s2", f"s{n}").replace('value="2">SEC. 2.', f'value="{n}">SEC. {n}.') for n in (2, 3))
    build(tmp_path, {"COMPS-1.xml": comp("1", "<dc:title>Placeholder Act</dc:title><citableAs>Public Law 99–1"
                                              "</citableAs>", "", secs)})
    ix = Index(tmp_path / "c.sqlite", "comps")
    edit = parse_text("SEC. 2. AMENDMENT.\nSection 3(a) of the Placeholder Act (Public Law 99–1) is amended by "
                      "striking “beta” and inserting “delta”.\n").instructions[0]
    base = edit.target.model_copy(update={"section": None, "path": []})

    def struct(i, words):
        return edit.model_copy(update={"id": i, "op": "UNPARSED", "source_text": words, "target": base})
    bill = [struct("r", "by redesignating section 2 as section 4;"),
            struct("s2", "by striking section 2;"),                         # (1): 2 is gone; 4 must stay
            struct("part", "by striking sections 3 and 9;"),                # (2): 3 struck, 9 does not exist
            edit]                                                            # (3): section 3 was struck
    act = run_bill_on_acts(bill, lambda i: ["pl:99-1"], ix)
    s2 = "/us/sComp/99/1/s2"
    assert not act.working[s2].removed
    assert [u.instruction_id for u in act.unplaced] == ["s2"] and "redesignated earlier" in act.unplaced[0].reason
    part = next(tr for tr in act.traces if tr.instruction.id == "part")
    assert part.result.status == "WARN" and "section 9" in part.result.detail
    last = act.traces[-1]
    assert last.instruction.id == edit.id and last.result.status == "TARGET_MISSING"
    assert structural("by redesignating title III as title II and inserting after title I the following:") is None


def test_sections_the_bill_adds_to_an_act_are_shown_new_and_edited_later(tmp_path):
    from ramseyer.comparative.html import views
    from ramseyer.comparative.redline import strip
    from ramseyer.dryrun.actside import run_bill_on_acts
    from ramseyer.parse import parse_text
    build(tmp_path, {"COMPS-1.xml": comp("1", "<dc:title>Placeholder Act</dc:title><citableAs>Public Law 99–1"
                                              "</citableAs>", "", SEC)})
    ix = Index(tmp_path / "c.sqlite", "comps")
    edit = parse_text("SEC. 2. AMENDMENT.\nSection 3(a) of the Placeholder Act (Public Law 99–1) is amended by "
                      "striking “beta” and inserting “delta”.\n").instructions[0]
    add = edit.model_copy(update={"id": "add", "op": "ADD_UNIT_AFTER", "find": None, "replace": None,
                                  "new_text": "“SEC. 3. PLACEHOLDER ADDITION.\n“(a) Alpha beta gamma.”",
                                  "target": edit.target.model_copy(update={"section": None, "path": []})})
    again = add.model_copy(update={"id": "again"})                  # adding a section the Act now has: reported
    act = run_bill_on_acts([add, edit, again], lambda i: ["pl:99-1"], ix)
    ident = "/us/sComp/new/comp1/s3"
    assert [tr.section for tr in act.traces] == [ident, ident] and act.traces[1].result.status == "CLEAN"
    assert act.working[ident].original is None
    assert [u.instruction_id for u in act.unplaced] == ["again"] and "already has" in act.unplaced[0].reason
    v = {x.identifier: x for x in views(act)}[ident]
    assert v.new and "delta" in strip(v.tree, "after")
