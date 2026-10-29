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
