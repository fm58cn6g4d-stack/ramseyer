"""M8 gate: the comparative print on the tuning laws (docs/07-comparative-print.md, Tests).

For every section the engine works on:
1. stripping the redline's marks gives back the original section's text and the engine's predicted text exactly
   (whitespace aside);
2. every instruction that is not CLEAN appears in the print with its marker;
3. the print renders as HTML (committee and working styles) and as Word.
Golden renders: for five laws, the HTML print's SHA-256 is compared with tests/oracle/m8_golden.json (`--refresh`
re-records it after a deliberate change; hashes only, so no statute text is committed).

Run:  .venv/bin/python scripts/m8_gate.py [--refresh]     Writes var/m8_gate.md.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
from pathlib import Path

from docx import Document

from ramseyer import config
from ramseyer.comparative import html as print_html
from ramseyer.comparative import word as print_word
from ramseyer.comparative.redline import changed, redline, strip
from ramseyer.data.http import Fetcher
from ramseyer.data.index import Index
from ramseyer.data.indexer import text_of
from ramseyer.dryrun.predict import run_bill
from ramseyer.oracle import store
from ramseyer.oracle.corpus import MANIFEST, Corpus
from ramseyer.parse import parse_text
from ramseyer.parse.xmltext import render
from ramseyer.resolve import popular
from ramseyer.resolve.actcode import classification_map
from ramseyer.resolve.resolver import Resolver, classification_rows

GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "oracle" / "m8_golden.json"
GOLDEN_LAWS = ["119-74", "119-75", "119-76", "119-83", "119-88"]


def flat(t: str | None) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    cfg = config.load()
    f = Fetcher(cfg)
    base = Resolver(Index(cfg.index_path, cfg.release_pin), popular.load(),
                    classification_map(classification_rows(f, cfg.olrc_base)))
    corpus = Corpus.load(MANIFEST)
    golden = json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}
    sections = shown = 0
    trip, missing_marks, render_fail, golden_diff, new_golden = [], [], [], [], {}
    for law in corpus.laws:
        print(law.pl, file=sys.stderr, flush=True)
        before = store.index(law.rp_before, store.ORACLE_DB)
        r = Resolver(before, base.popular, base.classification)
        r.positive = set(base.positive)
        path = f.get(law.enrolled_url).path
        run = run_bill(parse_text(render(path)).instructions, r, before)
        for ident, work in run.working.items():
            sections += 1
            red = redline(work.original, None if work.removed else work.el)
            if red is None:
                continue
            shown += changed(red)
            ok_b = flat(strip(red, "before")) == (flat(text_of(work.original)) if work.original is not None else "")
            ok_a = flat(strip(red, "after")) == (flat(text_of(work.el)) if not work.removed else "")
            if not (ok_b and ok_a):
                trip.append(f"- {law.pl} {ident}")
        meta = dict(title=f"Pub. L. {law.pl}", release_point=law.rp_before,
                    input_hash=hashlib.sha256(path.read_bytes()).hexdigest(), generated="(gate)", version="M8")
        try:
            page = print_html.report(run, style="committee", **meta)
            print_html.report(run, style="working", **meta)
            Document(io.BytesIO(print_word.document(run, style="committee", **meta)))
        except Exception as e:                       # noqa: BLE001 - any failure to render is a gate failure
            render_fail.append(f"- {law.pl}: {type(e).__name__}: {e}")
            continue
        for tr in run.traces:
            if tr.section and tr.result is not None and tr.result.status != "CLEAN":
                if f"<b>{tr.result.status}</b>" not in page:
                    missing_marks.append(f"- {law.pl} {tr.instruction.id} {tr.result.status}")
        if law.pl in GOLDEN_LAWS:
            h = hashlib.sha256(page.encode()).hexdigest()
            new_golden[law.pl] = h
            if not args.refresh and golden.get(law.pl) != h:
                golden_diff.append(f"- {law.pl}: {golden.get(law.pl, 'none recorded')[:12]} -> {h[:12]}")
    if args.refresh:
        GOLDEN.write_text(json.dumps(new_golden, indent=1) + "\n")
    checks = [("Stripping the marks gives back both sides (every section the engine works on)", not trip,
               f"{sections} sections, {shown} with a change shown; mismatches: {len(trip)}"),
              ("Every instruction that is not CLEAN appears with its marker", not missing_marks,
               f"missing: {len(missing_marks)}"),
              ("HTML (two styles) and Word render for every law", not render_fail, f"failures: {len(render_fail)}"),
              ("Golden renders unchanged (five laws)", not golden_diff,
               "re-recorded" if args.refresh else f"changed: {len(golden_diff)}")]
    lines = ["# M8 gate: comparative print", "", f"Tuning set: {len(corpus.laws)} laws", "",
             "| Check | Result | Detail |", "| --- | --- | --- |"]
    lines += [f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |" for name, ok, detail in checks]
    for title, rows in (("Round-trip mismatches", trip), ("Missing markers", missing_marks),
                        ("Render failures", render_fail), ("Golden renders changed", golden_diff)):
        if rows:
            lines += ["", f"## {title}", ""] + rows[:50]
    (cfg.var / "m8_gate.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:10]))
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
