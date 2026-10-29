"""Comparison harness (docs/12-testing.md): predicted post-amendment section text vs the next release point.

A predictor returns, per law, one Prediction per Code section it thinks the law changes. The harness
compares each with the section text at R_after (and R_before for context), and reports per-section
outcomes and the metrics from tab 11. Nothing is dropped: targets with no prediction are "missed";
predictions for sections the law does not touch are "extra".
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel

from ramseyer.data.index import Index, LookupError_
from ramseyer.oracle.corpus import Corpus, CorpusLaw

Status = Literal["CLEAN", "WARN", "AMBIGUOUS", "NOT_FOUND", "TARGET_MISSING", "STALE_BASELINE", "CONFLICT",
                 "UNPARSED"]
Stage = Literal["parser", "resolver", "engine", "verify", "editorial", "unclassified", "ungradable"]
LABELS = Path(__file__).resolve().parents[3] / "tests" / "oracle" / "labels.json"
QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})


class Prediction(BaseModel):
    identifier: str                  # section identifier, e.g. /us/usc/t49/s24101
    status: Status
    text: str | None = None          # predicted section text_plain after the law; None when removed/unknown
    stage: Stage | None = None       # where the predictor failed, when it knows
    model_tokens: int = 0            # tokens spent on this section by any model fallback
    deterministic: bool = True       # produced without a model
    release_point: str | None = None  # the release point the prediction was checked against (rule 3)


class SectionOutcome(BaseModel):
    pl: str
    identifier: str
    outcome: Literal["match", "mismatch", "missed", "extra", "unexpected_change", "pending"]
    status: str | None
    stage: str | None
    detail: str = ""
    after_differs: bool | None = None   # off-target predictions: does the predicted text differ from R_after?


class Report(BaseModel):
    predictor: str
    laws: int
    targets: int
    outcomes: list[SectionOutcome]
    metrics: dict[str, float | int]
    by_law: dict[str, dict[str, int]]


def normalize(text: str | None) -> str | None:
    """Whitespace and quote style never decide a comparison; every other character does."""
    if text is None:
        return None
    return re.sub(r"\s+", " ", text.translate(QUOTES)).strip()


def section_text(ix: Index, identifier: str) -> tuple[str | None, str]:
    """(text_plain or None, status) of a section at a release point; ('absent') when it does not exist."""
    try:
        node = ix.by_identifier(identifier)
    except LookupError_ as e:
        return None, "absent" if e.code == "not_found" else e.code
    return node.text, node.status


def truth(law: CorpusLaw, before: Index, after: Index) -> dict[str, dict]:
    """Per targeted section: before and after text and status, and whether the text actually changed."""
    out = {}
    for row in law.targets:
        ident = row.identifier
        if ident in out:
            out[ident]["rows"].append(row.description)
            continue
        bt, bs = section_text(before, ident)
        at, as_ = section_text(after, ident)
        changed = normalize(bt) != normalize(at) or bs != as_
        out[ident] = {"before": bt, "before_status": bs, "after": at, "after_status": as_, "changed": changed,
                      "rows": [row.description],
                      "pending": not changed and at is not None and pending_note(law, before, after, ident)}
    return out


def pending_note(law: CorpusLaw, before: Index, after: Index, ident: str) -> bool:
    """OLRC did not execute the law's amendment: a delayed effective date set it out in a new note instead
    ("..., provided that, effective one year after ..., this section is amended as follows: ...")."""
    try:
        a = after.by_identifier(ident)
    except LookupError_:
        return False
    try:
        b_notes = {r[0] for r in before.db.execute("SELECT text FROM notes WHERE section_id=?",
                                                   (before.by_identifier(ident).id,))}
    except LookupError_:
        b_notes = set()
    cite = "Pub. L. " + law.pl.replace("-", "\u2013")
    return any(cite in t and re.search(r"effective .{0,160}amended", t, re.S)
               for (t,) in after.db.execute("SELECT text FROM notes WHERE section_id=?", (a.id,)) if t not in b_notes)


def text_hash(text: str | None) -> str:
    return hashlib.sha256(normalize(text or "").encode()).hexdigest()[:16]


def label_stage(label, predicted: str | None, after: str | None) -> str | None:
    """A hand label applies only to the texts it was checked against: {"stage", "pred", "after", "reason"} with
    hashes of the predicted and R_after texts (red team F12). A changed text, or a bare label, does not apply."""
    if isinstance(label, dict) and label.get("pred") == text_hash(predicted) and label.get("after") == text_hash(after):
        return label.get("stage")
    return None


def evaluate(corpus: Corpus, predictor: Callable[[CorpusLaw, Index], list[Prediction]], name: str,
             open_index: Callable[[str], Index], labels: dict | None = None) -> Report:
    labels = labels if labels is not None else (json.loads(LABELS.read_text()) if LABELS.exists() else {})
    outcomes: list[SectionOutcome] = []
    by_law: dict[str, dict[str, int]] = {}
    tokens = deterministic = predicted_n = 0
    for law in corpus.laws:
        before, after = open_index(law.rp_before), open_index(law.rp_after)
        gt = truth(law, before, after)
        preds = {p.identifier: p for p in predictor(law, before)}
        counts = collections.Counter()
        for ident, t in gt.items():
            p = preds.get(ident)
            if t.get("pending"):
                o = SectionOutcome(pl=law.pl, identifier=ident, outcome="pending", status=p.status if p else None,
                                   stage=None, detail="amendment set out in a note (delayed effective date); "
                                                      "R_after text is unchanged by design")
            elif p is None:
                o = SectionOutcome(pl=law.pl, identifier=ident, outcome="missed", status=None, stage=None,
                                   detail="classified to this law; no prediction")
            else:
                same = normalize(p.text) == normalize(t["after"])
                stage = label_stage(labels.get(f"{law.pl} {ident}"), p.text, t["after"]) or p.stage or \
                    (None if same else "unclassified")
                o = SectionOutcome(pl=law.pl, identifier=ident, outcome="match" if same else "mismatch",
                                   status=p.status, stage=stage,
                                   detail="" if same else first_difference(p.text, t["after"]))
            outcomes.append(o)
            counts[o.outcome] += 1
        for ident, p in preds.items():
            predicted_n += 1
            tokens += p.model_tokens
            deterministic += p.deterministic
            if ident in gt:
                continue
            at, _ = section_text(after, ident)
            bt, _ = section_text(before, ident)
            kind = "extra" if normalize(p.text) == normalize(bt) == normalize(at) else "unexpected_change"
            differs = None if at is None and p.text is not None else normalize(p.text) != normalize(at)
            outcomes.append(SectionOutcome(pl=law.pl, identifier=ident, outcome=kind, status=p.status, stage=p.stage,
                                           detail="not classified to this law" + (
                                               "; " + first_difference(p.text, at) if differs else ""),
                                           after_differs=differs))
            counts[kind] += 1
        by_law[law.pl] = dict(counts)
    graded = [o for o in outcomes if o.outcome in ("match", "mismatch")]
    clean = [o for o in graded if o.status == "CLEAN"]
    false_clean = [o for o in clean if o.outcome == "mismatch"]
    targets = sum(1 for o in outcomes if o.outcome in ("match", "mismatch", "missed"))
    metrics = {
        "targets": targets,
        "matched": sum(o.outcome == "match" for o in outcomes),
        "mismatched": sum(o.outcome == "mismatch" for o in outcomes),
        "missed": sum(o.outcome == "missed" for o in outcomes),
        "extra": sum(o.outcome == "extra" for o in outcomes),
        "unexpected_change": sum(o.outcome == "unexpected_change" for o in outcomes),
        "pending": sum(o.outcome == "pending" for o in outcomes),
        "match_rate": round(sum(o.outcome == "match" for o in outcomes) / targets, 4) if targets else 0.0,
        "clean": len(clean),
        "false_clean": len(false_clean),
        "false_clean_rate": round(len(false_clean) / len(clean), 4) if clean else 0.0,
        # CLEAN on a section the law is not classified to: right only if the text equals R_after (red team F6).
        "clean_off_target": sum(o.outcome in ("extra", "unexpected_change") and o.status == "CLEAN" for o in outcomes),
        "clean_off_target_wrong": sum(o.outcome in ("extra", "unexpected_change") and o.status == "CLEAN"
                                      and o.after_differs is not False for o in outcomes),
        "deterministic_coverage": round(deterministic / predicted_n, 4) if predicted_n else 0.0,
        "model_tokens": tokens,
    }
    for stage, n in collections.Counter(o.stage for o in outcomes if o.outcome == "mismatch").items():
        metrics[f"mismatch_{stage}"] = n
    return Report(predictor=name, laws=len(corpus.laws), targets=targets, outcomes=outcomes, metrics=metrics,
                  by_law=by_law)


def first_difference(a: str | None, b: str | None) -> str:
    a, b = normalize(a) or "", normalize(b) or ""
    i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return f"at char {i}: predicted …{a[max(0, i - 40):i + 60]}… | R_after …{b[max(0, i - 40):i + 60]}…"


def compare_with_baseline(report: Report, baseline: dict) -> list[str]:
    """Regressions against a stored baseline (CI). Lower match rate or more false-clean is a regression."""
    m, b = report.metrics, baseline.get("metrics", {})
    out = []
    if m["match_rate"] < b.get("match_rate", 0):
        out.append(f"match_rate {m['match_rate']} < baseline {b['match_rate']}")
    if m["false_clean_rate"] > b.get("false_clean_rate", 1):
        out.append(f"false_clean_rate {m['false_clean_rate']} > baseline {b['false_clean_rate']}")
    return out
