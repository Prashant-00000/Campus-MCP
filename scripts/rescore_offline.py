"""
Offline re-scoring script for dev benchmark results.
Compares Grader v1 (rigid substring) vs Grader v2 (atomic facts + date variants)
across all 48 completed trials without making any LLM API calls.
"""

import csv
import glob
import json
import os
import sys

from collections import defaultdict
from tabulate import tabulate

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from agent.react_agent import AgentRunResult, ToolExecutionRecord
from eval.runner import EvalHarness
from eval.scoring import check_facts_present, check_facts_present_v1

CSV_PATH = "results/baseline_openai_gpt-oss-20b_dev.csv"
DATASET_PATH = "eval/dataset.jsonl"
LOGS_GLOB = "audit_logs/20261012T05*_openai_gpt-oss-20b.jsonl"


def run_rescore():
    # 1. Load dataset requirements
    dataset = {}
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            dataset[d.get("id")] = d

    # 2. Reconstruct per-session tool traces and final answers from audit logs.
    sessions = defaultdict(list)
    for p in sorted(glob.glob(LOGS_GLOB)):
        by_session = {}
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                session_id = d.get("session_id")
                if not session_id:
                    continue
                session = by_session.setdefault(session_id, {"tools": [], "end": None})
                if d.get("tool_name"):
                    session["tools"].append(d)
                elif d.get("event_type") == "session_end":
                    session["end"] = d
        for session in by_session.values():
            end = session["end"]
            if end and end.get("case_id"):
                sessions[end["case_id"]].append(session)

    # 3. Load CSV records
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"Loaded {len(rows)} trials across {len(sessions)} cases.")

    v1_passes = 0
    v2_passes = 0
    comparison_table = []
    
    # Track per-case trial index
    case_trial_tracker = defaultdict(int)
    offline_harness = EvalHarness(type("OfflineLLM", (), {"model_name": "offline", "provider": "offline"})())

    for r in rows:
        cid = r["case_id"]
        case_trial_tracker[cid] += 1
        trial_num = case_trial_tracker[cid]
        
        session_list = sessions.get(cid, [])
        session = session_list[trial_num - 1] if len(session_list) >= trial_num else {"tools": [], "end": {}}
        end = session["end"] or {}
        raw_ans = end.get("final_answer", "")

        case_def = dataset.get(cid, {})
        req_facts = case_def.get("required_facts", [])
        tool_ok = r.get("tool_selection_ok", "").lower() == "true"
        arg_ok = r.get("argument_ok", "").lower() == "true"
        failure_type_v1 = r.get("failure_type", "none")

        # Grader v1: literal verdict as originally evaluated and stored in CSV
        success_v1 = r.get("task_success", "").lower() == "true"

        # Grader v2 evaluation
        facts_ok_v2 = check_facts_present(raw_ans, req_facts) if req_facts else True
        success_v2 = tool_ok and arg_ok and facts_ok_v2 if r.get("failure_type") != "loop" else False
        failure_type_v2 = "none" if success_v2 else ("loop" if failure_type_v1 == "loop" else "right_tools_wrong_answer")

        tool_calls = [
            ToolExecutionRecord(
                tool_name=tool["tool_name"],
                arguments=tool.get("arguments", {}),
                result=tool.get("result_preview", ""),
                is_error=tool.get("is_error", False),
                latency_ms=float(tool.get("tool_latency_ms", 0.0) or 0.0),
            )
            for tool in session["tools"]
        ]
        v3_result = AgentRunResult(
            question=case_def.get("question", ""),
            final_answer=raw_ans,
            steps_taken=int(end.get("steps_taken", 0) or 0),
            tool_calls=tool_calls,
            completed=end.get("stop_reason") == "final_answer",
        )
        v3 = offline_harness.grade_case(case_def, v3_result)

        if success_v1:
            v1_passes += 1
        if success_v2:
            v2_passes += 1

        status_change = "SAME"
        if success_v2 and not success_v1:
            status_change = "FLIPPED (FAIL -> PASS)"
        elif not success_v2 and success_v1:
            status_change = "REGRESSED (PASS -> FAIL)"

        comparison_table.append([
            cid,
            trial_num,
            case_def.get("category"),
            "PASS" if success_v1 else "FAIL",
            "PASS" if success_v2 else "FAIL",
            failure_type_v2,
            status_change,
            "PASS" if v3["task_success"] else "FAIL",
            v3["tool_precision"],
            v3["tool_recall"],
            v3["extra_calls"],
            v3["redundant_calls"],
            v3["argument_accuracy"] if v3["argument_accuracy"] is not None else "N/A",
            v3["missing_args"],
            "PASS" if v3["tool_use_quality"] else "FAIL",
        ])

    print("\n" + "=" * 80)
    print("OFFLINE RESCORING COMPARISON (GRADER V1 vs GRADER V2 vs GRADER V3)")
    print("=" * 80)
    print(tabulate(comparison_table[:25], headers=[
        "Case ID", "Trial", "Category", "Grader v1", "Grader v2", "Failure Type v2", "Change",
        "Grader v3 Answer", "Precision", "Recall", "Extra", "Redundant", "Arg Acc", "Missing", "Tool Quality"
    ], tablefmt="github"))
    print(f"... ({len(comparison_table) - 25} more rows) ...")

    v3_passes = sum(1 for row in comparison_table if row[7] == "PASS")
    v3_quality_passes = sum(1 for row in comparison_table if row[14] == "PASS")
    print("\n" + "=" * 80)
    print(f"OVERALL RESCORING SUMMARY ({len(comparison_table)} Trials)")
    print("=" * 80)
    denominator = len(comparison_table)
    print(f"Grader v1 Task Success: {v1_passes}/{denominator} ({round(v1_passes/denominator*100, 1)}%)")
    print(f"Grader v2 Task Success: {v2_passes}/{denominator} ({round(v2_passes/denominator*100, 1)}%)")
    print(f"Grader v3 Task Success: {v3_passes}/{denominator} ({round(v3_passes/denominator*100, 1)}%)")
    print(f"Grader v3 Tool-Use Quality: {v3_quality_passes}/{denominator} ({round(v3_quality_passes/denominator*100, 1)}%)")
    print(f"v3 extra calls: {sum(int(row[10]) for row in comparison_table)}")
    print(f"v3 redundant calls: {sum(int(row[11]) for row in comparison_table)}")

    by_case = defaultdict(list)
    for row in comparison_table:
        by_case[row[0]].append(row)
    case_table = []
    for case_id, case_rows in sorted(by_case.items()):
        def verdict(index):
            passed = sum(row[index] == "PASS" for row in case_rows)
            return f"{passed}/{len(case_rows)}"

        case_table.append([
            case_id,
            f"{sum(float(row[8]) for row in case_rows) / len(case_rows):.2f}",
            f"{sum(float(row[9]) for row in case_rows) / len(case_rows):.2f}",
            sum(int(row[13]) for row in case_rows),
            sum(int(row[10]) for row in case_rows),
            sum(int(row[11]) for row in case_rows),
            verdict(3),
            verdict(4),
            verdict(7),
            verdict(14),
        ])

    print("\n" + "=" * 80)
    print("PER-CASE V1/V2/V3 AND TOOL-USE QUALITY")
    print("=" * 80)
    print(tabulate(case_table, headers=[
        "Case", "Tool Precision", "Tool Recall", "Missing Args", "Extra Calls", "Redundant Calls",
        "v1", "v2", "v3 Answer", "v3 Tool Quality"
    ], tablefmt="github"))

    # Hand-check 10 specific rows
    print("\n" + "=" * 80)
    print("HAND-CHECK: 10 SELECTED ROWS")
    print("=" * 80)
    sample_indices = [0, 3, 6, 9, 12, 15, 21, 24, 36, 42]
    hand_check = []
    for idx in sample_indices:
        if idx < len(comparison_table):
            hand_check.append(comparison_table[idx])
    print(tabulate(hand_check, headers=[
        "Case ID", "Trial", "Category", "Grader v1", "Grader v2", "Failure Type v2", "Change",
        "Grader v3 Answer", "Precision", "Recall", "Extra", "Redundant", "Arg Acc", "Missing", "Tool Quality"
    ], tablefmt="github"))


if __name__ == "__main__":
    run_rescore()
