"""
Model Context Protocol (MCP) Base Server Implementation.
Implements JSON-RPC 2.0 over stdio following the standard MCP specification.
Logs exclusively to stderr to avoid corrupting stdio communication.
"""

import sys
import json
import logging
from typing import Dict, Any, List, Callable, Optional

# Configure logging strictly to stderr
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger("mcp_server")

MAX_TOOL_OUTPUT_CHARS = 4000  # Cap output size to prevent context blowing / DOS

class MCPServer:
    def __init__(self, name: str, version: str = "1.0.0", max_output_chars: int = MAX_TOOL_OUTPUT_CHARS):
        self.name = name
        self.version = version
        self.max_output_chars = max_output_chars
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.resources: Dict[str, Dict[str, Any]] = {}
        self.prompts: Dict[str, Dict[str, Any]] = {}

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable[[Dict[str, Any]], Any]
    ):
        """Registers an MCP tool with schema and description."""
        self.tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
            "handler": handler
        }

    def register_resource(
        self,
        uri: str,
        name: str,
        description: str,
        mime_type: str,
        reader: Callable[[], str]
    ):
        """Registers an MCP resource."""
        self.resources[uri] = {
            "uri": uri,
            "name": name,
            "description": description,
            "mimeType": mime_type,
            "reader": reader
        }

    def register_prompt(
        self,
        name: str,
        description: str,
        arguments: List[Dict[str, Any]],
        generator: Callable[[Dict[str, Any]], List[Dict[str, Any]]]
    ):
        """Registers an MCP prompt template."""
        self.prompts[name] = {
            "name": name,
            "description": description,
            "arguments": arguments,
            "generator": generator
        }

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Processes a single JSON-RPC 2.0 request and returns the response."""
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                        "prompts": {"listChanged": False}
                    },
                    "serverInfo": {
                        "name": self.name,
                        "version": self.version
                    }
                }
            }

        elif method == "notifications/initialized":
            logger.info(f"Server {self.name} initialized successfully.")
            return None

        elif method == "tools/list":
            tool_list = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "inputSchema": t["inputSchema"]
                }
                for t in self.tools.values()
            ]
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": tool_list}
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            if tool_name not in self.tools:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"Tool '{tool_name}' not found on server '{self.name}'."
                    }
                }

            try:
                handler = self.tools[tool_name]["handler"]
                raw_result = handler(tool_args)
                if not isinstance(raw_result, str):
                    raw_result = json.dumps(raw_result, indent=2)

                # Cap output size
                if len(raw_result) > self.max_output_chars:
                    raw_result = (
                        raw_result[:self.max_output_chars]
                        + f"\n... [Output truncated to {self.max_output_chars} characters]"
                    )

                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": raw_result}
                        ],
                        "isError": False
                    }
                }
            except Exception as e:
                logger.exception(f"Error executing tool {tool_name}: {e}")
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "text", "text": f"Tool Execution Error: {str(e)}"}
                        ],
                        "isError": True
                    }
                }

        elif method == "resources/list":
            res_list = [
                {
                    "uri": r["uri"],
                    "name": r["name"],
                    "description": r["description"],
                    "mimeType": r["mimeType"]
                }
                for r in self.resources.values()
            ]
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"resources": res_list}
            }

        elif method == "resources/read":
            uri = params.get("uri")
            if uri not in self.resources:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": f"Resource URI '{uri}' not found on server '{self.name}'."
                    }
                }
            try:
                reader = self.resources[uri]["reader"]
                content = reader()
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "contents": [
                            {
                                "uri": uri,
                                "mimeType": self.resources[uri]["mimeType"],
                                "text": content
                            }
                        ]
                    }
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32603,
                        "message": f"Failed reading resource {uri}: {str(e)}"
                    }
                }

        elif method == "prompts/list":
            p_list = [
                {
                    "name": p["name"],
                    "description": p["description"],
                    "arguments": p["arguments"]
                }
                for p in self.prompts.values()
            ]
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"prompts": p_list}
            }

        elif method == "prompts/get":
            prompt_name = params.get("name")
            args = params.get("arguments", {})
            if prompt_name not in self.prompts:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32602,
                        "message": f"Prompt '{prompt_name}' not found on server '{self.name}'."
                    }
                }
            try:
                generator = self.prompts[prompt_name]["generator"]
                messages = generator(args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "description": self.prompts[prompt_name]["description"],
                        "messages": messages
                    }
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32603,
                        "message": f"Failed evaluating prompt {prompt_name}: {str(e)}"
                    }
                }

        elif method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {}
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32601,
                    "message": f"Method '{method}' not implemented."
                }
            }

    def run_stdio(self):
        """Standard stdio loop reading line-delimited JSON-RPC messages."""
        logger.info(f"Starting MCP stdio server: {self.name} v{self.version}")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                response = self.handle_request(req)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
            except json.JSONDecodeError as e:
                logger.error(f"Malformed JSON: {e}")
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"}
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
            except Exception as e:
                logger.exception(f"Unhandled server error: {e}")
                if isinstance(req, dict) and "id" in req:
                    err_resp = {
                        "jsonrpc": "2.0",
                        "id": req.get("id"),
                        "error": {"code": -32603, "message": "Internal server error"}
                    }
                    sys.stdout.write(json.dumps(err_resp) + "\n")
                    sys.stdout.flush()
