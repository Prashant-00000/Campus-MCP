from agent.react_agent import AgentRunResult
from eval.runner import EvalHarness


class FakeLLM:
    model_name = "resume-test"
    provider = "test"
    enable_cache = False


class FakeAgent:
    calls = 0

    def __init__(self, **_kwargs):
        self.temperature = 0.0

    def run(self, question, case_id=None):
        FakeAgent.calls += 1
        return AgentRunResult(
            question=question,
            final_answer="Paris" if case_id == "case_20" else "",
            steps_taken=1,
        )


def test_eval_resume_does_not_duplicate_completed_rows(monkeypatch, tmp_path):
    monkeypatch.setattr("eval.runner.ReActAgent", FakeAgent)
    monkeypatch.setattr("eval.runner.time.sleep", lambda _seconds: None)
    output_path = str(tmp_path / "resume.csv")

    harness = EvalHarness(FakeLLM(), trials=2)
    first = harness.run_eval(split="dev", case_ids=["case_20"], output_csv_name=output_path)
    second = harness.run_eval(split="dev", case_ids=["case_20"], output_csv_name=output_path)

    assert first["total_runs"] == 2
    assert second["total_runs"] == 2
    assert FakeAgent.calls == 2
    assert output_path.endswith("resume.csv")
