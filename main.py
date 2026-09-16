import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent2.privacy_guard import PrivacyRiskGuard, redact_sensitive


privacy_guard = PrivacyRiskGuard()

APPROVED_STATUSES = ("APPROVED", "APPROVED_WITH_WARNINGS")


def sanitize_expenses(expenses):
    """Redact identifiers users type into free-text categories before they reach Gemini."""
    clean = {}
    for category, amount in expenses.items():
        name, _ = redact_sensitive(str(category))
        # Two categories can redact to the same placeholder; keep both amounts.
        clean[name] = clean.get(name, 0) + amount
    return clean


def review_agent1_output(agent1_json_output):
    """Convert Agent 1's current payload into Agent 2's review contract."""
    if isinstance(agent1_json_output, str):
        try:
            analysis = json.loads(agent1_json_output)
        except json.JSONDecodeError:
            analysis = {"summary": agent1_json_output}
    else:
        analysis = agent1_json_output

    if not isinstance(analysis, dict):
        analysis = {"summary": str(analysis)}

    return privacy_guard.review(analysis)


def approved_content(review):
    """The sanitized summary and recommendations, or None if Agent 2 did not approve."""
    if review.get("overall_status") not in APPROVED_STATUSES:
        return None
    sanitized = review.get("sanitized_analysis", "{}")
    if isinstance(sanitized, str):
        try:
            sanitized = json.loads(sanitized)
        except json.JSONDecodeError:
            return {"summary": sanitized, "recommendations": []}
    if not isinstance(sanitized, dict):
        return {"summary": str(sanitized), "recommendations": []}
    return {
        "summary": str(sanitized.get("summary", "")),
        "recommendations": [str(item) for item in sanitized.get("recommendations", [])],
    }


def run_multi_agent_pipeline():
    from agent_1 import ai_financial_agent, get_user_inputs

    print("\n==========================================")
    print("🚀 STARTING MULTI-AGENT PIPELINE")
    print("==========================================")

    income, saving_goal, expenses = get_user_inputs()
    expenses = sanitize_expenses(expenses)

    print("\n🔄 [STEP 1] Agent 1 is analyzing data and calling tools...")
    agent1_json_output = ai_financial_agent(income, saving_goal, expenses)

    print("\n--- AGENT 1 OUTPUT (PRE-SAFETY) ---")
    print(agent1_json_output)

    print("\n🔒 [STEP 2] Passing payload to Agent 2 (Diana's Safety Guard)...")
    final_safe_output = review_agent1_output(agent1_json_output)

    print("\n==========================================")
    print("🛡️ AGENT 2 FINAL APPROVED OUTPUT")
    print("==========================================")
    print(json.dumps(final_safe_output, indent=2, ensure_ascii=False))

    return final_safe_output, income, expenses, saving_goal

def print_visual_dashboard(income, expenses, saving_goal):
    total_spent = sum(expenses.values())
    remaining = income - total_spent
    spent_ratio = total_spent / income if income > 0 else 1.0
    spent_pct = max(0, min(int(spent_ratio * 20), 20))

    spent_bar = "█" * spent_pct + "░" * (20 - spent_pct)

    print("\n📊 FINANCIAL VISUAL DASHBOARD")
    print("─" * 45)
    print(f"Income:   €{income:,.2f}")
    print(f"Spent:    [{spent_bar}] €{total_spent:,.2f} ({spent_ratio * 100:.1f}%)")
    print(f"Goal:     €{saving_goal:,.2f}")
    print(f"Buffer:   €{remaining - saving_goal:,.2f}")
    print("─" * 45)


if __name__ == "__main__":
    final_data, income, expenses, saving_goal = run_multi_agent_pipeline()

    print_visual_dashboard(income=income, expenses=expenses, saving_goal=saving_goal)

    print("\n==========================================")
    print("      📌 DAILY FINANCIAL ASSISTANT        ")
    print("==========================================")
    print(f"🔒 Privacy Guard: {final_data.get('privacy_status')}")
    print(f"🛡️ Risk Review:   {final_data.get('overall_status')}")
    print("-" * 45)

    content = approved_content(final_data)
    if content is not None:
        print("\n💡 Approved Advice:\n")
        print(content["summary"])
        for item in content["recommendations"]:
            print(f" • {item}")
        for note in final_data.get("safety_notes", []):
            print(f"\nℹ️ {note}")
    else:
        print("\n⚠️ Safety Flagged / High Risk Detected:")
        for item in final_data.get("risk_review", []):
            if item.get("risk_level") == "HIGH_RISK":
                print(f"• Reason: {item.get('reason')}")
        print("\nAgent 1's advice was withheld.")
    print("=" * 45)
