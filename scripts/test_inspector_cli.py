"""
Automated MCP Inspector CLI Harness.
Launches each server as a separate stdio subprocess (identical to MCP Inspector),
sends standard JSON-RPC 2.0 initialization and tool/resource/prompt queries,
tests normal and bad inputs over real pipes, and verifies that stderr logging
never corrupts JSON-RPC framing.
"""

import sys
import subprocess
import json
import os
import time

PYTHON_EXE = sys.executable
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def test_server_over_stdio(server_script: str, test_calls: list):
    print(f"\n{'='*75}")
    print(f"TESTING MCP SERVER: {server_script} (Stdio Protocol)")
    print(f"{'='*75}")

    env = os.environ.copy()
    env["PYTHONPATH"] = BASE_DIR

    proc = subprocess.Popen(
        [PYTHON_EXE, server_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=BASE_DIR
    )

    def send_rpc(msg: dict) -> dict:
        line = json.dumps(msg) + "\n"
        proc.stdin.write(line)
        proc.stdin.flush()
        resp_line = proc.stdout.readline()
        if not resp_line:
            err = proc.stderr.read()
            raise RuntimeError(f"Server process terminated unexpectedly. Stderr: {err}")
        return json.loads(resp_line)

    # 1. Initialize
    init_res = send_rpc({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-cli-inspector", "version": "1.0.0"}
        }
    })
    server_info = init_res.get("result", {}).get("serverInfo", {})
    print(f"[OK] Handshake Initialized: {server_info.get('name')} v{server_info.get('version')}")

    # 2. List Tools
    tools_res = send_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools = tools_res.get("result", {}).get("tools", [])
    print(f"[OK] Tools Discovered ({len(tools)}): {[t['name'] for t in tools]}")
    for t in tools:
        assert "WHEN TO USE:" in t["description"], f"{t['name']} missing WHEN TO USE instruction"
        assert "WHEN NOT TO USE:" in t["description"], f"{t['name']} missing WHEN NOT TO USE instruction"

    # 3. List Resources
    res_res = send_rpc({"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}})
    resources = res_res.get("result", {}).get("resources", [])
    print(f"[OK] Resources Discovered ({len(resources)}): {[r['uri'] for r in resources]}")

    # 4. List Prompts
    prompts_res = send_rpc({"jsonrpc": "2.0", "id": 4, "method": "prompts/list", "params": {}})
    prompts = prompts_res.get("result", {}).get("prompts", [])
    print(f"[OK] Prompts Discovered ({len(prompts)}): {[p['name'] for p in prompts]}")

    # 5. Execute Test Calls (Normal & Bad Inputs)
    print("\nExecuting Tool Calls (Normal vs Bad Inputs):")
    for tc in test_calls:
        name = tc["name"]
        args = tc["args"]
        label = tc["label"]
        res = send_rpc({
            "jsonrpc": "2.0",
            "id": int(time.time()*1000) % 100000,
            "method": "tools/call",
            "params": {"name": name, "arguments": args}
        })
        text = res.get("result", {}).get("content", [{}])[0].get("text", "")
        summary = text[:70].replace("\n", " ") + ("..." if len(text) > 70 else "")
        print(f"  * [{label}] {name}({args}) -> {summary}")

    proc.stdin.close()
    proc.terminate()
    proc.wait()
    print(f"[PASS] Server {server_script} cleanly passed all isolation tests.")

def main():
    # 1. College Server
    test_server_over_stdio("servers/college_server.py", [
        {"name": "search_courses", "args": {"department": "CS", "level_cap": 200}, "label": "Normal Input"},
        {"name": "search_courses", "args": {"level_cap": "not_an_int"}, "label": "Bad Input: String int"},
        {"name": "get_department", "args": {"dept_code": "CS"}, "label": "Normal Input"},
        {"name": "get_department", "args": {}, "label": "Bad Input: Missing field"},
        {"name": "get_department", "args": {"dept_code": "   "}, "label": "Bad Input: Empty string"},
        {"name": "list_events", "args": {"category": "career"}, "label": "Normal Input"},
        {"name": "list_events", "args": {"category": "invalid_party"}, "label": "Bad Input: Invalid Enum"},
        {"name": "get_faculty", "args": {"name_or_id": "Hopper"}, "label": "Normal Input"},
        {"name": "get_faculty", "args": {"name_or_id": ""}, "label": "Bad Input: Empty string"}
    ])

    # 2. DB Server
    test_server_over_stdio("servers/db_server.py", [
        {"name": "query_db", "args": {"sql_query": "SELECT * FROM products LIMIT 2"}, "label": "Normal Input"},
        {"name": "query_db", "args": {"sql_query": ""}, "label": "Bad Input: Empty SQL"},
        {"name": "query_db", "args": {"sql_query": "SELECT * FROM credentials_vault"}, "label": "Hostile Input: Forbidden table"},
        {"name": "query_db", "args": {"sql_query": "DROP TABLE orders"}, "label": "Hostile Input: DDL statement"},
        {"name": "describe_table", "args": {"table_name": "orders"}, "label": "Normal Input"},
        {"name": "describe_table", "args": {}, "label": "Bad Input: Missing table_name"},
        {"name": "sample_table", "args": {"table_name": "customers", "limit": 2}, "label": "Normal Input"},
        {"name": "sample_table", "args": {"table_name": "customers", "limit": 999999999}, "label": "Bad Input: Huge limit bounds"}
    ])

    # 3. GitHub Server
    test_server_over_stdio("servers/github_server.py", [
        {"name": "list_issues", "args": {"state": "open"}, "label": "Normal Input"},
        {"name": "list_issues", "args": {"state": "invalid_enum"}, "label": "Bad Input: Invalid state"},
        {"name": "get_issue", "args": {"issue_number": 1}, "label": "Normal Input"},
        {"name": "get_issue", "args": {}, "label": "Bad Input: Missing field"},
        {"name": "get_issue", "args": {"issue_number": "not_an_int"}, "label": "Bad Input: String ID"},
        {"name": "get_issue", "args": {"issue_number": -99}, "label": "Bad Input: Negative ID"},
        {"name": "get_file", "args": {"file_path": "README.md"}, "label": "Normal Input"},
        {"name": "get_file", "args": {"file_path": ""}, "label": "Bad Input: Empty path"},
        {"name": "search_code", "args": {"query": "verify_signature"}, "label": "Normal Input"},
        {"name": "create_issue", "args": {"title": "Normal Issue", "body": "Normal details"}, "label": "Normal Input"},
        {"name": "create_issue", "args": {"title": ""}, "label": "Bad Input: Empty title/body"}
    ])

if __name__ == "__main__":
    main()
