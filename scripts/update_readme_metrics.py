"""Regenerate the compact benchmark table in README.md from stored CSV results."""

import csv
import glob
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_PATH = os.path.join(BASE_DIR, "README.md")
RESULTS_GLOB = os.path.join(BASE_DIR, "results", "baseline_*.csv")
START = "<!-- GENERATED_METRICS_START -->"
END = "<!-- GENERATED_METRICS_END -->"


def _summary(path):
    with open(path, "r", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return None
    model = rows[0].get("model", os.path.basename(path))
    total = len(rows)
    tool_ok = sum(row.get("tool_selection_ok", "").lower() == "true" for row in rows)
    task_ok = sum(row.get("task_success", "").lower() == "true" for row in rows)
    arg_rows = [row for row in rows if int(row.get("argument_checks", 0) or 0) > 0]
    arg_ok = sum(row.get("argument_ok", "").lower() == "true" for row in arg_rows)
    has_v3 = "argument_checks" in rows[0]
    return [
        model,
        rows[0].get("split", ""),
        f"{tool_ok}/{total} ({tool_ok / total * 100:.1f}%)" + ("" if has_v3 else " [legacy CSV]"),
        f"{arg_ok}/{len(arg_rows)} ({arg_ok / len(arg_rows) * 100:.1f}%)" if arg_rows else "N/A",
        f"{task_ok}/{total} ({task_ok / total * 100:.1f}%)",
    ]


def update_readme():
    rows = [_summary(path) for path in sorted(glob.glob(RESULTS_GLOB))]
    rows = [row for row in rows if row]
    generated = [
        START,
        "### Stored Benchmark Artifacts",
        "Generated from CSV files currently present under `results/`; argument accuracy uses specified-argument cases only. Legacy CSVs predate Grader v3 fields and are labeled accordingly.",
        "",
        "| Model | Split | Tool Selection Gate | Argument Accuracy | Task Success |",
        "| :--- | :--- | :---: | :---: | :---: |",
    ]
    generated.extend(f"| {model} | {split} | {tool} | {arg} | {task} |" for model, split, tool, arg, task in rows)
    if not rows:
        generated.append("| No stored baseline CSVs | - | - | - | - |")
    generated.append(END)

    with open(README_PATH, "r", encoding="utf-8") as handle:
        readme = handle.read()
    block = "\n".join(generated)
    if START in readme and END in readme:
        before = readme.split(START, 1)[0]
        after = readme.split(END, 1)[1]
        readme = before + block + after
    else:
        marker = "\n\n## 1. Key Empirical Results"
        readme = readme.replace(marker, "\n\n" + block + marker, 1)
    with open(README_PATH, "w", encoding="utf-8", newline="") as handle:
        handle.write(readme)
    print(f"Updated {README_PATH} from {len(rows)} stored CSV artifact(s).")


if __name__ == "__main__":
    update_readme()
