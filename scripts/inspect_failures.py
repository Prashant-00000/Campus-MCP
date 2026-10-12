import json, glob, sys
sys.stdout.reconfigure(encoding="utf-8")
ids = sys.argv[1:] or ["case_02", "case_03", "case_04", "case_08", "case_12", "case_15"]
ds = {}
for line in open("eval/dataset.jsonl", encoding="utf-8"):
    d = json.loads(line)
    ds[d.get("case_id") or d.get("id")] = d
logs = sorted(glob.glob("audit_logs/20261012T05*_openai_gpt-oss-20b.jsonl"))
for cid in ids:
    print("=" * 70, "\n" + cid)
    print("DATASET:", json.dumps(ds.get(cid), ensure_ascii=False)[:600])
    for p in logs:
        for line in open(p, encoding="utf-8"):
            e = json.loads(line)
            if e.get("case_id") == cid and e.get("event_type") == "session_end":
                print("ANSWER:", repr(e["final_answer"])[:500])
