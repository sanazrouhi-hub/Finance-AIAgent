import json
import os
import re
import threading
import time
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

# Free-tier quotas are counted per model, so when one model is exhausted the next one
# in this list still has its own allowance.
GEMINI_FALLBACK_MODELS = [
    name.strip()
    for name in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash,gemini-2.5-flash,gemini-flash-lite-latest").split(",")
    if name.strip() and name.strip() != GEMINI_MODEL
]


class GeminiQuotaExhausted(RuntimeError):
    """Every configured Gemini model is out of quota right now."""

# Structured output so Agent 2 can review each recommendation on its own.
_ADVICE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "recommendations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "recommendations"],
}

_OVERLOADED_STATUS = {500, 502, 503, 504}
_DAILY_QUOTA_COOLDOWN = 60 * 60  # re-check a daily-exhausted model after an hour

_exhausted_until: dict[str, float] = {}
_exhausted_lock = threading.Lock()


@lru_cache(maxsize=1)
def _client():
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")
    return genai.Client(api_key=api_key)


def _quota_cooldown(exc: Exception) -> float:
    """Seconds to skip a model after a 429: an hour for daily quotas, else the server's retry hint."""
    text = str(exc)
    if "PerDay" in text:
        return _DAILY_QUOTA_COOLDOWN
    delay = re.search(r"retryDelay['\"]?:\s*['\"](\d+(?:\.\d+)?)s", text)
    return float(delay.group(1)) if delay else 60.0


def _generate(prompt: str, schema: dict | None = None) -> tuple[str, str]:
    """Call Gemini and return (text, model used).

    A model that is out of quota is skipped for its cooldown and the next fallback is tried,
    so one exhausted free-tier model does not take the app down. Overload errors (5xx) get
    one short retry on the same model before moving on.
    """
    from google.genai import errors, types

    config = None
    if schema is not None:
        config = types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=schema)

    models = [GEMINI_MODEL, *GEMINI_FALLBACK_MODELS]
    last_error: Exception | None = None
    for model in models:
        with _exhausted_lock:
            if _exhausted_until.get(model, 0) > time.monotonic():
                continue
        for attempt in range(2):
            try:
                response = _client().models.generate_content(model=model, contents=prompt, config=config)
                return response.text or "", model
            except errors.APIError as exc:
                last_error = exc
                if exc.code == 429:
                    with _exhausted_lock:
                        _exhausted_until[model] = time.monotonic() + _quota_cooldown(exc)
                    break
                if exc.code == 404:  # model not available to this key
                    with _exhausted_lock:
                        _exhausted_until[model] = time.monotonic() + 24 * 60 * 60
                    break
                if exc.code in _OVERLOADED_STATUS and attempt == 0:
                    time.sleep(2)
                    continue
                if exc.code in _OVERLOADED_STATUS:
                    break
                raise

    with _exhausted_lock:
        all_exhausted = all(_exhausted_until.get(m, 0) > time.monotonic() for m in models)
    if all_exhausted:
        raise GeminiQuotaExhausted(
            "Gemini quota is used up (or the model is unavailable) for every configured model: "
            f"{', '.join(models)}. Free-tier limits reset daily; try again later, or use a key with billing enabled."
        ) from last_error
    raise last_error or RuntimeError("Gemini returned no response.")


def calculate_financials(income: float, total_expenses: float, saving_goal: float) -> dict:
    remaining = income - total_expenses
    extra_or_shortfall = remaining - saving_goal
    return {
        "remaining": remaining,
        "saving_goal": saving_goal,
        "extra_or_shortfall": extra_or_shortfall,
        "status_code": 1 if extra_or_shortfall > 0 else (2 if remaining >= saving_goal else 3)
    }


def get_valid_float(prompt, minimum=0.0, allow_equal=True):
    while True:
        try:
            value = float(input(prompt))
            if value < minimum or (not allow_equal and value == minimum):
                print(f"❌ Please enter a number {'≥' if allow_equal else 'greater than'} {minimum:g}!")
                continue
            return value
        except ValueError:
            print("❌ Invalid input! Please enter a valid number.")

def get_valid_category(prompt):
    while True:
        category = input(prompt).strip()
        if not category:
            print("❌ Category cannot be empty!")
            continue
        if category.isdigit():
            print("❌ Category name should be text, not a number!")
            continue
        return category

def get_user_inputs():
    print("\n==========================================")
    print("      💰 DAILY FINANCIAL ASSISTANT        ")
    print("==========================================")

    income = get_valid_float("\n👉 Enter your total monthly income (EUR): ", allow_equal=False)
    saving_goal = get_valid_float("👉 Enter your target saving goal for THIS MONTH (EUR): ")

    expenses = {}
    print("\n📝 Enter your daily expenses (type 'done' when finished):")

    while True:
        category = get_valid_category("   • Expense category (e.g. food, rent) or 'done': ")
        if category.lower() == 'done':
            break
        amount = get_valid_float(f"     Amount for '{category}' (EUR): ")
        expenses[category] = amount

    return income, saving_goal, expenses


def ai_financial_agent(income, saving_goal, expenses):
    total_spent = sum(expenses.values())

    calc_res = calculate_financials(income, total_spent, saving_goal)

    prompt = (
        f"User Financial Summary:\n"
        f"- Monthly Income: {income} EUR\n"
        f"- Total Expenses: {total_spent} EUR ({expenses})\n"
        f"- Saving Goal: {saving_goal} EUR\n"
        f"- Calculated Remaining: {calc_res['remaining']} EUR\n"
        f"- Goal Extra/Shortfall: {calc_res['extra_or_shortfall']} EUR\n\n"
        f"Write a brief, encouragement-focused daily financial update for the user based on these numbers.\n"
        f"Return JSON: 'summary' is the short update (plain text, no markdown); "
        f"'recommendations' is 1-4 separate, concrete, practical actions, one per string."
    )

    text, model = _generate(prompt, schema=_ADVICE_SCHEMA)
    try:
        advice = json.loads(text)
    except json.JSONDecodeError:
        advice = {"summary": text}
    if not isinstance(advice, dict):
        advice = {"summary": text}

    proposal = {
        "summary": str(advice.get("summary", "")),
        "recommendations": [str(item) for item in advice.get("recommendations", []) if str(item).strip()],
        "model": model,
        "raw_income": income,
        "raw_expenses": total_spent,
        "status": "Pending_Safety_Review"
    }
    return json.dumps(proposal, ensure_ascii=False)


def ask_financial_agent(question: str, snapshot: dict) -> str:
    """Answer a free-text follow-up, grounded in the user's current figures."""
    prompt = (
        "You are a personal finance assistant talking to a user about their own budget.\n"
        f"Current figures (EUR): {json.dumps(snapshot, ensure_ascii=False)}\n\n"
        f"User question: {question}\n\n"
        "Answer briefly and practically in plain text, using only these figures. Do not invent numbers."
    )
    text, _ = _generate(prompt)
    return text


if __name__ == "__main__":
    income, saving_goal, expenses = get_user_inputs()
    output_json = ai_financial_agent(income, saving_goal, expenses)

    data = json.loads(output_json)
    print("\n" + data.get("summary", "No summary generated."))
    for item in data.get("recommendations", []):
        print(f" • {item}")
