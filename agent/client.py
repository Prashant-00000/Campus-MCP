"""
MCP Multi-Server Client Manager.
Connects to College, DB, and GitHub servers, discovers all tools,
converts schemas to OpenAI function calling format, and routes calls.
"""

from typing import Dict, Any, List, Optional
import json
import queue
import threading

from servers.college_server import server as college_server
from servers.db_server import server as db_server
from servers.github_server import server as github_server
from servers.mcp_base import MCPServer

class MCPClientManager:
    def __init__(self, tool_timeout_s: float = 10.0):
        self.servers: Dict[str, MCPServer] = {
            "college": college_server,
            "db": db_server,
            "github": github_server
        }
        self.tool_to_server: Dict[str, MCPServer] = {}
        self.tools_schema: List[Dict[str, Any]] = []
        self.tool_timeout_s = tool_timeout_s
        self._discover_tools()

    def _discover_tools(self):
        """Discovers tools across all registered MCP servers and builds OpenAI schema definitions."""
        self.tools_schema = []
        self.tool_to_server = {}

        for server_name, server in self.servers.items():
            req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
            resp = server.handle_request(req)
            if not resp or "result" not in resp:
                continue

            for tool in resp["result"]["tools"]:
                name = tool["name"]
                self.tool_to_server[name] = server
                self.tools_schema.append({
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": tool["description"],
                        "parameters": tool["inputSchema"]
                    }
                })

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """Returns the list of tools formatted for OpenAI / OpenAI-compatible tool calling."""
        return self.tools_schema

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> tuple[str, bool]:
        """
        Executes a tool on the appropriate server.
        Returns (result_text, is_error).
        """
        server = self.tool_to_server.get(name)
        if not server:
            return f"Error: Tool '{name}' not found on any connected MCP server.", True

        req = {
            "jsonrpc": "2.0",
            "id": "call",
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments
            }
        }
        response_queue = queue.Queue(maxsize=1)

        def invoke_server():
            try:
                response_queue.put(server.handle_request(req))
            except Exception as exc:
                response_queue.put(exc)

        worker = threading.Thread(target=invoke_server, daemon=True)
        worker.start()
        try:
            resp = response_queue.get(timeout=self.tool_timeout_s)
        except queue.Empty:
            return f"Error: Tool '{name}' timed out after {self.tool_timeout_s:.1f}s.", True

        if isinstance(resp, Exception):
            return f"Error: Tool '{name}' failed: {resp}", True
        if not resp:
            return "Error: Empty response from server.", True

        if "error" in resp:
            return f"Error ({resp['error'].get('code')}): {resp['error'].get('message')}", True

        result = resp.get("result", {})
        is_error = result.get("isError", False)
        contents = result.get("content", [])
        text = "\n".join([c.get("text", "") for c in contents if c.get("type") == "text"])
        return text, is_error
