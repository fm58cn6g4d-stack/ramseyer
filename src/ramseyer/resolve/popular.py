"""OLRC Table of Acts Cited by Popular Name (https://uscode.house.gov/popularnames/popularnames.html).

Verified 2026-10-28: each Act is <div class='popular-name-table-entry'> with <p class='popular-name'> and one or
more <p class='popular-name-information' content-type='cite' t3searchkey=... datekey=...>. The key is
"107-188" for a public law or "1944:373" (year:chapter) for an Act cited by date and chapter.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from lxml import html as lhtml

from ramseyer import config
from ramseyer.data.http import Fetcher

URL = "https://uscode.house.gov/popularnames/popularnames.html"


def norm_name(name: str) -> str:
    s = name.replace("’", "'").replace("–", "-").replace("—", "-")
    s = re.sub(r"^\s*the\s+", "", s, flags=re.I)
    return " ".join(s.lower().split()).rstrip(".")


def identity(key: str, datekey: str | None) -> str | None:
    if re.fullmatch(r"\d+-\d+", key):
        return f"pl:{key}"
    m = re.fullmatch(r"(\d{4}):(\w+)", key)
    if m and datekey:
        return f"act:{datekey}:{m.group(2)}"
    return None


def parse(page: str) -> dict[str, list[dict]]:
    """normalized name -> [{name, identities, release_point}] (several entries can share a name)."""
    doc = lhtml.fromstring(page)
    out: dict[str, list[dict]] = {}
    for div in doc.xpath("//div[contains(@class,'popular-name-table-entry')]"):
        name = " ".join(div.xpath("string(.//p[@class='popular-name'])").split())
        ids = []
        for p in div.xpath(".//p[@content-type='cite']"):
            i = identity(p.get("t3searchkey") or "", p.get("datekey"))
            if i and i not in ids:
                ids.append(i)
        if name:
            out.setdefault(norm_name(name), []).append({"name": name, "identities": ids,
                                                        "release_point": div.get("release-point")})
    return out


def load(cache: Path | None = None) -> dict[str, list[dict]]:
    cfg = config.load()
    cache = cache or cfg.var / "cache" / "popularnames.json"
    if cache.exists():
        return json.loads(cache.read_text())
    table = parse(Fetcher(cfg).get(URL).text())
    cache.write_text(json.dumps(table))
    return table
