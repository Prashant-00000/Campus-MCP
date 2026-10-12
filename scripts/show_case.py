"""Print tool calls and final answers for one case across audit transcripts."""

import glob
import json
import sys


if len(sys.argv) != 2:
    raise SystemExit("Usage: python scripts/show_case.py CASE_ID")

case_id = sys.argv[1]
sys.stdout.reconfigure(encoding="utf-8")

for path in sorted(glob.glob("audit_logs/*_openai_gpt-oss-20b.jsonl")):
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if record.get("case_id") != case_id:
                continue
            if record.get("tool_name"):
                result_text = record.get("result_full", record.get("result_preview", ""))
                print(
                    f"[{record['session_id'][-6:]}] step {record['step']}: "
                    f"{record['tool_name']} {record['arguments']} -> "
                    f"error={record['is_error']} | {result_text!r}"
                )
            elif record.get("event_type") == "session_end":
                print(f"[{record['session_id'][-6:]}] ANSWER: {record['final_answer']!r}\n")
