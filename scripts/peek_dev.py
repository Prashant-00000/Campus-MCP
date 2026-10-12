"""
Inspect results/baseline_openai_gpt-oss-20b_dev.csv for duplicates,
schema consistency, and compare early rows (run 1) vs late rows (resumed run).
"""

import csv
import os
from collections import Counter

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "results", "baseline_openai_gpt-oss-20b_dev.csv")

def peek():
    if not os.path.exists(CSV_PATH):
        print(f"Error: {CSV_PATH} does not exist.")
        return

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    total = len(reader)
    print(f"Total Rows: {total}")
    if total == 0:
        return

    fieldnames = list(reader[0].keys())
    print(f"Fields ({len(fieldnames)}): {', '.join(fieldnames)}")

    # Check for duplicates
    keys = [(r["case_id"], r["trial"], r["model"]) for r in reader]
    key_counts = Counter(keys)
    duplicates = [k for k, count in key_counts.items() if count > 1]
    print(f"Unique (case_id, trial, model) keys: {len(key_counts)}")
    print(f"Duplicates found: {len(duplicates)}")
    if duplicates:
        print(f"  Duplicate keys: {duplicates}")

    # Check timestamps to identify run boundaries
    timestamps = [r.get("run_timestamp", "") for r in reader]
    print(f"\nFirst row timestamp: {timestamps[0]}")
    print(f"Row 38 timestamp:    {timestamps[37] if total >= 38 else 'N/A'}")
    print(f"Row 39 timestamp:    {timestamps[38] if total >= 39 else 'N/A'}")
    print(f"Last row timestamp:  {timestamps[-1]}")

    # Display early rows (1 to 3)
    print("\n--- EARLY ROWS (Rows 1-3) ---")
    for i in range(min(3, total)):
        r = reader[i]
        print(f"Row {i+1}: case={r['case_id']} trial={r['trial']} task_success={r['task_success']} failure={r['failure_type']} n_tools={r.get('n_tool_calls')} n_llm={r.get('n_llm_calls')} llm_ms={r.get('llm_latency_ms')} retry_ms={r.get('retry_wait_ms')} ts={r.get('run_timestamp')}")

    # Display boundary rows around trial 38-40
    if total >= 39:
        print("\n--- BOUNDARY ROWS (Rows 37-41: stop & resume boundary) ---")
        for i in range(max(0, 36), min(total, 41)):
            r = reader[i]
            print(f"Row {i+1}: case={r['case_id']} trial={r['trial']} task_success={r['task_success']} failure={r['failure_type']} n_tools={r.get('n_tool_calls')} n_llm={r.get('n_llm_calls')} llm_ms={r.get('llm_latency_ms')} retry_ms={r.get('retry_wait_ms')} ts={r.get('run_timestamp')}")

    # Display late rows (last 3 rows)
    print(f"\n--- LATE ROWS (Rows {max(1, total-2)}-{total}) ---")
    for i in range(max(0, total-3), total):
        r = reader[i]
        print(f"Row {i+1}: case={r['case_id']} trial={r['trial']} task_success={r['task_success']} failure={r['failure_type']} n_tools={r.get('n_tool_calls')} n_llm={r.get('n_llm_calls')} llm_ms={r.get('llm_latency_ms')} retry_ms={r.get('retry_wait_ms')} ts={r.get('run_timestamp')}")

if __name__ == "__main__":
    peek()
