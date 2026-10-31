"""GPO's reading of a public law's USLM (parse/gpo.py), on a synthetic law (placeholder text)."""
from ramseyer.parse.gpo import loc_of, readings, section_of

NS = "http://schemas.gpo.gov/xml/uslm"


def test_bill_locations_map_to_ramseyer_s():
    assert loc_of("/us/pl/113/66/dA/tV/stI/s581/a/1") == "divA.titleV.subtI.sec581.a.1"
    assert loc_of("/us/pl/1/2/s3/s/1") == "sec3.s.1"          # a unit labelled (s) under a section


def test_readings_inherit_the_code_citation_and_skip_quoted_matter(tmp_path):
    p = tmp_path / "law.xml"
    p.write_text(
        f'<pLaw xmlns="{NS}"><main><section identifier="/us/pl/1/2/s5"><num value="5">SEC. 5.</num>'
        '<subsection identifier="/us/pl/1/2/s5/a"><chapeau><ref href="/us/usc/t99/s1/a">Section 1(a) of title 99</ref>'
        ', <amendingAction type="amend">is amended</amendingAction>—</chapeau>'
        '<paragraph identifier="/us/pl/1/2/s5/a/1"><content>by <amendingAction type="delete">striking</amendingAction> '
        '“<quotedText>alpha</quotedText>”;</content></paragraph>'
        '<paragraph identifier="/us/pl/1/2/s5/a/2"><content>by <amendingAction type="add">adding</amendingAction> at the '
        'end:<quotedContent><paragraph><content>(3) see <ref href="/us/usc/t98/s7">section 7</ref>, '
        '<amendingAction type="insert">inserted</amendingAction></content></paragraph></quotedContent></content>'
        '</paragraph></subsection></section></main></pLaw>')
    r = readings(p)
    assert (r["sec5.a"].verbs, r["sec5.a"].usc) == (["amend"], ["/us/usc/t99/s1/a"])
    assert (r["sec5.a.1"].verbs, r["sec5.a.1"].usc) == (["delete"], ["/us/usc/t99/s1/a"])
    assert (r["sec5.a.2"].verbs, r["sec5.a.2"].usc) == (["add"], ["/us/usc/t99/s1/a"])   # not the quoted ref or verb
    assert section_of("/us/usc/t99/s1/a") == "/us/usc/t99/s1"
