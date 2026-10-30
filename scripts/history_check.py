"""M6e: check the release-point history against release points indexed straight from OLRC's zips.

For every release point that is both in the oracle index (var/oracle/oracle.sqlite, built from OLRC's zips by
scripts/build_corpus.py) and in the history (var/history/history.sqlite, scripts/load_history.py), the same titles
are materialized from the history (oracle/history.materialize) and every section is compared:
  - text (text_plain), heading and status, exactly;
  - the set of subunit identifiers;
  - the notes (type, heading, text) and the source credits, in order.
Not compared: references, chapter-level structure and notes, and section order within a title.
Also: the history's release labels all parse, the label order rule reproduces the dataset's publication sequence,
and the M6d window rule is run over the full label list.
Run:  .venv/bin/python scripts/history_check.py [--labels 119-100 ...]
Writes var/history_check.md.
"""
from __future__ import annotations

import argparse
import collections
import sqlite3
import sys

from ramseyer import config
from ramseyer.oracle import releases as rl
from ramseyer.oracle.history import History, materialize

ORACLE = config.VAR / "oracle" / "oracle.sqlite"
CHECK = config.VAR / "history" / "check.sqlite"


def sections(db, rp: int) -> dict[str, tuple]:
    """identifier -> (text, heading, status, subunit identifiers, notes, source credits)."""
    out = {i: (t, h, s, set(), [], []) for i, t, h, s in db.execute(
        "SELECT identifier, text_plain, heading, status FROM nodes WHERE rp=? AND kind='section'", (rp,))}
    by_id = {nid: i for nid, i in db.execute("SELECT id, identifier FROM nodes WHERE rp=? AND kind='section'", (rp,))}
    for sid, ident in db.execute("SELECT section_id, identifier FROM nodes WHERE rp=? AND kind<>'section'", (rp,)):
        sec = by_id.get(sid)
        if sec in out:
            out[sec][3].add(ident)
    for sid, ntype, heading, text in db.execute(
            "SELECT n.section_id, n.note_type, n.heading, n.text FROM notes n JOIN nodes s ON s.id=n.section_id "
            "WHERE s.rp=? ORDER BY n.id", (rp,)):
        if by_id.get(sid) in out:
            out[by_id[sid]][4].append((ntype, heading, text))
    for sid, raw in db.execute("SELECT c.section_id, c.raw FROM source_credits c JOIN nodes s ON s.id=c.section_id "
                               "WHERE s.rp=? ORDER BY c.id", (rp,)):
        if by_id.get(sid) in out:
            out[by_id[sid]][5].append(raw)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", nargs="*")
    ap.add_argument("--show", type=int, default=25)
    a = ap.parse_args()
    cfg = config.load()
    h = History(cfg.var / "history" / "history.sqlite")
    hist = h.releases()
    lines = ["# Release-point history check (M6e)", ""]

    # Labels.
    bad = [r.label for r in hist if not rl.LABEL_RE.match(r.label)]
    by_rule = [p.raw for p in sorted((rl.parse(r.label) for r in hist if r.label not in bad), key=lambda p: p.order)]
    by_seq = [r.label for r in hist if r.label not in bad]
    disorder = [(x, y) for x, y in zip(by_seq, by_rule) if x != y]
    parsed = [rl.parse(l) for l in by_seq]
    lines += ["| Labels | Result |", "| --- | --- |",
              f"| Release points in the history | {len(hist)} ({hist[0].label} to {hist[-1].label}) |",
              f"| … that do not parse | {len(bad)}{': ' + ', '.join(bad[:10]) if bad else ''} |",
              f"| … with a u suffix | {sum(1 for p in parsed if p.reissue)} |",
              f"| … with several excluded laws | {sum(1 for p in parsed if len(p.excluded) > 1)} |",
              f"| Label order rule reproduces the dataset's publication sequence | "
              f"{'yes' if not disorder else f'no: {len(disorder)} positions'} |", ""]
    if disorder:
        lines += ["Order differences (sequence, rule): " + "; ".join(f"{x} / {y}" for x, y in disorder[:15]), ""]

    # Sections, against OLRC zips.
    oracle = sqlite3.connect(ORACLE)
    shared = [l for (l,) in oracle.execute("SELECT label FROM release_points WHERE complete=1 ORDER BY id")
              if l in {r.label for r in hist}]
    if a.labels:
        shared = [l for l in shared if l in a.labels]
    totals = collections.Counter()
    examples = []
    rows = ["| Release point | Titles | Sections (OLRC / history) | Identical | Text | Heading | Status | "
            "Structure | Notes | Credits | Only in OLRC | Only in history |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for label in shared:
        rp_o = oracle.execute("SELECT id FROM release_points WHERE label=?", (label,)).fetchone()[0]
        titles = [t for (t,) in oracle.execute("SELECT title FROM titles WHERE rp=? ORDER BY title", (rp_o,))]
        rp_h = materialize(h, label, titles, CHECK, log=lambda s: examples.append(("load", label, s)))
        chk = sqlite3.connect(CHECK)
        so, sh = sections(oracle, rp_o), sections(chk, rp_h)
        incomplete = {d for (d,) in chk.execute("SELECT detail FROM load_issues WHERE rp=? AND kind='history_incomplete'",
                                                (rp_h,))}
        c = collections.Counter()
        for ident in so.keys() & sh.keys():
            o, x = so[ident], sh[ident]
            diff = [k for k, i in (("text", 0), ("heading", 1), ("status", 2), ("structure", 3), ("notes", 4),
                                   ("credits", 5)) if o[i] != x[i]]
            if diff and ident in incomplete:
                c["incomplete in the source data"] += 1
                examples.append(("incomplete in the source data (not graded)", label, ident))
                continue
            c["identical" if not diff else "different"] += 1
            for k in diff:
                c[k] += 1
                if len(examples) < 400:
                    examples.append((k, label, ident))
        c["only_olrc"] = len(so.keys() - sh.keys())
        c["only_history"] = len(sh.keys() - so.keys())
        examples += [("only in OLRC", label, i) for i in sorted(so.keys() - sh.keys())[:5]]
        examples += [("only in history", label, i) for i in sorted(sh.keys() - so.keys())[:5]]
        totals.update(c)
        rows.append(f"| {label} | {', '.join(titles)} | {len(so)} / {len(sh)} | {c['identical']} | {c['text']} | "
                    f"{c['heading']} | {c['status']} | {c['structure']} | {c['notes']} | {c['credits']} | "
                    f"{c['only_olrc']} | {c['only_history']} |")
    compared = totals["identical"] + totals["different"] + totals["incomplete in the source data"]
    lines += [f"## Sections: history vs OLRC's zips ({len(shared)} release points)", "", *rows, "",
              f"Total: {totals['identical']} of {compared} sections identical "
              f"({totals['identical'] / max(compared, 1):.2%}); text {totals['text']}, heading {totals['heading']}, "
              f"status {totals['status']}, structure {totals['structure']}, notes {totals['notes']}, "
              f"credits {totals['credits']}; incomplete in the source data and marked "
              f"not gradable {totals['incomplete in the source data']}; only in OLRC {totals['only_olrc']}, "
              f"only in history {totals['only_history']}.", ""]
    if examples:
        lines += [f"## First {a.show} differences", ""] + [f"- {k} @ {l}: `{i}`" for k, l, i in examples[:a.show]]
    (cfg.var / "history_check.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:40]))
    return 0 if (not bad and not disorder and compared and totals["different"] == 0 and not totals["only_olrc"]
                 and not totals["only_history"]) else 1


if __name__ == "__main__":
    sys.exit(main())
