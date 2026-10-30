"""M6e: load the dreamproit/uscode `versions` config into var/history/history.sqlite (oracle/history.py).

Shards are fetched one at a time from Hugging Face, checked against the dataset's manifest.json (SHA-256), loaded and
deleted, so the disk holds one shard beside the store. Loaded shards are recorded; a rerun resumes.
Run:  .venv/bin/python scripts/load_history.py [--keep-shards]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time

import pyarrow.parquet as pq

from ramseyer import config
from ramseyer.oracle.history import History

BASE = "https://huggingface.co/datasets/dreamproit/uscode/resolve/main/"
COLUMNS = ["identifier", "title", "title_is_positive_law", "num_value", "heading", "status", "xml", "source_credit",
           "content_hash", "uslm_version", "first_release", "first_release_seq", "first_currency_date",
           "last_release", "last_release_seq", "last_currency_date", "releases", "identifier_collision",
           "parent_identifier", "seq_in_title"]


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-shards", action="store_true")
    a = ap.parse_args()
    cfg = config.load()
    work = cfg.var / "dreamproit"
    work.mkdir(parents=True, exist_ok=True)
    manifest_path = work / "manifest.json"
    subprocess.run(["curl", "-sSL", "-m", "120", "-o", str(manifest_path), BASE + "manifest.json"], check=True)
    manifest = json.loads(manifest_path.read_text())
    h = History(cfg.var / "history" / "history.sqlite")
    done = {n for (n,) in h.db.execute("SELECT name FROM loaded_shards")}
    shards = manifest["configs"]["versions"]["shards"]
    for sh in shards:
        name = sh["name"]
        if name in done:
            continue
        local = work / "versions" / name
        local.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.monotonic()
        if not local.exists() or sha256(local) != sh["sha256"]:
            subprocess.run(["curl", "-sSL", "-m", "1800", "--retry", "4", "-o", str(local),
                            BASE + "versions/" + name], check=True)
        if sha256(local) != sh["sha256"]:
            print(f"{name}: SHA-256 does not match the manifest", file=sys.stderr)
            return 1
        f = pq.ParquetFile(local)
        rows = 0
        # One transaction per shard, with its completion marker: an interrupted shard leaves nothing behind, so a
        # rerun loads it once.
        for g in range(f.metadata.num_row_groups):
            rows += h.load_rows(f.read_row_group(g, columns=COLUMNS).to_pylist())
            h.flush_release_map(commit=False)
        h.db.execute("INSERT INTO loaded_shards VALUES (?,?,?)", (name, sh["sha256"], rows))
        h.db.commit()
        if not a.keep_shards:
            local.unlink()
        print(f"{name}: {rows} versions ({time.monotonic() - t0:.0f}s)", flush=True)
    newest = manifest["fingerprint"]["newest_release"]["seq"]
    placed, empty = h.place_unsequenced(newest)
    unknown = h.flush_release_map()
    n_rel = h.db.execute("SELECT count(*) FROM releases").fetchone()[0]
    n_ver = h.db.execute("SELECT count(*) FROM versions").fetchone()[0]
    n_map = h.db.execute("SELECT count(*) FROM version_releases").fetchone()[0]
    fp = manifest["fingerprint"]["counts"]
    print(f"releases {n_rel}; versions {n_ver} (manifest {fp['section_versions']}); release map {n_map} "
          f"(manifest {fp['map_rows']}); placed by order: {placed or 'none'}; sequences with no rows: "
          f"{empty or 'none'}; labels with no sequence: {unknown or 'none'}")
    return 0 if not unknown and n_ver == fp["section_versions"] else 1


if __name__ == "__main__":
    sys.exit(main())
