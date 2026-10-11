"""
Run Full Evaluation Harness Across 2 Models on Test Set (3 trials per case).
Generates official baseline CSVs and prints comparison table with Wilson 95% CIs.
"""

import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tabulate import tabulate
from eval.runner import EvalHarness

def run_both_models():
    print("=" * 70)
    print("STARTING OFFICIAL 2-MODEL BENCHMARK ON TEST SPLIT")
    print("Split: test (21 cases, 3 trials = 63 executions per model)")
    print("=" * 70)

    # Model A: High-Reasoning / Standard Model
    harness_a = EvalHarness(model_name="model-a-simulator", trials=3)
    res_a = harness_a.run_eval(split="test", output_csv_name="baseline_model_a_test.csv")

    # Model B: Fast / Lightweight Model
    harness_b = EvalHarness(model_name="model-b-simulator", trials=3)
    res_b = harness_b.run_eval(split="test", output_csv_name="baseline_model_b_test.csv")

    # Comparative Table
    table_data = [
        ["Model Architecture", "Tool Selection Acc (95% CI)", "Argument Acc (95% CI)", "Task Success Rate (95% CI)", "Avg Steps", "Avg Latency"],
        [
            "Model A (High-Reasoning Equiv)",
            res_a["tool_selection_ci"],
            res_a["argument_ci"],
            res_a["task_success_ci"],
            f"{res_a['avg_steps']}",
            f"{res_a['avg_latency_ms']} ms"
        ],
        [
            "Model B (Fast-Tier Equiv)",
            res_b["tool_selection_ci"],
            res_b["argument_ci"],
            res_b["task_success_ci"],
            f"{res_b['avg_steps']}",
            f"{res_b['avg_latency_ms']} ms"
        ]
    ]

    print("\n" + "=" * 70)
    print("OFFICIAL 2-MODEL EVALUATION COMPARISON")
    print("=" * 70)
    print(tabulate(table_data, headers="firstrow", tablefmt="github"))

    # Save summary
    summary_path = os.path.join("results", "eval_comparison.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"model_a": res_a, "model_b": res_b}, f, indent=2)

    print(f"\nEvaluation summary saved to: {summary_path}\n")

if __name__ == "__main__":
    run_both_models()
