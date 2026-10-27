"""Project configuration: billmap.toml plus secrets from .env (never committed)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VAR = ROOT / "var"


def _load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Config:
    release_pin: str
    olrc_base: str
    govinfo_bulk: str
    congress_api: str
    min_interval: float
    timeout: float
    api_key: str | None
    contact: str | None
    var: Path

    @property
    def user_agent(self) -> str:
        contact = f" (+{self.contact})" if self.contact else ""
        return f"billmap/0.0.1{contact}"


def load(root: Path = ROOT) -> Config:
    raw = tomllib.loads((root / "billmap.toml").read_text())
    env = {**_load_dotenv(root / ".env"), **os.environ}
    return Config(
        release_pin=raw["release"]["pin"],
        olrc_base=raw["sources"]["olrc_base"],
        govinfo_bulk=raw["sources"]["govinfo_bulk"],
        congress_api=raw["sources"]["congress_api"],
        min_interval=float(raw["net"]["min_interval_seconds"]),
        timeout=float(raw["net"]["timeout_seconds"]),
        api_key=env.get("API_DATA_GOV_KEY") or None,
        contact=env.get("BILLMAP_CONTACT") or None,
        var=root / "var",
    )
