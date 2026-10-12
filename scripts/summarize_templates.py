"""Summarize evaluation results at case/template granularity."""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from eval.hard_cases import generate_hard_cases
from eval.hand_cases import generate_hand_cases
from eval.stats import format_ci


def load_cases():
    cases = {}
    with open(os.path.join(BASE_DIR, "eval", "dataset.jsonl"), encoding="utf-8") as handle:
        for line in handle:
            case = json.loads(line)
            cases[case["id"]] = case
    cases.update({case["id"]: case for case in generate_hard_cases()})
    cases.update({case["id"]: case for case in generate_hand_cases()})
    return cases


def summarize(path):
    cases = load_cases()
    with open(path, encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    grouped = defaultdict(lambda: defaultdict(list))
    for row in rows:
        case = cases.get(row.get("case_id"), {})
        template = row.get("template") or case.get("template") or case.get("category", "legacy")
        grouped[template][row.get("case_id")].append(row)

    print("| Template | Cases | Case answer-success rate | Case-level Wilson 95% CI |")
    print("| :--- | ---: | ---: | :--- |")
    for template, case_rows in sorted(grouped.items()):
        case_successes = sum(
            all(row.get("answer_correct", row.get("task_success", "")).lower() == "true" for row in trials)
            for trials in case_rows.values()
        )
        case_total = len(case_rows)
        print(f"| {template} | {case_total} | {case_successes}/{case_total} ({case_successes / case_total * 100:.1f}%) | {format_ci(case_successes, case_total)} |")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    summarize(parser.parse_args().csv_path)
