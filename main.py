import json
from agent_1 import get_user_inputs, ai_financial_agent
from agent_2 import privacy_and_safety_agent

def run_multi_agent_pipeline():
    print("\n==========================================")
    print("🚀 STARTING MULTI-AGENT PIPELINE")
    print("==========================================")
    
    income, saving_goal, expenses = get_user_inputs()
    
    print("\n🔄 [STEP 1] Agent 1 is analyzing data and calling tools...")
    agent1_json_output = ai_financial_agent(income, saving_goal, expenses)
    
    print("\n--- AGENT 1 OUTPUT (PRE-SAFETY) ---")
    print(agent1_json_output)
    
    print("\n🔒 [STEP 2] Passing payload to Agent 2 (Diana's Safety Guard)...")
    final_safe_output = privacy_and_safety_agent(agent1_json_output)
    
    print("\n==========================================")
    print("🛡️ AGENT 2 FINAL APPROVED OUTPUT")
    print("==========================================")
    print(final_safe_output)

if __name__ == "__main__":
    run_multi_agent_pipeline()