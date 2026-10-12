from eval.hard_cases import generate_hard_cases
from eval.split_assignment import assign_split


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
