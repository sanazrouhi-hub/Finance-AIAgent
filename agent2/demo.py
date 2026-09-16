"""Run the demo without a Flower runtime or an LLM key."""

import json

from .privacy_guard import PrivacyRiskGuard


if __name__ == "__main__":
    example = {
        "monthly_income": 4000,
        "total_expenses": 2800,
        "savings": 1200,
        "recommendations": [
            "Keep EUR 600 as emergency savings",
            "Invest EUR 400 monthly into a diversified low-cost portfolio",
            "Put EUR 200 into a speculative cryptocurrency",
        ],
        "notes": "User email is diana@example.com",
    }
    print(json.dumps(PrivacyRiskGuard().review(example), indent=2, ensure_ascii=False))