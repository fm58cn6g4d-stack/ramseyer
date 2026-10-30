"""M6d: check the incorporated-set release-point rule (src/ramseyer/oracle/releases.py) on OLRC's real labels.

1. Every label on OLRC's prior-release-points page parses, and the label order rule reproduces the page's own
   publication order.
2. For every public law in the 119th Congress classification tables, the window from the new rule is compared
   with the rule it replaces (a label ending "not<law>" in the 119th Congress, else the plain labels around the
   law's number). Each difference is listed.
Run:  .venv/bin/python scripts/release_windows_check.py [--refresh]
Writes var/release_windows_check.md.
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from urllib.parse import urljoin

from ramseyer import config
from ramseyer.data.http import Fetcher
from ramseyer.oracle import releases
from ramseyer.oracle.candidates import discover, num


def old_window(rps, plain, pl):
    """The rule M6d replaces (candidates.Discovery.window before 2026-10-30), kept here only for comparison."""
    excepted = [l for l in rps if l.endswith(f"not{num(pl)}") and l.startswith("119-")]
    if excepted:
        return excepted[0], excepted[0].split("not")[0]
    after = next((l for l in plain if num(l) >= num(pl)), None)
    if after is None or plain.index(after) == 0:
        return None
    return plain[plain.index(after) - 1], after


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="refetch OLRC's prior-release-points page")
    a = ap.parse_args()
    cfg = config.load()
    f = Fetcher(cfg)
    page = f.get(urljoin(cfg.olrc_base, "priorreleasepoints.html"), refresh=a.refresh).text()
    listed = [t.strip() for _, t in re.findall(r'<a class="releasepoint" href="([^"]+)">([^<]+)</a>', page)]
    labels = [re.search(r"(\d+-\d+\S*)", t).group(1) for t in listed]
    bad, parsed = [], []
    for l in labels:
        try:
            parsed.append(releases.parse(l))
        except ValueError:
            bad.append(l)
    # The page lists newest first.
    page_order = [p.raw for p in reversed(parsed)]
    rule_order = [p.raw for p in sorted(parsed, key=lambda p: p.order)]
    out_of_order = [(x, y) for x, y in zip(page_order, rule_order) if x != y]
    stats = collections.Counter()
    for p in parsed:
        stats["with u suffix"] += bool(p.reissue)
        stats["with one excluded law"] += len(p.excluded) == 1
        stats["with several excluded laws"] += len(p.excluded) > 1

    d = discover(f, cfg.olrc_base, include_current=True)
    every = list(d.rps)
    diffs, same, none_both = [], 0, 0
    for pl in sorted((p for p in d.by_law if p.startswith("119-")), key=num):
        new = releases.window(every, pl)
        old = old_window(d.rps, d.plain, pl)
        if new == old:
            same += 1 if new else 0
            none_both += 0 if new else 1
        else:
            diffs.append((pl, old, new))

    lines = ["# Release-point window check (M6d)", "",
             "| Measure | Result |", "| --- | --- |",
             f"| Labels on OLRC's prior-release-points page | {len(labels)} |",
             f"| … that do not parse | {len(bad)}{': ' + ', '.join(bad) if bad else ''} |",
             *[f"| … {k} | {v} |" for k, v in sorted(stats.items())],
             f"| Label order rule reproduces the page's publication order | "
             f"{'yes' if not out_of_order else f'no, {len(out_of_order)} positions differ'} |",
             f"| 119th Congress laws in the classification tables | {same + none_both + len(diffs)} |",
             f"| … same window under both rules | {same} |",
             f"| … no window under either rule | {none_both} |",
             f"| … window differs | {len(diffs)} |", ""]
    if out_of_order:
        lines += ["## Order differences (page, rule)", ""] + [f"- {x} | {y}" for x, y in out_of_order[:30]] + [""]
    if diffs:
        lines += ["## Window differences (law: old rule -> new rule)", ""]
        for pl, old, new in diffs:
            lines.append(f"- {pl}: {old} -> {new}; entering under the new rule: "
                         f"{', '.join(releases.entering(*new, d.by_law)) if new else '-'}")
    (cfg.var / "release_windows_check.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if not bad and not out_of_order else 1


if __name__ == "__main__":
    sys.exit(main())
