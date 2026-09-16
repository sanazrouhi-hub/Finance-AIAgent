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