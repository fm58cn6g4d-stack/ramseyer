"""Measure the XHTML -> USLM converter (src/billmap/data/xhtml_uslm.py) against the XML edition of the same release.

For every section of the pinned release point's XHTML edition (htm_uscAll zip, cached by `billmap sync`), the
converted section is compared with the indexed USLM section on
  - text: text_of() of both, after the harness normalization;
  - structure: the set of unit paths ("(a)(1)(B)") below the section.
Run:  .venv/bin/python scripts/xhtml_check.py [--titles 49 42] [--show 20] [--validate]
Writes var/xhtml_check.md and var/xhtml_check.jsonl (one line per differing section).
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import time
import zipfile
from pathlib import Path

from lxml import etree

from billmap import config
from billmap.data.http import Fetcher
from billmap.data.index import Index
from billmap.data.indexer import SUB, local, text_of
from billmap.data.xhtml import rendering_normalized
from billmap.data.xhtml_uslm import chunks, section_element
from billmap.oracle.harness import normalize

FILE_RE = re.compile(r"^PRELIMusc(\d+)([aA]?)\.htm$")


def paths(sec, ident: str) -> set[str]:
    out = set()
    for el in sec.iter():
        i = el.get("identifier") if isinstance(el.tag, str) else None
        if i and i.startswith(ident + "/") and local(el) in SUB:
            out.add("".join(f"({p})" for p in i[len(ident) + 1:].split("/")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--titles", nargs="*")
    ap.add_argument("--show", type=int, default=20)
    ap.add_argument("--validate", action="store_true", help="also validate converted sections against USLM.xsd")
    args = ap.parse_args()
    cfg = config.load()
    f = Fetcher(cfg)
    ix = Index(cfg.index_path, cfg.release_pin)
    zip_path = f.get(f"{cfg.olrc_base}download/releasepoints/us/pl/{cfg.release_pin.replace('-', '/')}/"
                     f"htm_uscAll@{cfg.release_pin}.zip").path
    schema = None
    if args.validate:
        xsd = config.VAR / "uslm" / "USLM.xsd"
        schema = etree.XMLSchema(etree.parse(str(xsd))) if xsd.exists() else None
    t0 = time.monotonic()
    counts = collections.Counter()
    per_title = collections.defaultdict(collections.Counter)
    out = open(cfg.var / "xhtml_check.jsonl", "w")
    examples = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in sorted(zf.namelist()):
            m = FILE_RE.match(name)
            if not m:
                continue
            code = str(int(m.group(1))) + ("a" if m.group(2) else "")
            if args.titles and code not in args.titles:
                continue
            page = zf.read(name).decode("utf-8", errors="replace")
            for c in chunks(page):
                try:
                    sec = section_element(c, code)
                except Exception as e:          # a converter crash is a measured failure, never skipped
                    counts["crash"] += 1
                    per_title[code]["crash"] += 1
                    out.write(json.dumps({"title": code, "item": c.itempath, "crash": repr(e)[:300]}) + "\n")
                    continue
                if sec is None:
                    continue
                ident = sec.get("identifier")
                try:
                    node = ix.by_identifier(ident)
                    real = etree.fromstring(ix.section_xml(node).encode("utf-8"))
                except Exception:
                    counts["not_in_index"] += 1
                    per_title[code]["not_in_index"] += 1
                    continue
                # Presentation-only differences (fractions, joiners, dot leaders) are discounted, as in M1.
                a = rendering_normalized(normalize(text_of(sec)))
                b = rendering_normalized(normalize(text_of(real)))
                pa, pb = paths(sec, ident), paths(real, ident)
                kind = "equal" if a == b and pa == pb else ("structure" if a == b else
                                                            ("text" if pa == pb else "both"))
                counts[kind] += 1
                per_title[code][kind] += 1
                if schema is not None and not schema.validate(sec):
                    counts["schema_invalid"] += 1
                if kind != "equal":
                    i = next((k for k, (p, q) in enumerate(zip(a, b)) if p != q), min(len(a), len(b)))
                    d = {"title": code, "ident": ident, "kind": kind,
                         "text": f"…{a[max(0, i - 40):i + 60]}… | …{b[max(0, i - 40):i + 60]}…" if a != b else "",
                         "only_converted": sorted(pa - pb)[:8], "only_xml": sorted(pb - pa)[:8]}
                    out.write(json.dumps(d, ensure_ascii=False) + "\n")
                    if len(examples) < args.show:
                        examples.append(d)
    graded = sum(counts[k] for k in ("equal", "text", "structure", "both"))
    lines = ["# XHTML -> USLM converter check", "",
             f"Release {cfg.release_pin}; {time.monotonic() - t0:.0f}s.", "",
             f"Sections compared: {graded}; equal (text and structure): {counts['equal']} "
             f"({counts['equal'] / max(graded, 1):.1%}); text differs only: {counts['text']}; structure differs "
             f"only: {counts['structure']}; both: {counts['both']}; converter crashes: {counts['crash']}; "
             f"not in index: {counts['not_in_index']}"
             + (f"; schema-invalid: {counts['schema_invalid']}" if schema is not None else ""), "",
             "| Title | Equal | Text | Structure | Both | Crash |", "| --- | --- | --- | --- | --- | --- |"]
    for code in sorted(per_title, key=lambda t: (int(re.sub(r'\D', '', t)), t)):
        c = per_title[code]
        lines.append(f"| {code} | {c['equal']} | {c['text']} | {c['structure']} | {c['both']} | {c['crash']} |")
    lines += ["", "## Examples", ""] + [f"- {e['ident']} [{e['kind']}] {e['text'][:260]} "
                                         f"{'converted-only ' + str(e['only_converted']) if e['only_converted'] else ''} "
                                         f"{'xml-only ' + str(e['only_xml']) if e['only_xml'] else ''}" for e in examples]
    (cfg.var / "xhtml_check.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:5 + len(per_title) + 3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
