"""Parser targets (M4/M5): references clauses, Acts cited by date or long title, nested Act units, "such Act".
Drafts are synthetic; Act names and numbers are placeholders."""
from billmap.parse import parse_text


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
