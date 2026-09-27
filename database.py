"""
SQLite storage layer for the MVP.

Deliberately plain sqlite3 rather than a full ORM: the schema (schema.sql)
is the source of truth, and every function here maps 1:1 to a table so it's
easy to extend as later phases (backtesting, Monte Carlo, model versioning)
add tables without breaking Phase 1.
"""
import sqlite3
import json
import os
from contextlib import contextmanager

DB_PATH = os.environ.get("MICROLYST_DB_PATH", "microlyst.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def init_db():
    with get_conn() as conn:
        with open(SCHEMA_PATH) as f:
            conn.executescript(f.read())


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_or_create_asset(conn, symbol: str, market: str | None = None) -> int:
    row = conn.execute("SELECT id FROM assets WHERE symbol = ?", (symbol,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO assets (symbol, market) VALUES (?, ?)", (symbol, market)
    )
    return cur.lastrowid


def insert_chart_image(conn, asset_id: int, timeframe: str, image_path: str,
                        lower_timeframe: str | None = None,
                        is_historical: bool = False, notes: str | None = None) -> int:
    cur = conn.execute(
        """INSERT INTO chart_images
           (asset_id, timeframe, lower_timeframe, image_path, is_historical, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (asset_id, timeframe, lower_timeframe, image_path, int(is_historical), notes),
    )
    return cur.lastrowid


def insert_chart_analysis(conn, chart_image_id: int, model: str, prompt_version: str,
                           parsed: dict, raw_response: str) -> int:
    cur = conn.execute(
        """INSERT INTO chart_analysis
           (chart_image_id, model, prompt_version, trend, market_regime,
            structure_json, supply_demand_json, liquidity_json,
            candlestick_json, candle_psychology_json, data_quality_score, raw_response)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            chart_image_id, model, prompt_version,
            parsed.get("trend"), parsed.get("market_regime"),
            json.dumps(parsed.get("structure", {})),
            json.dumps(parsed.get("supply_demand", {})),
            json.dumps(parsed.get("liquidity", {})),
            json.dumps(parsed.get("candlesticks", {})),
            json.dumps(parsed.get("candle_psychology", {})),
            parsed.get("data_quality_score"),
            raw_response,
        ),
    )
    return cur.lastrowid


def insert_trade_setup(conn, chart_analysis_id: int, setup: dict) -> int:
    cur = conn.execute(
        """INSERT INTO trade_setups
           (chart_analysis_id, direction, status, entry_zone_low, entry_zone_high,
            confirmation, stop_loss, tp1, tp2, tp3, risk_reward, invalidation,
            historical_probability, sample_size, confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            chart_analysis_id, setup.get("direction"), setup.get("status"),
            setup.get("entry_zone_low"), setup.get("entry_zone_high"),
            setup.get("confirmation"), setup.get("stop_loss"),
            setup.get("tp1"), setup.get("tp2"), setup.get("tp3"),
            setup.get("risk_reward"), setup.get("invalidation"),
            setup.get("historical_probability"), setup.get("sample_size"),
            setup.get("confidence"),
        ),
    )
    return cur.lastrowid


def record_outcome(conn, trade_setup_id: int, outcome: dict) -> int:
    """Section 43: continuous learning input. Also drops a row into
    historical_cases so future probability lookups can use this result."""
    cur = conn.execute(
        """INSERT INTO trade_outcomes
           (trade_setup_id, actual_direction, actual_entry, exit_price,
            r_multiple, mfe, mae, result, error_category)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trade_setup_id, outcome.get("actual_direction"), outcome.get("actual_entry"),
            outcome.get("exit_price"), outcome.get("r_multiple"), outcome.get("mfe"),
            outcome.get("mae"), outcome.get("result"), outcome.get("error_category"),
        ),
    )
    outcome_id = cur.lastrowid

    setup_row = conn.execute(
        "SELECT chart_analysis_id, direction FROM trade_setups WHERE id = ?",
        (trade_setup_id,),
    ).fetchone()
    if setup_row:
        conn.execute(
            """INSERT INTO historical_cases
               (chart_analysis_id, trade_outcome_id, setup_type, outcome_label)
               VALUES (?, ?, ?, ?)""",
            (
                setup_row["chart_analysis_id"], outcome_id,
                setup_row["direction"], outcome.get("result"),
            ),
        )
    return outcome_id


def get_probability(conn, setup_type: str, outcome_label: str):
    """Empirical frequency lookup (section 10). Returns None if no data yet —
    caller must then say 'insufficient historical data', never fabricate."""
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM historical_cases WHERE setup_type = ?",
        (setup_type,),
    ).fetchone()["n"]
    if total == 0:
        return None
    hits = conn.execute(
        "SELECT COUNT(*) AS n FROM historical_cases WHERE setup_type = ? AND outcome_label = ?",
        (setup_type, outcome_label),
    ).fetchone()["n"]
    return {"hits": hits, "sample_size": total, "probability": round(100 * hits / total, 1)}
