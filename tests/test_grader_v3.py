from agent.react_agent import AgentRunResult, ToolExecutionRecord
from eval.runner import EvalHarness


class FakeLLM:
    model_name = "grader-test"
    provider = "test"


def make_result(tool_calls, answer="The answer is correct.", completed=True, steps=1):
    records = [
        ToolExecutionRecord(
            tool_name=name,
            arguments=args,
            result=result,
            is_error=False,
            latency_ms=1.0,
        )
        for name, args, result in tool_calls
    ]
    return AgentRunResult(
        question="test",
        final_answer=answer,
        steps_taken=steps,
        tool_calls=records,
        completed=completed,
    )


def test_grader_v3_missing_argument_fails_and_reports_accuracy():
    harness = EvalHarness(FakeLLM())
    case = {
        "expected_tools": ["get_department"],
        "expected_args": {"dept_code": "CS"},
        "required_facts": ["correct"],
    }

    graded = harness.grade_case(
        case,
        make_result([("get_department", {}, "correct")]),
    )

    assert graded["argument_ok"] is False
    assert graded["argument_accuracy"] == 0.0
    assert graded["argument_checks"] == 1
    assert graded["task_success"] is True
    assert graded["answer_correct"] is True
    assert graded["tool_use_quality"] is False


def test_grader_v3_accepts_whole_word_argument_expansion():
    harness = EvalHarness(FakeLLM())
    case = {
        "expected_tools": ["get_faculty"],
        "expected_args": {"name_or_id": "Hopper"},
        "required_facts": ["correct"],
    }

    graded = harness.grade_case(
        case,
        make_result([("get_faculty", {"name_or_id": "Grace Hopper"}, "correct")]),
    )

    assert graded["argument_ok"] is True
    assert graded["tool_use_quality"] is True


def test_grader_v3_tool_precision_recall_and_redundancy():
    harness = EvalHarness(FakeLLM())
    case = {
        "expected_tools": ["get_issue", "search_code"],
        "expected_args": {},
        "required_facts": ["correct"],
    }

    graded = harness.grade_case(
        case,
        make_result([
            ("get_issue", {}, "correct"),
            ("search_code", {}, "correct"),
            ("search_code", {}, "correct"),
            ("list_issues", {}, "irrelevant"),
        ]),
    )

    assert graded["tool_precision"] == 0.5
    assert graded["tool_recall"] == 1.0
    assert graded["extra_calls"] == 2
    assert graded["redundant_calls"] == 1
    assert graded["tool_selection_ok"] is False
    assert graded["argument_accuracy"] is None
    assert graded["argument_checks"] == 0
    assert graded["task_success"] is True
    assert graded["answer_correct"] is True
    assert graded["tool_use_quality"] is False


def test_grader_v3_incomplete_loop_cannot_pass():
    harness = EvalHarness(FakeLLM())
    case = {
        "expected_tools": ["get_issue", "search_code"],
        "expected_args": {},
        "required_facts": ["correct"],
    }

    graded = harness.grade_case(
        case,
        make_result(
            [("get_issue", {}, "correct")] * 10,
            answer="",
            completed=False,
            steps=10,
        ),
    )

    assert graded["failure_type"] == "loop"
    assert graded["task_success"] is False
    assert graded["redundant_calls"] == 9
