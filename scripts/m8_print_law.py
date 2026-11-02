"""M8: the comparative print of an enacted oracle law, against its R_before (what the print would have shown the day
before enactment). Writes var/m8_print/<pl>.html, <pl>-working.html and <pl>.docx.

Run:  .venv/bin/python scripts/m8_print_law.py 119-74 [119-75 ...]
"""
from __future__ import annotations

import hashlib
import sys

from ramseyer import config
from ramseyer.comparative import html as print_html
from ramseyer.comparative import word as print_word
from ramseyer.data.http import Fetcher
from ramseyer.data.index import Index
from ramseyer.dryrun.predict import run_bill
from ramseyer.oracle import store
from ramseyer.oracle.corpus import MANIFEST, Corpus
from ramseyer.parse import parse_text
from ramseyer.parse.xmltext import render
from ramseyer.resolve import popular
from ramseyer.resolve.actcode import classification_map
from ramseyer.resolve.resolver import Resolver, classification_rows


def print_law(pl: str, cfg, f, base: Resolver) -> dict[str, bytes]:
    law = Corpus.load(MANIFEST).law(pl)
    before = store.index(law.rp_before, store.ORACLE_DB)
    r = Resolver(before, base.popular, base.classification)
    r.positive = set(base.positive)
    path = f.get(law.enrolled_url).path
    run = run_bill(parse_text(render(path)).instructions, r, before)
    meta = dict(title=f"Pub. L. {pl} ({law.name})", release_point=law.rp_before,
                input_hash=hashlib.sha256(path.read_bytes()).hexdigest(), generated="(oracle print)", version="M8")
    return {f"{pl}.html": print_html.report(run, style="committee", **meta).encode(),
            f"{pl}-working.html": print_html.report(run, style="working", **meta).encode(),
            f"{pl}.docx": print_word.document(run, style="committee", **meta)}


def main() -> int:
    cfg = config.load()
    f = Fetcher(cfg)
    base = Resolver(Index(cfg.index_path, cfg.release_pin), popular.load(),
                    classification_map(classification_rows(f, cfg.olrc_base)))
    out = cfg.var / "m8_print"
    out.mkdir(exist_ok=True)
    for pl in sys.argv[1:]:
        for name, data in print_law(pl, cfg, f, base).items():
            (out / name).write_bytes(data)
            print(out / name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
