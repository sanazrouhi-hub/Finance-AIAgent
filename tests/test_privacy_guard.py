import json

import pytest

from agent2.privacy_guard import PrivacyRiskGuard, redact_sensitive


def test_clean_input_passes_and_preserves_financial_information():
    result = PrivacyRiskGuard().review({"savings": 1200, "recommendations": ["Keep EUR 600 as emergency savings"]})
    assert result["privacy_status"] == "PASS"
    assert result["redactions"] == []
    assert result["risk_review"][0]["risk_level"] == "LOW_RISK"
    assert '"savings": 1200' in result["sanitized_analysis"]


def test_sensitive_values_are_redacted_and_not_repeated():
    raw = "IBAN DE89370400440532013000, card 4111 1111 1111 1111, email diana@example.com"
    sanitized, kinds = redact_sensitive(raw)
    assert "DE89370400440532013000" not in sanitized
    assert "4111 1111 1111 1111" not in sanitized
    assert "diana@example.com" not in sanitized
    assert {"IBAN", "CARD", "EMAIL"}.issubset(kinds)


@pytest.mark.parametrize(
    "text",
    [
        "Cutting 50 EUR brings groceries down to 270 EUR this month.",
        "Your budget: 2400 - 1300 = 1100 EUR left.",
        "You have 1,050.00 EUR remaining after 2400.0 EUR income.",
        "Consider a tax-advantaged account for long-term savings.",
        "Street food is a cheap lunch option.",
        "Name your savings goal so it feels concrete.",
        "Pay utilities on 15.03.2026 and rent on 2026-04-01.",
        "Move 400 EUR into your savings account 12 days before payday.",
    ],
)
def test_ordinary_budget_text_is_not_redacted(text):
    sanitized, kinds = redact_sensitive(text)
    assert kinds == []
    assert sanitized == text


@pytest.mark.parametrize(
    "text, kind",
    [
        ("IBAN DE89 3704 0044 0532 0130 00", "IBAN"),
        ("call me on +49 30 1234567", "PHONE"),
        ("mobile 0151 23456789", "PHONE"),
        ("phone 555-123-4567", "PHONE"),
        ("tax id: 12 345 678 901", "TAX_OR_GOVERNMENT_ID"),
        ("account number 1234 5678 90", "ACCOUNT"),
        ("payment reference: PAY-88231-XK", "TRANSACTION_OR_PAYMENT_REFERENCE"),
        ("address: 22 Baker Street, London", "ADDRESS"),
        ("I live at 221 Baker Street", "ADDRESS"),
        ("wohnhaft Hauptstraße 12", "ADDRESS"),
        ("Name: Diana Rossi", "NAME"),
    ],
)
def test_real_identifiers_are_still_redacted(text, kind):
    _, kinds = redact_sensitive(text)
    assert kind in kinds


def test_high_risk_crypto_is_rejected():
    result = PrivacyRiskGuard().review({"recommendations": ["Put EUR 200 into a speculative cryptocurrency"]})
    assert result["risk_review"][0]["risk_level"] == "HIGH_RISK"
    assert result["overall_status"] == "REJECTED"


def test_mixed_recommendations_are_classified_individually():
    result = PrivacyRiskGuard().review(
        {"recommendations": [
            "Keep EUR 600 as emergency savings",
            "Invest EUR 400 monthly into a diversified low-cost portfolio",
            "Borrow to invest in options with guaranteed returns",
        ]}
    )
    assert [item["risk_level"] for item in result["risk_review"]] == ["LOW_RISK", "LOW_RISK", "HIGH_RISK"]


def test_investing_is_not_waved_through_by_a_resilience_keyword():
    result = PrivacyRiskGuard().review({"recommendations": ["Put the surplus into an emergency fund or long-term investments"]})
    assert result["risk_review"][0]["risk_level"] == "MODERATE_RISK"


def _refine_with(monkeypatch, analysis, llm_reply):
    import agent2.privacy_guard as guard_module

    base = guard_module._deterministic_review(analysis, json.dumps(analysis), [])
    monkeypatch.setattr(guard_module.PrivacyRiskGuard, "_llm_refinement", lambda self, r: guard_module._merge_refinement(r, llm_reply))
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    return base, PrivacyRiskGuard().review(analysis)


def test_llm_refinement_cannot_approve_a_rejected_review(monkeypatch):
    analysis = {"recommendations": ["Buy bitcoin with your savings"]}
    lenient = {
        "overall_status": "APPROVED",
        "risk_review": [{"risk_level": "LOW_RISK", "reason": "Looks fine"}],
        "safety_notes": [],
        "sanitized_analysis": "Buy more bitcoin, it is guaranteed!",
    }
    base, result = _refine_with(monkeypatch, analysis, lenient)

    assert result["overall_status"] == "REJECTED"
    assert result["risk_review"][0]["risk_level"] == "HIGH_RISK"
    assert result["sanitized_analysis"] == base["sanitized_analysis"]


def test_llm_refinement_can_escalate_risk(monkeypatch):
    analysis = {"recommendations": ["Keep a budget for groceries"]}
    stricter = {"overall_status": "REJECTED", "risk_review": [{"risk_level": "HIGH_RISK", "reason": "Model found a concern"}]}
    _, result = _refine_with(monkeypatch, analysis, stricter)

    assert result["overall_status"] == "REJECTED"
    assert result["risk_review"][0] == {
        "recommendation": "Keep a budget for groceries",
        "risk_level": "HIGH_RISK",
        "reason": "Model found a concern",
    }


@pytest.mark.parametrize(
    "text",
    [
        "Since rent (900 EUR) is fixed, trim groceries instead.",
        "You have several options for your surplus.",
        "You covered 100% of your goal this month.",
        "Your current expenses are well within budget.",
        "Consider investigating cheaper transport options.",
        "Rental income is not included in these figures.",
    ],
)
def test_ordinary_budget_language_is_not_high_risk(text):
    result = PrivacyRiskGuard().review({"recommendations": [text]})
    assert result["risk_review"][0]["risk_level"] != "HIGH_RISK", result["risk_review"][0]["reason"]
    assert result["overall_status"] != "REJECTED"


@pytest.mark.parametrize(
    "text, reason",
    [
        ("Use your rent money to invest in stocks", "essential expenses"),
        ("Take out a loan and invest it in index funds", "borrows money"),
        ("Buy call options on tech companies", "complex, high-risk instrument"),
        ("Put 100% of your savings into one company", "concentration"),
        ("This fund offers guaranteed returns", "guaranteed-return"),
        ("Aim for 40% annual returns", "unrealistic return"),
        ("Use leverage to grow faster", "leverage"),
    ],
)
def test_genuinely_risky_advice_is_still_flagged(text, reason):
    item = PrivacyRiskGuard().review({"recommendations": [text]})["risk_review"][0]
    assert item["risk_level"] == "HIGH_RISK"
    assert reason in item["reason"]