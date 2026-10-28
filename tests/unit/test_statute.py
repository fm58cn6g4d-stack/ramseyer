"""StatuteService on a synthetic two-release-point index (placeholder text only, no statute content)."""
import zipfile
from pathlib import Path

import pytest

from billmap.data.indexer import Indexer
from billmap.statute import StatuteService, call

NS = "http://xml.house.gov/schemas/uslm/1.0"


def title_xml(rp: str, s2_text: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<uscDoc xmlns="{NS}" identifier="/us/usc/t99">
<meta><docPublicationName>Online@{rp}</docPublicationName><property role="is-positive-law">no</property></meta>
<main><title identifier="/us/usc/t99"><num value="99">Title 99—</num><heading>PLACEHOLDER</heading>
<chapter identifier="/us/usc/t99/ch1"><num value="1">CHAPTER 1—</num><heading>ALPHA</heading>
<section identifier="/us/usc/t99/s1"><num value="1">§ 1.</num><heading> Alpha one</heading>
<subsection identifier="/us/usc/t99/s1/a"><num value="a">(a)</num><heading> In general</heading>
<content>In this chapter, the term “widget” means a placeholder. See <ref href="/us/usc/t99/s2">section 2 of this title</ref>.</content></subsection>
<subsection identifier="/us/usc/t99/s1/b"><num value="b">(b)</num><content>Lorem ipsum dolor.</content></subsection>
<sourceCredit>(<ref href="/us/pl/150/7/s301/a">Pub. L. 150–7, § 301(a)</ref>, <date date="2087-01-02">Jan. 2, 2087</date>.)</sourceCredit>
</section>
<section identifier="/us/usc/t99/s2"><num value="2">§ 2.</num><heading> Alpha two</heading><content>{s2_text}</content></section>
<section identifier="/us/usc/t99/s3...5" status="repealed"><num value="3">[§§ 3 to 5.</num><heading> Repealed]</heading></section>
<section identifier="/us/usc/t99/s6"><num value="6">§ 6.</num><heading> First six</heading><content>Ipsum <ref href="/us/usc/t99/s1/a">section 1(a)</ref>.</content></section>
<section identifier="/us/usc/t99/s6"><num value="6">§ 6.</num><heading> Second six</heading><content>Dolor.</content></section>
</chapter></title></main></uscDoc>"""


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    d = tmp_path_factory.mktemp("ix")
    db = d / "t.sqlite"
    ix = Indexer(db)
    for rp, text in (("1-1", "Sit amet."), ("1-2", "Sit amet consectetur.")):
        z = d / f"{rp}.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("usc99.xml", title_xml(rp, text))
        rp_id = ix.load_release_point(z, rp, None, "test", log=lambda s: None)
        ix.mark_complete(rp_id)
    return StatuteService(index_path=Path(db), release_point="1-2")


def test_every_result_carries_release_point(svc):
    for tool, kw in [("resolve_cite", {"citation": "99 U.S.C. 1(a)"}), ("get_section", {"citation": "99 USC 2"}),
                     ("cited_by", {"citation": "99 U.S.C. 2"}), ("search", {"query": "lorem"}),
                     ("coverage", {}), ("resolve_cite", {"citation": "99 U.S.C. 77"})]:
        assert call(svc, tool, **kw)["release_point"] == "1-2"


def test_resolve_exact_range_and_missing(svc):
    assert svc.resolve_cite("99 U.S.C. 1(b)")["identifier"] == "/us/usc/t99/s1/b"
    r = svc.resolve_cite("99 U.S.C. 4")
    assert r["matched"] == "within range /us/usc/t99/s3...5" and r["status"] == "repealed"
    e = call(svc, "resolve_cite", citation="99 U.S.C. 1(c)")
    assert e["error"] == "not_found" and "exists but has no unit (c)" in e["message"]


def test_duplicate_section_is_ambiguous_never_guessed(svc):
    assert call(svc, "get_section", citation="99 U.S.C. 6")["error"] == "ambiguous"


def test_cited_by_includes_refs_to_subunits(svc):
    got = svc.cited_by("99 U.S.C. 1")
    assert got["total"] == 0 or all(i["citing_section"] for i in got["cited_by"])
    got = svc.cited_by("99 U.S.C. 2")
    assert [i["citing_cite"] for i in got["cited_by"]] == ["99 U.S.C. 1(a)"]
    assert "section 2 of this title" in got["cited_by"][0]["sentence"]


def test_definitions_scope_and_act_to_code(svc):
    d = svc.definitions("99 U.S.C. 1")["definitions"]
    assert [(x["term"], x["scope_kind"], x["reason"]) for x in d] == [("widget", "chapter", "resolved")]
    from billmap.resolve.resolver import Resolver
    svc._resolvers = {"1-2": Resolver(svc.ix, {}, {})}        # offline: no popular names or tables
    a = svc.act_to_code("Pub. L. 150-7", "301(a)")
    assert (a["outcome"], a["cite"], a["verified"]) == ("CODIFIED", "99 U.S.C. 1", False)
    assert "single source: source credits only" in a["flags"]
    assert svc.act_to_code("150-7", "30")["outcome"] == "UNCODIFIED"


def test_changes_between_release_points(svc):
    c = svc.changes("99 U.S.C. 2", from_rp="1-1", to_rp="1-2")
    assert [x["identifier"] for x in c["changed"]] == ["/us/usc/t99/s2"]
    assert c["added"] == c["removed"] == []
    assert call(svc, "get_section", citation="99 U.S.C. 2", as_of="1-1")["text"].endswith("Sit amet.")


def test_out_of_range(svc):
    assert call(svc, "get_section", citation="99 U.S.C. 2", as_of="9-9")["error"] == "out_of_range"
    assert call(svc, "search", query="x", limit=0)["error"] == "out_of_range"
