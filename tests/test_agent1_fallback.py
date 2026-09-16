"""Model fallback when Gemini quota runs out. Uses a fake client; no API calls or quota used."""

import json

import pytest
from google.genai import errors

import agent_1

DAILY_429 = {
    "error": {
        "code": 429,
        "status": "RESOURCE_EXHAUSTED",
        "message": "Quota exceeded for metric: generate_content_free_tier_requests",
        "details": [
            {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "35s"},
        ],
    }
}


class FakeModels:
    def __init__(self, behaviour):
        self.behaviour = behaviour  # model name -> response text, or an exception to raise
        self.calls = []

    def generate_content(self, model, contents, config=None):
        self.calls.append(model)
        outcome = self.behaviour.get(model, errors.ClientError(404, {"error": {"code": 404, "message": "not found"}}))
        if isinstance(outcome, Exception):
            raise outcome
        return type("Response", (), {"text": outcome})()


@pytest.fixture
def fake_gemini(monkeypatch):
    def install(behaviour):
        models = FakeModels(behaviour)
        monkeypatch.setattr(agent_1, "_client", lambda: type("Client", (), {"models": models})())
        monkeypatch.setattr(agent_1, "GEMINI_MODEL", "primary")
        monkeypatch.setattr(agent_1, "GEMINI_FALLBACK_MODELS", ["backup-a", "backup-b"])
        monkeypatch.setattr(agent_1, "_exhausted_until", {})
        monkeypatch.setattr(agent_1.time, "sleep", lambda _: None)
        return models

    return install


def test_daily_quota_falls_back_to_next_model_and_reports_it(fake_gemini):
    advice = json.dumps({"summary": "Fine month.", "recommendations": ["Keep a budget"]})
    models = fake_gemini({"primary": errors.ClientError(429, DAILY_429), "backup-a": advice})

    payload = json.loads(agent_1.ai_financial_agent(2000, 300, {"rent": 900}))

    assert payload["model"] == "backup-a"
    assert payload["recommendations"] == ["Keep a budget"]
    assert models.calls == ["primary", "backup-a"]


def test_exhausted_model_is_skipped_on_later_requests(fake_gemini):
    models = fake_gemini({"primary": errors.ClientError(429, DAILY_429), "backup-a": "ok"})

    agent_1.ask_financial_agent("q1", {})
    agent_1.ask_financial_agent("q2", {})

    assert models.calls == ["primary", "backup-a", "backup-a"]


def test_all_models_exhausted_raises_clear_quota_error(fake_gemini):
    quota = errors.ClientError(429, DAILY_429)
    fake_gemini({"primary": quota, "backup-a": quota, "backup-b": quota})

    with pytest.raises(agent_1.GeminiQuotaExhausted, match="quota is used up"):
        agent_1.ask_financial_agent("q", {})


def test_overloaded_model_is_retried_once_then_falls_back(fake_gemini):
    overloaded = errors.ServerError(503, {"error": {"code": 503, "message": "high demand"}})
    models = fake_gemini({"primary": overloaded, "backup-a": "ok"})

    assert agent_1.ask_financial_agent("q", {}) == "ok"
    assert models.calls == ["primary", "primary", "backup-a"]


def test_non_retryable_error_is_raised_immediately(fake_gemini):
    bad_key = errors.ClientError(401, {"error": {"code": 401, "message": "invalid key"}})
    models = fake_gemini({"primary": bad_key, "backup-a": "ok"})

    with pytest.raises(errors.ClientError):
        agent_1.ask_financial_agent("q", {})
    assert models.calls == ["primary"]
