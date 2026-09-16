"""Deterministic privacy scan and financial recommendation review."""

from __future__ import annotations

import json
import os
import re
from typing import Any


SYSTEM_PROMPT = """You are Agent 2, a Privacy & Risk Guard for a personal finance assistant.
The input has already been scanned and sensitive values are placeholders. Never infer,
restore, or repeat a private value. Return only JSON with keys privacy_status,
redactions, risk_review, overall_status, safety_notes, and sanitized_analysis.
Classify every recommendation as LOW_RISK, MODERATE_RISK, or HIGH_RISK. Flag leverage,
borrowing to invest, guaranteed returns, speculation, concentration, cryptocurrency,
options, essential-expense money, and unrealistic return assumptions. Never call an
investment guaranteed or completely safe. This is a safety review, not personal advice.
"""


_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "IBAN",
        "[REDACTED-IBAN]",
        re.compile(r"\b[A-Z]{2}\s?\d{2}(?:[ -]?[A-Z0-9]){11,30}\b", re.IGNORECASE),
    ),
    (
        "EMAIL",
        "[REDACTED-EMAIL]",
        re.compile(r"\b[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+\b"),
    ),
    (
        "PHONE",
        "[REDACTED-PHONE]",
        re.compile(r"(?<!\w)(?:\+?\d[\d ().-]{8,}\d)(?!\w)"),
    ),
    (
        "TAX_OR_GOVERNMENT_ID",
        "[REDACTED-GOV-ID]",
        re.compile(r"(?i)\b(?:tax|social security|national id|government id)\s*(?:number|no\.?|id)?\s*[:#-]?\s*[A-Z0-9 -]{5,24}\b"),
    ),
    (
        "ACCOUNT",
        "[REDACTED-ACCOUNT]",
        re.compile(r"(?i)\b(?:bank )?(?:account|acct)\s*(?:number|no\.?|#)?\s*[:#-]?\s*\d[\d -]{5,18}\b"),
    ),
    (
        "TRANSACTION_OR_PAYMENT_REFERENCE",
        "[REDACTED-TRANSACTION-REF]",
        re.compile(r"(?i)\b(?:transaction|payment|transfer)\s*(?:id|reference|ref)\s*[:#-]?\s*[A-Z0-9-]{5,40}\b"),
    ),
    (
        "ADDRESS",
        "[REDACTED-ADDRESS]",
        re.compile(r"(?i)\b(?:address|street|residence)\s*[:#-]?\s*[^\n,;]{8,80}"),
    ),
    (
        "NAME",
        "[REDACTED-NAME]",
        re.compile(r"(?i)\b(?:full name|customer name|client name|name)\s*[:#-]?\s*['\"]?[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}['\"]?"),
    ),
]


def _luhn_valid(value: str) -> bool:
    digits = [int(char) for char in value if char.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _redact_cards(text: str, redactions: set[str]) -> str:
    card_pattern = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")

    def replace(match: re.Match[str]) -> str:
        if _luhn_valid(match.group(0)):
            redactions.add("CARD")
            return "[REDACTED-CARD]"
        return match.group(0)

    return card_pattern.sub(replace, text)


def redact_sensitive(text: str) -> tuple[str, list[str]]:
    """Redact known financial and personal identifiers without inventing values."""
    redactions: set[str] = set()
    sanitized = _redact_cards(text, redactions)
    for kind, placeholder, pattern in _PATTERNS:
        sanitized, count = pattern.subn(placeholder, sanitized)
        if count:
            redactions.add(kind)
    return sanitized, sorted(redactions)


def _recommendations(analysis: Any) -> list[str]:
    if isinstance(analysis, dict):
        values = analysis.get("recommendations", [])
        if isinstance(values, list):
            return [str(value) for value in values]
        if isinstance(values, str):
            return [values]
    return []


def classify_recommendation(recommendation: str, analysis: Any) -> tuple[str, str]:
    text = recommendation.lower()
    context = json.dumps(analysis, ensure_ascii=False).lower()
    high_signals = {
        "leverage": "uses leverage",
        "borrow": "borrows money to invest",
        "guaranteed": "makes a guaranteed-return claim",
        "guarantee": "makes a guaranteed-return claim",
        "speculative": "is explicitly speculative",
        "cryptocurrency": "involves cryptocurrency speculation",
        "crypto": "involves cryptocurrency speculation",
        "options": "uses a complex, high-risk instrument",
        "all-in": "creates excessive concentration",
        "single stock": "creates excessive concentration",
        "100%": "creates excessive concentration",
        "essential": "may invest money needed for essential expenses",
        "rent": "may invest money needed for essential expenses",
        "unrealistic": "uses an unrealistic return assumption",
        "double your money": "uses an unrealistic return assumption",
    }
    matched = [reason for signal, reason in high_signals.items() if signal in text]
    if matched:
        return "HIGH_RISK", "; ".join(dict.fromkeys(matched)) + "."
    if "diversified" in text and ("low-cost" in text or "low cost" in text):
        return "LOW_RISK", "Diversification and low costs reduce avoidable concentration and fee risk."
    if any(term in text for term in ("emergency savings", "emergency fund", "pay down debt", "budget")):
        return "LOW_RISK", "Prioritizes liquidity or financial resilience rather than speculative returns."
    if "return" in text or "invest" in text or "portfolio" in text:
        if any(term in context for term in ("essential", "rent", "mortgage")):
            return "MODERATE_RISK", "Investment suitability depends on keeping essential expenses funded first."
        return "MODERATE_RISK", "Investment outcomes are uncertain and depend on suitability, horizon, and diversification."
    return "LOW_RISK", "No material high-risk investment signal was detected."


def _deterministic_review(analysis: Any, sanitized_analysis: str, redactions: list[str]) -> dict[str, Any]:
    risk_review = []
    for recommendation in _recommendations(analysis):
        risk_level, reason = classify_recommendation(recommendation, analysis)
        risk_review.append({"recommendation": redact_sensitive(recommendation)[0], "risk_level": risk_level, "reason": reason})

    high_risk = any(item["risk_level"] == "HIGH_RISK" for item in risk_review)
    warnings: list[str] = []
    if redactions:
        warnings.append("Sensitive information was redacted and must not be restored or shared.")
    if high_risk:
        warnings.append("High-risk recommendations require removal or qualified human review before presentation.")
    elif any(item["risk_level"] == "MODERATE_RISK" for item in risk_review):
        warnings.append("Moderate-risk recommendations need suitability, time-horizon, and diversification checks.")
    if warnings:
        warnings.insert(0, "This review is a safety checkpoint, not financial advice.")
    return {
        "privacy_status": "REDACTED" if redactions else "PASS",
        "redactions": redactions,
        "risk_review": risk_review,
        "overall_status": "REJECTED" if high_risk else ("APPROVED_WITH_WARNINGS" if warnings else "APPROVED"),
        "safety_notes": warnings,
        "sanitized_analysis": sanitized_analysis,
    }


class PrivacyRiskGuard:
    """Agent 2 policy engine with an optional LLM refinement step."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def review(self, analysis: Any) -> dict[str, Any]:
        raw_text = analysis if isinstance(analysis, str) else json.dumps(analysis, ensure_ascii=False)
        sanitized_text, redactions = redact_sensitive(raw_text)
        parsed_analysis: Any = analysis
        if isinstance(analysis, str):
            try:
                parsed_analysis = json.loads(analysis)
            except json.JSONDecodeError:
                parsed_analysis = {"analysis": analysis}
        result = _deterministic_review(parsed_analysis, sanitized_text, redactions)
        if os.getenv("OPENAI_API_KEY"):
            result = self._llm_refinement(result)
        return result

    def _llm_refinement(self, deterministic_result: dict[str, Any]) -> dict[str, Any]:
        try:
            from openai import OpenAI

            client = OpenAI()
            response = client.chat.completions.create(
                model=self.model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(deterministic_result, ensure_ascii=False)},
                ],
            )
            candidate = json.loads(response.choices[0].message.content or "{}")
            candidate["sanitized_analysis"], _ = redact_sensitive(str(candidate.get("sanitized_analysis", deterministic_result["sanitized_analysis"])))
            candidate["redactions"] = sorted(set(deterministic_result["redactions"]) | set(candidate.get("redactions", [])))
            candidate["privacy_status"] = "REDACTED" if candidate["redactions"] else "PASS"
            return candidate
        except Exception:
            return deterministic_result