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


# Patterns must be anchored on real identifier structure, not on nearby words: this text
# is ordinary budgeting advice full of amounts, dates and words like "tax" or "street".
_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "IBAN",
        "[REDACTED-IBAN]",
        # Country code + check digits, then 4-character groups (optionally space-separated).
        re.compile(r"\b[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]{4}){2,7}(?:[ -]?[A-Z0-9]{1,3})?\b"),
    ),
    (
        "EMAIL",
        "[REDACTED-EMAIL]",
        re.compile(r"\b[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+\b"),
    ),
    (
        "TAX_OR_GOVERNMENT_ID",
        "[REDACTED-GOV-ID]",
        re.compile(
            r"\b(?i:tax|social\s+security|national|government)\s+(?i:identification\s+)?(?i:number|no\.?|id)\b"
            r"\s*[:#-]?\s*(?=[A-Z0-9 -]*\d)[A-Z0-9][A-Z0-9 -]{3,22}[A-Z0-9]\b"
        ),
    ),
    (
        "ACCOUNT",
        "[REDACTED-ACCOUNT]",
        re.compile(r"(?i)\b(?:bank\s+)?(?:account|acct)\s*(?:number|no\.?|#)\s*[:#-]?\s*\d[\d -]{5,18}\d\b"),
    ),
    (
        "TRANSACTION_OR_PAYMENT_REFERENCE",
        "[REDACTED-TRANSACTION-REF]",
        re.compile(r"(?i)\b(?:transaction|payment|transfer)\s*(?:id|reference|ref)\s*[:#-]?\s*(?=[A-Z0-9-]*\d)[A-Z0-9-]{5,40}\b"),
    ),
    (
        "ADDRESS",
        "[REDACTED-ADDRESS]",
        re.compile(
            r"\b(?i:address|residence)\s*[:#-]\s*[^\n;]{8,80}"
            r"|\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}(?:Street|St\.|Avenue|Ave\.|Road|Rd\.|Lane|Drive|Boulevard|Blvd\.)"
            r"|\b[A-Z][a-zäöü]+(?:straße|strasse|weg|platz|gasse)\s+\d{1,4}[a-z]?\b"
        ),
    ),
    (
        "NAME",
        "[REDACTED-NAME]",
        # Label is case-insensitive; the name itself must be capitalised words.
        re.compile(r"\b(?i:full\s+name|customer\s+name|client\s+name|name)\s*[:#-]?\s*['\"]?[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}['\"]?"),
    ),
]

# Phones are checked by digit count in _redact_phones, so amounts and arithmetic survive.
_PHONE = re.compile(r"(?<![\w.,])(?:\+\d{1,3}[ .-]?)?(?:\(\d{1,4}\)[ .-]?)?\d{2,5}(?:[ .-]\d{2,8}){1,4}(?!\.?\d)")


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


def _redact_phones(text: str, redactions: set[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        digits = sum(char.isdigit() for char in value)
        if 9 <= digits <= 15:
            redactions.add("PHONE")
            return "[REDACTED-PHONE]"
        return value

    return _PHONE.sub(replace, text)


def redact_sensitive(text: str) -> tuple[str, list[str]]:
    """Redact known financial and personal identifiers without inventing values."""
    redactions: set[str] = set()
    sanitized = _redact_cards(text, redactions)
    for kind, placeholder, pattern in _PATTERNS:
        sanitized, count = pattern.subn(placeholder, sanitized)
        if count:
            redactions.add(kind)
    sanitized = _redact_phones(sanitized, redactions)
    return sanitized, sorted(redactions)


def _recommendations(analysis: Any) -> list[str]:
    """Every piece of text the user could be shown: the summary plus each recommendation."""
    if not isinstance(analysis, dict):
        return []
    items: list[str] = []
    summary = analysis.get("summary")
    if isinstance(summary, str) and summary.strip():
        items.append(summary)
    values = analysis.get("recommendations", [])
    if isinstance(values, str):
        values = [values]
    if isinstance(values, list):
        items.extend(str(value) for value in values)
    return list(dict.fromkeys(items))


# Signals are matched as whole words/phrases. Bare words such as "rent", "options" or
# "100%" appear in ordinary budgeting advice and must not reject it on their own.
_HIGH_RISK_SIGNALS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bleverag(?:e|ed|ing)\b|\bmargin\s+(?:trading|account|loan)s?\b"), "uses leverage"),
    (
        re.compile(r"\b(?:borrow\w*|loans?|credit\s+cards?)\b[^.]{0,40}\binvest\w*\b"),
        "borrows money to invest",
    ),
    (
        re.compile(r"\bguarantee(?:d|s)?\b[^.]{0,30}\b(?:returns?|profits?|gains?|yields?|income)\b|\brisk[- ]free\b|\bcan(?:'|no)t\s+lose\b"),
        "makes a guaranteed-return claim",
    ),
    (re.compile(r"\bspeculat(?:e|ive|ion|ing)\b"), "is explicitly speculative"),
    (re.compile(r"\bcrypto(?:currency|currencies)?\b|\bbitcoin\b|\bethereum\b"), "involves cryptocurrency speculation"),
    (
        re.compile(r"\b(?:call|put)\s+options?\b|\boptions?\s+(?:trading|contracts?)\b|\b(?:buy|sell|trade|trading|invest\w*\s+in)\s+options\b"),
        "uses a complex, high-risk instrument",
    ),
    (
        re.compile(r"\ball[- ]in\b|\bsingle\s+(?:stock|share|company)\b|\b(?:all|100\s?%)\s+of\s+(?:your|my|the)\s+(?:savings|money|income|cash|portfolio)\s+(?:in|into)\b"),
        "creates excessive concentration",
    ),
    (
        re.compile(
            r"\b(?:use|using|take|taking|dip\s+into|put)\b[^.]{0,20}\b(?:rent|mortgage|bills?|grocery|essential)\w*\b[^.]{0,30}\b(?:invest\w*|trad(?:e|ing)|stocks?)\b"
            r"|\binvest\w*\s+(?:your|my|the)?\s*(?:rent|mortgage|bill|grocery|essential)\w*\s+(?:money|funds|budget)\b"
        ),
        "may invest money needed for essential expenses",
    ),
    (
        re.compile(r"\bunrealistic\b|\bdouble\s+your\s+money\b|\bget\s+rich\s+quick\b|\b(?:[3-9]\d|\d{3,})\s?%\s+(?:annual|yearly|monthly|a\s+year|per\s+year|a\s+month|per\s+month|returns?)\b"),
        "uses an unrealistic return assumption",
    ),
]

_DIVERSIFIED = re.compile(r"\bdiversified\b")
_LOW_COST = re.compile(r"\blow[- ]cost\b")
_RESILIENCE = re.compile(r"\bemergency\s+(?:savings|fund)\b|\bpay\s+down\s+debt\b|\bbudget\w*\b")
_INVESTING = re.compile(r"\binvest\w*\b|\bportfolio\b|\breturns?\b")
_ESSENTIALS = re.compile(r"\b(?:essential|rent|mortgage)\b")


def classify_recommendation(recommendation: str, analysis: Any) -> tuple[str, str]:
    text = recommendation.lower()
    context = json.dumps(analysis, ensure_ascii=False).lower()
    matched = [reason for pattern, reason in _HIGH_RISK_SIGNALS if pattern.search(text)]
    if matched:
        return "HIGH_RISK", "; ".join(dict.fromkeys(matched)) + "."
    if _DIVERSIFIED.search(text) and _LOW_COST.search(text):
        return "LOW_RISK", "Diversification and low costs reduce avoidable concentration and fee risk."
    # Investing is checked before resilience so "emergency fund or investments" is not waved through.
    if _INVESTING.search(text):
        if _ESSENTIALS.search(context):
            return "MODERATE_RISK", "Investment suitability depends on keeping essential expenses funded first."
        return "MODERATE_RISK", "Investment outcomes are uncertain and depend on suitability, horizon, and diversification."
    if _RESILIENCE.search(text):
        return "LOW_RISK", "Prioritizes liquidity or financial resilience rather than speculative returns."
    return "LOW_RISK", "No material high-risk investment signal was detected."


_RISK_RANK = {"LOW_RISK": 0, "MODERATE_RISK": 1, "HIGH_RISK": 2}
_STATUS_RANK = {"APPROVED": 0, "APPROVED_WITH_WARNINGS": 1, "REJECTED": 2}


def _merge_refinement(base: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Accept an LLM refinement only where it is at least as strict as the deterministic review.

    The model may escalate a risk level, add a reason, or add safety notes. It can never
    lower a verdict, drop a redaction, or replace the sanitized text the user is shown.
    """
    merged = json.loads(json.dumps(base))
    proposed = candidate.get("risk_review")
    if isinstance(proposed, list) and len(proposed) == len(merged["risk_review"]):
        for item, suggestion in zip(merged["risk_review"], proposed):
            level = suggestion.get("risk_level") if isinstance(suggestion, dict) else None
            if _RISK_RANK.get(level, -1) > _RISK_RANK[item["risk_level"]]:
                item["risk_level"] = level
                item["reason"] = str(suggestion.get("reason") or item["reason"])

    levels = {item["risk_level"] for item in merged["risk_review"]}
    derived = "REJECTED" if "HIGH_RISK" in levels else ("APPROVED_WITH_WARNINGS" if "MODERATE_RISK" in levels or base["safety_notes"] else "APPROVED")
    suggested = candidate.get("overall_status")
    merged["overall_status"] = max(
        (base["overall_status"], derived, suggested if suggested in _STATUS_RANK else "APPROVED"),
        key=_STATUS_RANK.__getitem__,
    )

    notes = candidate.get("safety_notes")
    if isinstance(notes, list):
        merged["safety_notes"] = list(dict.fromkeys([*base["safety_notes"], *(redact_sensitive(str(n))[0] for n in notes)]))
    if merged["overall_status"] == "REJECTED" and base["overall_status"] != "REJECTED":
        merged["safety_notes"].append("High-risk recommendations require removal or qualified human review before presentation.")
    return merged


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
            if not isinstance(candidate, dict):
                return deterministic_result
            return _merge_refinement(deterministic_result, candidate)
        except Exception:
            return deterministic_result