import json
import os
from google import genai
from google.genai import types

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY_HERE")
client = genai.Client(api_key=GEMINI_API_KEY)

def calculate_financials(income: float, total_expenses: float, saving_goal: float) -> dict:
    remaining = income - total_expenses
    extra_or_shortfall = remaining - saving_goal
    return {
        "remaining": remaining,
        "saving_goal": saving_goal,
        "extra_or_shortfall": extra_or_shortfall,
        "status_code": 1 if extra_or_shortfall > 0 else (2 if remaining >= saving_goal else 3)
    }

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
        f"Call the calculate_financials function to evaluate their financials, "
        f"and then write a fun summary based on the results."
    )

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[calculate_financials],
            temperature=0.7,
        ),
    )

    summary_text = response.text

    proposal = {
        "summary": summary_text,
        "raw_income": income,
        "raw_expenses": total_spent,
        "status": "Pending_Safety_Review"
    }
    return json.dumps(proposal)

if __name__ == "__main__":
    income, saving_goal, expenses = get_user_inputs()
    output_json = ai_financial_agent(income, saving_goal, expenses)
    
    data = json.loads(output_json)
    print("\n" + data.get("summary", "No summary generated."))