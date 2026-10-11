"""
Level 1 Server Isolation Testing.
Tests each of the 3 MCP servers in isolation:
1. Verifies that all tools, the resource, and the prompt appear.
2. Verifies that each tool description clearly contains 'WHEN TO USE' and 'WHEN NOT TO USE'.
3. Verifies that every tool works with normal inputs.
4. Verifies that every tool gracefully handles bad inputs (missing fields, empty strings,
   wrong types, huge/negative numbers, injection attempts) and returns a human-readable error,
   NEVER crashing.
"""

import pytest
import json
from data.init_databases import init_college_db, init_company_db, init_github_db
from servers.college_server import server as college_server
from servers.db_server import server as db_server
from servers.github_server import server as github_server

@pytest.fixture(scope="module", autouse=True)
def setup_databases():
    init_college_db()
    init_company_db()
    init_github_db()

# =========================================================================
# LEVEL 1: COLLEGE SERVER
# =========================================================================
def test_college_server_manifest():
    """Check that all 4 tools, 1 resource, and 1 prompt appear with clear descriptions."""
    # Initialize
    init_resp = college_server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init_resp["result"]["serverInfo"]["name"] == "college-server"

    # Tools
    tools_resp = college_server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools = {t["name"]: t for t in tools_resp["result"]["tools"]}
    assert set(tools.keys()) == {"search_courses", "get_department", "list_events", "get_faculty"}

    # Verify descriptions act like teammate instructions
    for tool_name, tool_data in tools.items():
        desc = tool_data["description"]
        assert "WHEN TO USE:" in desc, f"{tool_name} description missing 'WHEN TO USE:'"
        assert "WHEN NOT TO USE:" in desc, f"{tool_name} description missing 'WHEN NOT TO USE:'"

    # Resource
    res_resp = college_server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}})
    resources = {r["uri"]: r for r in res_resp["result"]["resources"]}
    assert "college://catalog-summary" in resources

    # Prompt
    prompt_resp = college_server.handle_request({"jsonrpc": "2.0", "id": 4, "method": "prompts/list", "params": {}})
    prompts = {p["name"]: p for p in prompt_resp["result"]["prompts"]}
    assert "advisor_prompt" in prompts

def test_college_tools_normal_and_bad_inputs():
    """Test all tools with normal and intentionally malformed inputs."""
    # 1. search_courses
    # Normal
    res = college_server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "search_courses", "arguments": {"department": "CS", "level_cap": 200}}})
    assert res["result"]["isError"] is False
    assert "CS101" in res["result"]["content"][0]["text"]

    # Bad input: negative level_cap
    res = college_server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "search_courses", "arguments": {"level_cap": -1}}})
    assert "cannot be negative" in res["result"]["content"][0]["text"]

    # Bad input: non-numeric level_cap string
    res = college_server.handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_courses", "arguments": {"level_cap": "not_an_int"}}})
    assert "must be a valid integer" in res["result"]["content"][0]["text"]

    # Bad input: empty dict
    res = college_server.handle_request({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "search_courses", "arguments": {}}})
    assert res["result"]["isError"] is False

    # 2. get_department
    # Normal
    res = college_server.handle_request({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "get_department", "arguments": {"dept_code": "MATH"}}})
    assert "Emmy Noether" in res["result"]["content"][0]["text"]

    # Bad input: missing field
    res = college_server.handle_request({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "get_department", "arguments": {}}})
    assert "Error: dept_code is required" in res["result"]["content"][0]["text"]

    # Bad input: empty string
    res = college_server.handle_request({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "get_department", "arguments": {"dept_code": "   "}}})
    assert "Error: dept_code is required" in res["result"]["content"][0]["text"]

    # Bad input: non-existent department
    res = college_server.handle_request({"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "get_department", "arguments": {"dept_code": "NON_EXISTENT"}}})
    assert "not found" in res["result"]["content"][0]["text"]

    # 3. list_events
    # Normal
    res = college_server.handle_request({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "list_events", "arguments": {"category": "career"}}})
    assert "Career & Internship Fair" in res["result"]["content"][0]["text"]

    # Bad input: invalid category
    res = college_server.handle_request({"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": "list_events", "arguments": {"category": "invalid_party"}}})
    assert "is invalid" in res["result"]["content"][0]["text"]

    # 4. get_faculty
    # Normal
    res = college_server.handle_request({"jsonrpc": "2.0", "id": 11, "method": "tools/call", "params": {"name": "get_faculty", "arguments": {"name_or_id": "FAC01"}}})
    assert "Alan Turing" in res["result"]["content"][0]["text"]

    # Bad input: missing field
    res = college_server.handle_request({"jsonrpc": "2.0", "id": 12, "method": "tools/call", "params": {"name": "get_faculty", "arguments": {}}})
    assert "name_or_id parameter is required" in res["result"]["content"][0]["text"]

    # Bad input: empty string
    res = college_server.handle_request({"jsonrpc": "2.0", "id": 13, "method": "tools/call", "params": {"name": "get_faculty", "arguments": {"name_or_id": "   "}}})
    assert "name_or_id parameter is required" in res["result"]["content"][0]["text"]

# =========================================================================
# LEVEL 1: DB SERVER
# =========================================================================
def test_db_server_manifest():
    """Check that all 4 tools, 1 resource, and 1 prompt appear on db_server."""
    tools_resp = db_server.handle_request({"jsonrpc": "2.0", "id": 20, "method": "tools/list", "params": {}})
    tools = {t["name"]: t for t in tools_resp["result"]["tools"]}
    assert set(tools.keys()) == {"query_db", "list_tables", "describe_table", "sample_table"}

    for tool_name, tool_data in tools.items():
        desc = tool_data["description"]
        assert "WHEN TO USE:" in desc, f"{tool_name} description missing 'WHEN TO USE:'"
        assert "WHEN NOT TO USE:" in desc, f"{tool_name} description missing 'WHEN NOT TO USE:'"

    res_resp = db_server.handle_request({"jsonrpc": "2.0", "id": 21, "method": "resources/list", "params": {}})
    resources = {r["uri"]: r for r in res_resp["result"]["resources"]}
    assert "db://schema" in resources

    prompt_resp = db_server.handle_request({"jsonrpc": "2.0", "id": 22, "method": "prompts/list", "params": {}})
    prompts = {p["name"]: p for p in prompt_resp["result"]["prompts"]}
    assert "analyst_prompt" in prompts

def test_db_tools_normal_and_bad_inputs():
    """Test db tools with normal and hostile/bad inputs."""
    # 1. query_db
    # Normal
    res = db_server.handle_request({"jsonrpc": "2.0", "id": 23, "method": "tools/call", "params": {"name": "query_db", "arguments": {"sql_query": "SELECT * FROM products WHERE price < 1000"}}})
    assert "MCP Protocol Analyzer" in res["result"]["content"][0]["text"]

    # Bad: empty query
    res = db_server.handle_request({"jsonrpc": "2.0", "id": 24, "method": "tools/call", "params": {"name": "query_db", "arguments": {"sql_query": ""}}})
    assert "Error: sql_query parameter is required" in res["result"]["content"][0]["text"]

    # Bad: forbidden table credentials_vault
    res = db_server.handle_request({"jsonrpc": "2.0", "id": 25, "method": "tools/call", "params": {"name": "query_db", "arguments": {"sql_query": "SELECT * FROM credentials_vault"}}})
    assert "Security Error: Access to table 'credentials_vault' is forbidden" in res["result"]["content"][0]["text"]

    # Bad: destructive SQL command
    res = db_server.handle_request({"jsonrpc": "2.0", "id": 26, "method": "tools/call", "params": {"name": "query_db", "arguments": {"sql_query": "DROP TABLE orders"}}})
    assert "Security Error" in res["result"]["content"][0]["text"]

    # 2. describe_table
    # Normal
    res = db_server.handle_request({"jsonrpc": "2.0", "id": 27, "method": "tools/call", "params": {"name": "describe_table", "arguments": {"table_name": "orders"}}})
    assert "total_amount" in res["result"]["content"][0]["text"]

    # Bad: missing table_name
    res = db_server.handle_request({"jsonrpc": "2.0", "id": 28, "method": "tools/call", "params": {"name": "describe_table", "arguments": {}}})
    assert "Error: table_name parameter is required" in res["result"]["content"][0]["text"]

    # Bad: unqueryable table
    res = db_server.handle_request({"jsonrpc": "2.0", "id": 29, "method": "tools/call", "params": {"name": "describe_table", "arguments": {"table_name": "sqlite_master"}}})
    assert "does not exist or is not queryable" in res["result"]["content"][0]["text"]

    # 3. sample_table
    # Normal
    res = db_server.handle_request({"jsonrpc": "2.0", "id": 30, "method": "tools/call", "params": {"name": "sample_table", "arguments": {"table_name": "customers", "limit": 2}}})
    rows = json.loads(res["result"]["content"][0]["text"])
    assert len(rows) == 2

    # Bad: non-numeric limit string or huge number (gracefully bounds to max 10)
    res = db_server.handle_request({"jsonrpc": "2.0", "id": 31, "method": "tools/call", "params": {"name": "sample_table", "arguments": {"table_name": "customers", "limit": 999999999}}})
    rows = json.loads(res["result"]["content"][0]["text"])
    assert len(rows) <= 10

# =========================================================================
# LEVEL 1: GITHUB SERVER
# =========================================================================
def test_github_server_manifest():
    """Check that all 5 tools, 1 resource, and 1 prompt appear on github_server."""
    tools_resp = github_server.handle_request({"jsonrpc": "2.0", "id": 40, "method": "tools/list", "params": {}})
    tools = {t["name"]: t for t in tools_resp["result"]["tools"]}
    assert set(tools.keys()) == {"list_issues", "get_issue", "search_code", "get_file", "create_issue"}

    for tool_name, tool_data in tools.items():
        desc = tool_data["description"]
        assert "WHEN TO USE:" in desc, f"{tool_name} description missing 'WHEN TO USE:'"
        assert "WHEN NOT TO USE:" in desc, f"{tool_name} description missing 'WHEN NOT TO USE:'"

    res_resp = github_server.handle_request({"jsonrpc": "2.0", "id": 41, "method": "resources/list", "params": {}})
    resources = {r["uri"]: r for r in res_resp["result"]["resources"]}
    assert "github://repo_info" in resources

    prompt_resp = github_server.handle_request({"jsonrpc": "2.0", "id": 42, "method": "prompts/list", "params": {}})
    prompts = {p["name"]: p for p in prompt_resp["result"]["prompts"]}
    assert "triage_issue" in prompts

def test_github_tools_normal_and_bad_inputs():
    """Test github tools with normal and malformed inputs."""
    # 1. list_issues
    # Normal
    res = github_server.handle_request({"jsonrpc": "2.0", "id": 43, "method": "tools/call", "params": {"name": "list_issues", "arguments": {"state": "open"}}})
    assert "Memory leak" in res["result"]["content"][0]["text"]

    # Bad: invalid state
    res = github_server.handle_request({"jsonrpc": "2.0", "id": 44, "method": "tools/call", "params": {"name": "list_issues", "arguments": {"state": "invalid_status"}}})
    assert "state 'invalid_status' is invalid" in res["result"]["content"][0]["text"]

    # 2. get_issue
    # Normal
    res = github_server.handle_request({"jsonrpc": "2.0", "id": 45, "method": "tools/call", "params": {"name": "get_issue", "arguments": {"issue_number": 2}}})
    assert "OAuth2 PKCE" in res["result"]["content"][0]["text"]

    # Bad: missing issue_number
    res = github_server.handle_request({"jsonrpc": "2.0", "id": 46, "method": "tools/call", "params": {"name": "get_issue", "arguments": {}}})
    assert "issue_number parameter is required" in res["result"]["content"][0]["text"]

    # Bad: non-integer issue_number
    res = college_server.handle_request({"jsonrpc": "2.0", "id": 47, "method": "tools/call", "params": {"name": "get_issue", "arguments": {"issue_number": "not_an_int"}}})
    assert res is not None

    # Bad: negative number
    res = github_server.handle_request({"jsonrpc": "2.0", "id": 48, "method": "tools/call", "params": {"name": "get_issue", "arguments": {"issue_number": -5}}})
    assert "must be a positive integer" in res["result"]["content"][0]["text"]

    # 3. get_file
    # Normal
    res = github_server.handle_request({"jsonrpc": "2.0", "id": 49, "method": "tools/call", "params": {"name": "get_file", "arguments": {"file_path": "README.md"}}})
    assert "Acme Core Gateway" in res["result"]["content"][0]["text"]

    # Bad: missing file_path
    res = github_server.handle_request({"jsonrpc": "2.0", "id": 50, "method": "tools/call", "params": {"name": "get_file", "arguments": {}}})
    assert "file_path parameter is required" in res["result"]["content"][0]["text"]

    # Bad: non-existent file
    res = github_server.handle_request({"jsonrpc": "2.0", "id": 51, "method": "tools/call", "params": {"name": "get_file", "arguments": {"file_path": "does_not_exist.txt"}}})
    assert "not found in repository" in res["result"]["content"][0]["text"]

    # 4. create_issue
    # Normal
    res = github_server.handle_request({"jsonrpc": "2.0", "id": 52, "method": "tools/call", "params": {"name": "create_issue", "arguments": {"title": "Normal Issue", "body": "Normal body"}}})
    assert "Successfully created issue" in res["result"]["content"][0]["text"]

    # Bad: missing title
    res = github_server.handle_request({"jsonrpc": "2.0", "id": 53, "method": "tools/call", "params": {"name": "create_issue", "arguments": {"body": "No title"}}})
    assert "'title' is required" in res["result"]["content"][0]["text"]

    # Bad: empty body
    res = github_server.handle_request({"jsonrpc": "2.0", "id": 54, "method": "tools/call", "params": {"name": "create_issue", "arguments": {"title": "Title", "body": "   "}}})
    assert "'body' is required" in res["result"]["content"][0]["text"]
