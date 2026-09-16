import json
import runpy
from pathlib import Path


MAIN_PATH = Path(__file__).parents[1] / "main.py"


def _pipeline():
    return runpy.run_path(str(MAIN_PATH), run_name="pipeline_test")


def test_agent1_json_is_passed_to_agent2_and_summary_is_reviewed():
    review_agent1_output = _pipeline()["review_agent1_output"]

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
    review_agent1_output = _pipeline()["review_agent1_output"]

    result = review_agent1_output(
        '{"summary": "Email diana@example.com and transfer to IBAN DE89370400440532013000."}'
    )

    assert result["privacy_status"] == "REDACTED"
    assert "diana@example.com" not in result["sanitized_analysis"]
    assert "DE89370400440532013000" not in result["sanitized_analysis"]


def test_summary_and_each_recommendation_are_reviewed_separately():
    review_agent1_output = _pipeline()["review_agent1_output"]

    result = review_agent1_output(
        {
            "summary": "You are 700 EUR ahead of your goal.",
            "recommendations": ["Move 400 EUR to your emergency fund", "Buy bitcoin with the rest"],
        }
    )

    levels = [item["risk_level"] for item in result["risk_review"]]
    assert levels == ["LOW_RISK", "LOW_RISK", "HIGH_RISK"]
    assert result["overall_status"] == "REJECTED"


def test_approved_content_returns_sanitized_advice_only_when_approved():
    namespace = _pipeline()
    review, approved_content = namespace["review_agent1_output"], namespace["approved_content"]

    ok = review({"summary": "Nice month.", "recommendations": ["Keep a budget for groceries"]})
    assert ok["overall_status"] in ("APPROVED", "APPROVED_WITH_WARNINGS")
    assert approved_content(ok) == {"summary": "Nice month.", "recommendations": ["Keep a budget for groceries"]}

    blocked = review({"summary": "Nice month.", "recommendations": ["Go all-in on a single stock"]})
    assert approved_content(blocked) is None


def test_expense_categories_are_redacted_before_reaching_agent1():
    sanitize_expenses = _pipeline()["sanitize_expenses"]

    clean = sanitize_expenses({"rent": 900, "transfer to diana@example.com": 50, "loan to bob@example.com": 25})

    assert clean == {"rent": 900, "transfer to [REDACTED-EMAIL]": 50, "loan to [REDACTED-EMAIL]": 25}
    assert not any("@example.com" in name for name in clean)
