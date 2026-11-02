"""M8: the redline is built from the engine's edits; stripping its marks gives back each side's text
(synthetic section: structure only, placeholder text)."""
import re

from ramseyer.comparative.redline import blocks, changed, redline, strip
from ramseyer.data.indexer import text_of
from ramseyer.dryrun.engine import Engine, Working
from ramseyer.parse import parse_text

NS = "http://xml.house.gov/schemas/uslm/1.0"
XML = f"""<section xmlns="{NS}" identifier="/us/usc/t99/s1"><num value="1">§ 1.</num><heading> Placeholder</heading>
<subsection identifier="/us/usc/t99/s1/a"><num value="a">(a)</num><heading> Alpha Rule.—</heading>
<content>The determiner shall review each term. Reviews shall be made at least annually.</content></subsection>
<subsection identifier="/us/usc/t99/s1/b"><num value="b">(b)</num><content>The board may issue rules.</content>
</subsection>
<subsection identifier="/us/usc/t99/s1/c"><num value="c">(c)</num><content>The board shall report.</content>
</subsection></section>"""


def run(draft: str):
    work = Working(XML, "/us/usc/t99/s1", positive_law=True)
    eng = Engine(work)
    for i in parse_text("SEC. 2. AMENDMENTS.\n" + draft + "\n").instructions:
        eng.run(i, list(i.target.path))
    return work, redline(work.original, work.el)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def test_stripping_the_marks_gives_back_both_sides():
    work, red = run("Section 1 of title 99, United States Code, is amended—\n"
                    "(1) in subsection (a), by striking “annually” and inserting “quarterly”;\n"
                    "(2) by striking subsection (b); and\n"
                    "(3) by adding at the end the following:\n"
                    "“(d) Delta rule.—The board shall publish.”.")
    assert flat(strip(red, "before")) == flat(text_of(work.original))
    assert flat(strip(red, "after")) == flat(text_of(work.el))
    assert changed(red)


def test_an_edit_is_shown_in_the_block_it_touched():
    work, red = run("Section 1(a) of title 99, United States Code, is amended by striking “annually” and inserting "
                    "“quarterly”.")
    edited = [b for b in blocks(red) if any(r.state != "same" for r in b.runs)]
    assert len(edited) == 1 and edited[0].kind == "content"
    assert [(r.state, r.text) for r in edited[0].runs if r.state != "same"] == [("del", "annually"),
                                                                             ("ins", "quarterly")]


def test_a_unit_removed_or_added_whole_is_marked_whole():
    work, red = run("Section 1 of title 99, United States Code, is amended—\n"
                    "(1) by striking subsection (b); and\n"
                    "(2) by adding at the end the following:\n"
                    "“(d) Delta rule.—The board shall publish.”.")
    states = [(u.kind, u.state) for u in red.items if hasattr(u, "items")]
    assert ("subsection", "del") in states and ("subsection", "ins") in states
    assert not changed(redline(work.original, work.original))


def test_the_print_marks_omitted_text_in_brackets_and_new_matter_in_italics():
    from types import SimpleNamespace
    from ramseyer.comparative.html import report
    work, _ = run("Section 1(a) of title 99, United States Code, is amended by striking “annually” and inserting "
                  "“quarterly”.")
    page = report(SimpleNamespace(working={"/us/usc/t99/s1": work}, traces=[]), title="Placeholder Act",
                  release_point="1-1", input_hash="0" * 64, generated="2026-11-02", version="0")
    assert '<del><b class="br">[</b>annually<b class="br">]</b></del><ins>quarterly</ins>' in page
    assert "99 U.S.C. 1" in page and "black brackets" in page
    working = report(SimpleNamespace(working={"/us/usc/t99/s1": work}, traces=[]), title="t", release_point="1-1",
                     input_hash="0" * 64, generated="g", version="0", style="working")
    assert "<del>annually</del><ins>quarterly</ins>" in working
    assert "* * *" in page                       # subsections (b) and (c) are untouched and elided past the context


def test_the_word_print_carries_real_brackets_and_italics():
    import io
    from types import SimpleNamespace
    from docx import Document
    from ramseyer.comparative.word import document
    work, _ = run("Section 1(a) of title 99, United States Code, is amended by striking “annually” and inserting "
                  "“quarterly”.")
    data = document(SimpleNamespace(working={"/us/usc/t99/s1": work}, traces=[]), title="Placeholder Act",
                    release_point="1-1", input_hash="0" * 64, generated="g", version="0")
    runs = [r for p in Document(io.BytesIO(data)).paragraphs for r in p.runs]
    assert any(r.text == "quarterly" and r.italic for r in runs)
    i = next(i for i, r in enumerate(runs) if r.text == "annually")
    assert runs[i - 1].text == "[" and runs[i - 1].bold and runs[i + 1].text == "]"


def test_text_set_after_a_child_unit_is_part_of_the_redline():
    # 42 U.S.C. 1395cc-7 (Pub. L. 119-75): a sentence added after the last paragraph, inside the subsection.
    import copy
    from lxml import etree
    from ramseyer.comparative.redline import tag
    before = etree.fromstring(f'<subsection xmlns="{NS}"><num>(a)</num><paragraph><num>(1)</num><content>Alpha.'
                              f'</content></paragraph></subsection>')
    tag(before)
    after = copy.deepcopy(before)
    after.find(f"{{{NS}}}paragraph").tail = "The board may act."
    red = redline(before, after)
    assert flat(strip(red, "after")).endswith("The board may act.") and "board" not in strip(red, "before")


def test_a_unit_removed_whole_is_bracketed_once():
    from types import SimpleNamespace
    from ramseyer.comparative.html import report
    work, _ = run("Section 1 of title 99, United States Code, is amended by striking subsection (b).")
    page = report(SimpleNamespace(working={"/us/usc/t99/s1": work}, traces=[]), title="t", release_point="1-1",
                  input_hash="0" * 64, generated="g", version="0")
    assert page.count('<b class="br">[</b>') == 1 and page.count('<b class="br">]</b>') == 1
    assert '<del><b class="br">[</b>(b)</del> <del>The board may issue rules.<b class="br">]</b></del>' in page


def test_a_unit_replaced_whole_is_compared_word_by_word_with_the_one_it_replaces():
    # Committee reports print "amended to read as follows" as a word-level comparison with the old unit (part 2,
    # H.R. 6498): a removed and an added unit with the same designation are paired.
    work, red = run("Section 1 of title 99, United States Code, is amended by striking subsection (b) and inserting "
                    "the following:\n“(b) The board may issue binding rules.”.")
    runs = [(r.state, r.text) for b in blocks(red) for r in b.runs if r.state != "same"]
    assert runs == [("ins", "binding ")] or runs == [("ins", " binding")]
    assert flat(strip(red, "before")) == flat(text_of(work.original))
    assert flat(strip(red, "after")) == flat(text_of(work.el))
