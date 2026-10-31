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
                 "UNPARSED", "NOT_EXECUTED", "ALREADY_EXECUTED"]
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
    outcome: Literal["match", "mismatch", "missed", "extra", "unexpected_change", "pending", "ungradable"]
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
                      "pending": at is not None and pending_note(law, before, after, ident, changed),
                      "other_laws": other_laws(law, before, after, ident)}
    return out


PL_CITE = re.compile(r"Pub\. L\. (\d+)[–-](\d+)")


AMENDMENT_ENTRY = re.compile(r"(?<=\.)\s+(?=(?:Subsecs?\.|Pars?\.|Subpars?\.|Cls?\.|Pub\. L\.|\d{4}\u2014))")


def other_laws(law: CorpusLaw, before: Index, after: Index, ident: str) -> list[str]:
    """Laws other than this one that OLRC's amendment notes credit with changing the section between R_before and
    R_after: R_after then carries their changes too (a delayed amendment of an earlier law taking effect in the
    window, as the FY2021 NDAA's title XVIII did on Jan. 1, 2022), so the section cannot grade this law alone.
    Entries of the notes are compared, not the laws they cite: an earlier law may have amended the section before
    R_before too (Pub. L. 116-283 § 1081 in 2021, then § 1883 on Jan. 1, 2022)."""
    def entries(ix: Index) -> set[str]:
        try:
            sid = ix.by_identifier(ident).id
        except LookupError_:
            return set()
        out = set()
        for (t,) in ix.db.execute("SELECT text FROM notes WHERE section_id=? AND note_type='amendments'", (sid,)):
            out |= {" ".join(e.split()) for e in AMENDMENT_ENTRY.split(t)}
        return out
    new = entries(after) - entries(before)
    # The law an entry starts with is the one that acted; laws it mentions later ("... added by Pub. L. 116-92") did not.
    return sorted({f"{m.group(1)}-{m.group(2)}" for e in new if (m := PL_CITE.match(e))} - {law.pl})


DELAYED_NOTE = re.compile(r"Amendment of (?:Sections?|Subsections?|Paragraphs?|Subparagraphs?|Clauses?|Subclauses?|"
                          r"Items?)\b")


def pending_note(law: CorpusLaw, before: Index, after: Index, ident: str, changed: bool = False) -> bool:
    """OLRC did not execute (all of) the law's amendment: a delayed effective date set it out in a new note instead.
    OLRC heads such a note "Amendment of Subsection (a)" (or Section, Paragraph, ...), and it says so even when the
    law's other amendments to the section were executed, so the section is not gradable either way. A note without
    that heading counts only when the text did not change ("..., provided that, effective one year after ..., this
    section is amended as follows: ...")."""
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
    return any(cite in t and (DELAYED_NOTE.match(t) and cite in t[:300] or
                              not changed and re.search(r"effective .{0,160}amended", t, re.S))
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
             open_index: Callable[[str], Index], labels: dict | None = None,
             after_law: Callable[[CorpusLaw, list[SectionOutcome], Index, Index], dict] | None = None,
             checkpoint: Path | None = None, key: str = "", extras: dict[str, dict] | None = None) -> Report:
    """Grade every law of the corpus.

    after_law(law, its outcomes, R_before, R_after) runs while the law's release points are open and returns
    whatever its caller needs later (JSON-serializable), collected in `extras` by law. With `checkpoint`, each
    graded law is appended to that file, and a run with the same `key` (a hash of what the grading depends on)
    resumes after the last one; a different key starts over."""
    labels = labels if labels is not None else (json.loads(LABELS.read_text()) if LABELS.exists() else {})
    outcomes: list[SectionOutcome] = []
    by_law: dict[str, dict[str, int]] = {}
    tokens = deterministic = predicted_n = 0
    extras = extras if extras is not None else {}
    done: dict[str, dict] = {}
    if checkpoint is not None:
        lines = checkpoint.read_text().splitlines() if checkpoint.exists() else []
        if lines and json.loads(lines[0]).get("key") == key:
            for line in lines[1:]:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:          # a line cut short by the interruption
                    break
                done[rec["pl"]] = rec
        else:
            checkpoint.write_text(json.dumps({"key": key}) + "\n")
    for law in corpus.laws:
        if law.pl in done:
            rec = done[law.pl]
            outcomes += [SectionOutcome(**o) for o in rec["outcomes"]]
            by_law[law.pl] = rec["counts"]
            predicted_n += rec["predicted"]
            tokens += rec["tokens"]
            deterministic += rec["deterministic"]
            extras[law.pl] = rec["extra"]
            continue
        law_outcomes: list[SectionOutcome] = []
        law_predicted = law_tokens = law_deterministic = 0
        before, after = open_index(law.rp_before), open_index(law.rp_after)
        gt = truth(law, before, after)
        preds = {p.identifier: p for p in predictor(law, before)}
        counts = collections.Counter()
        for ident, t in gt.items():
            p = preds.get(ident)
            if t.get("other_laws") and not t.get("pending"):
                o = SectionOutcome(pl=law.pl, identifier=ident, outcome="ungradable", status=p.status if p else None,
                                   stage=None, detail="R_after's amendment notes credit other laws in the window "
                                                      f"too: {', '.join(t['other_laws'])}")
            elif t.get("pending"):
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
            law_outcomes.append(o)
            counts[o.outcome] += 1
        for ident, p in preds.items():
            law_predicted += 1
            law_tokens += p.model_tokens
            law_deterministic += p.deterministic
            if ident in gt:
                continue
            at, _ = section_text(after, ident)
            bt, _ = section_text(before, ident)
            kind = "extra" if normalize(p.text) == normalize(bt) == normalize(at) else "unexpected_change"
            differs = None if at is None and p.text is not None else normalize(p.text) != normalize(at)
            law_outcomes.append(SectionOutcome(pl=law.pl, identifier=ident, outcome=kind, status=p.status,
                                               stage=p.stage, detail="not classified to this law" + (
                                                   "; " + first_difference(p.text, at) if differs else ""),
                                               after_differs=differs))
            counts[kind] += 1
        by_law[law.pl] = dict(counts)
        extra = after_law(law, law_outcomes, before, after) if after_law else {}
        extras[law.pl] = extra
        if checkpoint is not None:
            with open(checkpoint, "a") as fh:
                fh.write(json.dumps({"pl": law.pl, "outcomes": [o.model_dump() for o in law_outcomes],
                                     "counts": dict(counts), "predicted": law_predicted, "tokens": law_tokens,
                                     "deterministic": law_deterministic, "extra": extra}, ensure_ascii=False) + "\n")
        outcomes += law_outcomes
        predicted_n += law_predicted
        tokens += law_tokens
        deterministic += law_deterministic
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
        "ungradable": sum(o.outcome == "ungradable" for o in outcomes),
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
