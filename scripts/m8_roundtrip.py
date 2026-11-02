"""M8 check: for every section the engine edits in a set of oracle laws, the redline's two sides, with the marks
stripped, are the original section's text and the engine's predicted text (whitespace aside).

Run:  .venv/bin/python scripts/m8_roundtrip.py [--law PL ...]     Writes var/m8_roundtrip.md; exits 1 on any mismatch.
"""
from __future__ import annotations

import argparse
import re
import sys

from ramseyer import config
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


def flat(t: str | None) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--law", nargs="+")
    args = ap.parse_args()
    cfg = config.load()
    f = Fetcher(cfg)
    resolver = Resolver(Index(cfg.index_path, cfg.release_pin), popular.load(),
                        classification_map(classification_rows(f, cfg.olrc_base)))
    corpus = Corpus.load(MANIFEST)
    if args.law:
        corpus.laws = [corpus.law(pl) for pl in args.law]
    sections = edited = 0
    bad = []
    for law in corpus.laws:
        print(law.pl, file=sys.stderr, flush=True)
        before = store.index(law.rp_before, store.ORACLE_DB)
        r = Resolver(before, resolver.popular, resolver.classification)
        r.positive = set(resolver.positive)
        run = run_bill(parse_text(render(f.get(law.enrolled_url).path)).instructions, r, before)
        for ident, work in run.working.items():
            sections += 1
            red = redline(work.original, None if work.removed else work.el)
            if red is None:
                continue
            edited += changed(red)
            want_before = flat(text_of(work.original)) if work.original is not None else ""
            want_after = flat(text_of(work.el)) if work.el is not None and not work.removed else ""
            got_before, got_after = flat(strip(red, "before")), flat(strip(red, "after"))
            if got_before != want_before or got_after != want_after:
                bad.append(f"- {law.pl} {ident}: " + ("before differs" if got_before != want_before else "")
                           + (" after differs" if got_after != want_after else ""))
    out = ["# M8: redline round trip", "", f"Laws: {len(corpus.laws)}; sections worked on: {sections}; "
           f"with a change shown: {edited}; round-trip mismatches: {len(bad)}", ""] + (bad or ["None."])
    (cfg.var / "m8_roundtrip.md").write_text("\n".join(out) + "\n")
    print("\n".join(out[:3]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
