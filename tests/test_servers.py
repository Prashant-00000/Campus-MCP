"""
Unit tests for College, DB, and GitHub MCP servers.
Verifies tool execution, resource reading, prompt generation, and security boundaries.
"""

import pytest
import json
from data.init_databases import init_college_db, init_company_db, init_github_db
from servers.college_server import server as college_server
from servers.db_server import server as db_server, validate_sql_query
from servers.github_server import server as github_server

@pytest.fixture(scope="module", autouse=True)
def setup_databases():
    init_college_db()
    init_company_db()
    init_github_db()

# =========================================================================
# College Server Tests
# =========================================================================
def test_college_search_courses():
    res = college_server.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "search_courses",
            "arguments": {"query": "Algorithms", "department": "CS"}
        }
    })
    assert res["result"]["isError"] is False
    content = json.loads(res["result"]["content"][0]["text"])
    assert any(c["course_code"] == "CS201" for c in content)

def test_college_get_department():
    res = college_server.handle_request({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "get_department",
            "arguments": {"dept_code": "CS"}
        }
    })
    assert res["result"]["isError"] is False
    dept = json.loads(res["result"]["content"][0]["text"])
    assert dept["chair"] == "Dr. Alan Turing"
    assert dept["code"] == "CS"

def test_college_list_events():
    res = college_server.handle_request({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "list_events",
            "arguments": {"category": "workshop"}
        }
    })
    assert res["result"]["isError"] is False
    events = json.loads(res["result"]["content"][0]["text"])
    assert len(events) >= 1
    assert "Hackathon" in events[0]["title"]

def test_college_get_faculty():
    res = college_server.handle_request({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "get_faculty",
            "arguments": {"name_or_id": "Hopper"}
        }
    })
    assert res["result"]["isError"] is False
    fac = json.loads(res["result"]["content"][0]["text"])
    assert fac[0]["id"] == "FAC02"

def test_college_resource_and_prompt():
    res_resource = college_server.handle_request({
        "jsonrpc": "2.0",
        "id": 5,
        "method": "resources/read",
        "params": {"uri": "college://catalog-summary"}
    })
    assert "College Catalog Overview" in res_resource["result"]["contents"][0]["text"]

    res_prompt = college_server.handle_request({
        "jsonrpc": "2.0",
        "id": 6,
        "method": "prompts/get",
        "params": {"name": "advisor_prompt", "arguments": {"student_major": "CS", "year": "Junior"}}
    })
    assert "CS" in res_prompt["result"]["messages"][0]["content"]["text"]

# =========================================================================
# DB Server Tests & Security Bounds
# =========================================================================
def test_db_valid_select_query():
    res = db_server.handle_request({
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/call",
        "params": {
            "name": "query_db",
            "arguments": {"sql_query": "SELECT order_id, total_amount, status FROM orders WHERE status = 'COMPLETED'"}
        }
    })
    assert res["result"]["isError"] is False
    orders = json.loads(res["result"]["content"][0]["text"])
    assert len(orders) >= 1
    assert orders[0]["status"] == "COMPLETED"

def test_db_security_block_destructive_queries():
    # DROP TABLE
    is_valid, err = validate_sql_query("DROP TABLE orders;")
    assert is_valid is False
    assert "Only 'SELECT' queries are allowed" in err

    # INSERT
    is_valid, err = validate_sql_query("INSERT INTO orders VALUES (999, 101, '2026-10-11', 100, 'COMPLETED');")
    assert is_valid is False

    # Stacked queries
    is_valid, err = validate_sql_query("SELECT * FROM orders; DROP TABLE products;")
    assert is_valid is False
    assert "Stacked" in err

def test_db_security_block_unauthorized_table():
    # Attempting to access sensitive credentials_vault
    is_valid, err = validate_sql_query("SELECT * FROM credentials_vault")
    assert is_valid is False
    assert "credentials_vault' is forbidden" in err

    # Calling query_db with forbidden table
    res = db_server.handle_request({
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "query_db",
            "arguments": {"sql_query": "SELECT * FROM credentials_vault"}
        }
    })
    assert "Security Error" in res["result"]["content"][0]["text"]

def test_db_list_and_describe_tables():
    res_list = db_server.handle_request({
        "jsonrpc": "2.0",
        "id": 12,
        "method": "tools/call",
        "params": {"name": "list_tables", "arguments": {}}
    })
    tables = json.loads(res_list["result"]["content"][0]["text"])
    table_names = [t["table_name"] for t in tables]
    assert "orders" in table_names
    assert "credentials_vault" not in table_names

    res_desc = db_server.handle_request({
        "jsonrpc": "2.0",
        "id": 13,
        "method": "tools/call",
        "params": {"name": "describe_table", "arguments": {"table_name": "products"}}
    })
    desc = json.loads(res_desc["result"]["content"][0]["text"])
    col_names = [c["name"] for c in desc["columns"]]
    assert "price" in col_names

# =========================================================================
# GitHub Server Tests
# =========================================================================
def test_github_list_and_get_issue():
    res_list = github_server.handle_request({
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {"name": "list_issues", "arguments": {"state": "open"}}
    })
    issues = json.loads(res_list["result"]["content"][0]["text"])
    assert len(issues) >= 1

    res_get = github_server.handle_request({
        "jsonrpc": "2.0",
        "id": 21,
        "method": "tools/call",
        "params": {"name": "get_issue", "arguments": {"issue_number": 1}}
    })
    issue = json.loads(res_get["result"]["content"][0]["text"])
    assert "Memory leak" in issue["title"]

def test_github_files_and_search():
    res_search = github_server.handle_request({
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/call",
        "params": {"name": "search_code", "arguments": {"query": "verify_signature"}}
    })
    matches = json.loads(res_search["result"]["content"][0]["text"])
    assert matches[0]["path"] == "src/auth.py"

    res_file = github_server.handle_request({
        "jsonrpc": "2.0",
        "id": 23,
        "method": "tools/call",
        "params": {"name": "get_file", "arguments": {"file_path": "README.md"}}
    })
    content = res_file["result"]["content"][0]["text"]
    assert "Acme Core Gateway" in content

def test_github_create_issue():
    res_create = github_server.handle_request({
        "jsonrpc": "2.0",
        "id": 24,
        "method": "tools/call",
        "params": {
            "name": "create_issue",
            "arguments": {"title": "Test Issue", "body": "Testing write tool."}
        }
    })
    res_data = json.loads(res_create["result"]["content"][0]["text"])
    assert res_data["status"] == "success"
    assert res_data["issue_number"] > 5
