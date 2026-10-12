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

    # 2. Extract final answers from audit logs keyed by (case_id, trial)
    answers = defaultdict(list)
    for p in sorted(glob.glob(LOGS_GLOB)):
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if d.get("event_type") == "session_end":
                    answers[d.get("case_id")].append(d.get("final_answer", ""))

    # 3. Load CSV records
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"Loaded {len(rows)} trials across {len(answers)} cases.")

    v1_passes = 0
    v2_passes = 0
    comparison_table = []
    
    # Track per-case trial index
    case_trial_tracker = defaultdict(int)

    for r in rows:
        cid = r["case_id"]
        case_trial_tracker[cid] += 1
        trial_num = case_trial_tracker[cid]
        
        # Get raw final answer from audit log
        ans_list = answers.get(cid, [])
        raw_ans = ans_list[trial_num - 1] if len(ans_list) >= trial_num else ""

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
        ])

    print("\n" + "=" * 80)
    print("OFFLINE RESCORING COMPARISON (GRADER V1 vs GRADER V2)")
    print("=" * 80)
    print(tabulate(comparison_table[:25], headers=[
        "Case ID", "Trial", "Category", "Grader v1", "Grader v2", "Failure Type v2", "Change"
    ], tablefmt="github"))
    print(f"... ({len(comparison_table) - 25} more rows) ...")

    print("\n" + "=" * 80)
    print("OVERALL RESCORING SUMMARY (48 Trials)")
    print("=" * 80)
    print(f"Grader v1 Task Success: {v1_passes}/48 ({round(v1_passes/48*100, 1)}%)")
    print(f"Grader v2 Task Success: {v2_passes}/48 ({round(v2_passes/48*100, 1)}%)")
    print(f"Net Score Improvement:  +{v2_passes - v1_passes} trials passed")

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
        "Case ID", "Trial", "Category", "Grader v1", "Grader v2", "Failure Type v2", "Change"
    ], tablefmt="github"))


if __name__ == "__main__":
    run_rescore()
