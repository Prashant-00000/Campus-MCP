"""
Tests for ReAct Agent loop, multi-tool queries, and audit logging.
"""

import pytest
import os
import json
from data.init_databases import init_college_db, init_company_db, init_github_db
from agent.client import MCPClientManager
from agent.llm import LLMProvider
from agent.audit_logger import AuditLogger
from agent.defenses import DefenseConfig
from agent.react_agent import ReActAgent

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    init_college_db()
    init_company_db()
    init_github_db()

def test_react_agent_single_tool():
    audit_path = os.path.join("audit_logs", "test_audit.jsonl")
    if os.path.exists(audit_path):
        os.remove(audit_path)

    llm = LLMProvider(model_name="model-a-simulator", provider="simulator")
    logger = AuditLogger(log_path=audit_path)
    agent = ReActAgent(llm=llm, audit_logger=logger)

    result = agent.run("What is the contact email and chair for the CS department?")
    assert result.completed is True
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool_name == "get_department"
    assert "Alan Turing" in result.final_answer

    # Verify audit log recorded the call
    assert os.path.exists(audit_path)
    with open(audit_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) >= 1
    last_log = json.loads(lines[-1])
    assert last_log["tool_name"] == "get_department"

def test_react_agent_multi_tool():
    llm = LLMProvider(model_name="model-a-simulator", provider="simulator")
    agent = ReActAgent(llm=llm)

    result = agent.run("Find the chair of the CS department and what courses are offered in that department.")
    assert result.completed is True
    assert len(result.tool_calls) == 2
    tool_names = [tc.tool_name for tc in result.tool_calls]
    assert "get_department" in tool_names
    assert "search_courses" in tool_names

def test_react_agent_no_tool_needed():
    llm = LLMProvider(model_name="model-a-simulator", provider="simulator")
    agent = ReActAgent(llm=llm)

    result = agent.run("What is the capital of France?")
    assert result.completed is True
    assert len(result.tool_calls) == 0
    assert "Paris" in result.final_answer
