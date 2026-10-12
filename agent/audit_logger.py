"""
Audit Logger for MCP Agent.
Records every tool call, parameters, result sizes, execution times,
and defense interceptions to append-only JSONL files.
"""

import os
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional, List

AUDIT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audit_logs")


def check_contamination_guard(file_path: str, configured_model: str) -> None:
    """
    Guards against accidental cross-model data contamination.
    Inspects an existing file (CSV, JSONL, or JSON). If it contains records
    with a 'model' attribute that does not match configured_model, raises RuntimeError.
    """
    if not os.path.exists(file_path):
        return
    if os.path.getsize(file_path) == 0:
        return

    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".csv":
        import csv
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row_idx, row in enumerate(reader):
                model_val = None
                for k, v in row.items():
                    if k and k.lower() == "model":
                        model_val = v
                        break
                if model_val and model_val.strip() and model_val.strip() != configured_model.strip():
                    raise RuntimeError(
                        f"Contamination Guard Violation: File '{file_path}' (row {row_idx + 1}) "
                        f"contains model '{model_val}', which does not match configured model '{configured_model}'. "
                        f"Refusing to start."
                    )

    elif ext in (".jsonl", ".log"):
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line_idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        model_val = data.get("model")
                        if model_val and str(model_val).strip() != configured_model.strip():
                            raise RuntimeError(
                                f"Contamination Guard Violation: Audit log '{file_path}' (line {line_idx + 1}) "
                                f"contains model '{model_val}', which does not match configured model '{configured_model}'. "
                                f"Refusing to start."
                            )
                except json.JSONDecodeError:
                    continue

    elif ext == ".json":
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
            if isinstance(data, dict):
                model_val = data.get("model")
                if model_val and str(model_val).strip() != configured_model.strip():
                    raise RuntimeError(
                        f"Contamination Guard Violation: JSON file '{file_path}' "
                        f"specifies model '{model_val}', which does not match configured model '{configured_model}'. "
                        f"Refusing to start."
                    )
        except (json.JSONDecodeError, OSError):
            pass


class AuditLogger:
    def __init__(self, log_path: str, model: Optional[str] = None):
        """
        Initializes AuditLogger with an explicit log path.
        No default path is permitted to prevent unisolated test pollution.
        """
        if not log_path or not str(log_path).strip():
            raise ValueError("AuditLogger requires an explicit, non-empty log_path with no default.")

        self.log_path = str(log_path)
        if model:
            check_contamination_guard(self.log_path, model)

        parent_dir = os.path.dirname(os.path.abspath(self.log_path))
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        self.session_id = f"sess_{int(time.time() * 1000)}"

    def new_session(self) -> str:
        """Starts a fresh session ID for a new question/run."""
        self.session_id = f"sess_{int(time.time() * 1000)}"
        return self.session_id

    def log_tool_call(
        self,
        step: int,
        model: str,
        tool_name: str,
        arguments: Dict[str, Any],
        result_text: str,
        is_error: bool,
        tool_latency_ms: float = 0.0,
        llm_latency_ms: float = 0.0,
        cache_hit: bool = False,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        finish_reason: Optional[str] = None,
        defense_triggered: Optional[str] = None,
        question: Optional[str] = None,
        case_id: Optional[str] = None,
        latency_ms: Optional[float] = None,
    ):
        """Appends a structured tool invocation record to the audit log."""
        if latency_ms is not None and tool_latency_ms == 0.0:
            tool_latency_ms = latency_ms

        preview = result_text[:200] if len(result_text) > 200 else result_text
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": self.session_id,
            "step": step,
            "model": model,
            "case_id": case_id,
            "question": question,
            "tool_name": tool_name,
            "arguments": arguments,
            "result_size_chars": len(result_text),
            "result_preview": preview,
            "is_error": is_error,
            "tool_latency_ms": round(tool_latency_ms, 2),
            "llm_latency_ms": round(llm_latency_ms, 2),
            "cache_hit": cache_hit,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "finish_reason": finish_reason,
            "defense_triggered": defense_triggered,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def log_llm_call(
        self,
        step: int,
        model: str,
        call_type: str,
        llm_latency_ms: float,
        cache_hit: bool,
        prompt_tokens: Optional[int],
        completion_tokens: Optional[int],
        finish_reason: Optional[str],
        retry_count: int = 0,
        retry_wait_ms: float = 0.0,
        tools_requested: Optional[List[str]] = None,
        question: Optional[str] = None,
        case_id: Optional[str] = None,
    ):
        """Appends a record for every LLM invocation (both tool selections and final answers)."""
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": self.session_id,
            "event_type": "llm_call",
            "step": step,
            "model": model,
            "case_id": case_id,
            "question": question,
            "call_type": call_type,
            "llm_latency_ms": round(llm_latency_ms, 2),
            "cache_hit": cache_hit,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "finish_reason": finish_reason,
            "retry_count": retry_count,
            "retry_wait_ms": round(retry_wait_ms, 2),
            "tools_requested": tools_requested or [],
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def log_session_end(
        self,
        model: str,
        steps_taken: int,
        final_answer: str,
        stop_reason: str,
        total_latency_ms: float,
        question: Optional[str] = None,
        case_id: Optional[str] = None,
        n_tool_calls: int = 0,
        n_llm_calls: int = 0,
        llm_latency_ms: float = 0.0,
        tool_latency_ms: float = 0.0,
        retry_wait_ms: float = 0.0,
    ):
        """Appends a session-end record documenting final outcome and stop reason."""
        record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "session_id": self.session_id,
            "event_type": "session_end",
            "model": model,
            "case_id": case_id,
            "question": question,
            "steps_taken": steps_taken,
            "n_llm_calls": n_llm_calls,
            "n_tool_calls": n_tool_calls,
            "final_answer": final_answer,
            "stop_reason": stop_reason,
            "llm_latency_ms": round(llm_latency_ms, 2),
            "tool_latency_ms": round(tool_latency_ms, 2),
            "retry_wait_ms": round(retry_wait_ms, 2),
            "total_latency_ms": round(total_latency_ms, 2),
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
