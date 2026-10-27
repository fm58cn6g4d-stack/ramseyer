"""govinfo bulk data listings (no key needed)."""
from __future__ import annotations

import json

from billmap.data.http import Fetcher


def list_bulk(fetcher: Fetcher, path: str) -> list[dict]:
    """List a bulkdata directory, e.g. 'BILLS/119/2/hr' or 'PLAW/119/public'."""
    url = fetcher.cfg.govinfo_bulk + "json/" + path.strip("/")
    r = fetcher.get(url, headers={"Accept": "application/json"})
    if r.status != 200:
        raise RuntimeError(f"govinfo listing {path}: HTTP {r.status}")
    return json.loads(r.text())["files"]
