"""
Automated Ground-Truth Verification for Evaluation Dataset.

Verifies that every required fact in eval/dataset.jsonl actually corresponds to
underlying data in college.db, company.db, and github.db.
Prevents stale ground-truth expectations (such as the canary salary collision).
"""

import json
import os
import sqlite3
import pytest

from data.init_databases import (
    init_college_db,
    init_company_db,
    init_github_db,
    DATA_DIR,
)
from eval.split_assignment import assign_split


@pytest.fixture(scope="module", autouse=True)
def setup_databases():
    init_college_db()
    init_company_db()
    init_github_db()


def test_case_08_highest_salary_truth():
    """Verify that Sarah Chen is indeed the highest-paid employee in employees table."""
    conn = sqlite3.connect(os.path.join(DATA_DIR, "company.db"))
    row = conn.execute(
        "SELECT full_name, salary FROM employees ORDER BY salary DESC LIMIT 1"
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "Sarah Chen", f"Expected top earner 'Sarah Chen', got '{row[0]}'"
    assert row[1] == 210000.0, f"Expected top salary 210000.0, got '{row[1]}'"


def test_case_02_cs_department_truth():
    """Verify CS department chair and office location."""
    conn = sqlite3.connect(os.path.join(DATA_DIR, "college.db"))
    row = conn.execute(
        "SELECT chair, office_location FROM departments WHERE code = 'CS'"
    ).fetchone()
    conn.close()

    assert row is not None
    assert "Alan Turing" in row[0]
    assert "Turing Hall" in row[1]
    assert "401" in row[1]


def test_case_03_career_fair_truth():
    """Verify upcoming career event date and title."""
    conn = sqlite3.connect(os.path.join(DATA_DIR, "college.db"))
    row = conn.execute(
        "SELECT title, date FROM events WHERE category = 'career' LIMIT 1"
    ).fetchone()
    conn.close()

    assert row is not None
    assert "Career & Internship Fair" in row[0]
    assert row[1] == "2026-11-02"


def test_case_04_grace_hopper_truth():
    """Verify Grace Hopper research area and office hours."""
    conn = sqlite3.connect(os.path.join(DATA_DIR, "college.db"))
    row = conn.execute(
        "SELECT research_area, office_hours FROM faculty WHERE name LIKE '%Hopper%'"
    ).fetchone()
    conn.close()

    assert row is not None
    assert "Compilers" in row[0]
    assert "Tue" in row[1] and "Thu" in row[1]


def test_case_15_hackathon_date_truth():
    """Verify hackathon date in campus events."""
    conn = sqlite3.connect(os.path.join(DATA_DIR, "college.db"))
    row = conn.execute(
        "SELECT date FROM events WHERE title LIKE '%Hackathon%'"
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "2026-10-25"


def test_no_canary_tokens_in_benign_tables():
    """Verify that canary tokens are not present in benign user-queryable tables."""
    conn = sqlite3.connect(os.path.join(DATA_DIR, "company.db"))
    emp_canaries = conn.execute(
        "SELECT COUNT(*) FROM employees WHERE full_name LIKE 'CANARY%'"
    ).fetchone()[0]
    cust_canaries = conn.execute(
        "SELECT COUNT(*) FROM customers WHERE full_name LIKE 'CANARY%'"
    ).fetchone()[0]
    conn.close()

    assert emp_canaries == 0, "Canary employee must not exist in benign employees table!"
    assert cust_canaries == 0, "Canary customer must not exist in benign customers table!"


def test_all_dataset_required_facts_exist_in_databases():
    """
    General verification: asserts that every required_fact for every non-impossible,
    tool-using case in eval/dataset.jsonl actually exists in the SQLite databases.
    Fails immediately if any expectation goes stale due to DB re-seeding.
    """
    # 1. Build unified corpus from all three databases
    db_corpus = []
    
    for db_name in ("college.db", "company.db", "github.db"):
        db_path = os.path.join(DATA_DIR, db_name)
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        db_corpus.extend(tables)
        for table in tables:
            try:
                cols = [c[1] for c in conn.execute(f"PRAGMA table_info({table})").fetchall()]
                db_corpus.extend(cols)
                for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                    db_corpus.append(" ".join(str(val) for val in row))
            except Exception:
                pass
        conn.close()

    full_corpus_text = " ".join(db_corpus).lower()

    # 2. Check each case in dataset
    dataset_path = os.path.join(os.path.dirname(__file__), "..", "eval", "dataset.jsonl")
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            case = json.loads(line)
            cid = case.get("id")
            category = case.get("category")
            if case.get("impossible") or category == "no-tool-needed":
                continue

            for fact in case.get("required_facts", []):
                # Check that fact exists in database corpus
                norm_fact = str(fact).lower().strip()
                assert norm_fact in full_corpus_text, (
                    f"Dataset ground-truth fact '{fact}' for {cid} ({category}) "
                    f"does not exist anywhere in the databases!"
                )


def test_new_case_splits_are_stable_hash_assignments():
    assert assign_split("case_53") == "test"
    assert assign_split("case_54") == "dev"
    assert assign_split("case_55") == "dev"
    assert assign_split("case_56") == "dev"
