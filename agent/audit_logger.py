"""
Audit Logger for MCP Agent.
Records every tool call, parameters, result sizes, execution times,
and defense interceptions to append-only JSONL files.
"""

import os
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional

AUDIT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audit_logs")
os.makedirs(AUDIT_DIR, exist_ok=True)
DEFAULT_AUDIT_FILE = os.path.join(AUDIT_DIR, "agent_audit.jsonl")

class AuditLogger:
    def __init__(self, log_path: str = DEFAULT_AUDIT_FILE):
        self.log_path = log_path
        self.session_id = f"sess_{int(time.time() * 1000)}"

    def log_tool_call(
        self,
        step: int,
        model: str,
        tool_name: str,
        arguments: Dict[str, Any],
        result_text: str,
        is_error: bool,
        latency_ms: float,
        defense_triggered: Optional[str] = None
    ):
        """Appends a structured tool invocation record to the audit log."""
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": self.session_id,
            "step": step,
            "model": model,
            "tool_name": tool_name,
            "arguments": arguments,
            "result_size_chars": len(result_text),
            "is_error": is_error,
            "latency_ms": round(latency_ms, 2),
            "defense_triggered": defense_triggered
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def log_event(self, event_type: str, data: Dict[str, Any]):
        """Logs general lifecycle events (e.g., run_start, run_finish, security_alert)."""
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": self.session_id,
            "event_type": event_type,
            **data
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
