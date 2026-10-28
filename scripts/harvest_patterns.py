"""Write tests/parse/patterns/P*.json: for each grammar pattern, positive and negative examples taken from the
enrolled text of the oracle corpus laws, chosen by simple regexes independent of the parser's grammar.

Each example keeps the lines needed to parse it on its own: the section heading, the enclosing units' text,
the unit itself and any quoted block. Run:  .venv/bin/python scripts/harvest_patterns.py
"""
from __future__ import annotations

import json
import re

from billmap import config
from billmap.data.http import Fetcher
from billmap.oracle.corpus import Corpus
from billmap.parse import parse_text
from billmap.parse.xmltext import render

OUT = config.ROOT / "tests" / "parse" / "patterns"
N_POS, N_NEG = 6, 4
Q = "[“][^”]{1,200}[”]"
# pattern id -> (positive regex on the unit's text, negative regex, expectation for positives)
SPECS = {
    "P1": (r"^Section \S+ of title \d+, United States Code, is amended", r"United States Code(?!, is amended)",
           {"target_kind": "usc"}),
    "P2": (rf"\bby striking {Q} and inserting {Q}[;.]?(?: and)?$", rf"\bby striking {Q}[;.]", {"op": "STRIKE_INSERT"}),
    "P3": (rf"^(?!.*heading).*\bby striking {Q}(?: each place it appears)?[;.]?(?: and)?$", rf"\bby striking {Q} and inserting",
           {"op": "STRIKE"}),
    "P4": (rf"^(?!.*heading).*\bby inserting {Q} after {Q}[;.]?(?: and)?$", r"\bby inserting after (?:sub)?(?:section|paragraph) \(", {"op": "INSERT_AFTER"}),
    "P5": (r"\bby adding at the end the following", r"\bby inserting after", {"op": "ADD_END"}),
    "P6": (r"\bby inserting after (?:sub)?(?:section|paragraph) \(\w+\) the following", r"\bby adding at the end",
           {"op": "ADD_UNIT_AFTER"}),
    "P7": (r"\bby striking (?:sub)?(?:section|paragraph) \(\w+\) and inserting the following", rf"\bby striking {Q}",
           {"op": "REPLACE_UNIT"}),
    "P8": (r"\bby redesignating (?:sub)?(?:section|paragraph)s? \(", r"\bas so redesignated\b(?!.*by redesignating)",
           {"op": "REDESIGNATE"}),
    "P9": (r"\bis (?:hereby )?repealed\.?$", r"^(?!.*\b(?:is|are) (?:hereby )?repealed).*\b[Rr]epeal", {"op": "REPEAL"}),
    "P10": (r"\bin the (?:section |subsection )?heading,? by (?:striking|inserting)", r"\bheading\b(?!.*by (?:striking|inserting))",
            {"op": "AMEND_HEADING"}),
    "P11": (r"\bby (?:striking|inserting after) the item relating to section", r"^(?!.*\bby (?:striking|inserting|adding)).*\bthe item relating to\b",
            {"op": "CONFORM_TOC"}),
    "P12": (rf"\bby striking {Q} each place it appears and inserting {Q}", rf"\bby striking {Q} and inserting {Q}[;.]",
            {"op": "STRIKE_INSERT", "occurrence": "each"}),
    "P13": (rf"\bby striking {Q} and all that follows through {Q}", rf"\bby striking {Q} and inserting {Q}",
            {"op": "STRIKE_THROUGH"}),
    "P14": (r"^Section \S+ of the [A-Z][^()]*Act[^()]* \(\d+ U\.S\.C\. [^)]+\) is amended", r"^Section \S+ of title \d+",
            {"target_kind": "act"}),
    "P15": (r"\bmay be cited as\b", r"\bis amended\b", {"freestanding_type": "short_title"}),
}


def contexts(nodes):
    """Yield (unit, lines needed to parse it alone)."""
    def walk(n, chain):
        yield n, chain
        for c in n.children:
            yield from walk(c, chain + [n])
    for r in nodes:
        yield from walk(r, [])


def line_of(n) -> list[str]:
    if n.level == "section":
        out = [f"SEC. {n.enum}. {(n.header or 'X').upper()}."]
        return out + ([n.text] if n.text else [])
    if n.enum is None:
        return [n.text] if n.text else []
    head = f"({n.enum}) " + (f"{n.header}.—" if n.header else "")
    out = [head + n.text]
    return out + (n.block.split("\n") if n.block else [])


def main() -> None:
    f = Fetcher(config.load())
    pos = {k: [] for k in SPECS}
    neg = {k: [] for k in SPECS}
    for law in Corpus.load().laws:
        result = parse_text(render(f.get(law.enrolled_url).path))
        for node, chain in contexts(result.nodes):
            if not node.text or node.cls == "TABLE_OF_CONTENTS":
                continue
            sec = [c for c in chain if c.level == "section"]
            if not sec and node.level != "section":
                continue
            units = chain[chain.index(sec[0]) + 1:] if sec else []
            lines = []
            for c in ([sec[0]] if sec else []) + units:
                lines += [x for x in line_of(c) if x][:1] if c.level != "section" else line_of(c)[:1]
                if c.level == "section" and c.text and c is not node:
                    lines.append(c.text)
            lines += line_of(node) if node.level != "section" else line_of(node)
            text = node.text.replace("\n", " ")
            for pid, (prx, nrx, expect) in SPECS.items():
                ex = {"law": law.pl, "loc": node.loc, "lines": lines}
                if re.search(prx, text) and len(pos[pid]) < N_POS:
                    pos[pid].append(ex | {"expect": expect})
                elif re.search(nrx, text) and not re.search(prx, text) and len(neg[pid]) < N_NEG:
                    neg[pid].append(ex | {"must_not": expect})
    OUT.mkdir(parents=True, exist_ok=True)
    for pid in SPECS:
        (OUT / f"{pid}.json").write_text(json.dumps({"pattern": pid, "source": "enrolled text of the oracle corpus "
                                                     "laws (tests/oracle/corpus.json)", "positive": pos[pid],
                                                     "negative": neg[pid]}, indent=1, ensure_ascii=False) + "\n")
        print(pid, len(pos[pid]), "positive,", len(neg[pid]), "negative")


if __name__ == "__main__":
    main()
