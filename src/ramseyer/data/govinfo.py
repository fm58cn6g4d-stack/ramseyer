"""govinfo bulk data listings (no key needed)."""
from __future__ import annotations

import json

from ramseyer.data.http import Fetcher


def list_bulk(fetcher: Fetcher, path: str) -> list[dict]:
    """List a bulkdata directory, e.g. 'BILLS/119/2/hr' or 'PLAW/119/public'."""
    url = fetcher.cfg.govinfo_bulk + "json/" + path.strip("/")
    r = fetcher.get(url, headers={"Accept": "application/json"})
    if r.status != 200:
        raise RuntimeError(f"govinfo listing {path}: HTTP {r.status}")
    return json.loads(r.text())["files"]


# ---- U.S. Code annual editions (api.govinfo.gov, api.data.gov key; records/verify-first.md, M6b) ----------
def _api(fetcher: Fetcher, path: str) -> dict:
    url = f"{fetcher.cfg.govinfo_api}{path}{'&' if '?' in path else '?'}api_key={fetcher.cfg.api_key}"
    r = fetcher.get(url)
    if r.status != 200:
        raise RuntimeError(f"govinfo {path}: HTTP {r.status}")
    return json.loads(r.text())


def uscode_package(year: int, title: str) -> str:
    return f"USCODE-{year}-title{title}"


def uscode_granules(fetcher: Fetcher, year: int, title: str) -> dict[str, str]:
    """Section number (as in the granule id, e.g. "24301", "40101") -> granule id, for one title edition."""
    out: dict[str, str] = {}
    mark = "*"
    while mark:
        d = _api(fetcher, f"packages/{uscode_package(year, title)}/granules?offsetMark={mark}&pageSize=1000")
        for g in d.get("granules", []):
            gid = g["granuleId"]
            if "-sec" in gid:
                out.setdefault(gid.rsplit("-sec", 1)[1], gid)
        nxt = d.get("nextPage")
        mark = nxt.split("offsetMark=", 1)[1].split("&", 1)[0] if nxt and "offsetMark=" in nxt else None
    return out


def uscode_section_htm(fetcher: Fetcher, year: int, title: str, granule_id: str) -> str:
    """One section's XHTML (OLRC's format, with the edition's currentthrough comment)."""
    url = (f"{fetcher.cfg.govinfo_api}packages/{uscode_package(year, title)}/granules/{granule_id}/htm"
           f"?api_key={fetcher.cfg.api_key}")
    r = fetcher.get(url)
    if r.status != 200:
        raise RuntimeError(f"govinfo {granule_id}: HTTP {r.status}")
    return r.text()


def current_through(htm: str) -> str | None:
    """'20240103' from '<!-- documentid:... currentthrough:20240103 ... -->'."""
    import re
    m = re.search(r"currentthrough:(\d{8})", htm)
    return m.group(1) if m else None
