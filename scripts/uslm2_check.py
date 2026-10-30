"""M6d: check that USLM 2.x Code titles index to the same text as USLM 1.0 (src/ramseyer/data/uslm.py, to_v1).

OLRC's 2.0.12 sample titles (1, 16 and 49, converted 2023-06-29; aih/uscode-redesign samples/uslm2) are indexed
into a scratch index through the normal indexer, then each section is paired with the pinned 1.0 release point
by identifier. The two dates differ, so only sections whose source credit is identical in both are compared: a
law that changed a section in between also changes its credit. For each compared section the check reports
  - text: text_plain (operative text) and heading, exactly;
  - structure: the set of subunit identifiers below the section.
Run:  .venv/bin/python scripts/uslm2_check.py [--samples DIR] [--show 20]
Writes var/uslm2_check.md and var/uslm2_check.jsonl (one line per differing section).
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import zlib
import sys
import zipfile
from pathlib import Path

from ramseyer import config
from lxml import etree

from ramseyer.data.indexer import NON_OPERATIVE, Indexer, text_of

# OLRC's 2.x sample titles, from aih/uscode-redesign (samples/uslm2/USLM2/usc01.xml, usc16.xml, usc49.xml); fetch with
#   git clone --depth 1 --filter=blob:none --sparse https://github.com/aih/uscode-redesign <dir>
#   git -C <dir> sparse-checkout set samples/uslm2 && cp <dir>/samples/uslm2/USLM2/usc*.xml var/uslm2/samples/
SAMPLES = config.VAR / "uslm2" / "samples"
LABEL = "uslm2-sample-2023-06-29"
REVIEWED = Path(__file__).resolve().parents[1] / "tests" / "oracle" / "uslm2_reviewed.json"


def sections(db: sqlite3.Connection, rp: int, titles: list[str]) -> dict[str, dict]:
    out, by_id = {}, {}
    marks = ",".join("?" * len(titles))
    q = (f"SELECT id, title, identifier, heading, text_plain, status FROM nodes "
         f"WHERE rp=? AND kind='section' AND title IN ({marks})")
    for nid, title, ident, heading, text, status in db.execute(q, (rp, *titles)):
        by_id[nid] = out[ident] = {"title": title, "heading": heading, "text": text, "status": status,
                                   "credits": set(), "subs": set()}
    # One pass per table (a lookup per section is slow where section_id is not indexed).
    for sid, raw in db.execute(f"SELECT c.section_id, c.raw FROM source_credits c JOIN nodes n ON n.id=c.section_id "
                               f"WHERE n.rp=? AND n.title IN ({marks})", (rp, *titles)):
        if sid in by_id:
            by_id[sid]["credits"].add(raw)
    for sid, nid, ident in db.execute(f"SELECT section_id, id, identifier FROM nodes WHERE rp=? AND title IN ({marks})",
                                      (rp, *titles)):
        if sid in by_id and sid != nid:
            by_id[sid]["subs"].add(ident)
    for s in out.values():
        s["credit"] = " | ".join(sorted(s.pop("credits")))
    return out


# A subunit's heading line, "(a) In general" or "(a) In General.—": 2.x samples print Act-style headings.
HEAD_LINE = re.compile(r"^(\([^)]+\)) (.+?)[.—]*$")


def squash(t: str) -> str:
    return "".join(t.split())


def heading_folded(t: str) -> str:
    out = []
    for line in t.split("\n"):
        m = HEAD_LINE.match(line)
        heading = m and len(m.group(2)) < 250 and ".—" not in m.group(2)
        out.append(m.group(1) + m.group(2).lower().rstrip(".") if heading else line)
    # A heading run into its text keeps the Act's ".—" mid-line ("(b) Boundary Modification.—The boundaries").
    return squash("\n".join(out).replace(".—", ""))


def without_footnote_refs(db: sqlite3.Connection, rp: int, ident: str) -> str:
    row = db.execute("SELECT x.xml_zlib FROM section_xml x JOIN nodes n ON n.id=x.node_id "
                     "WHERE n.rp=? AND n.identifier=? AND n.kind='section'", (rp, ident)).fetchone()
    el = etree.fromstring(zlib.decompress(row[0]))
    # A marker is <ref class="footnoteRef"> or, in 1.0 headings, a bare <sup>1</sup>.
    for ref in list(el.iter("{*}ref", "{*}sup")):
        if "footnoteRef" in (ref.get("class") or "") or (etree.QName(ref).localname == "sup"
                                                         and "".join(ref.itertext()).strip().isdigit()):
            parent, prev = ref.getparent(), ref.getprevious()
            if ref.tail:
                if prev is not None:
                    prev.tail = (prev.tail or "") + ref.tail
                else:
                    parent.text = (parent.text or "") + ref.tail
            parent.remove(ref)
    return text_of(el)


def why_text_differs(a: str, b: str, fn_a, fn_b) -> str:
    """The first explanation that accounts for the whole difference; 'unexplained' if none does."""
    if squash(a) == squash(b):
        return "layout only (line breaks or spacing)"
    if heading_folded(a) == heading_folded(b):
        return "heading style (Act-style headings in 2.x)"
    fa, fb = fn_a(), fn_b()
    if heading_folded(fa) == heading_folded(fb):
        return "footnote markers (and heading style)"
    if heading_folded(fa).casefold() == heading_folded(fb).casefold():
        return "case of a status or heading line (and the above)"
    return "unexplained"


def first_diff(a: str, b: str) -> str:
    # A common-prefix scan: SequenceMatcher is quadratic on long sections with large tables.
    i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return f"at char {i}: 1.0 …{a[max(0, i - 40):i + 60]!r}… | 2.x …{b[max(0, i - 40):i + 60]!r}…"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=Path, default=SAMPLES)
    ap.add_argument("--show", type=int, default=20)
    a = ap.parse_args()
    cfg = config.load()
    files = sorted(a.samples.glob("usc*.xml"))
    if not files:
        print(f"no sample titles under {a.samples}", file=sys.stderr)
        return 2
    work = cfg.var / "uslm2"
    work.mkdir(parents=True, exist_ok=True)
    zp = work / "samples.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.name)
    scratch = work / "uslm2.sqlite"
    for p in (scratch, Path(f"{scratch}-wal"), Path(f"{scratch}-shm")):
        p.unlink(missing_ok=True)
    ix = Indexer(scratch)
    rp2 = ix.load_release_point(zp, LABEL, "2023-06-29", str(a.samples), log=lambda m: print("  " + m))
    ix.mark_complete(rp2)
    issues = collections.Counter(k for (k,) in ix.db.execute("SELECT kind FROM load_issues WHERE rp=?", (rp2,)))
    titles = [t for (t,) in ix.db.execute("SELECT title FROM titles WHERE rp=?", (rp2,))]
    v2 = sections(ix.db, rp2, titles)

    main_db = sqlite3.connect(cfg.index_path)
    rp1, label1 = main_db.execute("SELECT id, label FROM release_points WHERE complete=1 ORDER BY id DESC").fetchone()
    v1 = sections(main_db, rp1, titles)

    # Identifiers as published in the raw 2.x files, to tell a nesting OLRC published from one the seam made; and
    # fidelity: the raw 2.x text (no conversion; inline footnotes skipped, as 1.0 keeps them in notes) must hold
    # exactly the non-whitespace characters the index stored, in order, so the seam adds, drops and reorders no text
    # (line breaks and spacing are compared separately, in the 1.0 comparison below).
    published: dict[str, set[str]] = {}
    fidelity, unfaithful = collections.Counter(), []
    skip = frozenset(NON_OPERATIVE | {"footnote"})
    for f in files:
        for sec in etree.parse(str(f)).getroot().iter("{*}section"):
            ident = sec.get("identifier")
            if not ident or any(etree.QName(a).localname == "section" for a in sec.iterancestors()):
                continue
            published[ident] = {e.get("identifier") for e in sec.iter() if isinstance(e.tag, str)
                                and e is not sec and e.get("identifier")}
            if ident in v2:
                same = squash(text_of(sec, skip)) == squash(v2[ident]["text"])
                fidelity["same" if same else "different"] += 1
                if not same:
                    unfaithful.append(ident)
    both = sorted(set(v1) & set(v2))
    same_credit = [i for i in both if v1[i]["credit"] == v2[i]["credit"]]
    rows, counts = [], collections.Counter()
    for i in same_credit:
        s1, s2 = v1[i], v2[i]
        bad = []
        if s1["text"] != s2["text"]:
            why = why_text_differs(s1["text"], s2["text"], lambda: without_footnote_refs(main_db, rp1, i),
                                   lambda: without_footnote_refs(ix.db, rp2, i))
            counts["text: " + why] += 1
            shown = (first_diff(s1["text"], s2["text"]) if why != "unexplained" else
                     first_diff(heading_folded(without_footnote_refs(main_db, rp1, i)).casefold(),
                                heading_folded(without_footnote_refs(ix.db, rp2, i)).casefold()) + " (normalized)")
            bad.append(("text", f"{why}; " + shown))
        if s1["heading"] != s2["heading"]:
            bad.append(("heading", f"{s1['heading']!r} | {s2['heading']!r}"))
        if s1["subs"] != s2["subs"]:
            why = ("as published (the 2.x file carries these identifiers)" if s2["subs"] <= published.get(i, set())
                   else "unexplained")
            counts["structure: " + why] += 1
            bad.append(("structure", f"{why}; only 1.0: {sorted(s1['subs'] - s2['subs'])[:5]}; "
                                     f"only 2.x: {sorted(s2['subs'] - s1['subs'])[:5]}"))
        if s1["status"] != s2["status"]:
            bad.append(("status", f"{s1['status']} | {s2['status']}"))
        counts["identical" if not bad else "different"] += 1
        for kind, detail in bad:
            counts[kind] += 1
        if bad:
            rows.append({"identifier": i, "differences": bad})

    out = cfg.var / "uslm2_check.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    lines = [
        "# USLM 2.x seam check (M6d)", "",
        f"2.x sample titles {', '.join(titles)} ({LABEL}) indexed through `uslm.to_v1`, compared with the 1.0 "
        f"release point {label1}.", "",
        "| Measure | Count |", "| --- | --- |",
        f"| Sections in the 2.x samples | {len(v2)} |",
        f"| Fidelity: indexed text holds exactly the raw 2.x non-whitespace characters | {fidelity['same']} of "
        f"{fidelity['same'] + fidelity['different']} |",
        f"| Sections in the 1.0 index for these titles | {len(v1)} |",
        f"| In both, by identifier | {len(both)} |",
        f"| In both with identical source credits (compared) | {len(same_credit)} |",
        f"| Compared and identical in text, heading, structure and status | {counts['identical']} |",
        f"| Compared and different | {counts['different']} |",
        f"| … text differs | {counts['text']} |",
        *[f"| … … {k[6:]} | {v} |" for k, v in sorted(counts.items()) if k.startswith("text: ")],
        f"| … heading differs | {counts['heading']} |",
        f"| … subunit identifiers differ | {counts['structure']} |",
        *[f"| … … {k[11:]} | {v} |" for k, v in sorted(counts.items()) if k.startswith("structure: ")],
        f"| … status differs | {counts['status']} |", "",
        "Load issues in the 2.x index: " + (", ".join(f"{k} {v}" for k, v in sorted(issues.items())) or "none"), "",
    ]
    reviewed = {k: v for k, v in json.loads(REVIEWED.read_text()).items() if not k.startswith("_")}
    needs_reason = [r for r in rows if any(d.startswith("unexplained") or k in ("heading", "status")
                                           for k, d in r["differences"])]
    for r in needs_reason:
        if r["identifier"] in reviewed:
            r["reviewed"] = reviewed[r["identifier"]]
    unexplained = [r for r in needs_reason if "reviewed" not in r]
    stale = sorted(set(reviewed) - {r["identifier"] for r in needs_reason})
    lines += [f"Reviewed publication differences (tests/oracle/uslm2_reviewed.json): {len(needs_reason) - len(unexplained)}"
              + (f"; entries no longer needed: {', '.join(stale)}" if stale else ""), ""]
    for r in needs_reason:
        if "reviewed" in r:
            lines.append(f"- `{r['identifier']}` ({r['reviewed']['kind']}): {r['reviewed']['reason']}")
    if unexplained:
        lines += ["", f"## Differences not explained by layout, heading style, footnote markers or review ({len(unexplained)})",
                  "", "Each needs a reason in tests/oracle/uslm2_reviewed.json after checking it, or a fix.", ""]
        for r in unexplained:
            for kind, detail in r["differences"]:
                if kind in ("heading", "status") or detail.startswith("unexplained"):
                    lines.append(f"- `{r['identifier']}` {kind}: {detail}")
    explained = [r for r in rows if r not in unexplained]
    if explained:
        lines += ["", f"## First {min(a.show, len(explained))} explained differences", ""]
        for r in explained[:a.show]:
            for kind, detail in r["differences"]:
                lines.append(f"- `{r['identifier']}` {kind}: {detail}")
    if unfaithful:
        lines += ["", f"## Sections the seam changed ({len(unfaithful)})", ""] + [f"- `{i}`" for i in unfaithful[:50]]
    report = cfg.var / "uslm2_check.md"
    report.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:20]))
    print(f"wrote {report} and {out}")
    return 0 if not unexplained and not unfaithful and not stale and same_credit else 1


if __name__ == "__main__":
    sys.exit(main())
