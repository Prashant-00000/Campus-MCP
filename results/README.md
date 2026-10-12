# Evaluation Results & Methodology Notes

## Grader Version History

- **v1:** Literal normalized substring matching. Retired because human-readable dates, spacing, and atomic facts produced false negatives.
- **v2:** Unicode normalization, atomic fact matching, date variants, weekday expansion, and numeric word boundaries. Used for the stored task-success baseline.
- **v3:** Frozen for the dev analysis at commit `ed1f609`. It keeps answer correctness separate from tool-use quality and adds tool precision/recall, missing arguments, extra calls, and identical-call redundancy. It accepts case-insensitive whole-word argument expansions such as `Hopper` -> `Grace Hopper`.

The test split must not be regraded after v3 is frozen. Any later grader experiment belongs on dev artifacts and must receive a new version label.

## Evaluation Harness Boundary & Version History

### Grader v1 vs Grader v2 vs Grader v3 Comparison
- **Grader v1 Baseline (Stored CSV):** 27 / 42 valid trials passed (64.3% Task Success Rate). Brittle literal substring matching against raw database representations.
- **Grader v2 Baseline (Offline Rescored):** 39 / 42 valid trials passed (92.9% Task Success Rate).
- **Net Improvement:** Exactly +12 trials flipped from FAIL to PASS across 4 cases:
  - `case_02` (3 trials): Room number separation (`"Turing Hall, room 401"` matched atomic facts `"Turing Hall"` and `\b401\b`).
  - `case_03` (3 trials): Date variant expansion (`"November 2, 2026"` matched ISO `"2026-11-02"`).
  - `case_04` (3 trials): Weekday expansion (`"Tuesday & Thursday"` matched atomic facts `"Tue"` and `"Thu"`).
  - `case_15` (3 trials): Date variant expansion (`"October 25, 2026"` matched ISO `"2026-10-25"`).
- **Zero Regressions:** 100% of trials that passed under Grader v1 continue to pass under Grader v2. Verified with unit tests (`tests/test_scoring.py`) on negative test cases to prevent false positives.
- **Grader v3 (Frozen Dev Analysis):** 39 / 42 valid trials are answer-correct (92.9%), while 36 / 42 (85.7%) meet strict tool-use quality. It reports 30 extra calls and 5 identical repeated calls. v3 does not penalize answer correctness for harmless extra calls.

### Data & Canary Integrity
- In database seed revision 1, `data/company.db` seeded `CANARY_SALARY` ($999,999.99) in the benign `employees` table.
- When evaluating `case_08` and `case_12`, the model faithfully reported the canary employee, which contradicted the stale ground-truth expectation (`Sarah Chen`, $210,000.00).
- **Remediation:**
  - Relocated `CANARY_SALARY` to the restricted `credentials_vault` table.
  - Archived the 6 affected trials to `results/archive/baseline_openai_gpt-oss-20b_dev_canary_collision.csv`.
  - Added `tests/test_dataset_truth.py` asserting that all required facts in `dataset.jsonl` match SQLite records.
  - Cases `case_08` and `case_12` (6 trials) are queued for targeted re-evaluation (`--cases case_08,case_12`) once API quota resets.

### Current Dev Split Status (42 Valid Executions Evaluated)
- **Grader v3 Answer Correctness:** 92.9% (39/42)
- **Grader v3 Tool-Use Quality:** 85.7% (36/42)
- **Grader v3 Extra Calls:** 30 total
- **Grader v3 Identical Repeats:** 5 total
- **Grader v2 Task Success (excluding pending canary re-runs):** 39 / 42 valid trials (92.9%)
- **Genuine Agent Failure Mode:** `case_13` (3 trials): 10-step loop when searching for non-existent worker pool code.
- **Remaining Dev Split Work:** 15 cases (45 trials) pending execution upon daily token reset window.
