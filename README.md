# Finance AI Agent

A two-agent personal finance assistant with a live web console.

- **Agent 1 — Advisor** (`agent_1.py`): runs the budget math, then asks Gemini for a short summary and a list of concrete recommendations.
- **Agent 2 — Privacy & Risk Guard** (`agent2/privacy_guard.py`): redacts personal identifiers and rates each recommendation LOW / MODERATE / HIGH risk. Anything high-risk is rejected and never shown to the user. An optional OpenAI step may *escalate* a verdict, never relax it.

User-typed text is redacted **before** it is sent to Gemini, and the model's output is reviewed again before it is shown.

```
your input ──redact──▶ Agent 1 (Gemini) ──draft──▶ Agent 2 (guard) ──approved only──▶ user
```

## Setup

```bash
python3 -m venv venv
./venv/bin/pip install -e ".[test]"
cp .env.example .env        # then put your GEMINI_API_KEY in .env
```

## Run the web console

```bash
./venv/bin/python server.py              # http://localhost:8000
./venv/bin/python server.py --port 8080  # any port
```

Everything streams over a WebSocket at `/ws`; `/health` returns the model in use.

### Gemini quota

Free-tier keys get a small daily request allowance **per model**. When a model runs out, Agent 1 moves to the next one in `GEMINI_FALLBACK_MODELS` (see `.env.example`) and skips the exhausted model for an hour. The Agent 1 card shows which model answered. If every model is exhausted, the page says so; the *Risky draft → guard test* scenario still works because it never calls Gemini.

### Demo scenarios (buttons at the top of the page)

| Button | What it shows |
|---|---|
| **Healthy month** | Full pipeline with a live Gemini call; advice is approved. |
| **Tight month** | Expenses leave a shortfall against the saving goal. |
| **Private data in expenses** | An IBAN and an email typed into expense names are redacted before Gemini ever sees them. |
| **Risky draft → guard test** | A *scripted* draft (labelled as such; Gemini is not called) with crypto, "guaranteed returns", rent money in options and an email address. Agent 2 redacts the email and rejects the draft. |

Click `{ }` on any card to flip it and see the raw JSON that passed between the agents. The chat box sends follow-up questions to Agent 1; answers go through Agent 2 as well.

## Command line

```bash
./venv/bin/python main.py        # interactive terminal version of the same pipeline
./venv/bin/python -m agent2.demo # Agent 2 on its own, no API key needed
```

## Tests

```bash
./venv/bin/python -m pytest
```

No API key is needed; the tests cover the guard and the pipeline glue.

## Flower

`agent2/app.py` wraps Agent 2 as a Flower `AgentApp`. The web console and `main.py` call the guard in-process and do not use it.
