"""
Evaluation Runner for MCP Agent Benchmark.
Runs 3 trials per case on specified dataset split ('dev', 'test', or 'all').
Measures tool selection accuracy, argument accuracy, task success, latency, steps.
Computes Wilson 95% Confidence Intervals and exports detailed CSV results.

Requires a real LLMProvider — NOT the simulator. Pass provider_from_env() or
construct LLMProvider() directly. No fallback to simulation.
"""

import os
import json
import csv
import time
import re
from collections import Counter
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
try:
    from tabulate import tabulate
except ImportError:
    def tabulate(data, headers="firstrow", tablefmt="github"):
        rows = list(data)
        if not rows:
            return ""
        return "\n".join([" | ".join(str(c) for c in r) for r in rows])

from agent.llm import LLMProvider
from agent.react_agent import ReActAgent
from agent.defenses import DefenseConfig
from agent.audit_logger import AuditLogger, check_contamination_guard, AUDIT_DIR
from data.init_databases import init_college_db, init_company_db, init_github_db
from eval.stats import wilson_score_interval, format_ci
from eval.hard_cases import generate_hard_cases

DATASET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset.jsonl")
GRADER_VERSION = "v4"
RESULTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

class EvalHarness:
    """
    Run the evaluation harness against a real LLM.

    Parameters
    ----------
    llm : LLMProvider
        A fully configured real provider.  Construct via provider_from_env() or
        LLMProvider(model_name=..., provider=...) directly.
        The simulator (tests/fakes.py) must NOT be passed here.
    trials : int
        How many independent runs per eval case (default 3).
    defenses : DefenseConfig | None
        Active defenses.  Defaults to no defenses (baseline).
    """

    def __init__(
        self,
        llm: LLMProvider,
        trials: int = 3,
        defenses: Optional[DefenseConfig] = None,
    ):
        self.llm = llm
        # Evaluation experiments must NEVER use caching (prevents trial contamination)
        if hasattr(self.llm, "enable_cache"):
            self.llm.enable_cache = False
        self.model_name = llm.model_name
        self.provider = llm.provider
        self.trials = trials
        self.defenses = defenses or DefenseConfig.none()

    def load_dataset(self, split: Optional[str] = None) -> List[Dict[str, Any]]:
        cases = []
        with open(DATASET_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                if split is None or item.get("split") == split or split == "all":
                    cases.append(item)
        for item in generate_hard_cases():
            if split is None or item.get("split") == split or split == "all":
                cases.append(item)
        return cases

    def grade_case(self, case: Dict[str, Any], agent_result) -> Dict[str, Any]:
        """Grade a run with strict tool precision/recall and explicit-arg scoring."""
        from eval.scoring import normalize_text, check_facts_present

        called_tools = [tc.tool_name for tc in agent_result.tool_calls]
        expected_tools = case.get("expected_tools", [])
        expected_args = case.get("expected_args", {})
        required_facts = case.get("required_facts", [])
        raw_ans = agent_result.final_answer or ""
        norm_answer = normalize_text(raw_ans)

        expected_counts = Counter(expected_tools)
        called_counts = Counter(called_tools)
        matched_calls = sum(min(called_counts.get(tool, 0), count) for tool, count in expected_counts.items())
        extra_calls = max(0, len(called_tools) - matched_calls)

        def call_signature(tool_call):
            def normalize_value(value):
                if isinstance(value, dict):
                    return {key: normalize_value(value[key]) for key in sorted(value)}
                if isinstance(value, list):
                    return [normalize_value(item) for item in value]
                return normalize_text(str(value)) if isinstance(value, str) else value
            return tool_call.tool_name, json.dumps(normalize_value(tool_call.arguments), sort_keys=True)

        call_signatures = Counter(call_signature(tc) for tc in agent_result.tool_calls)
        redundant_calls = sum(max(0, count - 1) for count in call_signatures.values())

        # Precision and recall are reported separately so extra calls are visible.
        tool_precision = matched_calls / len(called_tools) if called_tools else (1.0 if not expected_tools else 0.0)
        tool_recall = matched_calls / len(expected_tools) if expected_tools else (1.0 if not called_tools else 0.0)
        tool_selection_ok = tool_precision == 1.0 and tool_recall == 1.0

        # 2. Argument Accuracy: only cases with declared arguments contribute.
        specified_arg_checks = 0
        correct_arg_checks = 0
        missing_args = 0
        arg_ok = True
        if expected_args:
            expected_tool = expected_tools[0] if len(set(expected_tools)) == 1 else None
            matching_records = [tc for tc in agent_result.tool_calls if expected_tool is None or tc.tool_name == expected_tool]
            for key, expected_value in expected_args.items():
                specified_arg_checks += 1
                actual_values = [tc.arguments.get(key) for tc in matching_records if key in tc.arguments]
                expected_norm = normalize_text(str(expected_value))
                if not actual_values:
                    missing_args += 1
                    arg_ok = False
                elif all(
                    expected_norm == normalize_text(str(actual))
                    or bool(re.search(rf"\b{re.escape(expected_norm)}\b", normalize_text(str(actual))))
                    for actual in actual_values
                ):
                    correct_arg_checks += 1
                else:
                    arg_ok = False
        arg_accuracy = (correct_arg_checks / specified_arg_checks) if specified_arg_checks else None
        if expected_tools and not tool_selection_ok:
            arg_ok = False

        # 3. Separate answer correctness from tool-use quality.
        answer_correct = False
        failure_type = "none"
        is_impossible = case.get("impossible", False)
        forbidden_tools = set(case.get("forbidden_tools", []))

        if forbidden_tools.intersection(called_tools):
            failure_type = "forbidden_tool"
        elif is_impossible:
            # Must refuse precisely and stop after the configured search budget.
            max_tool_calls = case.get("max_tool_calls", 10)
            if (
                len(called_tools) <= max_tool_calls
                and (
                    check_facts_present(raw_ans, required_facts)
                    or any(indicator in norm_answer for indicator in case.get("refusal_indicators", []))
                )
            ):
                answer_correct = True
            else:
                failure_type = "excessive_search" if len(called_tools) > max_tool_calls else "right_tools_wrong_answer"
        elif not expected_tools:
            # Direct answer check using unicode-aware normalization
            if check_facts_present(raw_ans, required_facts):
                answer_correct = True
            else:
                failure_type = "right_tools_wrong_answer" if len(called_tools) == 0 else "wrong_tool"
        else:
            # Must have called tool and include required facts
            facts_present = check_facts_present(raw_ans, required_facts)
            answer_correct = facts_present
            if not answer_correct:
                failure_type = "right_tools_wrong_answer"

        if not agent_result.completed:
            failure_type = "loop" if agent_result.steps_taken >= 10 else "gave_up"
            answer_correct = False

        tool_use_quality = tool_selection_ok and arg_ok and agent_result.completed
        task_success = answer_correct

        return {
            "tool_selection_ok": tool_selection_ok,
            "tool_precision": tool_precision,
            "tool_recall": tool_recall,
            "extra_calls": extra_calls,
            "redundant_calls": redundant_calls,
            "missing_args": missing_args,
            "argument_ok": arg_ok,
            "argument_accuracy": arg_accuracy,
            "argument_checks": specified_arg_checks,
            "answer_correct": answer_correct,
            "tool_use_quality": tool_use_quality,
            "task_success": task_success,
            "failure_type": failure_type,
            "steps": agent_result.steps_taken,
            "latency_ms": agent_result.total_latency_ms
        }

    def run_eval(
        self,
        split: str = "test",
        output_csv_name: Optional[str] = None,
        run_id: Optional[str] = None,
        case_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        # Reset all databases to seed state before every run
        init_college_db()
        init_company_db()
        init_github_db()

        cases = self.load_dataset(split=split)
        if case_ids:
            cases = [c for c in cases if c.get("id") in case_ids]

        # 1. Determine run ID and output paths
        run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        clean_model_id = self.model_name.replace("/", "_").replace(":", "_")
        csv_filename = output_csv_name or f"baseline_{clean_model_id}_{split}.csv"
        csv_path = os.path.join(RESULTS_DIR, csv_filename)
        audit_log_path = os.path.join(AUDIT_DIR, f"{run_id}_{clean_model_id}.jsonl")

        # 2. Guard against cross-model data contamination
        check_contamination_guard(csv_path, self.model_name)
        check_contamination_guard(audit_log_path, self.model_name)

        # 3. Initialize per-run AuditLogger and ReActAgent
        audit_logger = AuditLogger(log_path=audit_log_path, model=self.model_name)
        agent = ReActAgent(llm=self.llm, defenses=self.defenses, audit_logger=audit_logger)

        # Read git commit for provenance
        git_commit = "unknown"
        try:
            import subprocess
            out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL)
            git_commit = out.decode("utf-8").strip()
        except Exception:
            pass

        fieldnames = [
            "case_id", "split", "category", "template", "trial", "model", "provider",
            "grader_version",
            "temperature", "git_commit", "run_timestamp",
            "tool_selection_ok", "tool_precision", "tool_recall", "extra_calls", "redundant_calls",
            "missing_args", "argument_ok", "argument_accuracy", "argument_checks",
            "answer_correct", "tool_use_quality", "task_success", "failure_type",
            "n_tool_calls", "n_llm_calls", "llm_latency_ms", "tool_latency_ms",
            "retry_wait_ms", "total_latency_ms"
        ]

        completed_keys = set()
        records = []
        if os.path.exists(csv_path) and os.path.getsize(csv_path) > 0:
            with open(csv_path, "r", encoding="utf-8", errors="replace") as rf:
                reader = csv.DictReader(rf)
                for row in reader:
                    records.append(row)
                    completed_keys.add((row.get("case_id"), str(row.get("trial")), row.get("model")))

        if not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
            with open(csv_path, "w", newline="", encoding="utf-8") as wf:
                writer = csv.DictWriter(wf, fieldnames=fieldnames)
                writer.writeheader()

        total_planned = len(cases) * self.trials
        print(f"\n=======================================================")
        print(f"Running Evaluation: {self.model_name} (Split: {split}, Trials: {self.trials})")
        print(f"Run ID: {run_id} | Audit Log: {audit_log_path}")
        print(f"Cases: {len(cases)} | Total Executions: {total_planned} (Already completed: {len(completed_keys)})")
        print(f"=======================================================")

        csv_file = open(csv_path, "a", newline="", encoding="utf-8")
        csv_writer = csv.DictWriter(csv_file, fieldnames=fieldnames)

        try:
            for case in cases:
                case_id = case["id"]
                question = case["question"]
                category = case["category"]

                for trial_idx in range(1, self.trials + 1):
                    key = (case_id, str(trial_idx), self.model_name)
                    if key in completed_keys:
                        continue

                    res = agent.run(question, case_id=case_id)
                    graded = self.grade_case(case, res)

                    record = {
                        "case_id": case_id,
                        "split": split,
                        "category": category,
                        "template": case.get("template", case.get("category", "legacy")),
                        "trial": trial_idx,
                        "model": self.model_name,
                        "provider": self.provider,
                        "grader_version": GRADER_VERSION,
                        "temperature": getattr(agent, "temperature", 0.0),
                        "git_commit": git_commit,
                        "run_timestamp": datetime.now(timezone.utc).isoformat(),
                        "tool_selection_ok": graded["tool_selection_ok"],
                        "tool_precision": graded["tool_precision"],
                        "tool_recall": graded["tool_recall"],
                        "extra_calls": graded["extra_calls"],
                        "redundant_calls": graded["redundant_calls"],
                        "missing_args": graded["missing_args"],
                        "argument_ok": graded["argument_ok"],
                        "argument_accuracy": graded["argument_accuracy"],
                        "argument_checks": graded["argument_checks"],
                        "answer_correct": graded["answer_correct"],
                        "tool_use_quality": graded["tool_use_quality"],
                        "task_success": graded["task_success"],
                        "failure_type": graded["failure_type"],
                        "n_tool_calls": res.n_tool_calls,
                        "n_llm_calls": res.n_llm_calls,
                        "llm_latency_ms": round(res.llm_latency_ms, 2),
                        "tool_latency_ms": round(res.tool_latency_ms, 2),
                        "retry_wait_ms": round(res.retry_wait_ms, 2),
                        "total_latency_ms": round(res.total_latency_ms, 2),
                    }
                    csv_writer.writerow(record)
                    csv_file.flush()
                    records.append(record)
                    completed_keys.add(key)
                    time.sleep(1.0)
        finally:
            csv_file.close()

        total_evals = len(records)
        if total_evals == 0:
            return {"error": "No evaluations completed"}

        tool_successes = sum(1 for r in records if str(r.get("tool_selection_ok")).lower() == "true")
        arg_records = [r for r in records if int(r.get("argument_checks", 0) or 0) > 0]
        arg_successes = sum(1 for r in arg_records if str(r.get("argument_ok")).lower() == "true")
        task_successes = sum(1 for r in records if str(r.get("task_success")).lower() == "true")
        total_tool_calls = sum(int(r.get("n_tool_calls", 0)) for r in records)
        total_llm_calls = sum(int(r.get("n_llm_calls", 0)) for r in records)
        total_llm_latency = sum(float(r.get("llm_latency_ms", 0.0)) for r in records)

        tool_ci = format_ci(tool_successes, total_evals)
        arg_ci = format_ci(arg_successes, len(arg_records))
        task_ci = format_ci(task_successes, total_evals)
        avg_tool_calls = round(total_tool_calls / total_evals, 2)
        avg_llm_calls = round(total_llm_calls / total_evals, 2)
        avg_llm_latency = round(total_llm_latency / total_evals, 2)

        def extract_ci_brackets(ci_str: str) -> str:
            if "[" in ci_str:
                return "[" + ci_str.split("[", 1)[1]
            return ci_str

        summary_data = [
            ["Metric", "Value", "Wilson 95% Confidence Interval"],
            ["Tool Selection Accuracy", f"{round(tool_successes/total_evals*100, 1)}%", extract_ci_brackets(tool_ci)],
            ["Argument Accuracy (specified args only)", f"{round(arg_successes/len(arg_records)*100, 1) if arg_records else 'N/A'}%", extract_ci_brackets(arg_ci)],
            ["Task Success Rate", f"{round(task_successes/total_evals*100, 1)}%", extract_ci_brackets(task_ci)],
            ["Avg Tool Calls / Task", f"{avg_tool_calls}", "N/A"],
            ["Avg LLM Calls / Task", f"{avg_llm_calls}", "N/A"],
            ["Avg LLM Latency (ms)", f"{avg_llm_latency} ms", "N/A"]
        ]
        print(tabulate(summary_data, headers="firstrow", tablefmt="github"))

        # Failure Breakdown
        from collections import Counter
        fail_counts = Counter(r.get("failure_type", "none") for r in records if str(r.get("task_success")).lower() != "true")
        if fail_counts:
            print("\nFAILURE TYPE BREAKDOWN:")
            fail_table = [["Failure Type", "Count", "Percentage"]]
            for f_type, cnt in fail_counts.most_common():
                pct = round(cnt / total_evals * 100, 1)
                fail_table.append([f_type, str(cnt), f"{pct}%"])
            print(tabulate(fail_table, headers="firstrow", tablefmt="github"))
        else:
            print("\nFAILURE TYPE BREAKDOWN: None (100% success)")

        print(f"\nRaw results committed to: {csv_path}\n")

        return {
            "model": self.model_name,
            "split": split,
            "run_id": run_id,
            "audit_log_path": audit_log_path,
            "total_runs": total_evals,
            "tool_selection_accuracy": round(tool_successes / total_evals * 100, 1),
            "tool_selection_ci": tool_ci,
            "argument_accuracy": round(arg_successes / len(arg_records) * 100, 1) if arg_records else None,
            "argument_ci": arg_ci,
            "task_success_rate": round(task_successes / total_evals * 100, 1),
            "task_success_ci": task_ci,
            "avg_tool_calls": avg_tool_calls,
            "avg_llm_calls": avg_llm_calls,
            "avg_llm_latency_ms": avg_llm_latency,
            "csv_path": csv_path
        }

if __name__ == "__main__":
    from agent.llm import provider_from_env
    harness = EvalHarness(llm=provider_from_env(), trials=3)
    harness.run_eval(split="dev")
