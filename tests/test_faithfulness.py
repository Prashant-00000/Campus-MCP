from eval.faithfulness import assess_faithfulness, extract_claim_tokens


def test_faithfulness_accepts_claims_present_in_tool_evidence():
    answer = "Dr. Alan Turing is Professor & Chair in CS, office 401, email aturing@univ.edu."
    evidence = [
        "name: Dr. Alan Turing; title: Professor & Chair; department: CS; office: 401; email: aturing@univ.edu"
    ]

    result = assess_faithfulness(answer, evidence)
    assert result["unsupported_claims"] == []
    assert result["unsupported_claim_rate"] == 0.0


def test_faithfulness_flags_unsupported_specific_claims():
    answer = "Dr. Alan Turing works with Electrical Engineering and has office CS 203."
    evidence = ["name: Dr. Alan Turing; department: CS; office_hours: Mon/Wed 2-4 PM"]

    result = assess_faithfulness(answer, evidence)
    assert "Electrical Engineering" in result["unsupported_claims"]
    assert "CS 203" in result["unsupported_claims"]
    assert result["unsupported_claim_rate"] > 0


def test_faithfulness_normalizes_numbers_underscores_and_weekdays():
    answer = "Revenue was $19,498.00. Product ID 503 was highest on Monday & Wednesday."
    evidence = [
        "total_revenue: 19498.0; product_id: 503; office_hours: Mon/Wed 2-4 PM"
    ]

    result = assess_faithfulness(answer, evidence)
    assert result["unsupported_claims"] == []


def test_faithfulness_does_not_hide_unrelated_expansions():
    result = assess_faithfulness(
        "The department researches Artificial Intelligence.",
        ["department: CS; research_area: Theory of Computation"],
    )
    assert "Artificial Intelligence" in result["unsupported_claims"]


def test_claim_extraction_deduplicates_tokens():
    assert set(extract_claim_tokens("Room 401, then room 401; email a@b.co")) == {"401", "a@b.co"}
