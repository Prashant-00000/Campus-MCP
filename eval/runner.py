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

DATASET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset.jsonl")
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
        return cases

    def grade_case(self, case: Dict[str, Any], agent_result) -> Dict[str, Any]:
        """Grades a single agent run against the ground truth rules."""
        called_tools = [tc.tool_name for tc in agent_result.tool_calls]
        expected_tools = case.get("expected_tools", [])
        expected_args = case.get("expected_args", {})
        required_facts = case.get("required_facts", [])
        raw_ans = agent_result.final_answer.lower()
        answer = (
            raw_ans.replace("\u2011", "-")
            .replace("\u2013", "-")
            .replace("\u2014", "-")
            .replace("\u202f", " ")
            .replace("\xa0", " ")
        )

        # 1. Tool Selection Accuracy
        if not expected_tools:
            # Expected no tools
            tool_selection_ok = (len(called_tools) == 0)
        else:
            # Check if all expected tools were called
            tool_selection_ok = all(t in called_tools for t in expected_tools)

        # 2. Argument Accuracy
        arg_ok = True
        if expected_args and tool_selection_ok:
            for tc in agent_result.tool_calls:
                actual_args = tc.arguments
                for k, exp_val in expected_args.items():
                    if k in actual_args:
                        actual_val = str(actual_args[k]).lower()
                        if str(exp_val).lower() not in actual_val:
                            arg_ok = False
        elif expected_tools and not tool_selection_ok:
            arg_ok = False

        # 3. Task Success
        task_success = False
        failure_type = "none"
        is_impossible = case.get("impossible", False)

        if is_impossible:
            # Must state impossibility / inability
            if any(term in answer for term in ["cannot", "impossible", "predict", "not available", "unknown"]):
                task_success = True
            else:
                failure_type = "right_tools_wrong_answer"
        elif not expected_tools:
            # Direct answer check
            if all(f.lower() in answer for f in required_facts):
                task_success = True
            else:
                failure_type = "right_tools_wrong_answer" if len(called_tools) == 0 else "wrong_tool"
        else:
            # Must have called tool and include required facts
            facts_present = all(f.lower() in answer for f in required_facts)
            if tool_selection_ok and arg_ok and facts_present:
                task_success = True
            else:
                if not tool_selection_ok:
                    failure_type = "wrong_tool"
                elif not arg_ok:
                    failure_type = "wrong_args"
                else:
                    failure_type = "right_tools_wrong_answer"

        if not agent_result.completed:
            failure_type = "loop" if agent_result.steps_taken >= 10 else "gave_up"

        return {
            "tool_selection_ok": tool_selection_ok,
            "argument_ok": arg_ok,
            "task_success": task_success,
            "failure_type": failure_type,
            "steps": agent_result.steps_taken,
            "latency_ms": agent_result.total_latency_ms
        }

    def run_eval(
        self,
        split: str = "test",
        output_csv_name: Optional[str] = None,
        run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        # Reset all databases to seed state before every run
        init_college_db()
        init_company_db()
        init_github_db()

        cases = self.load_dataset(split=split)

        # 1. Determine run ID and output paths
        run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        clean_model_id = self.model_name.replace("/", "_").replace(":", "_")
        csv_filename = output_csv_name or f"baseline_{clean_model_id}_{split}.csv"
        csv_path = os.path.join(RESULTS_DIR, csv_filename)
        audit_log_path = os.path.join(AUDIT_DIR, f"{run_id}_{clean_model_id}.jsonl")

        # 2. Guard against cross-model data contamination
        # Refuses to start if target results CSV or audit log contains a mismatched model
        check_contamination_guard(csv_path, self.model_name)
        check_contamination_guard(audit_log_path, self.model_name)

        # 3. Initialize per-run AuditLogger and ReActAgent
        audit_logger = AuditLogger(log_path=audit_log_path, model=self.model_name)
        agent = ReActAgent(llm=self.llm, defenses=self.defenses, audit_logger=audit_logger)
        run_timestamp = datetime.now(timezone.utc).isoformat()

        records = []
        total_evals = 0
        tool_successes = 0
        arg_successes = 0
        task_successes = 0
        total_steps = 0
        total_latency = 0.0

        print(f"\n=======================================================")
        print(f"Running Evaluation: {self.model_name} (Split: {split}, Trials: {self.trials})")
        print(f"Run ID: {run_id} | Audit Log: {audit_log_path}")
        print(f"Cases: {len(cases)} | Total Executions: {len(cases) * self.trials}")
        print(f"=======================================================")

        for case in cases:
            case_id = case["id"]
            question = case["question"]
            category = case["category"]

            for trial_idx in range(1, self.trials + 1):
                res = agent.run(question, case_id=case_id)
                graded = self.grade_case(case, res)

                total_evals += 1
                if graded["tool_selection_ok"]:
                    tool_successes += 1
                if graded["argument_ok"]:
                    arg_successes += 1
                if graded["task_success"]:
                    task_successes += 1

                total_steps += graded["steps"]
                total_latency += graded["latency_ms"]

                records.append({
                    "case_id": case_id,
                    "split": split,
                    "category": category,
                    "trial": trial_idx,
                    "model": self.model_name,
                    "provider": self.provider,
                    "run_timestamp": run_timestamp,
                    "tool_selection_ok": graded["tool_selection_ok"],
                    "argument_ok": graded["argument_ok"],
                    "task_success": graded["task_success"],
                    "failure_type": graded["failure_type"],
                    "steps": graded["steps"],
                    "latency_ms": round(graded["latency_ms"], 2)
                })

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "case_id", "split", "category", "trial", "model", "provider",
                "run_timestamp", "tool_selection_ok", "argument_ok", "task_success",
                "failure_type", "steps", "latency_ms"
            ])
            writer.writeheader()
            writer.writerows(records)

        tool_ci = format_ci(tool_successes, total_evals)
        arg_ci = format_ci(arg_successes, total_evals)
        task_ci = format_ci(task_successes, total_evals)
        avg_steps = round(total_steps / total_evals, 2)
        avg_latency = round(total_latency / total_evals, 2)

        def extract_ci_brackets(ci_str: str) -> str:
            if "[" in ci_str:
                return "[" + ci_str.split("[", 1)[1]
            return ci_str

        summary_data = [
            ["Metric", "Value", "Wilson 95% Confidence Interval"],
            ["Tool Selection Accuracy", f"{round(tool_successes/total_evals*100, 1)}%", extract_ci_brackets(tool_ci)],
            ["Argument Accuracy", f"{round(arg_successes/total_evals*100, 1)}%", extract_ci_brackets(arg_ci)],
            ["Task Success Rate", f"{round(task_successes/total_evals*100, 1)}%", extract_ci_brackets(task_ci)],
            ["Average Steps per Task", f"{avg_steps}", "N/A"],
            ["Average Latency (ms)", f"{avg_latency} ms", "N/A"]
        ]
        print(tabulate(summary_data, headers="firstrow", tablefmt="github"))
        print(f"\nRaw results committed to: {csv_path}\n")

        return {
            "model": self.model_name,
            "split": split,
            "run_id": run_id,
            "audit_log_path": audit_log_path,
            "total_runs": total_evals,
            "tool_selection_accuracy": round(tool_successes / total_evals * 100, 1),
            "tool_selection_ci": tool_ci,
            "argument_accuracy": round(arg_successes / total_evals * 100, 1),
            "argument_ci": arg_ci,
            "task_success_rate": round(task_successes / total_evals * 100, 1),
            "task_success_ci": task_ci,
            "avg_steps": avg_steps,
            "avg_latency_ms": avg_latency,
            "csv_path": csv_path
        }

if __name__ == "__main__":
    from agent.llm import provider_from_env
    harness = EvalHarness(llm=provider_from_env(), trials=3)
    harness.run_eval(split="dev")
