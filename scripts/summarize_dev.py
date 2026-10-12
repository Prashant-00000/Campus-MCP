"""
Summarize evaluation results on dev split from results/baseline_openai_gpt-oss-20b_dev.csv
Prints:
- Overall accuracy & Wilson 95% CIs
- Failure type breakdown
- Per-category results
- Flip-flop cases (cases with inconsistent trials)
"""

import csv
import math
import os
from collections import Counter, defaultdict
from tabulate import tabulate

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "results", "baseline_openai_gpt-oss-20b_dev.csv")

def wilson_ci(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    spread = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denom
    return max(0.0, centre - spread) * 100, min(100.0, centre + spread) * 100

def summarize():
    if not os.path.exists(CSV_PATH):
        print(f"Error: {CSV_PATH} not found.")
        return

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        records = list(csv.DictReader(f))

    total = len(records)
    if total == 0:
        print("No records found in CSV.")
        return

    # Accuracy calculations
    tool_ok = sum(1 for r in records if r.get("tool_selection_ok", "").lower() == "true")
    arg_ok = sum(1 for r in records if r.get("argument_ok", "").lower() == "true")
    task_ok = sum(1 for r in records if r.get("task_success", "").lower() == "true")

    tool_low, tool_high = wilson_ci(tool_ok, total)
    arg_low, arg_high = wilson_ci(arg_ok, total)
    task_low, task_high = wilson_ci(task_ok, total)

    avg_tools = round(sum(int(r.get("n_tool_calls", 0)) for r in records) / total, 2)
    avg_llm_calls = round(sum(int(r.get("n_llm_calls", 0)) for r in records) / total, 2)
    avg_llm_ms = round(sum(float(r.get("llm_latency_ms", 0.0)) for r in records) / total, 2)
    avg_retry_ms = round(sum(float(r.get("retry_wait_ms", 0.0)) for r in records) / total, 2)

    print("=" * 75)
    print(f"DEV SPLIT BENCHMARK SUMMARY ({total} Trials Evaluated)")
    print(f"Model: {records[0].get('model')} | Provider: {records[0].get('provider')}")
    print("=" * 75)

    overview = [
        ["Metric", "Value", "95% Wilson CI"],
        ["Tool Selection Accuracy", f"{round(tool_ok/total*100, 1)}% ({tool_ok}/{total})", f"[{round(tool_low, 1)}% - {round(tool_high, 1)}%]"],
        ["Argument Accuracy", f"{round(arg_ok/total*100, 1)}% ({arg_ok}/{total})", f"[{round(arg_low, 1)}% - {round(arg_high, 1)}%]"],
        ["Task Success Rate", f"{round(task_ok/total*100, 1)}% ({task_ok}/{total})", f"[{round(task_low, 1)}% - {round(task_high, 1)}%]"],
        ["Avg Tool Calls / Trial", f"{avg_tools}", "N/A"],
        ["Avg LLM Calls / Trial", f"{avg_llm_calls}", "N/A"],
        ["Avg Pure LLM Latency", f"{avg_llm_ms} ms", "N/A"],
        ["Avg Throttling Retry Wait", f"{avg_retry_ms} ms", "N/A"],
    ]
    print(tabulate(overview, headers="firstrow", tablefmt="github"))

    # Failure Breakdown
    failures = [r.get("failure_type", "none") for r in records if r.get("task_success", "").lower() != "true"]
    fail_counts = Counter(failures)
    print("\n" + "=" * 75)
    print(f"FAILURE BREAKDOWN ({len(failures)} Total Failures / {total} Trials)")
    print("=" * 75)
    if fail_counts:
        fail_table = [["Failure Type", "Count", "% of All Trials", "% of Failures"]]
        for f_type, cnt in fail_counts.most_common():
            fail_table.append([f_type, str(cnt), f"{round(cnt/total*100, 1)}%", f"{round(cnt/len(failures)*100, 1)}%"])
        print(tabulate(fail_table, headers="firstrow", tablefmt="github"))
    else:
        print("No failures encountered (100% success rate).")

    # Per-Category Breakdown
    cat_groups = defaultdict(list)
    for r in records:
        cat_groups[r.get("category", "unknown")].append(r)

    print("\n" + "=" * 75)
    print("PER-CATEGORY BREAKDOWN")
    print("=" * 75)
    cat_table = [["Category", "Trials", "Successes", "Success Rate", "Dominant Failure"]]
    for cat, rows in sorted(cat_groups.items()):
        n_cat = len(rows)
        n_ok = sum(1 for r in rows if r.get("task_success", "").lower() == "true")
        cat_fails = Counter(r.get("failure_type") for r in rows if r.get("task_success", "").lower() != "true")
        dom_fail = cat_fails.most_common(1)[0][0] if cat_fails else "none"
        cat_table.append([cat, str(n_cat), str(n_ok), f"{round(n_ok/n_cat*100, 1)}%", dom_fail])
    print(tabulate(cat_table, headers="firstrow", tablefmt="github"))

    # Case-by-case & Flip-Flops
    case_trials = defaultdict(list)
    for r in records:
        case_trials[r.get("case_id")].append(r)

    flip_flops = []
    unanimous_pass = []
    unanimous_fail = []

    for case_id, rows in sorted(case_trials.items()):
        passes = sum(1 for r in rows if r.get("task_success", "").lower() == "true")
        n = len(rows)
        cat = rows[0].get("category")
        if passes == n:
            unanimous_pass.append((case_id, cat, n))
        elif passes == 0:
            fails = Counter(r.get("failure_type") for r in rows)
            unanimous_fail.append((case_id, cat, n, fails.most_common(1)[0][0]))
        else:
            flip_flops.append((case_id, cat, passes, n))

    print("\n" + "=" * 75)
    print("TRIAL CONSISTENCY & FLIP-FLOP CASES")
    print("=" * 75)
    print(f"Cases with 3/3 Pass: {len(unanimous_pass)} cases: {[c[0] for c in unanimous_pass]}")
    print(f"Cases with 0/3 Pass: {len(unanimous_fail)} cases: {[(c[0], c[3]) for c in unanimous_fail]}")
    if flip_flops:
        print(f"Flip-Flop Cases (inconsistent trials across 3 runs): {len(flip_flops)}")
        ff_table = [["Case ID", "Category", "Passes / Trials", "Pass Rate"]]
        for cid, cat, p, n in flip_flops:
            ff_table.append([cid, cat, f"{p}/{n}", f"{round(p/n*100, 1)}%"])
        print(tabulate(ff_table, headers="firstrow", tablefmt="github"))
    else:
        print("Flip-Flop Cases: 0 (all evaluated cases were 100% deterministic across all 3 trials)")

if __name__ == "__main__":
    summarize()
