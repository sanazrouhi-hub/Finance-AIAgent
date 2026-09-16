"""WebSocket console for the two-agent finance pipeline.

Serves a single-page UI at http://localhost:8000/ and streams every stage of the
Agent 1 -> Agent 2 pipeline over ws://localhost:8000/ws as it happens.

The agent modules are used as-is; nothing here reimplements their logic.

    python server.py                  # http://localhost:8000
    python server.py --port 8080      # any port; PORT / HOST env vars also work
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_1 import GEMINI_MODEL as MODEL_NAME
from agent_1 import GeminiQuotaExhausted, ai_financial_agent, ask_financial_agent, calculate_financials
from agent2.privacy_guard import redact_sensitive
from main import approved_content, review_agent1_output, sanitize_expenses

INDEX_FILE = ROOT / "web" / "index.html"

app = FastAPI(title="Finance AI Agent Console")


class BadInput(ValueError):
    """Client sent something the pipeline cannot run on."""


# --------------------------------------------------------------------------- #
# input coercion
# --------------------------------------------------------------------------- #

def _as_amount(value: Any, label: str) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise BadInput(f"{label} must be a number.") from None
    if amount < 0:
        raise BadInput(f"{label} cannot be negative.")
    if amount != amount or amount in (float("inf"), float("-inf")):
        raise BadInput(f"{label} must be a real number.")
    return amount


def _as_expenses(value: Any) -> dict[str, float]:
    if value in (None, "", []):
        return {}
    if not isinstance(value, dict):
        raise BadInput("Expenses must be a mapping of category to amount.")
    expenses: dict[str, float] = {}
    for category, amount in value.items():
        name = str(category).strip()
        if not name:
            raise BadInput("An expense category cannot be empty.")
        expenses[name] = _as_amount(amount, f"Amount for '{name}'")
    return expenses


# --------------------------------------------------------------------------- #
# pipeline helpers
# --------------------------------------------------------------------------- #

def _final_view(review: dict[str, Any]) -> dict[str, Any]:
    """What is actually safe to show the user, per Agent 2's verdict."""
    content = approved_content(review)
    blocking = [item for item in review.get("risk_review", []) if item.get("risk_level") == "HIGH_RISK"]

    return {
        "overall_status": review.get("overall_status", ""),
        "privacy_status": review.get("privacy_status", ""),
        "approved": content is not None,
        "text": content["summary"] if content else "",
        "recommendations": content["recommendations"] if content else [],
        "blocked_reasons": [item.get("reason", "") for item in blocking],
        "safety_notes": review.get("safety_notes", []),
        "redactions": review.get("redactions", []),
    }


# --------------------------------------------------------------------------- #
# websocket protocol
# --------------------------------------------------------------------------- #

async def send(ws: WebSocket, event: str, **payload: Any) -> None:
    await ws.send_text(json.dumps({"type": event, **payload}, ensure_ascii=False))


async def run_pipeline(ws: WebSocket, message: dict[str, Any]) -> None:
    income = _as_amount(message.get("income"), "Income")
    saving_goal = _as_amount(message.get("saving_goal"), "Saving goal")
    expenses = sanitize_expenses(_as_expenses(message.get("expenses")))
    if income <= 0:
        raise BadInput("Income must be greater than zero.")

    total_expenses = sum(expenses.values())

    # Stage 0 - the deterministic tool Agent 1 calls before it prompts the model.
    figures = calculate_financials(income, total_expenses, saving_goal)
    await send(
        ws,
        "math",
        data={
            "income": income,
            "total_expenses": total_expenses,
            "expenses": expenses,
            "redacted_before_model": sum("[REDACTED-" in name for name in expenses),
            **figures,
        },
    )

    # Stage 1 - Agent 1 drafts advice with Gemini.
    await send(ws, "status", stage="agent1", state="running")
    started = time.perf_counter()
    raw_agent1 = await asyncio.to_thread(ai_financial_agent, income, saving_goal, expenses)
    try:
        agent1_payload = json.loads(raw_agent1)
    except json.JSONDecodeError:
        agent1_payload = {"summary": raw_agent1}
    await send(ws, "agent1", data=agent1_payload, raw=raw_agent1, ms=_elapsed_ms(started))
    await send(ws, "status", stage="agent1", state="done")

    await review_and_publish(ws, raw_agent1)


async def review_and_publish(ws: WebSocket, draft: str) -> None:
    """Stage 2 - Agent 2 redacts and risk-reviews the draft, then the final view is sent."""
    await send(ws, "status", stage="agent2", state="running")
    started = time.perf_counter()
    review = await asyncio.to_thread(review_agent1_output, draft)
    await send(ws, "agent2", data=review, ms=_elapsed_ms(started))
    await send(ws, "status", stage="agent2", state="done")

    await send(ws, "final", data=_final_view(review))


async def run_guard_test(ws: WebSocket, message: dict[str, Any]) -> None:
    """Send a scripted draft straight to Agent 2. Gemini is not called; the UI labels it as scripted."""
    draft = message.get("draft")
    if not isinstance(draft, dict) or not (draft.get("summary") or draft.get("recommendations")):
        raise BadInput("A guard test needs a draft with a summary or recommendations.")
    payload = {
        "summary": str(draft.get("summary", "")),
        "recommendations": [str(item) for item in draft.get("recommendations", []) if str(item).strip()],
        "status": "Scripted_Draft_For_Guard_Test",
    }
    raw = json.dumps(payload, ensure_ascii=False)
    await send(ws, "agent1", data=payload, raw=raw, scripted=True)
    await review_and_publish(ws, raw)


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


async def run_follow_up(ws: WebSocket, message: dict[str, Any]) -> None:
    question = str(message.get("question", "")).strip()
    if not question:
        raise BadInput("Ask Agent 1 something first.")

    snapshot = message.get("snapshot") if isinstance(message.get("snapshot"), dict) else {}
    if isinstance(snapshot.get("expenses"), dict):
        snapshot = {**snapshot, "expenses": sanitize_expenses(_as_expenses(snapshot["expenses"]))}
    turn_id = message.get("turn_id")

    await send(ws, "status", stage="agent1", state="running")
    answer = await asyncio.to_thread(ask_financial_agent, redact_sensitive(question)[0], snapshot)
    await send(ws, "status", stage="agent1", state="done")

    # Follow-up answers go through the same guard as the main draft.
    await send(ws, "status", stage="agent2", state="running")
    review = await asyncio.to_thread(
        review_agent1_output, json.dumps({"summary": answer}, ensure_ascii=False)
    )
    await send(ws, "status", stage="agent2", state="done")

    await send(
        ws,
        "reply",
        turn_id=turn_id,
        draft=answer,
        review=review,
        final=_final_view(review),
    )


HANDLERS = {"analyze": run_pipeline, "ask": run_follow_up, "guard_test": run_guard_test}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    await send(ws, "hello", model=MODEL_NAME)
    try:
        while True:
            try:
                message = json.loads(await ws.receive_text())
            except json.JSONDecodeError:
                await send(ws, "error", message="Malformed message (expected JSON).")
                continue
            if not isinstance(message, dict):
                await send(ws, "error", message="Malformed message (expected a JSON object).")
                continue

            kind = message.get("type")
            if kind == "ping":
                await send(ws, "pong")
                continue

            handler = HANDLERS.get(kind)
            if handler is None:
                await send(ws, "error", message=f"Unknown message type: {kind!r}")
                continue

            try:
                await handler(ws, message)
            except BadInput as exc:
                await send(ws, "error", message=str(exc), kind="input")
            except GeminiQuotaExhausted as exc:
                await send(ws, "error", message=str(exc), kind="quota")
            except Exception as exc:  # model/network failures must not kill the socket
                await send(ws, "error", message=f"{type(exc).__name__}: {exc}", kind="runtime")
    except (WebSocketDisconnect, RuntimeError):
        return  # client went away mid-exchange


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "model": MODEL_NAME})


@app.get("/")
async def index() -> HTMLResponse:
    if not INDEX_FILE.exists():
        return HTMLResponse(f"<h1>Missing UI</h1><p>Expected {INDEX_FILE}</p>", status_code=500)
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="Finance AI Agent web console")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"), help="bind address (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")), help="port (default 8000)")
    args = parser.parse_args()

    print(f"\n  Finance AI Agent console  ->  http://localhost:{args.port}\n", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
