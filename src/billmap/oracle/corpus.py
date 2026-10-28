"""The oracle corpus: enacted laws with the release points just before and just after their classification.

The manifest (tests/oracle/corpus.json) holds references and hashes only. Law text and statute text
live under var/ (rule 6) and are re-fetched from the recorded URLs.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel

from billmap import config

MANIFEST = config.ROOT / "tests" / "oracle" / "corpus.json"


class ClassifiedRow(BaseModel):
    """One row of OLRC's classification table for the law (Public Law order)."""
    title: str
    section: str
    description: str          # "" = amended, "new", "repealed", "prec", ...
    law_section: str

    @property
    def is_note(self) -> bool:
        return "nt" in self.description.split()

    @property
    def identifier(self) -> str:
        from billmap.data.cite import normalize_section
        return f"/us/usc/t{self.title.lower()}/s{normalize_section(self.section)}"


class CorpusLaw(BaseModel):
    pl: str                   # "119-75"
    name: str
    bill: str                 # "119 hr 7148"
    enrolled_url: str         # bill DTD XML of the enrolled bill
    enrolled_sha256: str
    rp_before: str
    rp_after: str
    titles: list[str]         # Code titles the law's classified rows touch (notes excluded)
    rows: list[ClassifiedRow]
    reason: str               # why it was selected

    @property
    def targets(self) -> list[ClassifiedRow]:
        """Rows that change Code section text: amended, new, repealed, ... (not notes)."""
        return [r for r in self.rows if not r.is_note]


class ReleasePointRef(BaseModel):
    label: str
    date: str | None
    page_url: str
    titles: list[str]         # titles the oracle index loads for this release point
    zip_urls: list[str]


class Corpus(BaseModel):
    version: int = 1
    built: str
    selection: str            # the rule used, in words
    release_points: list[ReleasePointRef]
    laws: list[CorpusLaw]

    def law(self, pl: str) -> CorpusLaw:
        return next(x for x in self.laws if x.pl == pl)

    def save(self, path: Path = MANIFEST) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.model_dump(), indent=1, ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, path: Path = MANIFEST) -> "Corpus":
        return cls.model_validate_json(path.read_text())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def title_sort_key(t: str) -> tuple:
    return (int(re.sub(r"\D", "", t)), t)
