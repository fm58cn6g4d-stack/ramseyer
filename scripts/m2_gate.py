"""M2 gate (docs/03-free-statute-server.md): the statute tools work over MCP, 50 spot checks match
uscode.house.gov, and cited_by equals the inverted refs table.

Run:  .venv/bin/python scripts/m2_gate.py [--spot 50] [--seed 20261028]
Writes var/m2_gate.md; exit status 1 if any check fails. Spot-check pages are cached under var/cache.
"""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import random
import re
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from billmap import config
from billmap.data import xhtml
from billmap.data.http import Fetcher
from billmap.statute import TOOLS, StatuteService, call

MCP_CALLS = [
    ("resolve_cite", {"citation": "49 U.S.C. 24101(a)"}),
    ("get_section", {"citation": "4 U.S.C. 1"}),
    ("cited_by", {"citation": "49 U.S.C. 24102", "limit": 5}),
    ("search", {"query": "intercity rail passenger transportation", "title": "49", "limit": 3}),
    ("get_pincite", {"citation": "42 U.S.C. 1395w-22(a)(1)"}),
    ("coverage", {}),
    ("resolve_cite", {"citation": "49 U.S.C. 999999"}),         # must come back as a structured not_found
]


async def mcp_round_trip(cfg) -> tuple[list[str], list[tuple[str, dict]]]:
    params = StdioServerParameters(command=str(config.ROOT / ".venv/bin/billmap"), args=["serve-mcp"],
                                   cwd=str(config.ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = sorted(t.name for t in (await session.list_tools()).tools)
            results = []
            for name, args in MCP_CALLS:
                r = await session.call_tool(name, args)
                payload = r.structured_content
                if payload is None and r.content:
                    payload = json.loads(r.content[0].text)
                if isinstance(payload, dict) and set(payload) == {"result"}:
                    payload = payload["result"]
                results.append((name, payload))
            return tools, results


def page_parts(page: str) -> tuple[str | None, str | None, list[str]]:
    """(release point stamp, section head, body words) from a uscode.house.gov section page."""
    stamp = re.search(r'lawsInEffect">[^<]*?Public Law (\d+-\d+)', page)
    head = re.search(r'<h3 class="section-head">(.*?)</h3>', page, re.S)
    start = head.end() if head else -1
    end = page.find('class="source-credit"', start)
    if end < 0:
        end = page.find('class="note-', start)
    if end > start:
        end = page.rfind("<", start, end)      # cut before the tag that carries the class
    body = page[start:end] if start >= 0 and end > start else ""
    words = html.unescape(re.sub(r"<[^>]+>", " ", body)).split()
    head_text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", head.group(1))).split()) if head else None
    return (stamp.group(1) if stamp else None), head_text, words


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spot", type=int, default=50)
    ap.add_argument("--seed", type=int, default=20261028)
    args = ap.parse_args()
    cfg = config.load()
    svc = StatuteService()
    db, rp = svc.db, svc.ix.rp_id
    checks: list[tuple[str, bool, str]] = []
    t0 = time.monotonic()

    # 1. Tools over MCP (stdio), each response carrying the release point.
    tools, results = asyncio.run(mcp_round_trip(cfg))
    missing = sorted(set(TOOLS) - set(tools))
    bad = [n for n, p in results if not isinstance(p, dict) or p.get("release_point") != cfg.release_pin]
    errors = [(n, p.get("error")) for n, p in results if isinstance(p, dict) and "error" in p]
    ok = not missing and not bad and errors == [("resolve_cite", "not_found")]
    detail = (f"{len(tools)} tools listed ({', '.join(tools)}); {len(results)} calls; missing {missing or 'none'}; "
              f"without release point {bad or 'none'}; errors {errors} (only the deliberate not_found expected). "
              f"Samples: " + "; ".join(
                  f"{n} -> {p.get('cite') or p.get('target') or p.get('query') or p.get('sections') or p.get('error')}"
                  for n, p in results if isinstance(p, dict)))
    checks.append(("resolve_cite, get_section, cited_by and search work over MCP", ok, detail))

    # 2. Spot checks against uscode.house.gov at the pinned release point.
    ids = [r[0] for r in db.execute("SELECT id FROM nodes WHERE rp=? AND kind='section' AND status='current' "
                                    "AND synthetic=0 AND identifier GLOB '/us/usc/t[0-9]*/s*' ORDER BY id", (rp,))]
    sample = random.Random(args.seed).sample(ids, args.spot)
    f = Fetcher(cfg)
    tally = {"equal": 0, "rendering": 0, "content": 0}
    problems = []
    for nid in sample:
        node = svc.ix._node(nid)
        sec = svc.get_section(node.identifier)
        url = sec["link"]
        resp = f.get(url)
        if resp.status != 200:
            problems.append(f"{sec['cite']}: HTTP {resp.status} {url}")
            continue
        stamp, head, words = page_parts(resp.text())
        if stamp != cfg.release_pin:
            problems.append(f"{sec['cite']}: page stamped {stamp}, expected {cfg.release_pin}")
        ours_head = " ".join(f"{node.num or ''}{node.heading or ''}".split())
        if head is None or xhtml.comparable(head.split()) != xhtml.comparable(ours_head.split()):
            problems.append(f"{sec['cite']}: heading {head!r} vs index {ours_head!r}")
        kind, diff = xhtml.compare(xhtml.body_words(sec["text"]), words)
        tally[kind] += 1
        if kind == "content":
            problems.append(f"{sec['cite']}: text differs: {diff}")
    checks.append((f"{args.spot} spot checks match uscode.house.gov (seed {args.seed})", not problems,
                   f"text equal {tally['equal']}, rendering-only {tally['rendering']}, content {tally['content']}; "
                   f"pages stamped {cfg.release_pin}; " + ("no problems" if not problems else
                                                          "problems: " + " | ".join(problems))))

    # 3. cited_by equals the inverted refs table (computed independently here in SQL).
    targets = [r[0] for r in db.execute(
        "SELECT s.id FROM nodes s WHERE s.rp=? AND s.kind='section' AND EXISTS (SELECT 1 FROM refs r JOIN nodes d "
        "ON d.id=r.dst_id WHERE d.section_id=s.id) ORDER BY s.id", (rp,))]
    picked = random.Random(args.seed + 1).sample(targets, min(300, len(targets)))
    mismatch, compared, skipped = [], 0, 0
    for sid in picked:
        node = svc.ix._node(sid)
        for include_notes, contexts in ((False, ("text",)), (True, ("text", "note", "credit"))):
            expected = {r[0] for r in db.execute(
                f"SELECT r.id FROM refs r JOIN nodes d ON d.id=r.dst_id WHERE d.section_id=? AND r.context IN "
                f"({','.join('?' * len(contexts))})", (sid, *contexts))}
            if len(expected) > 500:
                skipped += 1
                continue
            got = call(svc, "cited_by", citation=node.identifier, limit=500, include_notes=include_notes)
            ids_got = {i["ref_id"] for i in got.get("cited_by", [])}
            compared += 1
            if ids_got != expected or got.get("total") != len(expected):
                mismatch.append(f"{node.cite} notes={include_notes}: got {len(ids_got)}, refs table {len(expected)}")
    checks.append(("cited_by equals the inverted refs table", not mismatch,
                   f"{compared} comparisons over {len(picked)} cited sections (text only, and with notes); "
                   f"{skipped} skipped over the 500 limit; {len(mismatch)} mismatches" +
                   ("" if not mismatch else ": " + "; ".join(mismatch[:10]))))

    # 4. Every tool's direct-call result carries the release point; error codes are from the documented set.
    direct = [call(svc, n, **a) for n, a in MCP_CALLS] + [
        call(svc, "cross_refs", citation="49 U.S.C. 24101"), call(svc, "definitions", citation="49 U.S.C. 24102"),
        call(svc, "neighbors", citation="49 U.S.C. 24101"), call(svc, "act_to_code", public_law="117-58", section="22101"),
        call(svc, "changes", citation="4 U.S.C. 1", from_rp=cfg.release_pin, to_rp=cfg.release_pin),
        call(svc, "get_section", citation="4 U.S.C. 1", as_of="0-0"),
        call(svc, "get_section", citation="10 U.S.C. 130g")]
    no_rp = [d for d in direct if "release_point" not in d]
    codes = sorted({d["error"] for d in direct if "error" in d})
    checks.append(("Every response includes the release point; errors use the documented codes",
                   not no_rp and set(codes) <= {"not_found", "ambiguous", "repealed", "out_of_range"},
                   f"{len(direct)} calls, {len(no_rp)} without release point; error codes seen: {codes}"))

    lines = ["# M2 gate", "", f"Release point {svc.ix.release_point}; run "
             f"{time.strftime('%Y-%m-%d %H:%M:%SZ', time.gmtime())}; {time.monotonic() - t0:.0f}s.", "",
             "| Check | Result | Measured |", "| --- | --- | --- |"]
    lines += [f"| {n} | {'PASS' if ok else 'FAIL'} | {d.replace('|', '/')} |" for n, ok, d in checks]
    (cfg.var / "m2_gate.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
