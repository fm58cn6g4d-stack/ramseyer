"""The oracle index: the corpus release points, each loaded with only the titles the corpus needs."""
from __future__ import annotations

from pathlib import Path

from billmap import config
from billmap.data.http import Fetcher
from billmap.data.index import Index
from billmap.data.indexer import Indexer
from billmap.oracle.corpus import Corpus

ORACLE_DB = config.VAR / "oracle" / "oracle.sqlite"


def build(corpus: Corpus, db_path: Path = ORACLE_DB, log=print) -> None:
    cfg = config.load()
    f = Fetcher(cfg)
    ix = Indexer(db_path)
    for rp in corpus.release_points:
        row = ix.db.execute("SELECT id, complete FROM release_points WHERE label=?", (rp.label,)).fetchone()
        if row and row[1]:
            have = {r[0] for r in ix.db.execute("SELECT title FROM titles WHERE rp=?", (row[0],))}
            if have >= set(rp.titles):
                continue
            ix.drop_release_point(row[0])
        paths = []
        for url in rp.zip_urls:
            resp = f.get(url)
            if resp.status != 200:
                raise RuntimeError(f"{rp.label}: HTTP {resp.status} for {url}")
            paths.append(resp.path)
        log(f"release point {rp.label}: titles {', '.join(rp.titles)}")
        rp_id = ix.load_release_point(paths, rp.label, rp.date, rp.page_url, titles=rp.titles,
                                      log=lambda s: None)
        ix.mark_complete(rp_id)


def index(label: str, db_path: Path = ORACLE_DB) -> Index:
    return Index(db_path, label)
