"""M5 gate (docs/05-resolver.md): zero silent mis-resolutions on 50 Act-section references drawn from the
oracle corpus, checked against the next release point.

Truth for an instruction comes from OLRC's classification table for the amending law: the row whose law
section matches the instruction's bill location names the Code section (or note) it changed. A resolution
is silent and wrong when it claims a location (CODIFIED or NOTE) that the table contradicts and it is not
flagged for review. UNKNOWN, UNCODIFIED and SPLIT make no claim and are counted as unresolved, never dropped.

Run:  .venv/bin/python scripts/m5_gate.py [--sample 50] [--seed 20261028]      Writes var/m5_gate.md.
"""
from __future__ import annotations

import argparse
import collections
import random
import sys
import time

from ramseyer import config
from ramseyer.data.cite import normalize_section
from ramseyer.data.http import Fetcher
from ramseyer.data.index import Index, LookupError_
from ramseyer.oracle import harness, store
from ramseyer.oracle.corpus import Corpus
from ramseyer.parse import parse_text
from ramseyer.parse.xmltext import render
from ramseyer.resolve import popular
from ramseyer.resolve.actcode import classification_map
from ramseyer.resolve.cites import designation, parse_designation, prefix_match
from ramseyer.resolve.resolver import Resolver, classification_rows


def truth_for(law, bill_loc: str) -> set[tuple[str, str, bool]]:
    d = designation(bill_loc)
    if d is None:
        return set()
    sec, path = d
    matches = []
    for r in law.rows:
        rs, rpath = parse_designation(r.law_section)
        if rs == sec and prefix_match(rpath, path):
            matches.append((len(rpath), r))
    if not matches:
        return set()
    # Rows at or below the instruction's location all belong to it (a list-form repeal at 811(b) has rows at
    # 811(b)(1) and 811(b)(2)(A)); otherwise the deepest row above it.
    below = [r for n, r in matches if n >= len(path)]
    best = max(m[0] for m in matches)
    return {(r.title.lower(), normalize_section(r.section), "nt" in r.description.split())
            for r in (below or [r for n, r in matches if n == best])}


def claim(res, ix: Index):
    if res.outcome not in ("CODIFIED", "NOTE") or res.section_id is None:
        return None
    node = ix.by_identifier(res.note_anchor) if res.outcome == "NOTE" and res.note_anchor else ix._node(res.section_id)
    title = node.identifier.split("/")[3][1:]
    return title, node.identifier.split("/s", 1)[1].split("...")[0], res.outcome == "NOTE"


def oracle_changed(law, title: str, section: str) -> dict[str, bool]:
    """What changed for a section between the law's release points: its text, and its notes."""
    ident = f"/us/usc/t{title}/s{section}"
    out = {}
    for label in ("text", "notes"):
        vals = []
        for rp in (law.rp_before, law.rp_after):
            ix = store.index(rp)
            try:
                node = ix.by_identifier(ident)
            except LookupError_:
                vals.append(None)
                continue
            if label == "text":
                vals.append(node.text)
            else:
                vals.append(tuple(r[0] for r in ix.db.execute("SELECT text FROM notes WHERE section_id=? ORDER BY id",
                                                             (node.id,))))
        out[label] = vals[0] != vals[1]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=50)
    ap.add_argument("--seed", type=int, default=20261028)
    args = ap.parse_args()
    cfg = config.load()
    f = Fetcher(cfg)
    t0 = time.monotonic()
    ix = Index(cfg.index_path, cfg.release_pin)
    resolver = Resolver(ix, popular.load(), classification_map(classification_rows(f, cfg.olrc_base)))
    corpus = Corpus.load()
    refs, everything = [], collections.Counter()
    for law in corpus.laws:
        result = parse_text(render(f.get(law.enrolled_url).path))
        seen = set()
        for ins in result.instructions:
            if ins.op == "UNPARSED" or ("." in ins.id.split("#")[1] and not ins.id.endswith(".0")) or \
                    "rule of application, not an amendment" in ins.flags:      # not an amendment of the Code
                continue
            res = resolver.resolve(ins.target)
            everything[(ins.target.kind, res.outcome)] += 1
            if ins.target.kind not in ("act", "pl"):
                continue
            key = (law.pl, ins.target.cite_raw, tuple(ins.target.path), ins.bill_loc.split(".")[0])
            if key in seen:
                continue
            seen.add(key)
            refs.append((law, ins, res, truth_for(law, ins.bill_loc)))
    checkable = [r for r in refs if r[3]]
    sample = random.Random(args.seed).sample(checkable, min(args.sample, len(checkable)))

    def grade(items):
        g = collections.Counter()
        details = []
        for law, ins, res, truth in items:
            c = claim(res, ix)
            if c is None:
                g[f"unresolved:{res.outcome}"] += 1
                continue
            ok = c in truth
            kind_note = ""
            if not ok and (c[0], c[1], not c[2]) in truth:
                # Same section; the table and the resolution differ on text vs note. Ask the oracle which changed.
                ch = oracle_changed(law, c[0], c[1])
                ok = ch["notes"] if c[2] else ch["text"]
                g["note_vs_text_settled_by_oracle" if ok else "note_vs_text_contradicted"] += 1
                kind_note = f" [oracle: text changed {ch['text']}, notes changed {ch['notes']}]"
            flagged = (not res.verified) or "needs review" in res.flags
            g["correct" if ok else ("wrong_flagged" if flagged else "SILENT_WRONG")] += 1
            if not ok:
                details.append(f"{law.pl} {ins.bill_loc} '{ins.target.cite_raw}' -> {res.cite} "
                               f"({'flagged' if flagged else 'SILENT'}); table says {sorted(truth)}{kind_note}")
        return g, details

    g, details = grade(sample)
    # Next release point: each correct CODIFIED claim's section changed between the law's release points.
    changed = unchanged = pending = new = 0
    nochange = []
    for law, ins, res, truth in sample:
        c = claim(res, ix)
        if c is None or c not in truth or c[2]:
            continue
        before, after = store.index(law.rp_before), store.index(law.rp_after)
        ident = f"/us/usc/t{c[0]}/s{c[1]}"
        try:
            a_node = after.by_identifier(ident)
        except LookupError_:
            unchanged += 1
            nochange.append(f"{law.pl} {ins.bill_loc} -> {res.cite}: absent at {law.rp_after}")
            continue
        try:
            b = before.by_identifier(ident).text
        except LookupError_:
            new += 1                          # the law added this section
            continue
        if b != a_node.text:
            changed += 1
            continue
        # A delayed effective date: OLRC sets the amendment out in an "Amendment of Section" note instead.
        if harness.pending_note(law, before, after, ident):     # same test as the oracle harness
            pending += 1
            continue
        unchanged += 1
        if True:
            nochange.append(f"{law.pl} {ins.bill_loc} -> {res.cite}: notes changed "
                            f"{oracle_changed(law, c[0], c[1])['notes']}")
    ga, details_all = grade(checkable)
    checks = [
        (f"Zero silent mis-resolutions on {len(sample)} Act-section references (seed {args.seed})",
         g["SILENT_WRONG"] == 0 and len(sample) == args.sample,
         f"correct {g['correct']}, wrong but flagged {g['wrong_flagged']}, SILENT wrong {g['SILENT_WRONG']}, "
         + ", ".join(f"{k} {v}" for k, v in sorted(g.items()) if k.startswith("unresolved")) +
         (f"; wrong: {' | '.join(details)}" if details else "")),
        ("Resolved sections changed at the next release point", unchanged == 0,
         f"{changed + new + pending} of {changed + new + pending + unchanged} correct Code resolutions show the law at "
         f"R_after: text changed {changed}, section added {new}, amendment set out as a pending-effective-date note "
         f"{pending}"
         + (f"; unchanged: {' | '.join(nochange)}" if nochange else "")),
        ("All checkable Act references in the corpus (measurement)", ga["SILENT_WRONG"] == 0,
         f"{len(checkable)} references with a classification row ({len(refs)} Act references in all): correct "
         f"{ga['correct']}, wrong flagged {ga['wrong_flagged']}, SILENT wrong {ga['SILENT_WRONG']}, " +
         ", ".join(f"{k} {v}" for k, v in sorted(ga.items()) if k.startswith("unresolved")) +
         (f"; wrong: {' | '.join(details_all[:12])}" if details_all else "")),
    ]
    dist = collections.defaultdict(dict)
    for (kind, outcome), n in everything.items():
        dist[kind][outcome] = n
    lines = ["# M5 gate", "", f"Index {ix.release_point}; run {time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}; "
             f"{time.monotonic() - t0:.0f}s.", "", "| Check | Result | Measured |", "| --- | --- | --- |"]
    lines += [f"| {n} | {'PASS' if ok else 'FAIL'} | {d.replace('|', '/')} |" for n, ok, d in checks]
    lines += ["", "## Outcomes for every parsed corpus instruction, by target kind", ""]
    lines += [f"- {k}: " + ", ".join(f"{o} {n}" for o, n in sorted(v.items(), key=lambda x: -x[1])) for k, v in dist.items()]
    (cfg.var / "m5_gate.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if all(ok for _, ok, _ in checks[:2]) else 1


if __name__ == "__main__":
    sys.exit(main())
