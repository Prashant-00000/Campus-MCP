from eval.hand_cases import generate_hand_cases
from eval.split_assignment import assign_split
import os
import sqlite3

from data.init_databases import DATA_DIR


def test_hand_cases_are_varied_and_hash_assigned():
    cases = generate_hand_cases()
    assert len(cases) == 10
    assert len({case["id"] for case in cases}) == 10
    assert {case["template"] for case in cases} == {
        "hand-dependent-order", "hand-issue-file-hop", "hand-confusable-physics",
        "hand-hidden-table", "hand-ambiguous-person", "hand-unavailable-code",
        "hand-product-lookup", "hand-event-location", "hand-restricted-schema",
        "hand-general-mcp",
    }
    assert all(case["split"] == assign_split(case["id"]) for case in cases)


def test_hand_cases_include_hidden_and_bounded_unavailable_behaviors():
    cases = generate_hand_cases()
    hidden = [case for case in cases if case["category"] == "hidden-table"]
    assert len(hidden) == 2
    assert all("query_db" in case["forbidden_tools"] for case in hidden)
    unavailable = next(case for case in cases if case["category"] == "answer-not-in-data")
    assert unavailable["max_tool_calls"] == 3
    assert unavailable["refusal_indicators"]


def test_hand_unavailable_entity_is_absent_from_seed_databases():
    corpus = []
    for database in ("college.db", "company.db", "github.db"):
        connection = sqlite3.connect(os.path.join(DATA_DIR, database))
        for table, in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            for row in connection.execute(f"SELECT * FROM [{table}]"):
                corpus.append(" ".join(str(value) for value in row))
        connection.close()
    assert "worker-pool implementation" not in " ".join(corpus).lower()
