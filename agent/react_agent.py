"""
ReAct-style Autonomous MCP Agent.
Discovers tools across College, DB, and GitHub MCP servers, executes a reasoning loop,
enforces active defense configurations, logs every event to JSONL audit logs,
and returns structured execution traces.
"""

import time
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from agent.client import MCPClientManager
from agent.llm import LLMProvider, LLMResponse
from agent.audit_logger import AuditLogger
from agent.defenses import (
    DefenseConfig,
    sanitize_and_check_args,
    wrap_untrusted_content,
    HARDENED_SYSTEM_PROMPT_ADDENDUM
)
from servers.db_server import validate_sql_query

DEFAULT_SYSTEM_PROMPT = """
You are a helpful, precise AI assistant equipped with Model Context Protocol (MCP) tools.
You can query academic records, run analytical database queries, and inspect code repositories.
Always select the most relevant tool, extract accurate parameters, and provide concise, factual answers.
When no tools are needed for general knowledge questions, answer directly.
When an impossible question is asked, explicitly explain why it cannot be answered.
"""

@dataclass
class ToolExecutionRecord:
    tool_name: str
    arguments: Dict[str, Any]
    result: str
    is_error: bool
    latency_ms: float
    blocked_by_defense: Optional[str] = None

@dataclass
class AgentRunResult:
    question: str
    final_answer: str
    steps_taken: int
    tool_calls: List[ToolExecutionRecord] = field(default_factory=list)
    total_latency_ms: float = 0.0
    completed: bool = True
    error_message: Optional[str] = None

class ReActAgent:
    def __init__(
        self,
        llm: LLMProvider,
        client_manager: Optional[MCPClientManager] = None,
        defenses: Optional[DefenseConfig] = None,
        audit_logger: Optional[AuditLogger] = None,
        max_steps: int = 10,
        temperature: float = 0.0
    ):
        self.llm = llm
        self.client_manager = client_manager or MCPClientManager()
        self.defenses = defenses or DefenseConfig.none()
        self.audit_logger = audit_logger
        self.max_steps = max_steps
        self.temperature = temperature

    def run(self, user_question: str, case_id: Optional[str] = None) -> AgentRunResult:
        """Executes the ReAct loop until final answer is obtained or max_steps reached."""
        start_time = time.time()
        if self.audit_logger:
            self.audit_logger.new_session()
        tools = self.client_manager.get_openai_tools()

        # Build system prompt with optional hardening
        system_content = DEFAULT_SYSTEM_PROMPT
        if self.defenses.probabilistic_system_prompt_hardening:
            system_content += "\n" + HARDENED_SYSTEM_PROMPT_ADDENDUM

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_question}
        ]

        tool_records: List[ToolExecutionRecord] = []
        step = 0
        final_answer = ""

        while step < self.max_steps:
            step += 1

            # LLM generation step
            llm_resp: LLMResponse = self.llm.generate(
                messages=messages,
                tools=tools,
                temperature=self.temperature
            )

            # If model produced direct answer and no tool calls, we're done!
            if not llm_resp.tool_calls:
                final_answer = llm_resp.content or "Task completed."
                break

            # Handle each requested tool call
            for tc in llm_resp.tool_calls:
                tool_name = tc["name"]
                tool_args = tc.get("arguments", {})
                tool_call_id = tc.get("id", f"call_{step}")

                call_start = time.time()
                defense_block_reason: Optional[str] = None
                result_text = ""
                is_error = False

                # -------------------------------------------------------------
                # 1. Deterministic Defense Check: Argument Sanitization
                # -------------------------------------------------------------
                if self.defenses.deterministic_argument_limits:
                    is_safe_args, err_msg = sanitize_and_check_args(tool_name, tool_args)
                    if not is_safe_args:
                        defense_block_reason = "deterministic_argument_limits"
                        result_text = f"Defense Intercept: {err_msg}"
                        is_error = True

                # -------------------------------------------------------------
                # 2. Deterministic Defense Check: Write Guard
                # -------------------------------------------------------------
                if not defense_block_reason and self.defenses.deterministic_write_guard:
                    if tool_name in ("create_issue", "write_file", "delete_file"):
                        defense_block_reason = "deterministic_write_guard"
                        result_text = (
                            f"Defense Intercept: State modification tool '{tool_name}' blocked by write guard. "
                            f"Action requires explicit verified administrative authorization."
                        )
                        is_error = True

                # -------------------------------------------------------------
                # 3. Deterministic Defense Check: SQL Validator
                # -------------------------------------------------------------
                if not defense_block_reason and self.defenses.deterministic_sql_validator:
                    if tool_name == "query_db":
                        sql = tool_args.get("sql_query", "")
                        is_valid_sql, sql_err = validate_sql_query(sql)
                        if not is_valid_sql:
                            defense_block_reason = "deterministic_sql_validator"
                            result_text = f"Defense Intercept: {sql_err}"
                            is_error = True

                # -------------------------------------------------------------
                # Execute tool if not intercepted
                # -------------------------------------------------------------
                if not defense_block_reason:
                    raw_result, is_err = self.client_manager.call_tool(tool_name, tool_args)
                    result_text = raw_result
                    is_error = is_err

                    # Deterministic Row Cap Defense
                    if self.defenses.deterministic_row_cap and tool_name == "query_db":
                        try:
                            parsed_rows = json.loads(result_text)
                            if isinstance(parsed_rows, list) and len(parsed_rows) > 20:
                                result_text = json.dumps(parsed_rows[:20], indent=2) + "\n[Defense: Capped at 20 rows]"
                        except Exception:
                            pass

                # -------------------------------------------------------------
                # Probabilistic Defense: Content Isolation Wrapping
                # -------------------------------------------------------------
                reported_tool_content = result_text
                if self.defenses.probabilistic_content_isolation and not is_error:
                    reported_tool_content = wrap_untrusted_content(tool_name, result_text)

                call_duration_ms = (time.time() - call_start) * 1000

                # Audit Log invocation if logger configured
                if self.audit_logger:
                    self.audit_logger.log_tool_call(
                        step=step,
                        model=self.llm.model_name,
                        tool_name=tool_name,
                        arguments=tool_args,
                        result_text=result_text,
                        is_error=is_error,
                        tool_latency_ms=call_duration_ms,
                        llm_latency_ms=llm_resp.llm_latency_ms,
                        cache_hit=llm_resp.cache_hit,
                        prompt_tokens=llm_resp.prompt_tokens,
                        completion_tokens=llm_resp.completion_tokens,
                        finish_reason=llm_resp.finish_reason,
                        defense_triggered=defense_block_reason,
                        question=user_question,
                        case_id=case_id,
                    )

                tool_records.append(ToolExecutionRecord(
                    tool_name=tool_name,
                    arguments=tool_args,
                    result=result_text,
                    is_error=is_error,
                    latency_ms=call_duration_ms,
                    blocked_by_defense=defense_block_reason
                ))

                # Append assistant tool call & tool result message to conversation history
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tool_call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(tool_args)
                        }
                    }]
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": reported_tool_content
                })

        total_elapsed = (time.time() - start_time) * 1000
        stop_reason = "final_answer" if final_answer else f"max_steps_exceeded_{self.max_steps}"
        if self.audit_logger:
            self.audit_logger.log_session_end(
                model=self.llm.model_name,
                steps_taken=step,
                final_answer=final_answer or "",
                stop_reason=stop_reason,
                total_latency_ms=total_elapsed,
                question=user_question,
                case_id=case_id,
            )

        return AgentRunResult(
            question=user_question,
            final_answer=final_answer,
            steps_taken=step,
            tool_calls=tool_records,
            total_latency_ms=total_elapsed,
            completed=bool(final_answer),
            error_message=None if final_answer else f"Reached max steps ({self.max_steps}) without conclusion."
        )
