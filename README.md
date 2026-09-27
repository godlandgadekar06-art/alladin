# MICROLYST Market Analysis Engine — MVP (Phase 1)

This is the working core of the full spec: upload a chart → extract structure,
trend, supply/demand, liquidity, and candlestick behavior → look up empirical
probability from your own stored historical cases → generate a conditional
trade setup with entry/SL/TP/R:R/invalidation. Nothing is invented — every
number is either read off the image by the vision model or computed from
stored data (`database.get_probability`), and a setup can come back
`no_trade` if the evidence doesn't support one.

## What's deliberately NOT in this MVP

Per the spec's own phased build-out (section 48), these are follow-on phases,
not missing bugs:
- Multi-timeframe alignment scoring (section 6)
- Pattern similarity search / embeddings (section 9)
- Bayesian updating, confidence intervals, walk-forward validation (11–12, 45)
- Backtesting engine, Monte Carlo simulation (22–23)
- Annotated chart image overlay (section 28)
- Dashboard UI, session/regime breakdowns, error-category analytics (32–36, 40)
- Model calibration tracking / Brier score (section 46)

Each of these can be added as a new module reading from the same schema
(`schema.sql`) without breaking Phase 1 — that's why analysis results are
stored as JSON blobs (`chart_analysis.structure_json` etc.) rather than
rigid columns.

## Running it

```bash
pip install -r requirements.txt --break-system-packages
export ANTHROPIC_API_KEY=your_key_here
uvicorn main:app --reload
```

The SQLite file (`microlyst.db`) and uploaded images (`uploads/`) are created
automatically on first run.

## Bootstrapping the historical library

The probability engine (`/probability`, and the automatic lookup inside
`/analyze`) only returns numbers once you have labeled history. Backfill your
past trades/analyses with:

```bash
curl -X POST http://localhost:8000/assets/upload-historical \
  -F "asset=XAUUSD" -F "timeframe=1D" \
  -F "setup_type=bearish BOS + retest of supply" \
  -F "outcome_label=bearish_continuation" \
  -F "direction=short" -F "r_multiple=2.4" \
  -F "file=@/path/to/old_chart.png"
```

Do this for as many past setups as you have. Until sample sizes are
reasonable (the spec's own examples use 50–200+), `/analyze` will correctly
report "insufficient historical data" rather than showing a fabricated
percentage — that's intended behavior (section 10), not a bug.

## Analyzing a current chart

```bash
curl -X POST http://localhost:8000/analyze \
  -F "asset=XAUUSD" -F "timeframe=1D" -F "lower_timeframe=30M" \
  -F "file=@/path/to/current_chart.png"
```

## Next phases, in order

1. Wire `/analyze` results into a simple frontend (the artifact prototype
   included alongside this covers the visual layer for now)
2. Add multi-timeframe support — call `/analyze` once per timeframe and add
   an alignment-scoring function
3. Add the annotated-image overlay (draw entry/SL/TP/zones back onto the
   uploaded chart using Pillow)
4. Only then move to backtesting/Monte Carlo — those need a much larger
   historical library to be meaningful anyway
