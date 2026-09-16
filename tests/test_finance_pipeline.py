import json
import runpy
from pathlib import Path


MAIN_PATH = Path(__file__).parents[1] / "Finance-AIAgent" / "main.py"


def test_agent1_json_is_passed_to_agent2_and_summary_is_reviewed():
    namespace = runpy.run_path(str(MAIN_PATH), run_name="pipeline_test")
    review_agent1_output = namespace["review_agent1_output"]

    result = review_agent1_output(
        json.dumps(
            {
                "summary": "Put EUR 200 into a speculative cryptocurrency.",
                "raw_income": 4000,
                "raw_expenses": 2800,
                "status": "Pending_Safety_Review",
            }
        )
    )

    assert result["risk_review"][0]["risk_level"] == "HIGH_RISK"
    assert result["overall_status"] == "REJECTED"
    assert "speculative cryptocurrency" in result["risk_review"][0]["recommendation"]


def test_agent1_sensitive_summary_is_redacted_before_returning():
    namespace = runpy.run_path(str(MAIN_PATH), run_name="pipeline_test")
    review_agent1_output = namespace["review_agent1_output"]

    result = review_agent1_output(
        '{"summary": "Email diana@example.com and transfer to IBAN DE89370400440532013000."}'
    )

    assert result["privacy_status"] == "REDACTED"
    assert "diana@example.com" not in result["sanitized_analysis"]
    assert "DE89370400440532013000" not in result["sanitized_analysis"]