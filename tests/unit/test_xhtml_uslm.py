"""XHTML -> USLM converter on synthetic section markup (structure as OLRC prints it; placeholder text)."""
from ramseyer.data.indexer import text_of
from ramseyer.data.xhtml_uslm import NS, chunks, section_element

HEAD = ('<!-- documentid:99_1 --><!-- itempath:/990/CHAPTER 1/Sec. 1 -->'
        '<!-- field-start:head --><h3 class="section-head">&sect;1. Placeholder rule</h3><!-- field-end:head -->')


def convert(statute: str, extra: str = ""):
    page = HEAD + f"<!-- field-start:statute -->{statute}<!-- field-end:statute -->{extra}"
    return section_element(chunks(page)[0], "99")


def paths(sec):
    out = []
    for el in sec.iter():
        i = el.get("identifier") if isinstance(el.tag, str) else None
        if i and i != "/us/usc/t99/s1":
            out.append(i.rsplit("/s1/", 1)[1])
    return out


def test_inline_headings_and_flush_paragraphs():
    sec = convert('<p class="statutory-body">(a) <cap-smallcap>Alpha</cap-smallcap>.&mdash;The board&mdash;</p>'
                  '<p class="statutory-body-1em">(1) shall act; and</p>'
                  '<p class="statutory-body-1em">(2) shall report.</p>'
                  '<p class="statutory-body">(b)(1) The first rule.</p>'
                  '<p class="statutory-body">(2) The second rule.</p>')
    assert paths(sec) == ["a", "a/1", "a/2", "b", "b/1", "b/2"]
    a = sec.find(f"{NS}subsection")
    assert "".join(a.find(f"{NS}heading").itertext()) == " Alpha.—"
    assert a.find(f"{NS}chapeau").text == "The board—"


def test_h4_headings_and_first_child_paragraph():
    sec = convert('<h4 class="subsection-head">(a) In general</h4><p class="statutory-body">Text of (a).</p>'
                  '<h4 class="subsection-head">(b) Rules</h4><p class="statutory-body">(1) The first rule.</p>'
                  '<p class="statutory-body">(2) The second rule.</p>')
    assert paths(sec) == ["a", "b", "b/1", "b/2"]


def test_roman_after_h_by_indentation():
    sec = convert('<p class="statutory-body">(h) Text of (h)&mdash;</p>'
                  '<p class="statutory-body-1em">(1) Lead&mdash;</p>'
                  '<p class="statutory-body-2em">(A) Lead&mdash;</p>'
                  '<p class="statutory-body-3em">(i) a clause; and</p>'
                  '<p class="statutory-body-3em">(ii) another clause.</p>'
                  '<p class="statutory-body">(i) Text of subsection (i).</p>')
    assert paths(sec) == ["h", "h/1", "h/1/A", "h/1/A/i", "h/1/A/ii", "i"]


def test_continuation_after_a_list_belongs_to_the_chained_unit():
    sec = convert('<p class="statutory-body">(a)(1) A carrier may not&mdash;</p>'
                  '<p class="statutory-body-1em">(A) abandon a line; or</p>'
                  '<p class="statutory-body-1em">(B) discontinue service,</p>'
                  '<p class="statutory-body-block">unless it files an application.</p>'
                  '<p class="statutory-body">(2) The second rule.</p>')
    one = sec.find(f"{NS}subsection").find(f"{NS}paragraph")
    assert "unless it files" in text_of(one.find(f"{NS}continuation"))
    assert paths(sec) == ["a", "a/1", "a/1/A", "a/1/B", "a/2"]


def test_footnotes_repealed_stub_and_section_sign_spacing():
    sec = convert('<p class="statutory-body">(a) Under section 5&#160;<sup><a href="#1_1_target" name="1_1">1</a>'
                  '</sup> of this title and &sect;12.</p><p class="statutory-body">[(b) Repealed.]</p>'
                  '<p class="statutory-body">(c) Text.</p>',
                  '<!-- field-start:footnote --><p class="footnote"><a href="#1_1" name="1_1_target"><sup>1</sup>'
                  '&#160;So in original.</a></p><!-- field-end:footnote -->')
    assert paths(sec) == ["a", "b", "c"]
    ref = sec.find(f".//{NS}ref")
    assert ref.get("class") == "footnoteRef" and ref.text == "1"
    assert "§ 12" in text_of(sec)
    assert sec.find(f"{NS}subsection[2]/{NS}num").text == "[(b)"
