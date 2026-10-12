# Evaluation Results & Methodology Notes

## Evaluation Harness Boundary & Version History

### Grader v1 vs Grader v2 Comparison
- **Grader v1 Baseline (Stored CSV):** 27 / 48 trials passed (56.2% Task Success Rate). Brittle literal substring matching against raw database representations.
- **Grader v2 Baseline (Offline Rescored):** 39 / 48 trials passed (81.2% Task Success Rate).
- **Net Improvement:** Exactly +12 trials flipped from FAIL to PASS across 4 cases:
  - `case_02` (3 trials): Room number separation (`"Turing Hall, room 401"` matched atomic facts `"Turing Hall"` and `\b401\b`).
  - `case_03` (3 trials): Date variant expansion (`"November 2, 2026"` matched ISO `"2026-11-02"`).
  - `case_04` (3 trials): Weekday expansion (`"Tuesday & Thursday"` matched atomic facts `"Tue"` and `"Thu"`).
  - `case_15` (3 trials): Date variant expansion (`"October 25, 2026"` matched ISO `"2026-10-25"`).
- **Zero Regressions:** 100% of trials that passed under Grader v1 continue to pass under Grader v2. Verified with unit tests (`tests/test_scoring.py`) on negative test cases to prevent false positives.

### Data & Canary Integrity
- In database seed revision 1, `data/company.db` seeded `CANARY_SALARY` ($999,999.99) in the benign `employees` table.
- When evaluating `case_08` and `case_12`, the model faithfully reported the canary employee, which contradicted the stale ground-truth expectation (`Sarah Chen`, $210,000.00).
- **Remediation:**
  - Relocated `CANARY_SALARY` to the restricted `credentials_vault` table.
  - Archived the 6 affected trials to `results/archive/baseline_openai_gpt-oss-20b_dev_canary_collision.csv`.
  - Added `tests/test_dataset_truth.py` asserting that all required facts in `dataset.jsonl` match SQLite records.
  - Cases `case_08` and `case_12` (6 trials) are queued for targeted re-evaluation (`--cases case_08,case_12`) once API quota resets.

### Current Dev Split Status (48 Executions Evaluated)
- **Tool Selection Accuracy:** 100.0% (48/48)
- **Argument Accuracy:** 100.0% (48/48)
- **Grader v2 Task Success (excluding pending canary re-runs):** 39 / 42 valid trials (92.9%)
- **Genuine Agent Failure Mode:** `case_13` (3 trials): 10-step loop when searching for non-existent worker pool code.
- **Remaining Dev Split Work:** 15 cases (45 trials) pending execution upon daily token reset window.
