import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AGENT1_ROOT = Path(__file__).resolve().parent
if str(AGENT1_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT1_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent2.privacy_guard import PrivacyRiskGuard


privacy_guard = PrivacyRiskGuard()


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

    review_input = dict(analysis)
    if not review_input.get("recommendations") and review_input.get("summary"):
        review_input["recommendations"] = [review_input["summary"]]

    return privacy_guard.review(review_input)

def run_multi_agent_pipeline():
    from agent_1 import ai_financial_agent, get_user_inputs

    print("\n==========================================")
    print("🚀 STARTING MULTI-AGENT PIPELINE")
    print("==========================================")
    
    income, saving_goal, expenses = get_user_inputs()
    
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

if __name__ == "__main__":
    run_multi_agent_pipeline()
