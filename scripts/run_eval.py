"""
Run Full Evaluation Harness Across 2 Real Models on Test Set (3 trials per case).

Configuration (in .env or environment):
  Requires TWO model configurations. Specify model pairs via:
    MODEL_A_PROVIDER, MODEL_A_MODEL  (e.g. groq + llama-3.1-8b-instant)
    MODEL_B_PROVIDER, MODEL_B_MODEL  (e.g. groq + llama-3.3-70b-versatile)

  Plus the appropriate API key (GROQ_API_KEY, OPENROUTER_API_KEY, etc.)

Generates official baseline CSVs and prints comparison table with Wilson 95% CIs.
"""

import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tabulate import tabulate
from agent.llm import LLMProvider
from eval.runner import EvalHarness


def run_both_models():
    # -- Read model config from environment --
    provider_a = os.getenv("MODEL_A_PROVIDER", os.getenv("LLM_PROVIDER", "")).strip()
    model_a = os.getenv("MODEL_A_MODEL", os.getenv("LLM_MODEL", "")).strip()
    provider_b = os.getenv("MODEL_B_PROVIDER", "").strip()
    model_b = os.getenv("MODEL_B_MODEL", "").strip()

    if not provider_a or not model_a:
        print(
            "ERROR: Set MODEL_A_PROVIDER and MODEL_A_MODEL (or LLM_PROVIDER / LLM_MODEL) in .env\n"
            "  Example for Groq:\n"
            "    MODEL_A_PROVIDER=groq\n"
            "    MODEL_A_MODEL=llama-3.1-8b-instant\n"
            "    MODEL_B_PROVIDER=groq\n"
            "    MODEL_B_MODEL=llama-3.3-70b-versatile\n"
            "    GROQ_API_KEY=gsk_..."
        )
        sys.exit(1)

    llm_a = LLMProvider(model_name=model_a, provider=provider_a)

    if provider_b and model_b:
        llm_b = LLMProvider(model_name=model_b, provider=provider_b)
        two_model_run = True
    else:
        print(
            f"WARNING: MODEL_B_PROVIDER / MODEL_B_MODEL not set. "
            f"Running single-model eval for {provider_a}/{model_a}.\n"
            f"Set both to get a comparative 2-model benchmark."
        )
        llm_b = None
        two_model_run = False

    print("=" * 70)
    print("STARTING OFFICIAL 2-MODEL BENCHMARK ON TEST SPLIT")
    print(f"Model A: {provider_a}/{model_a}")
    if two_model_run:
        print(f"Model B: {provider_b}/{model_b}")
    print("Split: test (3 trials per case)")
    print("=" * 70)

    harness_a = EvalHarness(llm=llm_a, trials=3)
    res_a = harness_a.run_eval(split="test", output_csv_name=f"baseline_{model_a.replace('/', '_')}_test.csv")

    if two_model_run:
        harness_b = EvalHarness(llm=llm_b, trials=3)
        res_b = harness_b.run_eval(split="test", output_csv_name=f"baseline_{model_b.replace('/', '_')}_test.csv")
    else:
        res_b = None

    # Comparative table
    if two_model_run:
        table_data = [
            ["Model", "Provider", "Tool Selection (95% CI)", "Task Success (95% CI)", "Avg Steps", "Avg Latency"],
            [
                model_a, provider_a,
                res_a["tool_selection_ci"], res_a["task_success_ci"],
                res_a["avg_steps"], f"{res_a['avg_latency_ms']} ms"
            ],
            [
                model_b, provider_b,
                res_b["tool_selection_ci"], res_b["task_success_ci"],
                res_b["avg_steps"], f"{res_b['avg_latency_ms']} ms"
            ],
        ]
        print("\n" + "=" * 70)
        print("OFFICIAL 2-MODEL EVALUATION COMPARISON")
        print("=" * 70)
        print(tabulate(table_data, headers="firstrow", tablefmt="github"))

    # Save summary
    summary_path = os.path.join("results", "eval_comparison.json")
    summary = {"model_a": res_a}
    if two_model_run:
        summary["model_b"] = res_b
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print(f"\nEvaluation summary saved to: {summary_path}\n")


if __name__ == "__main__":
    run_both_models()
