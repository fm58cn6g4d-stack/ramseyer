"""The release-point history store and materializer (oracle/history.py), on synthetic rows (placeholder text)."""
import sqlite3

from ramseyer.oracle.history import History, materialize, title_document

V1 = "http://xml.house.gov/schemas/uslm/1.0"
V2 = "http://schemas.gpo.gov/xml/uslm"


def sec(ns: str, num: str, text: str) -> str:
    return (f'<section xmlns="{ns}" identifier="/us/usc/t99/s{num}"><num value="{num}">§ {num}.</num>'
            f'<heading> Placeholder {num}</heading><content>{text}</content></section>')


def row(num, text, releases, ns=V1, parent="/us/usc/t99/ch1", seq=1):
    first, last = releases[0], releases[-1]
    seqs = {"118-1": 1, "118-5not3": 2, "118-5": 3, "118-9": 4}
    return {"identifier": f"/us/usc/t99/s{num}", "title": "99", "title_is_positive_law": False, "num_value": num,
            "heading": f"Placeholder {num}", "status": None, "xml": sec(ns, num, text), "source_credit": None,
            "content_hash": f"{num}:{text}", "uslm_version": "2" if ns == V2 else "1",
            "first_release": first, "first_release_seq": seqs[first], "first_currency_date": None,
            "last_release": last, "last_release_seq": seqs[last], "last_currency_date": None,
            "releases": releases, "identifier_collision": False, "parent_identifier": parent, "seq_in_title": seq}


def history(tmp_path):
    h = History(tmp_path / "h.sqlite")
    h.load_rows([
        row("1", "Lorem ipsum.", ["118-1", "118-5not3"]),
        row("1", "Lorem ipsum dolor.", ["118-5"], ns=V2),          # a 2.x text from 118-5 on
        row("1", "Lorem ipsum.", ["118-9"]),                       # the first text again (a recurrence)
        row("2", "Sit amet.", ["118-1", "118-5not3", "118-5", "118-9"], seq=2),
    ])
    assert h.flush_release_map() == []
    return h


def test_releases_in_publication_order(tmp_path):
    h = history(tmp_path)
    assert [r.label for r in h.releases()] == ["118-1", "118-5not3", "118-5", "118-9"]


def test_section_at_a_release_point(tmp_path):
    h = history(tmp_path)
    assert "Lorem ipsum.<" in h.section_xml("/us/usc/t99/s1", "118-5not3")[0]
    assert "dolor" in h.section_xml("/us/usc/t99/s1", "118-5")[0]
    assert "dolor" not in h.section_xml("/us/usc/t99/s1", "118-9")[0]
    assert h.section_xml("/us/usc/t99/s3", "118-5") == []


def test_title_document_nests_sections_under_their_chapter(tmp_path):
    h = history(tmp_path)
    doc, n, notes = title_document(h, "99", "118-5")
    assert n == 2 and notes == []
    assert b'<chapter identifier="/us/usc/t99/ch1">' in doc
    assert V2.encode() not in doc                                   # the 2.x section was converted


def test_materialized_release_point_reads_like_an_index(tmp_path):
    h = history(tmp_path)
    rp = materialize(h, "118-5", ["99"], tmp_path / "ix.sqlite", log=lambda s: None)
    db = sqlite3.connect(tmp_path / "ix.sqlite")
    text = db.execute("SELECT text_plain FROM nodes WHERE rp=? AND identifier='/us/usc/t99/s1'", (rp,)).fetchone()[0]
    assert text.endswith("Lorem ipsum dolor.")
    kinds = dict(db.execute("SELECT identifier, kind FROM nodes WHERE rp=?", (rp,)).fetchall())
    assert kinds["/us/usc/t99/ch1"] == "chapter" and kinds["/us/usc/t99/s2"] == "section"
    assert materialize(h, "118-5", ["99"], tmp_path / "ix.sqlite", log=lambda s: None) == rp   # reused


def test_a_label_never_first_or_last_is_placed_in_its_gap(tmp_path):
    # 118-22u1 and 118-40 are in the dataset only inside release lists; their sequence comes from the order rule.
    h = History(tmp_path / "h.sqlite")
    r = row("1", "Lorem.", ["118-1", "118-5"])
    r["releases"] = ["118-1", "118-5not3", "118-5"]
    h.load_rows([r])
    assert h.flush_release_map() == ["118-5not3"]
    placed, empty = h.place_unsequenced(4)
    assert placed == {"118-5not3": 2} and empty == [4]
    assert "Lorem." in h.section_xml("/us/usc/t99/s1", "118-5not3")[0]
