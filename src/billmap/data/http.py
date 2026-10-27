"""Polite, caching HTTP fetcher. Every download lands under var/cache/ and is reused."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import httpx

from billmap.config import Config

SECRET_PARAMS = {"api_key"}


def redact(url: str) -> str:
    """Drop secret query parameters so keys never reach logs or cache metadata."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in SECRET_PARAMS]
    return urlunsplit(parts._replace(query=urlencode(query)))


@dataclass
class Response:
    url: str
    status: int
    headers: dict[str, str]
    path: Path | None  # cached body on disk; None for HEAD
    from_cache: bool

    def text(self) -> str:
        assert self.path is not None
        return self.path.read_text(encoding="utf-8", errors="replace")

    def bytes(self) -> bytes:
        assert self.path is not None
        return self.path.read_bytes()


class Fetcher:
    def __init__(self, cfg: Config, cache_dir: Path | None = None):
        self.cfg = cfg
        self.cache_dir = cache_dir or cfg.var / "cache" / "http"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last: dict[str, float] = {}
        self._client = httpx.Client(
            headers={"User-Agent": cfg.user_agent},
            timeout=cfg.timeout,
            follow_redirects=True,
        )

    def _wait(self, url: str) -> None:
        host = urlsplit(url).netloc
        gap = time.monotonic() - self._last.get(host, 0.0)
        if gap < self.cfg.min_interval:
            time.sleep(self.cfg.min_interval - gap)
        self._last[host] = time.monotonic()

    def _key(self, url: str) -> str:
        return hashlib.sha256(redact(url).encode()).hexdigest()[:24]

    def get(self, url: str, *, refresh: bool = False, headers: dict | None = None) -> Response:
        key = self._key(url)
        body, meta = self.cache_dir / key, self.cache_dir / f"{key}.json"
        if not refresh and body.exists() and meta.exists():
            m = json.loads(meta.read_text())
            return Response(m["url"], m["status"], m["headers"], body, True)
        self._wait(url)
        tmp = body.with_suffix(".part")
        with self._client.stream("GET", url, headers=headers) as r:
            with tmp.open("wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)
            status, hdrs = r.status_code, dict(r.headers)
        if status != 200:
            tmp.unlink(missing_ok=True)
            return Response(redact(url), status, hdrs, None, False)
        tmp.replace(body)
        meta.write_text(json.dumps({"url": redact(url), "status": status, "headers": hdrs,
                                    "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
        return Response(redact(url), status, hdrs, body, False)

    def head(self, url: str) -> Response:
        self._wait(url)
        r = self._client.head(url)
        return Response(redact(url), r.status_code, dict(r.headers), None, False)
