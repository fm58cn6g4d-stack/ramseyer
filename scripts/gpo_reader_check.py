"""M6e: GPO as a second reader, measured before it is used (docs/06-dry-run.md).

For each law of a history set, GPO's public-law USLM is read (parse/gpo.py): per bill location, the amending verbs
and the Code citations it tags. Each instruction the gate graded (its trace, in var/<tag>_checkpoint.jsonl) is
compared by location with the Code section it was applied to: GPO agrees (it cites that section), disagrees (it
cites only other sections), or is silent (no Code citation there or above it, or no USLM for the law).

Reported per CLEAN section: how many of the false cleans a "GPO disagrees" rule would have lowered to WARN, and how
many right ones it would cost. Nothing changes a status here.
Run:  .venv/bin/python scripts/gpo_reader_check.py [--set history_dev]      Writes var/gpo_reader_<set>.md.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys

from ramseyer import config
from ramseyer.data.http import Fetcher
from ramseyer.parse.gpo import readings, section_of, uslm_path

# ramseyer's operation -> the GPO amendingAction types that describe it.
VERBS = {"STRIKE": {"delete"}, "STRIKE_INSERT": {"delete", "insert", "substitute", "amend"},
         "INSERT_AFTER": {"insert", "add"}, "INSERT_BEFORE": {"insert", "add"}, "ADD_END": {"add", "insert"},
         "ADD_UNIT_AFTER": {"add", "insert"}, "ADD_UNIT_BEFORE": {"add", "insert"},
         "REPLACE_UNIT": {"amend", "substitute", "delete", "insert"}, "REDESIGNATE": {"redesignate"},
         "STRIKE_UNIT": {"delete", "repeal"}, "REPEAL": {"repeal", "delete"},
         "AMEND_HEADING": {"delete", "insert", "amend", "substitute"}, "STRIKE_THROUGH": {"delete", "insert"}}
TAGS = {"history_dev": "m6e_dev", "history_test": "m6e_test", "history_sealed": "m6e_sealed", "tuning": "m6"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="history_dev", choices=sorted(TAGS))
    a = ap.parse_args()
    cfg = config.load()
    f = Fetcher(cfg)
    lines = (cfg.var / f"{TAGS[a.set]}_checkpoint.jsonl").read_text().splitlines()[1:]
    by_ins = collections.Counter()
    sections = collections.Counter()
    examples = []
    no_uslm = []
    for line in lines:
        rec = json.loads(line)
        pl = rec["pl"]
        path = uslm_path(f, cfg, pl)
        if path is None:
            no_uslm.append(pl)
        read = readings(path) if path is not None else {}
        verdict: dict[str, str] = {}                  # section -> worst verdict over its CLEAN instructions
        for t in rec["extra"]["traces"]:
            if t["status"] != "CLEAN" or not t["section"]:
                continue
            loc = t["id"].split("#")[0]
            r = read.get(loc)
            while r is None and "." in loc:
                loc = loc.rsplit(".", 1)[0]
                r = read.get(loc)
            secs = {section_of(h) for h in (r.usc if r else [])} - {None}
            v = "silent" if not secs else ("agrees" if t["section"] in secs else "disagrees")
            own = read.get(t["id"].split("#")[0])
            if v != "disagrees" and own is not None and own.verbs and t["op"] in VERBS and \
                    not set(own.verbs) & VERBS[t["op"]]:
                v = "disagrees"                       # GPO tags a verb at this very location that ours is not
            by_ins[v] += 1
            if v == "disagrees" or verdict.get(t["section"]) is None:
                verdict[t["section"]] = v if verdict.get(t["section"]) != "disagrees" else "disagrees"
            if v == "disagrees" and len(examples) < 40:
                examples.append(f"{pl} {t['id']}: ours {t['section']}, GPO {sorted(secs)}")
        for o in rec["outcomes"]:
            if o["status"] != "CLEAN" or o["outcome"] not in ("match", "mismatch"):
                continue
            wrong = o["outcome"] == "mismatch" and o["stage"] != "editorial" and \
                o["identifier"] not in rec["extra"].get("editorial", {})
            sections[(verdict.get(o["identifier"], "silent"), "wrong" if wrong else "right")] += 1
    out = [f"# GPO as a second reader ({a.set})", "",
           f"Laws: {len(lines)}; without public-law USLM: {len(no_uslm)}"
           + (f" ({', '.join(no_uslm[:12])})" if no_uslm else ""), "",
           "CLEAN instructions by GPO's Code citation at their bill location: "
           + ", ".join(f"{k} {v}" for k, v in by_ins.most_common()), "",
           "| GPO on the section's CLEAN instructions | Right in substance | Wrong in substance |", "| --- | --- | --- |"]
    for v in ("agrees", "silent", "disagrees"):
        out.append(f"| {v} | {sections[(v, 'right')]} | {sections[(v, 'wrong')]} |")
    out += ["", "A rule lowering CLEAN to WARN where GPO disagrees would catch "
            f"{sections[('disagrees', 'wrong')]} wrong and cost {sections[('disagrees', 'right')]} right.", "",
            "## Disagreements (first 40)", ""] + [f"- {e}" for e in examples]
    (cfg.var / f"gpo_reader_{a.set}.md").write_text("\n".join(out) + "\n")
    print("\n".join(out[:14]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
