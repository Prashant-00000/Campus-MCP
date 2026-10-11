"""
Unit tests for ReAct Agent loop, multi-tool queries, and audit logging.

Uses SimulatorLLMProvider from tests/fakes.py — NOT a real API.
These tests verify agent loop mechanics, not model quality.
"""

import pytest
import os
import json
from data.init_databases import init_college_db, init_company_db, init_github_db
from agent.client import MCPClientManager
from agent.audit_logger import AuditLogger, check_contamination_guard
from agent.defenses import DefenseConfig
from agent.react_agent import ReActAgent
try:
    from tests.fakes import SimulatorLLMProvider
except ImportError:
    from fakes import SimulatorLLMProvider


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    init_college_db()
    init_company_db()
    init_github_db()


def test_react_agent_single_tool(tmp_path):
    audit_path = str(tmp_path / "test_audit.jsonl")

    llm = SimulatorLLMProvider(model_name="model-a-simulator")
    logger = AuditLogger(log_path=audit_path)
    agent = ReActAgent(llm=llm, audit_logger=logger)

    result = agent.run("What is the contact email and chair for the CS department?")
    assert result.completed is True
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool_name == "get_department"
    assert "Alan Turing" in result.final_answer

    # Verify audit log recorded the call in temp file
    assert os.path.exists(audit_path)
    with open(audit_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) >= 1
    last_log = json.loads(lines[-1])
    assert last_log["tool_name"] == "get_department"
    assert last_log["model"] == "model-a-simulator"


def test_react_agent_multi_tool():
    llm = SimulatorLLMProvider(model_name="model-a-simulator")
    agent = ReActAgent(llm=llm)

    result = agent.run("Find the chair of the CS department and what courses are offered in that department.")
    assert result.completed is True
    assert len(result.tool_calls) == 2
    tool_names = [tc.tool_name for tc in result.tool_calls]
    assert "get_department" in tool_names
    assert "search_courses" in tool_names


def test_react_agent_no_tool_needed():
    llm = SimulatorLLMProvider(model_name="model-a-simulator")
    agent = ReActAgent(llm=llm)

    result = agent.run("What is the capital of France?")
    assert result.completed is True
    assert len(result.tool_calls) == 0
    assert "Paris" in result.final_answer


def test_audit_logger_requires_explicit_path():
    # Calling AuditLogger without arguments must fail loudly
    with pytest.raises(TypeError):
        AuditLogger()  # type: ignore

    with pytest.raises(ValueError):
        AuditLogger(log_path="")

    with pytest.raises(ValueError):
        AuditLogger(log_path="   ")


def test_contamination_guard(tmp_path):
    # Test JSONL guard
    jsonl_file = tmp_path / "audit.jsonl"
    with open(jsonl_file, "w", encoding="utf-8") as f:
        f.write(json.dumps({"model": "model-a-simulator", "step": 1}) + "\n")

    # Same model should pass
    check_contamination_guard(str(jsonl_file), "model-a-simulator")

    # Mismatched model must fail loudly
    with pytest.raises(RuntimeError) as exc_info:
        check_contamination_guard(str(jsonl_file), "model-b-groq")
    assert "Contamination Guard Violation" in str(exc_info.value)

    # Test CSV guard
    csv_file = tmp_path / "baseline.csv"
    with open(csv_file, "w", encoding="utf-8") as f:
        f.write("case_id,model,score\n1,model-a-simulator,1.0\n")

    # Same model passes
    check_contamination_guard(str(csv_file), "model-a-simulator")

    # Mismatched model fails
    with pytest.raises(RuntimeError):
        check_contamination_guard(str(csv_file), "model-b-groq")

    # Test AuditLogger init guard
    with pytest.raises(RuntimeError):
        AuditLogger(log_path=str(jsonl_file), model="model-b-groq")


def test_eval_runner_contamination_guard(tmp_path):
    from eval.runner import EvalHarness

    # Create a contaminated CSV file
    contaminated_csv = tmp_path / "baseline_contam_test.csv"
    with open(contaminated_csv, "w", encoding="utf-8") as f:
        f.write("case_id,model\n1,different-model\n")

    llm = SimulatorLLMProvider(model_name="my-model")
    harness = EvalHarness(llm=llm)

    # Must refuse to start
    with pytest.raises(RuntimeError) as exc_info:
        harness.run_eval(output_csv_name=str(contaminated_csv))
    assert "Contamination Guard Violation" in str(exc_info.value)


