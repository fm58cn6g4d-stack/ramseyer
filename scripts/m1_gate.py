"""M1 gate: data-layer invariants from docs/02-data-layer.md, measured on the pinned release point.

Run:  .venv/bin/python scripts/m1_gate.py [--sample 100] [--seed 20261028]
Writes var/m1_gate.md; exit status 1 if any check fails.
"""
from __future__ import annotations

import argparse
import collections
import html
import random
import re
import sys
import time
import zipfile

from billmap import config
from billmap.data import cite as citemod
from billmap.data.http import Fetcher
from billmap.data.index import Index, LookupError_
from billmap.data.indexer import MEMBER_RE

SEC_LEAF = re.compile(r"^\[?Secs?\.\s+(.+?)\]?$")   # "[Sec. 2" marks a repealed section


def xhtml_listing(path):
    """Per title: list of (first section number, statute words or None) from OLRC's XHTML edition."""
    out: dict[str, list] = {}
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            m = re.match(r"^PRELIM(usc\d+[aA]?)\.htm$", name)
            if not m:
                continue
            code = str(int(MEMBER_RE.match(m.group(1) + ".xml").group(1))) + (
                "a" if m.group(1)[-1] in "aA" else "")
            entries, last_doc = [], None
            for chunk in zf.read(name).decode("utf-8", errors="replace").split("<!-- documentid:")[1:]:
                doc_id = chunk.split(None, 1)[0]
                p = re.search(r"<!-- itempath:([^>]*?) -->", chunk)
                leaf = SEC_LEAF.match(p.group(1).rsplit("/", 1)[-1]) if p else None
                if not leaf:
                    continue
                # "Secs. 3, 4" / "Secs. 1001 to 1004" -> first number; "130g_2" is OLRC's tag for a duplicate number.
                first = re.sub(r"_\d+$", "", re.split(r",\s*| to ", leaf.group(1))[0])
                body = re.search(r"<!-- field-start:statute -->(.*?)<!-- field-end:statute -->", chunk, re.S)
                words = html.unescape(re.sub(r"<[^>]+>", " ", body.group(1))).split() if body else None
                key = (doc_id, leaf.group(1))      # duplicates differ in the leaf: "130g" vs "130g_2"
                if key == last_doc and entries:    # one section split over two documents (18a § 2)
                    prev_num, prev_words = entries[-1]
                    entries[-1] = (prev_num, (prev_words or []) + (words or []) or None)
                    continue
                last_doc = key
                entries.append((citemod.normalize_section(first), words))
            out[code] = entries
    return out


def first_number(identifier: str) -> str:
    """'/us/usc/t2/s1001...1004' -> '1001'; '/us/usc/t2/s3' -> '3'."""
    return identifier.rsplit("/s", 1)[1].split("...", 1)[0]


QUOTES = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"})


def comparable(words: list[str]) -> str:
    """Whitespace and curly/straight quote style are rendering choices; every other character must match."""
    return "".join(words).translate(QUOTES)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=100)
    ap.add_argument("--seed", type=int, default=20261028)
    args = ap.parse_args()
    cfg = config.load()
    ix = Index(cfg.index_path, cfg.release_pin)
    db, rp = ix.db, ix.rp_id
    checks: list[tuple[str, bool, str]] = []
    t0 = time.monotonic()

    # 1. Non-null id, kind, path; an empty path only on titles, appendices and section-level units.
    bad = db.execute("SELECT count(*) FROM nodes WHERE rp=? AND (identifier IS NULL OR kind IS NULL OR path IS NULL "
                     "OR text_plain IS NULL OR (path = '' AND kind NOT IN ('title','appendix','section',"
                     "'courtRule','reorganizationPlan')))", (rp,)).fetchone()[0]
    total = db.execute("SELECT count(*) FROM nodes WHERE rp=?", (rp,)).fetchone()[0]
    checks.append(("Every node has non-null id, kind and path", bad == 0, f"{total:,} nodes, {bad} violations"))

    # 2. Section count and section numbers per title vs the OLRC XHTML edition (an independent OLRC rendering).
    f = Fetcher(cfg)
    base = f"{cfg.olrc_base}download/releasepoints/us/pl/{cfg.release_pin.replace('-', '/')}/"
    xh_resp = f.get(f"{base}htm_uscAll@{cfg.release_pin}.zip")
    listing = xhtml_listing(xh_resp.path)
    mismatches, explained = [], []
    for code, sections in db.execute("SELECT title, sections FROM titles WHERE rp=? ORDER BY rowid", (rp,)):
        ours = collections.Counter(
            first_number(r[0]) for r in db.execute(
                "SELECT identifier FROM nodes WHERE rp=? AND title=? AND kind='section'", (rp, code)))
        theirs = collections.Counter(n for n, _ in listing.get(code, []))
        if ours != theirs:
            only_ours, only_theirs = ours - theirs, theirs - ours
            mismatches.append(f"title {code}: index {sum(ours.values())}, XHTML {sum(theirs.values())}; "
                              f"only index {sorted(only_ours)[:8]}, only XHTML {sorted(only_theirs)[:8]}")
    n_titles = db.execute("SELECT count(*) FROM titles WHERE rp=?", (rp,)).fetchone()[0]
    checks.append(("Section count and numbers per title match OLRC's XHTML listing", not mismatches,
                   f"{n_titles} titles compared; {len(mismatches)} differ" + ("" if not mismatches else ": " +
                                                                              " | ".join(mismatches))))

    # 3. Random sections round-trip cite -> node -> text, and the text matches OLRC's XHTML statute field.
    ids = [r[0] for r in db.execute("SELECT id FROM nodes WHERE rp=? AND kind='section' ORDER BY id", (rp,))]
    sample = random.Random(args.seed).sample(ids, args.sample)
    xh_words = {(code, num): w for code, entries in listing.items() for num, w in entries}
    rt_fail, ambiguous_ok, text_fail, text_ok, no_field, no_cite = [], 0, [], 0, 0, 0
    no_field_status = collections.Counter()
    for nid in sample:
        node = ix._node(nid)
        try:
            if node.cite is None:          # e.g. /us/usc/t18a/pl/91/538/s1: reachable by identifier only
                no_cite += 1
            back = ix.get_section(node.cite or node.identifier)
            if back.id != node.id or back.identifier != node.identifier or not back.text:
                rt_fail.append(f"{node.cite}: returned node {back.id}")
                continue
        except LookupError_ as e:
            dup = db.execute("SELECT count(*) FROM node_ident WHERE rp=? AND identifier=?",
                             (rp, node.identifier)).fetchone()[0]
            if e.code == "ambiguous" and dup > 1:
                ambiguous_ok += 1
                continue
            rt_fail.append(f"{node.cite}: {e}")
            continue
        except Exception as e:  # report, never drop
            rt_fail.append(f"{node.identifier}: {type(e).__name__}: {e}")
            continue
        words = xh_words.get((node.title, first_number(node.identifier)))
        if words is None:
            no_field += 1
            no_field_status[node.status] += 1
            continue
        mine = node.text.split("\n", 1)[1].split() if "\n" in node.text else []
        a, b = comparable(mine), comparable(words)
        if a == b:
            text_ok += 1
        else:
            i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            text_fail.append(f"{node.cite}: first difference at char {i}: index {a[i-20:i+30]!r} vs XHTML {b[i-20:i+30]!r}")
    checks.append((f"{args.sample} random sections round-trip cite -> node -> text (seed {args.seed})",
                   not rt_fail,
                   f"{args.sample - len(rt_fail) - ambiguous_ok} exact, {ambiguous_ok} correctly reported ambiguous "
                   f"(duplicate section numbers in the Code), {len(rt_fail)} failed; {no_cite} had no U.S.C. citation "
                   f"form and round-tripped by identifier" +
                   ("" if not rt_fail else ": " + "; ".join(rt_fail))))
    checks.append(("Sampled section text equals the XHTML statute field (ignoring whitespace and quote style)",
                   not text_fail,
                   f"{text_ok} equal, {len(text_fail)} differ, {no_field} have no statute field in XHTML "
                   f"(statuses: {sorted(no_field_status.items())})" +
                   ("" if not text_fail else ": " + " | ".join(text_fail[:10]))))

    # Whole population, as a measurement: every section's citation resolves back to it.
    pop_fail = pop_amb = pop_nocite = 0
    for nid, ident in db.execute("SELECT id, identifier FROM nodes WHERE rp=? AND kind='section'", (rp,)).fetchall():
        try:
            c = str(citemod.from_identifier(ident))
        except citemod.CiteError:
            pop_nocite += 1
            c = ident
        try:
            if ix.get_section(c).id != nid:
                pop_fail += 1
        except LookupError_ as e:
            pop_amb += e.code == "ambiguous"
            pop_fail += e.code != "ambiguous"
    checks.append(("All sections round-trip cite -> node", pop_fail == 0,
                   f"{len(ids):,} sections; {pop_fail} failed; {pop_amb} ambiguous (duplicate numbers); "
                   f"{pop_nocite} by identifier (no U.S.C. citation form)"))

    # 4. Every ref resolves or carries dst_raw and a reason.
    unexplained = db.execute("SELECT count(*) FROM refs WHERE rp=? AND dst_id IS NULL AND (dst_raw IS NULL OR "
                             "reason IN ('resolved','pending') OR reason = '')", (rp,)).fetchone()[0]
    reasons = db.execute("SELECT kind, reason, count(*) FROM refs WHERE rp=? GROUP BY 1, 2 ORDER BY 3 DESC",
                         (rp,)).fetchall()
    n_refs = sum(r[2] for r in reasons)
    checks.append(("Every ref resolves or is stored with dst_raw and a reason", unexplained == 0,
                   f"{n_refs:,} refs, {unexplained} unexplained. " +
                   "; ".join(f"{k}/{r}: {c:,}" for k, r, c in reasons)))

    # 5. Every query result carries the release point.
    n = ix.get_section("4 U.S.C. 1")
    checks.append(("Query results carry the release point", n.release_point == cfg.release_pin,
                   f"get_section('4 U.S.C. 1').release_point = {n.release_point}"))

    size = cfg.index_path.stat().st_size
    counts = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in
              ["nodes", "node_ident", "refs", "notes", "source_credits", "definitions", "section_xml", "load_issues"]}
    issues = db.execute("SELECT kind, count(*) FROM load_issues WHERE rp=? GROUP BY 1", (rp,)).fetchall()
    defs = db.execute("SELECT reason, count(*) FROM definitions GROUP BY 1 ORDER BY 2 DESC LIMIT 4").fetchall()

    lines = ["# M1 gate", "", f"Release point {ix.release_point}; run {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}; "
             f"{time.monotonic() - t0:.0f}s.", "", "| Check | Result | Measured |", "| --- | --- | --- |"]
    lines += [f"| {name} | {'PASS' if ok else 'FAIL'} | {detail.replace('|', '/')} |" for name, ok, detail in checks]
    lines += ["", f"Index size: {size / 1e9:.2f} GB ({size:,} bytes) at `{cfg.index_path.relative_to(config.ROOT)}`.",
              "", "Row counts: " + ", ".join(f"{k} {v:,}" for k, v in counts.items()) + ".",
              "", "Load issues: " + ", ".join(f"{k} {v}" for k, v in issues) + ".",
              "", "Definitions: " + ", ".join(f"{k} {v:,}" for k, v in defs) + "."]
    out = cfg.var / "m1_gate.md"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
