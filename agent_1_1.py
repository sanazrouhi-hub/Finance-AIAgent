import json
import os
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "YOUR_OPENAI_API_KEY_HERE")
client = OpenAI(api_key=OPENAI_API_KEY)

def calculate_financials(income: float, total_expenses: float, saving_goal: float):
    remaining = income - total_expenses
    extra_or_shortfall = remaining - saving_goal
    return {
        "remaining": remaining,
        "saving_goal": saving_goal,
        "extra_or_shortfall": extra_or_shortfall,
        "status_code": 1 if extra_or_shortfall > 0 else (2 if remaining >= saving_goal else 3)
    }

tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "calculate_financials",
            "description": "Calculates remaining money and checks if the monthly saving goal is met.",
            "parameters": {
                "type": "object",
                "properties": {
                    "income": {"type": "number"},
                    "total_expenses": {"type": "number"},
                    "saving_goal": {"type": "number"}
                },
                "required": ["income", "total_expenses", "saving_goal"]
            }
        }
    }
]

def get_valid_float(prompt):
    while True:
        try:
            value = float(input(prompt))
            if value < 0:
                print("❌ Please enter a positive number!")
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
        if category.isdigit() and category.lower() != 'done':
            print("❌ Category name should be text, not a number!")
            continue
        return category

def get_user_inputs():
    print("\n==========================================")
    print("      💰 DAILY FINANCIAL ASSISTANT        ")
    print("==========================================")
    
    income = get_valid_float("\n👉 Enter your total monthly income (EUR): ")
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
    
    prompt = (
        f"User has a monthly income of {income} EUR, a saving goal of {saving_goal} EUR for this month, "
        f"and total expenses of {total_spent} EUR ({expenses}). "
        f"Use the calculate_financials tool to evaluate their financials. "
        f"Then generate a clear summary with a fun tone based on whether they can save/spend extra."
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        tools=tools_schema,
        tool_choice="auto"
    )

    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls

    if tool_calls:
        tool_call = tool_calls[0]
        args = json.loads(tool_call.function.arguments)
        
        tool_result = calculate_financials(
            income=args.get("income"),
            total_expenses=args.get("total_expenses"),
            saving_goal=args.get("saving_goal")
        )

        final_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": prompt},
                response_message,
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result)
                }
            ]
        )
        
        summary_text = final_response.choices[0].message.content
        
        proposal = {
            "summary": summary_text,
            "raw_income": income,
            "raw_expenses": total_spent,
            "status": "Pending_Safety_Review"
        }
        return json.dumps(proposal)

    return json.dumps({"error": "Agent failed to call tool."})

if __name__ == "__main__":
    income, saving_goal, expenses = get_user_inputs()
    output_json = ai_financial_agent(income, saving_goal, expenses)
    
    data = json.loads(output_json)
    print("\n" + data.get("summary", "No summary generated."))