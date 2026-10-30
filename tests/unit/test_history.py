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
    assert placed == {"118-5not3": 2} and empty == [0, 4]          # the dataset numbers from 0
    assert "Lorem." in h.section_xml("/us/usc/t99/s1", "118-5not3")[0]


def test_a_title_not_loaded_at_a_release_point_carries_forward(tmp_path):
    # The dataset loads a title only where OLRC updated it; 118-9 here holds title 99 as of 118-5.
    h = History(tmp_path / "h.sqlite")
    h.load_rows([row("1", "Lorem.", ["118-1", "118-5"]), row("2", "Other title.", ["118-1", "118-9"])])
    h.db.execute("UPDATE versions SET title='98', identifier='/us/usc/t98/s2' WHERE identifier='/us/usc/t99/s2'")
    h.flush_release_map()
    assert "Lorem." in h.section_xml("/us/usc/t99/s1", "118-9")[0]
    assert h.section_xml("/us/usc/t99/s1", "118-9") == h.section_xml("/us/usc/t99/s1", "118-5")


def test_a_section_split_out_of_another_is_kept_out_and_its_parent_marked(tmp_path):
    # 25 U.S.C. 5329's model agreement ("SECTION 1.", /us/usc/t25/s1) is a separate row whose parent is a section.
    h = History(tmp_path / "h.sqlite")
    h.load_rows([row("1", "Lorem.", ["118-1"]), row("1", "Nested agreement.", ["118-1"], parent="/us/usc/t99/s2"),
                 row("2", "Host.", ["118-1"], seq=2)])
    h.flush_release_map()
    doc, n, notes = title_document(h, "99", "118-1")
    assert n == 2 and b"Nested agreement" not in doc
    rp = materialize(h, "118-1", ["99"], tmp_path / "ix.sqlite", log=lambda s: None)
    db = sqlite3.connect(tmp_path / "ix.sqlite")
    assert db.execute("SELECT detail FROM load_issues WHERE rp=? AND kind='history_incomplete'", (rp,)).fetchall() == \
        [("/us/usc/t99/s2",)]


def test_an_interrupted_shard_leaves_nothing_behind(tmp_path):
    # The loader commits a shard only with its completion marker (Codex, PR #5).
    h = History(tmp_path / "h.sqlite")
    h.load_rows([row("1", "Lorem.", ["118-1"])])
    h.flush_release_map(commit=False)
    h.db.close()                                                   # interrupted before the marker and the commit
    h = History(tmp_path / "h.sqlite")
    assert h.db.execute("SELECT count(*) FROM versions").fetchone()[0] == 0


def test_title_release_map_follows_later_loads(tmp_path):
    # A read before loading finishes must not freeze the derived title -> release map (Codex, PR #5).
    h = History(tmp_path / "h.sqlite")
    h.load_rows([row("1", "Lorem.", ["118-1", "118-5"])])
    h.flush_release_map()
    assert h.seq("118-5") == h.title_seq("99", "118-5")
    h.load_rows([row("1", "Lorem ipsum.", ["118-9"])])
    h.flush_release_map()
    assert h.title_seq("99", "118-9") == h.seq("118-9")
    assert "Lorem ipsum." in h.section_xml("/us/usc/t99/s1", "118-9")[0]


def test_a_cached_release_point_with_fewer_titles_is_rebuilt(tmp_path):
    # A release point built for one set must not serve a set that needs more titles there (Codex, PR #6).
    from ramseyer.oracle.history import ReleaseIndexes
    h = History(tmp_path / "h.sqlite")
    other = row("2", "Other title.", ["118-1"])
    other.update(identifier="/us/usc/t98/s2", title="98")
    other["xml"] = other["xml"].replace("/us/usc/t99/s2", "/us/usc/t98/s2")
    h.load_rows([row("1", "Lorem.", ["118-1"]), other])
    h.flush_release_map()
    ReleaseIndexes(h, {"118-1": ["99"]}, tmp_path / "cache", log=lambda s: None)("118-1")
    ix = ReleaseIndexes(h, {"118-1": ["98", "99"]}, tmp_path / "cache", log=lambda s: None)("118-1")
    assert {t for (t,) in ix.db.execute("SELECT title FROM titles")} == {"98", "99"}


def test_an_interrupted_materialization_is_rebuilt(tmp_path):
    # A run killed before the full-text step leaves a release point with nodes but no FTS rows; dropping it must
    # not ask FTS5 to delete rows it never indexed ("database disk image is malformed").
    h = history(tmp_path)
    path = tmp_path / "ix.sqlite"
    materialize(h, "118-5", ["99"], path, log=lambda s: None)
    db = sqlite3.connect(path)
    db.execute("INSERT INTO fts_nodes(fts_nodes) VALUES ('delete-all')")
    db.execute("UPDATE release_points SET complete=0")
    db.commit()
    db.close()
    rp = materialize(h, "118-5", ["99"], path, log=lambda s: None)
    db = sqlite3.connect(path)
    db.execute("INSERT INTO fts_nodes(fts_nodes) VALUES ('integrity-check')")
    hits = db.execute("SELECT rowid FROM fts_nodes WHERE fts_nodes MATCH 'dolor'").fetchall()
    assert hits == db.execute("SELECT id FROM nodes WHERE rp=? AND identifier='/us/usc/t99/s1'", (rp,)).fetchall()
