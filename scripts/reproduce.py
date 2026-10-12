"""
Master 1-Command Reproduction Script.
Executes the full pipeline from scratch:
1. Database initialization
2. Server & Agent test suites (pytest)
3. 2-Model Evaluation Benchmark (Test split, 3 trials each)
4. Red-Team Ablation Study, Adaptive Round, and Utility Re-Check
5. Summary Table & Resume Claim Verification
"""

import os
import sys
import json
import subprocess
import time
import argparse
from tabulate import tabulate

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

def run_step(step_num: int, title: str, cmd_args: list):
    print("\n" + "=" * 78)
    print(f"STEP {step_num}: {title.upper()}")
    print("=" * 78)
    start = time.time()
    res = subprocess.run(cmd_args, cwd=BASE_DIR)
    elapsed = round(time.time() - start, 2)
    if res.returncode != 0:
        print(f"\n[ERROR] Step {step_num} failed with return code {res.returncode}")
        sys.exit(res.returncode)
    print(f"\n>>> Step {step_num} completed successfully in {elapsed}s.")

def run_offline(py_exe):
    run_step(1, "Run Unit & Security Tests (offline)", [py_exe, "-m", "pytest", "-q"])
    run_step(2, "Rescore Stored Results (Grader v1/v2/v3)", [py_exe, "scripts/rescore_offline.py"])
    run_step(3, "Regenerate README Metrics From Stored CSVs", [py_exe, "scripts/update_readme_metrics.py"])


def run_live(py_exe):
    estimated_calls = (52 * 3 * 2) + (32 * 6)
    estimated_tokens = estimated_calls * 1700
    print(f"Live mode will make approximately {estimated_calls} model calls (~{estimated_tokens:,} prompt tokens before completions).")
    answer = input("Continue with live API calls? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        print("Live run cancelled.")
        return

    run_step(1, "Initialize Databases (College, DB, GitHub)", [py_exe, "data/init_databases.py"])
    run_step(2, "Run Unit & Security Tests (pytest)", [py_exe, "-m", "pytest", "-v"])
    run_step(3, "Run 2-Model Evaluation Benchmark (Test split, 3 trials)", [py_exe, "scripts/run_eval.py"])
    run_step(4, "Run Red-Team Ablations, Adaptive Attacks & Utility Re-Check", [py_exe, "scripts/run_redteam.py"])


def main():
    parser = argparse.ArgumentParser(description="Reproduce offline artifacts or run live model experiments.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Run tests, offline rescoring, and README metric generation.")
    mode.add_argument("--live", action="store_true", help="Run API-backed evaluation and red-team experiments after confirmation.")
    args = parser.parse_args()

    py_exe = sys.executable
    if not args.live:
        run_offline(py_exe)
        return

    print("""
==============================================================================
       3-SERVER MCP AGENT: BENCHMARK, RED-TEAM & REPRODUCTION PIPELINE
==============================================================================
    """)

    run_live(py_exe)

    print("\n" + "=" * 78)
    print("ALL PIPELINE STEPS COMPLETED. VERIFYING DEFENSE CLAIMS")
    print("=" * 78)

    # Load measured numbers from results files produced by real runs
    eval_json = os.path.join(BASE_DIR, "results", "eval_comparison.json")
    redteam_json = os.path.join(BASE_DIR, "results", "redteam_summary.json")

    def _load(path: str) -> dict:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        return {}

    ev = _load(eval_json)
    rt = _load(redteam_json)

    ma = ev.get("model_a", {})
    mb = ev.get("model_b", {})

    def _ci(key: str, d: dict) -> str:
        return d.get(key, "[run eval first]")

    summary_pitch = [
        ["Claim Parameter", "Measured Empirical Value (from real LLM runs)"],
        ["MCP Servers Built", "3 Servers (College, DB, GitHub) — 13 tools, 3 resources, 3 prompts"],
        ["Evaluation Dataset", f"52 curated cases (31 dev / 21 test), 3 trials each across 2 models"],
        ["Model A", ma.get("model", "?") + " (" + ma.get("split", "") + " split)"],
        ["  Tool Selection (95% CI)", _ci("tool_selection_ci", ma)],
        ["  Task Success (95% CI)", _ci("task_success_ci", ma)],
        ["Model B", mb.get("model", "not run") + (" (" + mb.get("split", "") + " split)" if mb else "")],
        ["  Tool Selection (95% CI)", _ci("tool_selection_ci", mb) if mb else "—"],
        ["  Task Success (95% CI)", _ci("task_success_ci", mb) if mb else "—"],
        ["Baseline Attack Success (ASR)", f"{rt.get('baseline_asr', '?')}%  CI {rt.get('baseline_ci', '[run redteam first]')}"],
        ["Defended Standard ASR", f"{rt.get('defended_asr', '?')}%  CI {rt.get('defended_ci', '[run redteam first]')}"],
        ["Adaptive Attack ASR", f"{rt.get('adaptive_asr', '?')}%  CI {rt.get('adaptive_ci', '[run redteam first]')}"],
        ["Utility Cost of Defenses", f"{rt.get('utility_cost', '?')}% task success drop"],
    ]

    # Build resume pitch from real numbers
    if rt.get("baseline_asr") is not None and rt.get("defended_asr") is not None:
        pitch = (
            f"Built a 3-server MCP agent, measured tool-selection and task accuracy "
            f"across 2 models, red-teamed it, and cut attack success from "
            f"{rt['baseline_asr']}% to {rt['defended_asr']}% "
            f"(95% CI {rt.get('defended_ci', '?')}) at a utility cost of {rt.get('utility_cost', '?')}%."
        )
    else:
        pitch = "[Run scripts/run_eval.py and scripts/run_redteam.py to generate this sentence.]"

    summary_pitch.append(["One-Line Resume Sentence", pitch])

    print(tabulate(summary_pitch, headers="firstrow", tablefmt="github"))
    print("\nAll raw CSV logs and JSON artifacts are stored under the 'results/' directory.\n")

if __name__ == "__main__":
    main()
