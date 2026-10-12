"""
Level 2: Run 5 easy questions against ONE real model and read the audit log.
This is the first real-model smoke test. Expect surprises.

Usage:
    # Set in .env first:
    # LLM_PROVIDER=groq
    # LLM_MODEL=llama-3.1-8b-instant
    # GROQ_API_KEY=gsk_...

    python scripts/level2_smoke.py

What to look for in the output:
  - Did the model pick the right tool?
  - Did it pass reasonable arguments?
  - Did it ever call NO tool when one was needed (or vice versa)?
  - Does the final answer contain the required facts?
  - How long did it take (latency)?

Write down any surprise in FAILURES.md before you forget.
"""

import os
import sys
import json
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.llm import provider_from_env
from agent.react_agent import ReActAgent
from agent.audit_logger import AuditLogger, check_contamination_guard
from data.init_databases import init_college_db, init_company_db, init_github_db

EASY_QUESTIONS = [
    {
        "id": "L2-01",
        "question": "What is the contact email and chair for the CS department?",
        "expected_tool": "get_department",
        "required_facts": ["cs-chair@univ.edu", "turing"],
    },
    {
        "id": "L2-02",
        "question": "List the upcoming campus events in the workshop category.",
        "expected_tool": "list_events",
        "required_facts": ["hackathon"],
    },
    {
        "id": "L2-03",
        "question": "What algorithms courses are available?",
        "expected_tool": "search_courses",
        "required_facts": ["algorithm"],
    },
    {
        "id": "L2-04",
        "question": "What is the capital of France?",
        "expected_tool": None,  # Should answer directly, NO tool call
        "required_facts": ["paris"],
    },
    {
        "id": "L2-05",
        "question": "Find information about professor Grace Hopper.",
        "expected_tool": "get_faculty",
        "required_facts": ["hopper"],
    },
]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    import argparse
    parser = argparse.ArgumentParser(description="Level 2 Smoke Test")
    parser.add_argument("--no-cache", action="store_true", help="Disable LLM caching")
    args, _ = parser.parse_known_args()
    if args.no_cache:
        os.environ["LLM_CACHE"] = "0"

    print("Initializing databases...")
    init_college_db()
    init_company_db()
    init_github_db()

    print("Building LLM from environment...")
    try:
        llm = provider_from_env()
    except EnvironmentError as e:
        print(f"\nERROR: {e}")
        print("\nCreate a .env file with:")
        print("  LLM_PROVIDER=groq")
        print("  LLM_MODEL=llama-3.1-8b-instant")
        print("  GROQ_API_KEY=gsk_...")
        sys.exit(1)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    clean_model_id = llm.model_name.replace('/', '_').replace(':', '_')
    audit_path = os.path.join("audit_logs", f"{run_id}_{clean_model_id}.jsonl")
    check_contamination_guard(audit_path, llm.model_name)
    logger = AuditLogger(log_path=audit_path, model=llm.model_name)
    agent = ReActAgent(llm=llm, audit_logger=logger)

    print(f"\n{'='*70}")
    print(f"LEVEL 2 SMOKE TEST: {llm.provider}/{llm.model_name}")
    print(f"Audit log: {audit_path}")
    print(f"Cache enabled: {llm.enable_cache}")
    print(f"{'='*70}\n")

    results = []
    for q in EASY_QUESTIONS:
        print(f"--- {q['id']}: {q['question'][:60]}...")
        res = agent.run(q["question"], case_id=q["id"])

        tools_called = [tc.tool_name for tc in res.tool_calls]
        answer_lower = (
            res.final_answer.lower()
            .replace('\u2011', '-')
            .replace('\u2013', '-')
            .replace('\u202f', ' ')
            .replace('\xa0', ' ')
        )

        tool_ok = (
            (q["expected_tool"] is None and len(tools_called) == 0)
            or (q["expected_tool"] is not None and q["expected_tool"] in tools_called)
        )
        facts_ok = all(f.lower() in answer_lower for f in q["required_facts"])

        status = "✅ PASS" if (tool_ok and facts_ok) else "❌ FAIL"
        safe_answer = res.final_answer[:150].encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8")
        print(f"  Tool called : {tools_called or '(none)'}")
        print(f"  Expected    : {q['expected_tool'] or '(none)'}")
        print(f"  Facts found : {q['required_facts']}")
        print(f"  Answer      : {safe_answer}")
        print(f"  Latency     : {round(res.total_latency_ms)}ms")
        print(f"  Result      : {status}")
        if not tool_ok:
            print(f"  ⚠️  TOOL MISMATCH — write this in FAILURES.md!")
        if not facts_ok:
            missing = [f for f in q["required_facts"] if f.lower() not in answer_lower]
            print(f"  ⚠️  MISSING FACTS: {missing} — check grading rules or model behavior.")
        print()

        time.sleep(2.0)

        results.append({
            "id": q["id"],
            "question": q["question"],
            "expected_tool": q["expected_tool"],
            "tools_called": tools_called,
            "tool_ok": tool_ok,
            "facts_ok": facts_ok,
            "latency_ms": round(res.total_latency_ms),
            "answer_excerpt": res.final_answer[:200],
        })

    passed = sum(1 for r in results if r["tool_ok"] and r["facts_ok"])
    print(f"\n{'='*70}")
    print(f"SUMMARY: {passed}/{len(results)} passed")
    print(f"Audit log written to: {audit_path}")
    print(f"\nNext steps:")
    print(f"  1. Read the audit log for surprises")
    print(f"  2. Note anything unexpected in FAILURES.md")
    print(f"  3. If >=4/5 pass, proceed to: python scripts/run_eval.py")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
