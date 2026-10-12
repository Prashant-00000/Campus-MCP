import io
import json
import time

from agent.client import MCPClientManager
from servers.github_server import create_issue_handler, set_writes_enabled
from servers.mcp_base import MCPServer


def test_write_policy_denies_by_default_and_allows_explicit_enable():
    set_writes_enabled(False)
    assert "disabled by server policy" in create_issue_handler({"title": "x", "body": "y"})
    set_writes_enabled(True)
    try:
        result = json.loads(create_issue_handler({"title": "x", "body": "y"}))
        assert result["status"] == "success"
    finally:
        set_writes_enabled(False)


def test_stdio_returns_internal_error_for_request_and_silences_notification(monkeypatch):
    server = MCPServer("test-server")

    def fail(_request):
        raise RuntimeError("boom")

    server.handle_request = fail
    stdin = io.StringIO(
        json.dumps({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "explode", "arguments": {}},
        })
        + "\n"
        + json.dumps({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "explode", "arguments": {}},
        })
        + "\n"
    )
    stdout = io.StringIO()
    monkeypatch.setattr("sys.stdin", stdin)
    monkeypatch.setattr("sys.stdout", stdout)

    server.run_stdio()
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert responses == [{
        "jsonrpc": "2.0",
        "id": 7,
        "error": {"code": -32603, "message": "Internal server error"},
    }]


def test_client_returns_timeout_for_stalled_tool():
    server = MCPServer("slow-server")

    def slow(_args):
        time.sleep(0.2)
        return "done"

    server.register_tool("slow", "slow", {"type": "object"}, slow)
    manager = MCPClientManager(tool_timeout_s=0.01)
    manager.servers = {"slow": server}
    manager.tool_to_server = {"slow": server}
    result, is_error = manager.call_tool("slow", {})
    assert is_error is True
    assert "timed out" in result
