"""Red-team harness: run ramseyer's real parse -> resolve -> dry-run pipeline (dryrun.predict.run_bill) on drafts
against a small synthetic index. All statute text here is synthetic placeholder text; the USLM structure follows
the real release XML. The index is built under var/redteam/ (gitignored).

Run:  .venv/bin/python redteam/synthetic.py            # every case
      .venv/bin/python redteam/synthetic.py CASE_NAME  # one case
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

from ramseyer.data.index import Index
from ramseyer.data.indexer import Indexer
from ramseyer.dryrun.predict import run_bill
from ramseyer.parse import parse_text
from ramseyer.resolve.popular import norm_name
from ramseyer.resolve.resolver import Resolver

NS = "http://xml.house.gov/schemas/uslm/1.0"
VAR = Path(__file__).resolve().parents[1] / "var" / "redteam"


def credit(pl: str, sec: str) -> str:
    c, n = pl.split("-")
    return (f'<sourceCredit>(<ref href="/us/pl/{c}/{n}/s{sec}">Pub. L. {c}–{n}, § {sec}</ref>, '
            f'<date date="2087-01-02">Jan. 2, 2087</date>.)</sourceCredit>')


def sub(ident, num, heading, body, children=""):
    h = f"<heading> {heading}</heading>" if heading else ""
    inner = f"<content>{body}</content>" if body and not children else (f"<chapeau>{body}</chapeau>" if body else "")
    return f'<subsection identifier="{ident}/{num}"><num value="{num}">({num})</num>{h}{inner}{children}</subsection>'


def para(ident, num, body):
    return f'<paragraph identifier="{ident}/{num}"><num value="{num}">({num})</num><content> {body}</content></paragraph>'


def t98() -> str:
    """A positive-law title: chapter 1, sections 101-103."""
    s = "/us/usc/t98/s101"
    s101 = (f'<section identifier="{s}"><num value="101">§ 101.</num><heading> Lorem board</heading>'
            + sub(s, "a", "Establishment.—", "There is established the Lorem Board. The U.S. Government shall fund "
                  "the Board. The Board shall meet quarterly.")
            + sub(s, "b", "Grants.—", "The Board may award grants of not more than $1,000,000 to each eligible "
                  "entity for each fiscal year.")
            + sub(s, "c", "Duties.—", "The Board shall—", para(f"{s}/c", "1", "file a report;")
                  + para(f"{s}/c", "2", "keep a record; and") + para(f"{s}/c", "3", "notify the Secretary."))
            + '</section>')
    s = "/us/usc/t98/s102"
    s102 = (f'<section identifier="{s}"><num value="102">§ 102.</num><heading> Ipsum duties</heading>'
            + sub(s, "a", "In general.—", "The Board shall consult the Secretary before each award.")
            + sub(s, "b", "Limit.—", "No award may exceed 10 percent of the amount appropriated.")
            + '</section>')
    s = "/us/usc/t98/s103"
    s103 = (f'<section identifier="{s}"><num value="103">§ 103.</num><heading> Dolor reports</heading>'
            + sub(s, "a", "Report.—", "The Board shall report to the Secretary each year.")
            + '</section>')
    return (f'<?xml version="1.0" encoding="UTF-8"?><uscDoc xmlns="{NS}" identifier="/us/usc/t98"><meta>'
            '<docPublicationName>Online@1-1</docPublicationName><property role="is-positive-law">yes</property></meta>'
            '<main><title identifier="/us/usc/t98"><num value="98">Title 98—</num><heading>PLACEHOLDER</heading>'
            '<chapter identifier="/us/usc/t98/ch1"><num value="1">CHAPTER 1—</num><heading>LOREM</heading>'
            f'{s101}{s102}{s103}</chapter></title></main></uscDoc>')


def t99() -> str:
    """A non-positive-law title holding sections of the 'Placeholder Act' (Pub. L. 150-7, sections 301-302)."""
    s = "/us/usc/t99/s1"
    s1 = (f'<section identifier="{s}"><num value="1">§ 1.</num><heading> Alpha program</heading>'
          + sub(s, "a", "In general", "The Administrator shall carry out the alpha program.")
          + sub(s, "b", "Funding", "There is authorized to be appropriated $5,000,000 for each fiscal year.")
          + credit("150-7", "301") + '</section>')
    s = "/us/usc/t99/s2"
    s2 = (f'<section identifier="{s}"><num value="2">§ 2.</num><heading> Beta program</heading>'
          + sub(s, "a", "In general", "The Administrator shall carry out the beta program.")
          + credit("150-7", "302") + '</section>')
    return (f'<?xml version="1.0" encoding="UTF-8"?><uscDoc xmlns="{NS}" identifier="/us/usc/t99"><meta>'
            '<docPublicationName>Online@1-1</docPublicationName><property role="is-positive-law">no</property></meta>'
            '<main><title identifier="/us/usc/t99"><num value="99">Title 99—</num><heading>PLACEHOLDER</heading>'
            '<chapter identifier="/us/usc/t99/ch1"><num value="1">CHAPTER 1—</num><heading>ALPHA</heading>'
            f'{s1}{s2}</chapter></title></main></uscDoc>')


def build() -> Path:
    VAR.mkdir(parents=True, exist_ok=True)
    db = VAR / "synthetic.sqlite"
    if db.exists():
        db.unlink()
    z = VAR / "1-1.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("usc98.xml", t98())
        zf.writestr("usc99.xml", t99())
    ix = Indexer(db)
    rp = ix.load_release_point(z, "1-1", None, "synthetic", log=lambda s: None)
    ix.mark_complete(rp)
    return db


def run(draft: str, ix: Index, resolver: Resolver) -> None:
    ins = parse_text("SEC. 2. AMENDMENTS.\n" + draft.strip() + "\n").instructions
    out = run_bill(ins, resolver, ix)
    for tr in out.traces:
        r = tr.result
        print(f"  ins {tr.instruction.id:<14} op={tr.instruction.op:<14} resolution={tr.resolution.outcome:<9} "
              f"section={tr.section} -> {r.status if r else 'NO RESULT (not applied, nothing reported)'}"
              f"{' : ' + r.detail[:110] if r and r.detail else ''}")
    for p in out.predictions:
        print(f"  PREDICTION {p.identifier}: {p.status}")
        for line in (p.text or "(removed)").strip().splitlines():
            if line.strip():
                print("     | " + line.strip())


CASES = {
    # 1. A chapter-wide substitution next to an ordinary edit of a section in that chapter.
    "chapter_wide_substitution": """
(a) Chapter 1 of title 98, United States Code, is amended by striking “Board” each place it appears and inserting “Commission”.
(b) Section 101(c)(1) of title 98, United States Code, is amended by striking “a report” and inserting “an annual report”.
""",
    # 2. Same, at Act level: "The Placeholder Act is amended by striking ... each place it appears".
    "act_wide_substitution": """
(a) The Placeholder Act (Public Law 150-7) is amended by striking “Administrator” each place it appears and inserting “Director”.
(b) Section 301(b) of the Placeholder Act (99 U.S.C. 1(b)) is amended by striking “$5,000,000” and inserting “$6,000,000”.
""",
    # 3. A stale quote: the draft was written when (b) read "$1,000"; the Code now reads "$1,000,000".
    "stale_amount_substring": """
Section 101(b) of title 98, United States Code, is amended by striking “$1,000” and inserting “$2,000”.
""",
    # 4. Sentence-qualified edit; "U.S. Government" breaks the sentence splitter.
    "sentence_split_abbreviation": """
Section 101(a) of title 98, United States Code, is amended in the second sentence by striking “Board” and inserting “Commission”.
""",
    # 5. A section repealed, then amended later in the same bill (a drafting conflict).
    "amend_after_repeal": """
(a) Section 103 of title 98, United States Code, is repealed.
(b) Section 103(a) of title 98, United States Code, is amended by striking “each year” and inserting “each quarter”.
""",
    # 6. Wrong section number in the draft (meant 102); the quoted words occur in 103 as well.
    "wrong_section_same_words": """
Section 103(a) of title 98, United States Code, is amended by striking “the Secretary” and inserting “the Under Secretary”.
""",
    # 7. Act target with no U.S.C. parenthetical: one witness (source credits) only.
    "act_target_single_witness": """
Section 302(a) of the Placeholder Act is amended by striking “beta” and inserting “gamma”.
""",
    # 8. Delayed effective date: the amendment's quote does not exist in the Code.
    "delayed_effective_hides_not_found": """
(a) Section 101(b) of title 98, United States Code, is amended by striking “$7,500” and inserting “$9,000”.
(b) Effective date.—The amendments made by this section shall take effect 1 year after the date of enactment of this Act.
""",
    # 9. Title-wide substitution.
    "title_wide_substitution": """
(a) Title 98, United States Code, is amended by striking “Secretary” each place it appears and inserting “Administrator”.
(b) Section 102(b) of title 98, United States Code, is amended by striking “10 percent” and inserting “15 percent”.
""",
    # 10. A conforming "each place it appears" across several named sections.
    "several_sections_each_place": """
Sections 101, 102, and 103 of title 98, United States Code, are each amended by striking “the Secretary” each place it appears and inserting “the Under Secretary”.
""",
    # 11. Inserted unit at the wrong level: plain-text comparison cannot see depth.
    "insert_paragraph_after_subsection_label": """
Section 101 of title 98, United States Code, is amended by inserting after subsection (c)(3) the following:
“(4) publish the record.”.
""",
    # 12. "third sentence": with the abbreviation split, the edit lands in the wrong sentence.
    "sentence_split_wrong_sentence": """
Section 101(a) of title 98, United States Code, is amended in the third sentence by striking “the Board” and inserting “the Commission”.
""",
    # 13. Matter-preceding qualifier where the words are only in the paragraphs: the report says an earlier
    # instruction of the bill changed them (no such instruction exists).
    "qualifier_misdiagnosed_as_conflict": """
Section 101(c) of title 98, United States Code, is amended in the matter preceding paragraph (1) by striking “a record” and inserting “records”.
""",
    # 14. A non-standard verb the grammar does not know.
    "unknown_verb": """
(a) Section 102(a) of title 98, United States Code, is amended by replacing “before each award” with “after each award”.
(b) Section 102(b) of title 98, United States Code, is amended by striking “10 percent” and inserting “12 percent”.
""",
    # 15. A redesignation that leaves an internal cross-reference pointing at the wrong paragraph.
    "redesignation_breaks_reference": """
Section 101(c) of title 98, United States Code, is amended—
(1) by redesignating paragraphs (2) and (3) as paragraphs (3) and (4), respectively; and
(2) by inserting after paragraph (1) the following:
“(2) consult the Secretary;”.
""",
    # 16. A quoted block that itself contains amendatory wording.
    "quoted_block_with_instruction_words": """
Section 103 of title 98, United States Code, is amended by adding at the end the following:
“(b) Conforming rule.—Section 102 of this title is amended by striking ‘Board’ and inserting ‘Commission’ only for purposes of this subsection.”.
""",
    # 17. Ordinal occurrence.
    "second_place_it_appears": """
Section 101(a) of title 98, United States Code, is amended by striking “Board” the second place it appears and inserting “Commission”.
""",
    # 18. A cross-reference amended in one section, while the bill amends the same words with no target at all.
    "freestanding_conforming_without_target": """
(a) Section 102(b) of title 98, United States Code, is amended by striking “10 percent” and inserting “20 percent”.
(b) Conforming amendment.—Any reference in law to the Lorem Board shall be deemed a reference to the Lorem Commission.
""",
    # 19. Replacement block whose label differs from the unit it replaces.
    "replace_unit_label_mismatch": """
Section 102 of title 98, United States Code, is amended by striking subsection (b) and inserting the following:
“(c) Limit.—No award may exceed 12 percent of the amount appropriated.”.
""",
    # 20. A unit added at the end whose label already exists.
    "add_end_duplicate_label": """
Section 102 of title 98, United States Code, is amended by adding at the end the following:
“(b) Review.—The Board shall review each award.”.
""",
    # 21. Strike-through whose end words occur before the start words as well.
    "strike_through_endpoints": """
Section 101(a) of title 98, United States Code, is amended by striking “The U.S. Government” and all that follows through “Board.”.
""",
    # 22. Insert after words that occur twice, no occurrence given.
    "insert_after_ambiguous_anchor": """
Section 101(a) of title 98, United States Code, is amended by inserting “Lorem” after “The”.
""",
}


def main(argv: list[str]) -> int:
    db = build()
    ix = Index(db, "1-1")
    popular = {norm_name("Placeholder Act"): [{"identities": ["pl:150-7"]}]}
    resolver = Resolver(ix, popular, {})
    for name, draft in CASES.items():
        if argv and name not in argv:
            continue
        print(f"\n=== {name}\n  draft: " + " / ".join(x.strip() for x in draft.strip().splitlines()))
        run(draft, ix, resolver)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
