"""Regression tests from the red-team review (records/red-team-2026-10.md): billmap's real parse -> resolve ->
dry-run pipeline on the review's synthetic index (redteam/synthetic.py; placeholder statute text only)."""
import importlib.util
import zipfile
from pathlib import Path

import pytest

from billmap.data.index import Index
from billmap.data.indexer import Indexer
from billmap.dryrun.predict import run_bill
from billmap.parse import parse_text
from billmap.resolve.popular import norm_name
from billmap.resolve.resolver import Resolver

_spec = importlib.util.spec_from_file_location("synthetic", Path(__file__).parents[2] / "redteam" / "synthetic.py")
synthetic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synthetic)
CASES = synthetic.CASES


@pytest.fixture(scope="module")
def resolver(tmp_path_factory):
    d = tmp_path_factory.mktemp("redteam")
    z = d / "1-1.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("usc98.xml", synthetic.t98())
        zf.writestr("usc99.xml", synthetic.t99())
    ix = Indexer(d / "synthetic.sqlite")
    ix.mark_complete(ix.load_release_point(z, "1-1", None, "synthetic", log=lambda s: None))
    index = Index(d / "synthetic.sqlite", "1-1")
    return Resolver(index, {norm_name("Placeholder Act"): [{"identities": ["pl:150-7"]}]}, {})


def bill(resolver, draft: str):
    run = run_bill(parse_text("SEC. 2. AMENDMENTS.\n" + draft.strip() + "\n").instructions, resolver, resolver.ix)
    return run, {p.identifier: p for p in run.predictions}


def text(pred) -> str:
    return " ".join((pred.text or "").split())


def test_ordinal_occurrence_changes_only_that_occurrence(resolver):
    run, preds = bill(resolver, CASES["second_place_it_appears"])
    t = text(preds["/us/usc/t98/s101"])
    assert "the Lorem Board. The U.S. Government shall fund the Commission. The Board shall meet" in t


@pytest.mark.parametrize("ordinal,occ", [("first", "nth:1"), ("second", "nth:2"), ("third", "nth:3"),
                                         ("last", "last")])
def test_ordinals_parse(ordinal, occ):
    ins = parse_text(f"SEC. 2. X.\nSection 1 of title 99, United States Code, is amended by striking “a” the {ordinal} "
                     f"place it appears and inserting “b”.\n").instructions
    assert ins[0].occurrence == occ


def test_chapter_wide_edit_reaches_every_section_and_is_not_clean(resolver):
    run, preds = bill(resolver, CASES["chapter_wide_substitution"])
    assert set(preds) == {"/us/usc/t98/s101", "/us/usc/t98/s102", "/us/usc/t98/s103"}
    assert all(p.status == "WARN" and "Board" not in text(p).split("Lorem board", 1)[-1] for p in preds.values())


def test_title_wide_edit_reaches_every_section(resolver):
    run, preds = bill(resolver, CASES["title_wide_substitution"])
    assert all("Secretary" not in text(p) and p.status == "WARN" for p in preds.values())


def test_act_wide_edit_reaches_the_acts_sections(resolver):
    run, preds = bill(resolver, CASES["act_wide_substitution"])
    assert {"/us/usc/t99/s1", "/us/usc/t99/s2"} <= set(preds)
    assert all("Administrator" not in text(p) and p.status == "WARN" for p in preds.values())


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_instruction_has_a_status(resolver, name):
    run, _ = bill(resolver, CASES[name])
    assert run.traces and all(tr.result is not None and tr.result.status for tr in run.traces)
