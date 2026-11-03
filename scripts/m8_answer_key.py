"""M8 part 2: grade the comparative print against House committee reports' "Changes in Existing Law Made by the Bill,
as Reported" sections (House Rule XIII, clause 3(e); records/verify-first.md, M8).

For a fixed sample of 119th-Congress House reports (every k-th report by number) that carry that section and
accompany a House bill:
- the answer key: text the report omits, from the black brackets in its text version, and new matter, from the italic
  words in its PDF (needs pdfplumber: `uv pip install -e '.[answerkey]'`);
- ramseyer's print of the bill as reported (BILLS-119hr<N>rh), run against the pinned release point;
- word-level recall and precision of ramseyer's omitted and new words against the report's.
A bill the pinned release point already carries (enacted since the report) has nothing left to print and is counted
apart; so is a report whose changes are to Acts the Code does not hold (no Code section reached).

Run:  .venv/bin/python scripts/m8_answer_key.py [--every 20]     Writes var/m8_answer_key.md and var/m8_answer_key.jsonl.
Downloads stay under var/crpt.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys

from ramseyer import config
from ramseyer.analyze import analyze
from ramseyer.comparative.html import views
from ramseyer.comparative.redline import blocks
from ramseyer.data.http import Fetcher

WORD = re.compile(r"[\w$%.,/-]+")


def words(text: str) -> list[str]:
    return [w.strip(".,").lower() for w in WORD.findall(text) if w.strip(".,")]


def section_of(text: str) -> str | None:
    """The report's changes-in-existing-law section (the last heading of that name, after the table of contents)."""
    starts = [m.end() for m in re.finditer(r"(?i)changes in existing law (?:made|proposed) by the bill", text)]
    if not starts:
        return None
    body = text[starts[-1]:]
    end = re.search(r"\n\s*(?:ADDITIONAL|MINORITY|DISSENTING) VIEWS", body)
    return body[:end.start()] if end else body


def omitted_spans(sec: str) -> list[str]:
    """Text in black brackets. A long omitted passage opens a bracket at each of its paragraphs and closes once at its
    end ("[(a) ... [(1) ... [(2) ... ."]"), so every "[" inside an open bracket continues it, and "]" closes it."""
    spans, buf, depth = [], [], False
    for ch in sec:
        if ch == "[":
            depth = True
            continue
        if ch == "]" and depth:
            spans.append("".join(buf))
            buf, depth = [], False
            continue
        if depth:
            buf.append(ch)
    return spans


def key_from(htm: str, pdf_path) -> tuple[list[str], list[str]]:
    """(omitted words, new words) printed in the report's changes section."""
    import pdfplumber
    sec = section_of(re.sub(r"<[^>]+>", "", htm)) or ""
    omitted = [w for span in omitted_spans(sec) for w in words(span)]
    new: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        inside = False
        for page in pdf.pages:
            text = page.extract_text() or ""
            if re.search(r"(?i)changes in existing law (?:made|proposed) by the bill", text) and \
                    "......" not in text:
                inside = True
            if not inside:
                continue
            new += [w for x in page.extract_words(extra_attrs=["fontname"]) if "Italic" in x["fontname"]
                    for w in words(x["text"])]
            if re.search(r"(?i)(additional|minority|dissenting) views", text):
                break
    return omitted, new


def overlap(ours: list[str], key: list[str]) -> int:
    a, b = collections.Counter(ours), collections.Counter(key)
    return sum(min(a[w], b[w]) for w in a)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=int, default=20)
    ap.add_argument("--offset", type=int, default=0,
                    help="start the every-k sample here; --offset 10 is disjoint from the tuning sample (review of #22)")
    ap.add_argument("--tag", default="", help="suffix for the output files")
    args = ap.parse_args()
    cfg = config.load()
    f = Fetcher(cfg)
    key_env = os.environ.get("API_DATA_GOV_KEY", "")
    out_dir = cfg.var / "crpt"
    out_dir.mkdir(exist_ok=True)
    pkgs, url = [], ("https://api.govinfo.gov/collections/CRPT/2025-01-01T00:00:00Z?pageSize=100&offsetMark=%2A"
                     "&congress=119&docClass=hrpt")
    while url:
        d = json.loads(f.get(url + f"&api_key={key_env}", refresh=True).path.read_text())
        pkgs += [p["packageId"] for p in d.get("packages", [])]
        url = d.get("nextPage") or None
        if url:
            url = re.sub(r"&api_key=[^&]*", "", url)
    nums = sorted({int(m.group(1)) for p in pkgs if (m := re.fullmatch(r"CRPT-119hrpt(\d+)", p))})
    sample = nums[args.offset::args.every]
    rows, tallies = [], collections.Counter()
    for n in sample:
        pid = f"CRPT-119hrpt{n}"
        print(pid, file=sys.stderr, flush=True)
        htm = f.get(f"https://www.govinfo.gov/content/pkg/{pid}/html/{pid}.htm").path.read_text(errors="replace")
        bill = re.search(r"\[To accompany H\.R\. (\d+)\]", htm)
        if not section_of(htm) or not bill:
            tallies["no changes section or not a House bill"] += 1
            continue
        try:
            xml = f.get(f"https://www.govinfo.gov/content/pkg/BILLS-119hr{bill.group(1)}rh/xml/"
                        f"BILLS-119hr{bill.group(1)}rh.xml")
            pdf = f.get(f"https://www.govinfo.gov/content/pkg/{pid}/pdf/{pid}.pdf").path
        except Exception as e:                      # noqa: BLE001 - reported per report, never dropped
            tallies["bill text or PDF not available"] += 1
            rows.append({"report": pid, "skipped": f"download: {e}"})
            continue
        omitted_key, new_key = key_from(htm, pdf)
        if not omitted_key and not new_key:
            # The report defers its comparative print ("will make the analysis available as soon as possible",
            # report 231, H.R. 3838): no answer key to grade against.
            tallies["report prints no changes (deferred or published separately)"] += 1
            rows.append({"report": pid, "skipped": "the report's changes section marks no text"})
            continue
        a = analyze(f"H.R. {bill.group(1)} (reported).xml", xml.path.read_bytes())
        if a.counts and set(a.counts) <= {"ALREADY_EXECUTED"}:
            tallies["already in the pinned Code (enacted since)"] += 1
            rows.append({"report": pid, "skipped": "already executed at the pinned release point"})
            continue
        run = a.run
        ours_del, ours_ins = [], []
        for v in views(run) + (views(a.act) if getattr(a, "act", None) is not None else []):
            if v.tree is None:
                continue
            for b in blocks(v.tree):
                for r in b.runs:
                    (ours_del if r.state == "del" else ours_ins if r.state == "ins" else []).extend(words(r.text))
        if not ours_del and not ours_ins:
            tallies["no Code section reached"] += 1
            rows.append({"report": pid, "skipped": "no Code section reached", "counts": a.counts})
            continue
        tallies["graded"] += 1
        row = {"report": pid, "bill": f"H.R. {bill.group(1)}", "counts": a.counts,
               "key_omitted": len(omitted_key), "key_new": len(new_key),
               "ours_omitted": len(ours_del), "ours_new": len(ours_ins),
               "omitted_hit": overlap(ours_del, omitted_key), "new_hit": overlap(ours_ins, new_key)}
        rows.append(row)
    graded = [r for r in rows if "omitted_hit" in r]

    def ratio(num, den):
        return f"{num / den:.1%}" if den else "n/a"
    ok, kn = sum(r["key_omitted"] for r in graded), sum(r["key_new"] for r in graded)
    oo, on = sum(r["ours_omitted"] for r in graded), sum(r["ours_new"] for r in graded)
    ho, hn = sum(r["omitted_hit"] for r in graded), sum(r["new_hit"] for r in graded)
    lines = ["# M8 part 2: the print against committee reports", "",
             f"House reports, 119th Congress: {len(nums)}; sample (every {args.every}th from position {args.offset}): "
             f"{len(sample)}", "",
             "| Sample | Reports |", "| --- | --- |"] + [f"| {k} | {v} |" for k, v in tallies.most_common()] + [
             "", "| Words | Report | ramseyer | In both | Recall | Precision |", "| --- | --- | --- | --- | --- | --- |",
             f"| Omitted | {ok} | {oo} | {ho} | {ratio(ho, ok)} | {ratio(ho, oo)} |",
             f"| New matter | {kn} | {on} | {hn} | {ratio(hn, kn)} | {ratio(hn, on)} |", "",
             "## Per report", ""] + [
             f"- {r['report']} ({r.get('bill', '')}): " + (r["skipped"] if "skipped" in r else
             f"omitted {r['omitted_hit']}/{r['key_omitted']} (ours {r['ours_omitted']}), new {r['new_hit']}/"
             f"{r['key_new']} (ours {r['ours_new']}); statuses {r['counts']}") for r in rows]
    (cfg.var / f"m8_answer_key{args.tag}.md").write_text("\n".join(lines) + "\n")
    with open(cfg.var / f"m8_answer_key{args.tag}.jsonl", "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print("\n".join(lines[:20]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
