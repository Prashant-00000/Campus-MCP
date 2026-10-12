"""
Unit tests for Grader v2 text normalization and atomic fact scoring in eval/scoring.py.
Includes positive (correct answer) and negative (incorrect answer) validation cases.
"""

import pytest
from eval.scoring import (
    normalize_text,
    check_facts_present,
    check_facts_present_v1,
    date_variants,
    check_single_fact
)


def test_normalize_l2_01_verbatim():
    """Exact raw text produced by model in L2-01 with narrow NBSP and non-breaking hyphen."""
    raw_answer = "**Computer Science Department**\n\n- **Chair:** Dr. Alan\u202fTuring  \n- **Contact Email:** cs\u2011chair@univ.edu"
    assert check_facts_present(raw_answer, ["cs-chair@univ.edu", "Alan Turing"])


def test_grader_v2_case_02_right_and_wrong():
    """Case 02: Office location and chair (atomic facts: Alan Turing, Turing Hall, 401)."""
    facts = ["Alan Turing", "Turing Hall", "401"]
    
    # Correct answer with narrow NBSP
    correct_ans = "The chair of the Computer\u202fScience department is **Dr. Alan\u202fTuring**, and his office is located in **Turing Hall, room\u202f401**."
    assert check_facts_present(correct_ans, facts)

    # Wrong room number (402 instead of 401) -> MUST FAIL
    wrong_room = "The chair of the Computer\u202fScience department is **Dr. Alan\u202fTuring**, and his office is located in **Turing Hall, room\u202f402**."
    assert not check_facts_present(wrong_room, facts)

    # Wrong person (Grace Hopper instead of Alan Turing) -> MUST FAIL
    wrong_person = "The chair of the Computer\u202fScience department is **Dr. Grace Hopper**, and his office is located in **Turing Hall, room\u202f401**."
    assert not check_facts_present(wrong_person, facts)

    # Room 4010 must NOT match 401 due to word boundary matching -> MUST FAIL
    stray_room = "Dr. Alan\u202fTuring is in Turing Hall, room 4010."
    assert not check_facts_present(stray_room, facts)


def test_grader_v2_case_03_right_and_wrong():
    """Case 03: Date variant matching and event title (Career & Internship Fair, 2026-11-02)."""
    facts = ["Career & Internship Fair", "2026-11-02"]

    # Correct: Model writes 'November 2, 2026' with non-breaking hyphen in description
    correct_ans = "Upcoming: November\u202f2,\u202f2026 Tech Career & Internship Fair in Campus Pavilion. Full\u2011time roles."
    assert check_facts_present(correct_ans, facts)

    # Wrong date: 'November 3, 2026' -> MUST FAIL
    wrong_date = "Upcoming: November 3, 2026 Tech Career & Internship Fair in Campus Pavilion."
    assert not check_facts_present(wrong_date, facts)

    # Wrong event: 'November 2, 2026' but hackathon instead -> MUST FAIL
    wrong_event = "Upcoming: November 2, 2026 Fall Hackathon in Student Union Ballroom."
    assert not check_facts_present(wrong_event, facts)


def test_grader_v2_case_04_right_and_wrong():
    """Case 04: Office hours day expansion (Compilers, Tue, Thu)."""
    facts = ["Compilers", "Tue", "Thu"]

    # Correct: Model expands to 'Tuesday & Thursday'
    correct_ans = "**Dr. Grace Hopper**\n- Research area: Compilers, Architecture\n- Office hours: Tuesday & Thursday, 10\u202fAM\u202f–\u202f12\u202fPM"
    assert check_facts_present(correct_ans, facts)

    # Wrong days: 'Monday & Wednesday' -> MUST FAIL
    wrong_days = "**Dr. Grace Hopper**\n- Research area: Compilers, Architecture\n- Office hours: Monday & Wednesday, 10 AM – 12 PM"
    assert not check_facts_present(wrong_days, facts)

    # Missing research area -> MUST FAIL
    missing_area = "**Dr. Grace Hopper**\n- Research area: Distributed Systems\n- Office hours: Tuesday & Thursday, 10 AM – 12 PM"
    assert not check_facts_present(missing_area, facts)


def test_grader_v2_case_15_right_and_wrong():
    """Case 15: Hackathon date variant (2026-10-25)."""
    facts = ["2026-10-25"]

    # Correct: 'October 25, 2026'
    correct_ans = "Fall Hackathon 2026 is scheduled on October\u202f25,\u202f2026 at Student Union Ballroom."
    assert check_facts_present(correct_ans, facts)

    # Wrong date: 'October 26, 2026' -> MUST FAIL
    wrong_date = "Fall Hackathon 2026 is scheduled on October 26, 2026 at Student Union Ballroom."
    assert not check_facts_present(wrong_date, facts)


def test_word_boundary_numeric_matching():
    """Numeric word-boundary matching prevents substring false positives."""
    norm = normalize_text("The result is 4010 items.")
    assert not check_single_fact(norm, "401")
    assert check_single_fact(norm, "4010")

    norm2 = normalize_text("Office is in room 401.")
    assert check_single_fact(norm2, "401")


def test_date_variants_generation():
    """Date variant expansion handles various canonical textual representations."""
    variants = date_variants("2026-11-02")
    assert "2026-11-02" in variants
    assert "november 2, 2026" in variants
    assert "nov 2, 2026" in variants
    assert "2 november 2026" in variants
    assert "november 3, 2026" not in variants


def test_provenance_v1_vs_v2():
    """Demonstrate v1 fails on natural language dates while v2 passes."""
    ans = "Event is on November 2, 2026."
    facts = ["2026-11-02"]
    assert not check_facts_present_v1(ans, facts)
    assert check_facts_present(ans, facts)


def test_stronger_dev_case_facts_reject_weak_answers():
    assert check_facts_present(
        "CS201 Data Structures & Algorithms",
        ["CS201", "Data Structures", "Algorithms"],
    )
    assert not check_facts_present(
        "CS201 Algorithms",
        ["CS201", "Data Structures", "Algorithms"],
    )

    assert check_facts_present(
        "products: price REAL; stock_quantity INTEGER",
        ["products", "price", "stock_quantity"],
    )
    assert not check_facts_present(
        "the table has price and stock_quantity columns",
        ["products", "price", "stock_quantity"],
    )

    assert check_facts_present(
        "Dr. Alan Turing, Professor & Chair, Theory of Computation",
        ["Alan Turing", "Professor & Chair", "Theory of Computation"],
    )
    assert not check_facts_present(
        "Dr. Alan Turing is faculty",
        ["Alan Turing", "Professor & Chair", "Theory of Computation"],
    )
