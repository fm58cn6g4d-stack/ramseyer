"""Parser targets (M4/M5): references clauses, Acts cited by date or long title, nested Act units, "such Act".
Drafts are synthetic; Act names and numbers are placeholders."""
from ramseyer.parse import parse_text


def targets(draft: str):
    return [i.target for i in parse_text(draft).instructions]


def test_references_clause_supplies_the_act():
    t = targets("TITLE I—ALPHA\nSEC. 101. REFERENCES.\nExcept as otherwise expressly provided, wherever in this title an "
                "amendment or repeal is expressed in terms of an amendment to, or repeal of, a section or other "
                "provision, the reference shall be considered to be made to that section or other provision of the "
                "Placeholder Programs Act.\nSEC. 102. CHANGE.\nSection 425 (99 U.S.C. 625) is amended by striking "
                "“2023” and inserting “2029”.\n")
    assert t[0].kind == "act" and t[0].act == "Placeholder Programs Act" and t[0].section == "425"


def test_references_clause_is_limited_to_its_scope():
    t = targets("TITLE I—ALPHA\nSEC. 101. REFERENCES.\nWherever in this title an amendment is expressed in terms of an "
                "amendment to a section, the reference shall be considered to be made to a section of the Placeholder "
                "Programs Act.\nTITLE II—BETA\nSEC. 201. CHANGE.\nSection 425 (99 U.S.C. 625) is amended by striking "
                "“2023” and inserting “2029”.\n")
    assert t[0].act is None


def test_act_cited_by_date_and_by_long_title():
    t = targets("SEC. 2. CHANGES.\n(a) One.—Section 3(c) of the Act of August 13, 1946 (99 U.S.C. 426g(c)) is amended "
                "by striking “a” and inserting “b”.\n(b) Two.—Section 8(d)(2) of the Act entitled, “An Act to "
                "establish a placeholder”, approved June 3, 1976 (99 U.S.C. 3008(d)(2)) is amended by striking “a” and "
                "inserting “b”.\n")
    assert (t[0].act, t[0].section, t[0].path) == ("Act of August 13, 1946", "3", ["(c)"])
    assert t[1].act.startswith("Act entitled") and t[1].act.endswith("approved June 3, 1976")
    assert t[1].section == "8"


def test_a_section_of_an_unknown_law_takes_no_root_from_context():
    t = targets("SEC. 2. CHANGES.\n(a) One.—Section 14 of the Placeholder Control Act of 1946 (99 U.S.C. 701r) is "
                "amended by striking “a” and inserting “b”.\n(b) Two.—Section 3(c) of the Placeholder Compact of 1950 "
                "is amended by striking “a” and inserting “b”.\n")
    assert t[1].act != "Placeholder Control Act of 1946"


def test_section_of_a_title_of_an_act_and_such_act():
    t = targets("SEC. 2. CHANGES.\n(a) One.—Section 1701 of title I of the Placeholder Streets Act of 1968 (99 U.S.C. "
                "10381) is amended by striking “a” and inserting “b”.\n(b) Two.—Title III of the Placeholder Vote Act of "
                "2002 (99 U.S.C. 21081 et seq.) is amended by striking “a” and inserting “b”.\n(c) Three.—Section 401 "
                "of such Act (99 U.S.C. 21111) is amended by striking “c” and inserting “d”.\n")
    assert (t[0].act, t[0].section) == ("Placeholder Streets Act of 1968", "1701")
    assert (t[2].act, t[2].section, t[2].usc_parenthetical) == ("Placeholder Vote Act of 2002", "401", "99 U.S.C. 21111")


def test_amendments_act_name_is_not_cut_short():
    t = targets("SEC. 2. CHANGE.\nSection 105 of the Placeholder Association Amendments Act of 2003 (99 U.S.C. 1921d) "
                "is amended by striking “a” and inserting “b”.\n")
    assert t[0].act == "Placeholder Association Amendments Act of 2003"


def test_title_of_the_code_is_not_an_act():
    t = targets("SEC. 2. CHANGE.\nTitle 10, United States Code, is amended—\n(1) in section 1558(b), by striking “a” "
                "and inserting “b”; and\n(2) in section 1559, by striking “c” and inserting “d”.\n")
    assert (t[0].kind, t[0].title, t[0].section) == ("usc", "10", "1558")


def test_striking_a_section_and_inserting_replaces_it():
    ins = parse_text("SEC. 2. CHANGE.\nChapter 9 of title 99, United States Code, is amended by striking section 905 and "
                     "inserting the following:\n“§ 905. Placeholder\n“The rule.”.\n").instructions
    assert (ins[0].op, ins[0].target.section, ins[0].target.qualifiers) == ("REPLACE_UNIT", "905", [])


def test_such_subchapter_reaches_back_to_an_earlier_section():
    ins = parse_text("SEC. 2. ONE.\nSubchapter II of chapter 17 of title 99, United States Code, is amended by adding at "
                     "the end the following new section:\n“§ 1720K. Alpha\n“The rule.”.\nSEC. 3. TWO.\nSuch subchapter is "
                     "further amended by inserting after section 1720K (as added by section 2) the following new section "
                     "(and conforming the table of sections at the beginning of such chapter accordingly):\n“§ 1720L. "
                     "Beta\n“The rule.”.\n").instructions
    t = ins[1].target
    assert (t.title, t.qualifiers) == ("99", ["subchapter ii of chapter 17"])
    assert ins[1].confidence == 1.0 and not any(f.startswith("unconsumed") for f in ins[1].flags)


def test_heading_edits_are_recognised():
    ins = parse_text("SEC. 2. HEADINGS.\n(a) One.—The heading for section 723 of title 99, United States Code, is amended by "
                     "striking “alpha” and inserting “beta”.\n(b) Two.—Title 99, United States Code, is amended—\n(1) In "
                     "the subsection heading for subsection (c) of section 3072, by striking “gamma” and inserting "
                     "“delta”; and\n(2) in section 2107(k), by striking the subsection heading.\n(c) Three.—Section 9 "
                     "of title 99, United States Code, is amended by striking the term “one” and inserting “two” in "
                     "each place it appears in text or headings.\n").instructions
    assert [i.op for i in ins] == ["AMEND_HEADING", "AMEND_HEADING", "AMEND_HEADING", "STRIKE_INSERT"]
    assert (ins[1].target.section, ins[1].target.path) == ("3072", ["(c)"])
    assert "heading struck" in ins[2].flags and "each place, headings included" in ins[3].flags


def test_such_section_is_the_whole_section():
    ins = parse_text("SEC. 2. CHANGES.\n(a) One.—Section 129a of title 99, United States Code, is amended in subsection "
                     "(b) by striking “a” and inserting “b”.\n(b) Two.—Such section 129a is amended by adding at the end "
                     "the following:\n“(h) Report.—Text.”.\n").instructions
    assert (ins[1].target.section, ins[1].target.path) == ("129a", [])


def test_definition_parentheticals_and_exceptions_do_not_name_the_target():
    ins = parse_text("SEC. 2. CHANGES.\n(a) One.—Except as provided in paragraph (2), each covered law (as defined in "
                     "section 102 of title 99, United States Code) is amended by striking the term “alpha officer” and "
                     "inserting “beta officer” in each place it appears in text or headings.\n").instructions
    assert ins[0].target.section is None and ins[0].target.path == []
