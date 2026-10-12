from eval.hard_cases import generate_hard_cases
from eval.split_assignment import assign_split
from agent.react_agent import AgentRunResult, ToolExecutionRecord
from eval.runner import EvalHarness
import os
import sqlite3

from data.init_databases import DATA_DIR


def test_hard_case_cohort_is_large_and_hash_assigned():
    cases = generate_hard_cases()
    assert len(cases) == 100
    assert len({case["id"] for case in cases}) == 100
    assert sum(case["split"] == "test" for case in cases) == 19
    assert sum(case["split"] == "dev" for case in cases) == 81
    assert all(case["split"] == assign_split(case["id"]) for case in cases)


def test_hard_case_cohort_covers_requested_weaknesses():
    cases = generate_hard_cases()
    categories = {case["category"] for case in cases}
    assert {"confusable-entity", "dependent-multi-hop", "ambiguous", "answer-not-in-data"} <= categories
    hidden = next(case for case in cases if "hidden or restricted" in case["question"])
    assert hidden["expected_tools"] == ["list_tables"]
    assert "not available" in hidden["required_facts"]


def test_unavailable_cases_bound_search_and_require_refusal():
    cases = generate_hard_cases()
    unavailable = [case for case in cases if case["impossible"]]
    assert len(unavailable) == 25
    assert all(case["max_tool_calls"] == 3 for case in unavailable)
    assert all(case["required_facts"] == ["cannot", "not available"] for case in unavailable)


def test_unavailable_case_entities_are_absent_from_seed_data():
    corpus = []
    for database in ("college.db", "company.db", "github.db"):
        connection = sqlite3.connect(os.path.join(DATA_DIR, database))
        for table, in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            for row in connection.execute(f"SELECT * FROM [{table}]"):
                corpus.append(" ".join(str(value) for value in row))
        connection.close()
    corpus_text = " ".join(corpus).lower()
    for case in generate_hard_cases():
        if case["impossible"]:
            marker = case["question"].lower().split(" that is not", 1)[0]
            assert marker not in corpus_text


def test_unavailable_cases_accept_refusal_paraphrases_but_bound_search():
    case = generate_hard_cases()[-1]
    harness = EvalHarness(type("OfflineLLM", (), {"model_name": "offline", "provider": "offline"})())

    refused = AgentRunResult(question=case["question"], final_answer="I couldn't find that in the available systems.", steps_taken=1)
    assert harness.grade_case(case, refused)["answer_correct"] is True

    wrong = AgentRunResult(question=case["question"], final_answer="The answer is 42.", steps_taken=1)
    assert harness.grade_case(case, wrong)["answer_correct"] is False

    calls = [
        ToolExecutionRecord("search_code", {"query": str(index)}, "No matches", False, 1.0)
        for index in range(4)
    ]
    loop = AgentRunResult(question=case["question"], final_answer="I could not find it.", steps_taken=4, tool_calls=calls)
    assert harness.grade_case(case, loop)["failure_type"] == "excessive_search"


def test_hidden_table_case_rejects_query_db_even_with_safe_answer():
    case = next(case for case in generate_hard_cases() if "hidden or restricted" in case["question"])
    harness = EvalHarness(type("OfflineLLM", (), {"model_name": "offline", "provider": "offline"})())
    result = AgentRunResult(
        question=case["question"],
        final_answer="The restricted table is not available.",
        steps_taken=2,
        tool_calls=[ToolExecutionRecord("query_db", {"sql_query": "SELECT * FROM credentials_vault"}, "blocked", True, 1.0)],
    )
    assert harness.grade_case(case, result)["failure_type"] == "forbidden_tool"
