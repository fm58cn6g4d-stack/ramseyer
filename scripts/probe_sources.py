"""M0 network probe: try each data source once and write a pass/fail table to var/probe.md.

Run:  .venv/bin/python scripts/probe_sources.py
Exit status is the number of failed probes.
"""
from __future__ import annotations

import platform
import sys
import time
import traceback
from urllib.parse import urljoin

from lxml import etree, html as lhtml

from ramseyer import config
from ramseyer.data import congress, govinfo, olrc, uslm
from ramseyer.data.http import Fetcher

SMALL_TITLE = "04"
BILL = (119, "hr", 1)  # enacted; has an enrolled XML text version
GOVINFO_DIR = "BILLS/119/1/hr"
PLAW_DIR = "PLAW/119/public"


def probe_release_point(f: Fetcher, cfg, state):
    url = urljoin(cfg.olrc_base, "download.html")
    r = f.get(url, refresh=True)
    if r.status != 200:
        raise RuntimeError(f"HTTP {r.status} for {url}")
    rp = olrc.parse_release_point(r.text(), url)
    state["rp"] = rp
    pin = "matches pin" if rp.label == cfg.release_pin else f"DIFFERS from pin {cfg.release_pin}"
    return f"{url}: release point {rp.label} ({rp.date}), {pin}; {len(rp.xml_titles)} per-title XML links"


def probe_title_xml(f: Fetcher, cfg, state):
    rp = state["rp"]
    url = rp.xml_titles[SMALL_TITLE]
    r = f.get(url)
    if r.status != 200:
        raise RuntimeError(f"HTTP {r.status} for {url}")
    s = uslm.summarize_title_zip(r.path)
    if s.root_tag != "uscDoc" or s.sections == 0 or s.malformed_ids:
        raise RuntimeError(f"unexpected USLM: {s}")
    return (f"{url}: {r.path.stat().st_size:,} bytes; member {s.member}; root <{s.root_tag}> "
            f"identifier {s.title_identifier}; {s.publication}; {s.sections} section identifiers, "
            f"all match /us/usc/t{{N}}/s{{N}}")


def probe_all_zip(f: Fetcher, cfg, state):
    url = state["rp"].xml_all
    r = f.head(url)
    if r.status != 200:
        raise RuntimeError(f"HTTP {r.status} for {url}")
    size = int(r.headers.get("content-length", 0))
    return f"{url}: {size:,} bytes ({size / 1e6:.1f} MB), last-modified {r.headers.get('last-modified')}"


def probe_classification(f: Fetcher, cfg, state):
    index = urljoin(cfg.olrc_base, "classification/tables.html")
    r = f.get(index, refresh=True)
    if r.status != 200:
        raise RuntimeError(f"HTTP {r.status} for {index}")
    hrefs = lhtml.fromstring(r.text()).xpath("//a/@href")
    target = next((h for h in hrefs if h.endswith("tbl119pl_2nd.html")), None)
    if not target:
        raise RuntimeError("no 119th Congress 2nd session Public Law order table linked")
    url = urljoin(index, target)
    t = f.get(url, refresh=True)
    if t.status != 200:
        raise RuntimeError(f"HTTP {t.status} for {url}")
    rows = olrc.parse_classification_table(t.text())
    laws = sorted({row.public_law for row in rows}, key=lambda p: int(p.split("-")[1]))
    return f"{url}: {len(rows)} rows parsed, {len(laws)} public laws ({laws[0]} .. {laws[-1]})"


def probe_congress_api(f: Fetcher, cfg, state):
    versions = congress.text_versions(f, *BILL)
    urls = congress.xml_urls(versions)
    if not urls:
        raise RuntimeError("no XML text URL among text versions")
    state["bill_xml"] = urls[0]
    return f"bill {BILL}: {len(versions)} text versions; XML e.g. {urls[0]}"


def probe_bill_text(f: Fetcher, cfg, state):
    congress_no, kind, number = BILL
    url = state.get("bill_xml") or (
        f"https://www.congress.gov/{congress_no}/bills/{kind}{number}/BILLS-{congress_no}{kind}{number}enr.xml")
    r = f.get(url)
    if r.status != 200:
        raise RuntimeError(f"HTTP {r.status} for {url}")
    root = etree.parse(str(r.path)).getroot()
    source = "URL from API" if "bill_xml" in state else "URL by pattern (API unavailable)"
    return f"{url} ({source}): {r.path.stat().st_size:,} bytes, root <{root.tag}>"


def probe_govinfo(f: Fetcher, cfg, state):
    files = govinfo.list_bulk(f, GOVINFO_DIR)
    xmls = [x for x in files if x["fileExtension"] == "xml"]
    plaw = govinfo.list_bulk(f, PLAW_DIR)
    smallest = min(xmls, key=lambda x: x["size"])
    r = f.get(smallest["link"])
    if r.status != 200:
        raise RuntimeError(f"HTTP {r.status} for {smallest['link']}")
    root = etree.parse(str(r.path)).getroot()
    return (f"{GOVINFO_DIR}: {len(xmls)} XML files; {PLAW_DIR}: {len(plaw)} entries; "
            f"downloaded {smallest['link']} ({r.path.stat().st_size:,} bytes, root <{root.tag}>)")


PROBES = [
    ("OLRC release point page", "GET current release point page", probe_release_point),
    ("OLRC per-title XML", f"Download title {SMALL_TITLE} XML zip", probe_title_xml),
    ("OLRC all-titles zip", "HEAD only", probe_all_zip),
    ("OLRC classification tables", "GET 119th Congress, 2nd session table", probe_classification),
    ("Congress.gov API", f"Text versions for {BILL}", probe_congress_api),
    ("Congress.gov bill text", "Download one bill text XML", probe_bill_text),
    ("govinfo bulk data", "List BILLS and PLAW dirs, download one file", probe_govinfo),
]


def cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def main() -> int:
    cfg = config.load()
    f = Fetcher(cfg)
    state: dict = {}
    results = []
    for name, test, fn in PROBES:
        t0 = time.monotonic()
        try:
            detail, ok = fn(f, cfg, state), True
        except congress.MissingKey as e:
            detail, ok = f"BLOCKED: {e}. Get a free key at https://api.data.gov/signup/", False
        except Exception as e:  # report every failure with its reason; never drop a row
            detail, ok = f"{type(e).__name__}: {e}", False
            traceback.print_exc()
        results.append((name, test, ok, detail, time.monotonic() - t0))
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")

    stamp = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())
    lines = [
        "# Source probe", "",
        f"Run {stamp} on {platform.node()} (Python {platform.python_version()}), "
        f"User-Agent `{cfg.user_agent}`, pinned release point {cfg.release_pin}.", "",
        "| Source | Test | Result | Seconds | Detail |", "| --- | --- | --- | --- | --- |",
    ]
    for name, test, ok, detail, secs in results:
        lines.append(f"| {name} | {test} | {'PASS' if ok else 'FAIL'} | {secs:.1f} | {cell(detail)} |")
    failed = sum(not r[2] for r in results)
    lines += ["", f"{len(results) - failed}/{len(results)} passed."]
    out = cfg.var / "probe.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out}")
    return failed


if __name__ == "__main__":
    sys.exit(main())
