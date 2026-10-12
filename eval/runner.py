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
        """Grades a single agent run against the ground truth rules using robust normalization."""
        from eval.scoring import normalize_text, check_facts_present

        called_tools = [tc.tool_name for tc in agent_result.tool_calls]
        expected_tools = case.get("expected_tools", [])
        expected_args = case.get("expected_args", {})
        required_facts = case.get("required_facts", [])
        raw_ans = agent_result.final_answer or ""
        norm_answer = normalize_text(raw_ans)

        # 1. Tool Selection Accuracy
        if not expected_tools:
            tool_selection_ok = (len(called_tools) == 0)
        else:
            tool_selection_ok = all(t in called_tools for t in expected_tools)

        # 2. Argument Accuracy
        arg_ok = True
        if expected_args and tool_selection_ok:
            for tc in agent_result.tool_calls:
                actual_args = tc.arguments
                for k, exp_val in expected_args.items():
                    if k in actual_args:
                        actual_val = normalize_text(str(actual_args[k]))
                        exp_val_norm = normalize_text(str(exp_val))
                        if exp_val_norm not in actual_val:
                            arg_ok = False
        elif expected_tools and not tool_selection_ok:
            arg_ok = False

        # 3. Task Success
        task_success = False
        failure_type = "none"
        is_impossible = case.get("impossible", False)

        if is_impossible:
            # Must state impossibility / inability
            if any(term in norm_answer for term in ["cannot", "impossible", "predict", "not available", "unknown"]):
                task_success = True
            else:
                failure_type = "right_tools_wrong_answer"
        elif not expected_tools:
            # Direct answer check using unicode-aware normalization
            if check_facts_present(raw_ans, required_facts):
                task_success = True
            else:
                failure_type = "right_tools_wrong_answer" if len(called_tools) == 0 else "wrong_tool"
        else:
            # Must have called tool and include required facts
            facts_present = check_facts_present(raw_ans, required_facts)
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
            "case_id", "split", "category", "trial", "model", "provider",
            "temperature", "git_commit", "run_timestamp",
            "tool_selection_ok", "argument_ok", "task_success", "failure_type",
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
                        "trial": trial_idx,
                        "model": self.model_name,
                        "provider": self.provider,
                        "temperature": getattr(agent, "temperature", 0.0),
                        "git_commit": git_commit,
                        "run_timestamp": datetime.now(timezone.utc).isoformat(),
                        "tool_selection_ok": graded["tool_selection_ok"],
                        "argument_ok": graded["argument_ok"],
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
        arg_successes = sum(1 for r in records if str(r.get("argument_ok")).lower() == "true")
        task_successes = sum(1 for r in records if str(r.get("task_success")).lower() == "true")
        total_tool_calls = sum(int(r.get("n_tool_calls", 0)) for r in records)
        total_llm_calls = sum(int(r.get("n_llm_calls", 0)) for r in records)
        total_llm_latency = sum(float(r.get("llm_latency_ms", 0.0)) for r in records)

        tool_ci = format_ci(tool_successes, total_evals)
        arg_ci = format_ci(arg_successes, total_evals)
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
            ["Argument Accuracy", f"{round(arg_successes/total_evals*100, 1)}%", extract_ci_brackets(arg_ci)],
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
            "argument_accuracy": round(arg_successes / total_evals * 100, 1),
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
