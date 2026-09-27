"""
Prompt construction + response parsing for chart analysis.

Kept in its own module (prompt_version below) so it can be revised without
touching main.py, and so every stored chart_analysis row can record exactly
which prompt version produced it (spec section 38, model versioning).
"""

PROMPT_VERSION = "mvp-v1"

SYSTEM_PROMPT = """You are a market-structure analyst assisting a discretionary trader.
You analyze a single chart image and extract ONLY what is visually determinable.

Hard rules (violating any of these is a failure):
- Never invent price levels, candles, or patterns that are not visibly present.
- Never state a probability, statistic, or historical frequency yourself — that
  is computed separately from stored historical data, not from this image.
- Never claim certainty about future price direction.
- If something is not clearly visible (timeframe, asset, precise price labels),
  say "not visible / insufficient information" for that field rather than guessing.
- Candle psychology must be phrased as "consistent with" / "suggests", never as
  a direct fact about trader intent.
- If the image quality or clarity is too low to analyze confidently, say so in
  data_quality_score and reduce confidence accordingly.

Respond with ONLY a single JSON object, no prose before or after, matching this
shape exactly (use null for anything not determinable — never omit a key):

{
  "asset_guess": string or null,
  "timeframe_guess": string or null,
  "trend": "bullish" | "bearish" | "neutral" | "transitional" | null,
  "market_regime": string or null,
  "structure": {
    "hh_hl_lh_ll": string or null,
    "bos": string or null,
    "mss_choch": string or null,
    "phase": "consolidation" | "expansion" | "compression" | "range" | "trend" | null
  },
  "supply_demand": {
    "supply_zones": [string],
    "demand_zones": [string],
    "notes": string or null
  },
  "liquidity": {
    "equal_highs_lows": string or null,
    "sweeps": string or null,
    "notes": string or null
  },
  "candlesticks": {
    "important_candle": string or null,
    "formation": string or null,
    "context": string or null
  },
  "candle_psychology": {
    "buyer_behavior": string or null,
    "seller_behavior": string or null,
    "indecision": string or null
  },
  "important_levels": {
    "resistance": [number],
    "support": [number],
    "entry_area_notes": string or null
  },
  "setup_type": string or null,
  "primary_scenario": {
    "condition": string or null,
    "direction": "long" | "short" | null,
    "entry_zone_low": number or null,
    "entry_zone_high": number or null,
    "confirmation_required": string or null,
    "stop_loss": number or null,
    "tp1": number or null,
    "tp2": number or null,
    "tp3": number or null,
    "invalidation": string or null,
    "status": "observational" | "executable" | "no_trade",
    "no_trade_reason": string or null
  },
  "alternative_scenario": {
    "condition": string or null,
    "direction": "long" | "short" | null
  },
  "data_quality_score": integer 0-100,
  "risks_limitations": string or null
}
"""

USER_PROMPT_TEMPLATE = """Analyze this chart image.

Asset (if known): {asset}
Timeframe (if known): {timeframe}
Lower timeframe (if provided): {lower_timeframe}
User notes: {notes}

Return the JSON object described in your instructions. Nothing else."""


def build_messages(image_b64: str, media_type: str, asset: str, timeframe: str,
                    lower_timeframe: str | None, notes: str | None):
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                },
                {
                    "type": "text",
                    "text": USER_PROMPT_TEMPLATE.format(
                        asset=asset or "not provided",
                        timeframe=timeframe or "not provided",
                        lower_timeframe=lower_timeframe or "none",
                        notes=notes or "none",
                    ),
                },
            ],
        }
    ]


def compute_risk_reward(entry_low, entry_high, stop_loss, tp1):
    """Derive R:R from levels the model extracted — never let the model state
    R:R itself, since that's arithmetic, not vision."""
    if None in (entry_low, entry_high, stop_loss, tp1):
        return None
    entry = (entry_low + entry_high) / 2
    risk = abs(entry - stop_loss)
    reward = abs(tp1 - entry)
    if risk == 0:
        return None
    return round(reward / risk, 2)
