"""
MICROLYST Market Analysis Engine — Phase 1 MVP.

Endpoints:
  POST /assets/upload-historical   store a past chart + its known outcome
  POST /analyze                    upload a current chart, get structured analysis + setup
  POST /setups/{id}/outcome        record what actually happened (feeds the learning loop)
  GET  /probability                empirical frequency lookup for a setup_type

Run:
  pip install -r requirements.txt --break-system-packages
  export ANTHROPIC_API_KEY=...
  uvicorn main:app --reload
"""
import base64
import json
import os
import uuid
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from anthropic import Anthropic

import database as db
from analysis_prompt import (
    SYSTEM_PROMPT, PROMPT_VERSION, build_messages, compute_risk_reward,
)

app = FastAPI(title="MICROLYST Market Analysis Engine — MVP")
client = Anthropic()  # reads ANTHROPIC_API_KEY from env

UPLOAD_DIR = os.environ.get("MICROLYST_UPLOAD_DIR", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.on_event("startup")
def startup():
    db.init_db()


def _save_image(file: UploadFile) -> tuple[str, bytes, str]:
    ext = os.path.splitext(file.filename or "")[1] or ".png"
    path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}{ext}")
    raw = file.file.read()
    with open(path, "wb") as f:
        f.write(raw)
    media_type = file.content_type or "image/png"
    return path, raw, media_type


def _run_vision_analysis(raw: bytes, media_type: str, asset: str, timeframe: str,
                          lower_timeframe: Optional[str], notes: Optional[str]) -> dict:
    b64 = base64.b64encode(raw).decode("utf-8")
    messages = build_messages(b64, media_type, asset, timeframe, lower_timeframe, notes)
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        raise HTTPException(500, f"Model did not return valid JSON: {text[:500]}")
    return parsed, text


@app.post("/assets/upload-historical")
def upload_historical(
    asset: str = Form(...),
    timeframe: str = Form(...),
    outcome_label: str = Form(...),  # bullish_continuation / bearish_continuation / reversal / range / false_breakout
    setup_type: str = Form(...),
    direction: Optional[str] = Form(None),
    r_multiple: Optional[float] = Form(None),
    notes: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    """Add a past, already-resolved chart to the training library (section 4).
    This does NOT run the AI extraction — it just stores the labeled case so
    the probability engine has real sample data to draw from."""
    path, raw, media_type = _save_image(file)
    with db.get_conn() as conn:
        asset_id = db.get_or_create_asset(conn, asset)
        chart_id = db.insert_chart_image(
            conn, asset_id, timeframe, path, is_historical=True, notes=notes
        )
        analysis_id = db.insert_chart_analysis(
            conn, chart_id, model="human_labeled", prompt_version="n/a",
            parsed={}, raw_response="human-labeled historical case",
        )
        setup_id = db.insert_trade_setup(conn, analysis_id, {
            "direction": direction, "status": "executable",
        })
        db.record_outcome(conn, setup_id, {
            "actual_direction": direction, "r_multiple": r_multiple,
            "result": outcome_label,
        })
        conn.execute(
            "UPDATE historical_cases SET setup_type = ? WHERE trade_outcome_id = "
            "(SELECT id FROM trade_outcomes WHERE trade_setup_id = ?)",
            (setup_type, setup_id),
        )
    return {"chart_image_id": chart_id, "stored": True}


@app.post("/analyze")
def analyze(
    asset: str = Form(...),
    timeframe: str = Form(...),
    lower_timeframe: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    """Phase 1 core: upload a current chart, get structure + probability +
    a conditional setup. Every number in the response is either read directly
    off the image or computed from stored historical_cases — nothing is
    invented (section 30)."""
    path, raw, media_type = _save_image(file)
    parsed, raw_text = _run_vision_analysis(raw, media_type, asset, timeframe, lower_timeframe, notes)

    with db.get_conn() as conn:
        asset_id = db.get_or_create_asset(conn, asset)
        chart_id = db.insert_chart_image(conn, asset_id, timeframe, path, lower_timeframe, notes=notes)
        analysis_id = db.insert_chart_analysis(conn, chart_id, "claude-sonnet-4-6", PROMPT_VERSION, parsed, raw_text)

        setup_type = parsed.get("setup_type") or "unclassified"
        primary = parsed.get("primary_scenario", {}) or {}

        rr = compute_risk_reward(
            primary.get("entry_zone_low"), primary.get("entry_zone_high"),
            primary.get("stop_loss"), primary.get("tp1"),
        )

        prob_continuation = db.get_probability(conn, setup_type, "bullish_continuation" if primary.get("direction") == "long" else "bearish_continuation")

        setup_id = db.insert_trade_setup(conn, analysis_id, {
            "direction": primary.get("direction"),
            "status": primary.get("status", "no_trade"),
            "entry_zone_low": primary.get("entry_zone_low"),
            "entry_zone_high": primary.get("entry_zone_high"),
            "confirmation": primary.get("confirmation_required"),
            "stop_loss": primary.get("stop_loss"),
            "tp1": primary.get("tp1"), "tp2": primary.get("tp2"), "tp3": primary.get("tp3"),
            "risk_reward": rr,
            "invalidation": primary.get("invalidation"),
            "historical_probability": prob_continuation["probability"] if prob_continuation else None,
            "sample_size": prob_continuation["sample_size"] if prob_continuation else 0,
            "confidence": "moderate" if prob_continuation and prob_continuation["sample_size"] >= 30 else "low",
        })

    return {
        "chart_image_id": chart_id,
        "analysis_id": analysis_id,
        "trade_setup_id": setup_id,
        "analysis": parsed,
        "risk_reward": rr,
        "historical_probability": prob_continuation if prob_continuation else "insufficient historical data",
    }


@app.post("/setups/{setup_id}/outcome")
def report_outcome(
    setup_id: int,
    actual_direction: Optional[str] = Form(None),
    exit_price: Optional[float] = Form(None),
    r_multiple: Optional[float] = Form(None),
    result: str = Form(...),  # win / loss / breakeven
    error_category: Optional[str] = Form(None),
):
    """Closes the learning loop (section 43): this trade's real outcome
    becomes a new historical_cases row future probability lookups can use."""
    with db.get_conn() as conn:
        outcome_id = db.record_outcome(conn, setup_id, {
            "actual_direction": actual_direction, "exit_price": exit_price,
            "r_multiple": r_multiple, "result": result, "error_category": error_category,
        })
    return {"outcome_id": outcome_id, "stored": True}


@app.get("/probability")
def probability(setup_type: str, outcome_label: str):
    with db.get_conn() as conn:
        result = db.get_probability(conn, setup_type, outcome_label)
    if result is None:
        return {"probability": None, "message": "Insufficient historical data."}
    return result
