"""Flower AgentApp adapter for Agent 2."""

import json

from flwr.agentapp import AgentApp, AgentSession
from flwr.common import Context

from .privacy_guard import PrivacyRiskGuard

app = AgentApp()
guard = PrivacyRiskGuard()


@app.main()
def main(agent: AgentSession, context: Context) -> None:
    """Review Agent 1 JSON carried in the Flower node configuration."""
    payload = context.node_config.get("agent1_analysis", "{}")
    analysis = json.loads(payload) if isinstance(payload, str) else payload
    result = guard.review(analysis)
    agent.events.emit(
        {
            "type": "agent2_result",
            "result": result,
        }
    )