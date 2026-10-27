"""Congress.gov API v3 (needs a free api.data.gov key in .env as API_DATA_GOV_KEY)."""
from __future__ import annotations

import json

from billmap.data.http import Fetcher


class MissingKey(RuntimeError):
    pass


def text_versions(fetcher: Fetcher, congress: int, bill_type: str, number: int) -> list[dict]:
    key = fetcher.cfg.api_key
    if not key:
        raise MissingKey("API_DATA_GOV_KEY is not set in .env")
    url = (f"{fetcher.cfg.congress_api}bill/{congress}/{bill_type}/{number}/text"
           f"?format=json&api_key={key}")
    r = fetcher.get(url)
    if r.status != 200:
        raise RuntimeError(f"Congress.gov text versions: HTTP {r.status}")
    return json.loads(r.text())["textVersions"]


def xml_urls(versions: list[dict]) -> list[str]:
    return [f["url"] for v in versions for f in v.get("formats", []) if f["url"].endswith(".xml")]
