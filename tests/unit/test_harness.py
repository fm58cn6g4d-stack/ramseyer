"""Harness on a synthetic corpus: one placeholder law that changes § 2 and adds § 3."""
import zipfile

import pytest

from ramseyer.data.index import Index
from ramseyer.data.indexer import Indexer
from ramseyer.oracle import harness
from ramseyer.oracle.corpus import ClassifiedRow, Corpus, CorpusLaw
from ramseyer.oracle.harness import Prediction

NS = "http://xml.house.gov/schemas/uslm/1.0"


def doc(sections: str) -> str:
    return (f'<uscDoc xmlns="{NS}" identifier="/us/usc/t99"><main><title identifier="/us/usc/t99">'
            f'<num value="99">Title 99</num><heading>X</heading>{sections}</title></main></uscDoc>')


def sec(n: str, text: str) -> str:
    return (f'<section identifier="/us/usc/t99/s{n}"><num value="{n}">§ {n}.</num><heading> H{n}</heading>'
            f'<content>{text}</content></section>')


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    d = tmp_path_factory.mktemp("o")
    db = d / "o.sqlite"
    ix = Indexer(db)
    for label, body in (("1-1", sec("1", "Alpha.") + sec("2", "Beta gamma.")),
                        ("1-2", sec("1", "Alpha.") + sec("2", "Beta “delta”.") + sec("3", "New text."))):
        z = d / f"{label}.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("usc99.xml", doc(body))
        ix.mark_complete(ix.load_release_point(z, label, None, "t", log=lambda s: None))
    law = CorpusLaw(pl="1-2", name="t", bill="1 hr 1", enrolled_url="x", enrolled_sha256="x", rp_before="1-1",
                    rp_after="1-2", titles=["99"], reason="t",
                    rows=[ClassifiedRow(title="99", section="2", description="", law_section="1"),
                          ClassifiedRow(title="99", section="3", description="new", law_section="2"),
                          ClassifiedRow(title="99", section="1", description="nt", law_section="3")])
    corpus = Corpus(built="t", selection="t", release_points=[], laws=[law])
    return corpus, (lambda label: Index(db, label))


def run(setup, fn):
    corpus, open_index = setup
    return harness.evaluate(corpus, fn, "t", open_index, labels={}).metrics


def test_notes_are_not_targets(setup):
    corpus, open_index = setup
    t = harness.truth(corpus.laws[0], open_index("1-1"), open_index("1-2"))
    assert set(t) == {"/us/usc/t99/s2", "/us/usc/t99/s3"}
    assert t["/us/usc/t99/s3"]["before_status"] == "absent" and t["/us/usc/t99/s2"]["changed"]


def test_perfect_prediction_ignores_quote_and_space_style(setup):
    def p(law, before):
        return [Prediction(identifier="/us/usc/t99/s2", status="CLEAN", text='§ 2. H2\nBeta  "delta".'),
                Prediction(identifier="/us/usc/t99/s3", status="CLEAN", text="§ 3. H3\nNew text.")]
    m = run(setup, p)
    assert (m["match_rate"], m["false_clean"]) == (1.0, 0)


def test_wrong_clean_prediction_is_false_clean(setup):
    def p(law, before):
        return [Prediction(identifier="/us/usc/t99/s2", status="CLEAN", text="§ 2. H2\nBeta gamma."),
                Prediction(identifier="/us/usc/t99/s3", status="NOT_FOUND", text=None, stage="engine")]
    m = run(setup, p)
    assert (m["mismatched"], m["false_clean"], m["clean"], m["mismatch_unclassified"], m["mismatch_engine"]) == \
        (2, 1, 1, 1, 1)


def test_missed_and_extra(setup):
    def p(law, before):
        return [Prediction(identifier="/us/usc/t99/s1", status="CLEAN", text="§ 1. H1\nAlpha.", deterministic=False,
                           model_tokens=7)]
    m = run(setup, p)
    assert (m["missed"], m["extra"], m["model_tokens"], m["deterministic_coverage"]) == (2, 1, 7, 0.0)


def test_a_checkpointed_run_resumes_without_grading_again(setup, tmp_path):
    corpus, open_index = setup
    calls = []

    def p(law, before):
        calls.append(law.pl)
        return [Prediction(identifier="/us/usc/t99/s2", status="CLEAN", text='§ 2. H2\nBeta "delta".')]

    def hook(law, outs, before, after):
        return {"seen": sorted(o.identifier for o in outs), "after": after.release_point}
    ck = tmp_path / "ck.jsonl"
    first = harness.evaluate(corpus, p, "t", open_index, labels={}, after_law=hook, checkpoint=ck, key="k")
    x2 = {}
    again = harness.evaluate(corpus, p, "t", open_index, labels={}, after_law=hook, checkpoint=ck, key="k", extras=x2)
    assert calls == ["1-2"]                                             # the second run read the checkpoint
    assert again.metrics == first.metrics and again.outcomes == first.outcomes
    assert x2["1-2"] == {"seen": ["/us/usc/t99/s2", "/us/usc/t99/s3"], "after": "1-2"}
    harness.evaluate(corpus, p, "t", open_index, labels={}, after_law=hook, checkpoint=ck, key="other")
    assert calls == ["1-2", "1-2"]                                      # a different key starts over


def test_a_line_cut_short_by_an_interruption_is_graded_again(setup, tmp_path):
    corpus, open_index = setup
    calls = []

    def p(law, before):
        calls.append(law.pl)
        return []
    ck = tmp_path / "ck.jsonl"
    ck.write_text('{"key": "k"}\n{"pl": "1-2", "outc')
    m = harness.evaluate(corpus, p, "t", open_index, labels={}, checkpoint=ck, key="k").metrics
    assert calls == ["1-2"] and m["missed"] == 2


def test_a_section_with_a_delayed_amendment_note_is_pending_even_when_other_changes_were_executed(tmp_path):
    # OLRC executes a law's immediate amendments and sets out its delayed ones in an "Amendment of ..." note
    # (M6e dev: 36 sections), so R_after is not the law's full effect there and the section is not graded.
    note = ('<notes><note topic="amendments"><heading>Amendment of Subsection (b)</heading><p>Pub. L. 1–2, § 2, '
            'provided that, applicable to plan years beginning after 2030, subsection (b) is amended.</p></note>'
            '</notes>')
    db = tmp_path / "o.sqlite"
    ix = Indexer(db)
    for label, body in (("1-1", sec("2", "Beta gamma.")), ("1-2", sec("2", "Beta delta.").replace(
            "</section>", note + "</section>"))):
        z = tmp_path / f"{label}.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("usc99.xml", doc(body))
        ix.mark_complete(ix.load_release_point(z, label, None, "t", log=lambda s: None))
    law = CorpusLaw(pl="1-2", name="t", bill="1 hr 1", enrolled_url="x", enrolled_sha256="x", rp_before="1-1",
                    rp_after="1-2", titles=["99"], reason="t",
                    rows=[ClassifiedRow(title="99", section="2", description="", law_section="1")])
    t = harness.truth(law, Index(db, "1-1"), Index(db, "1-2"))
    assert t["/us/usc/t99/s2"]["changed"] and t["/us/usc/t99/s2"]["pending"]
    other = law.model_copy(update={"pl": "1-3"})                       # a note citing another law does not count
    assert not harness.truth(other, Index(db, "1-1"), Index(db, "1-2"))["/us/usc/t99/s2"]["pending"]


def test_a_section_another_law_also_amended_in_the_window_is_not_graded(tmp_path):
    # R_after carries every law executed in the window; when OLRC's amendment notes credit another law with
    # changing the section there (M6e dev: the FY2021 NDAA's Jan. 1, 2022 changes in the FY2022 NDAA's window),
    # the section cannot grade this law alone.
    def amendments(*laws):
        body = " ".join(f"Pub. L. {pl.replace('-', '–')} substituted text." for pl in laws)
        return f'<notes><note topic="amendments"><heading>Amendments</heading><p>{body}</p></note></notes>'
    db = tmp_path / "o.sqlite"
    ix = Indexer(db)
    for label, body in (("1-1", sec("2", "Beta gamma.").replace("</section>", amendments("1-1") + "</section>")),
                        ("1-2", sec("2", "Beta delta.").replace("</section>", amendments("1-2", "0-9", "1-1")
                                                            + "</section>"))):
        z = tmp_path / f"{label}.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("usc99.xml", doc(body))
        ix.mark_complete(ix.load_release_point(z, label, None, "t", log=lambda s: None))
    law = CorpusLaw(pl="1-2", name="t", bill="1 hr 1", enrolled_url="x", enrolled_sha256="x", rp_before="1-1",
                    rp_after="1-2", titles=["99"], reason="t",
                    rows=[ClassifiedRow(title="99", section="2", description="", law_section="1")])
    corpus = Corpus(built="t", selection="t", release_points=[], laws=[law])

    def p(law, before):
        return [Prediction(identifier="/us/usc/t99/s2", status="CLEAN", text="§ 2. H2\nBeta delta.")]
    rep = harness.evaluate(corpus, p, "t", lambda label: Index(db, label), labels={})
    assert [o.outcome for o in rep.outcomes] == ["ungradable"] and "0-9" in rep.outcomes[0].detail
    assert (rep.metrics["targets"], rep.metrics["ungradable"]) == (0, 1)


def test_a_section_the_law_has_not_reached_at_r_after_is_not_graded(tmp_path):
    # OLRC may list a law in a release point before executing it in every title (Pub. L. 116-283's title 46
    # amendments: listed in 116-344, executed in 117-17). A section unchanged at R_after with no note citing the law
    # is not graded; one with such a note is.
    db = tmp_path / "o.sqlite"
    ix = Indexer(db)
    cited = '<notes><note topic="amendments"><heading>Amendments</heading><p>Pub. L. 1–2 struck text.</p></note></notes>'
    for label, body in (("1-1", sec("2", "Beta gamma.") + sec("3", "Gamma.")),
                        ("1-2", sec("2", "Beta gamma.") + sec("3", "Gamma.").replace("</section>", cited + "</section>"))):
        z = tmp_path / f"{label}.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("usc99.xml", doc(body))
        ix.mark_complete(ix.load_release_point(z, label, None, "t", log=lambda s: None))
    law = CorpusLaw(pl="1-2", name="t", bill="1 hr 1", enrolled_url="x", enrolled_sha256="x", rp_before="1-1",
                    rp_after="1-2", titles=["99"], reason="t",
                    rows=[ClassifiedRow(title="99", section=s, description="", law_section="1") for s in ("2", "3")])
    corpus = Corpus(built="t", selection="t", release_points=[], laws=[law])

    def p(law, before):
        return [Prediction(identifier=f"/us/usc/t99/s{s}", status="CLEAN", text=f"§ {s}. H{s}\nDelta.")
                for s in ("2", "3")]
    rep = harness.evaluate(corpus, p, "t", lambda label: Index(db, label), labels={})
    assert {o.identifier[-2:]: o.outcome for o in rep.outcomes} == {"s2": "unexecuted", "s3": "mismatch"}
    assert (rep.metrics["targets"], rep.metrics["unexecuted"]) == (1, 1)


def test_materialized_release_points_are_stamped_with_the_code_that_built_them(tmp_path):
    # A file built by other code is never reused (review of #10): it sits under another stamp and is removed.
    from ramseyer.oracle.history import ReleaseIndexes, code_stamp
    stale = tmp_path / "code-000000000000"
    stale.mkdir()
    (stale / "1-1.sqlite").write_text("x")
    (tmp_path / "1-2.sqlite").write_text("x")
    ri = ReleaseIndexes(None, {}, tmp_path, log=lambda s: None)
    assert ri.dir == tmp_path / f"code-{code_stamp()}" and ri.dir.is_dir()
    assert not stale.exists() and not (tmp_path / "1-2.sqlite").exists()


def test_unicode_encoding_never_decides_a_comparison():
    assert harness.normalize("Attaché Program") == harness.normalize("Attaché Program")


def test_a_fraction_is_its_digits():
    assert harness.normalize("the first 5 ½ percent") == harness.normalize("the first 5 1/2 percent")
    assert harness.normalize("multiplying 7⁄10") == harness.normalize("multiplying 7/10")


def test_a_transfer_and_amendment_note_is_a_delayed_amendment():
    # 10 U.S.C. 930 (Pub. L. 114-328 § 5443): effective on a date the President designates.
    assert harness.DELAYED_NOTE.match("Transfer and Amendment of Section\nPub. L. 114–328 ... provided that, effective")
    assert not harness.DELAYED_NOTE.match("Amendments\n2016—Pub. L. 114–328 substituted")
