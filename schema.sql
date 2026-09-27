-- MICROLYST Market Analysis Engine — MVP schema (Phase 1)
-- Covers: chart storage, extracted analysis, trade setups, outcomes, and the
-- historical case library the probability engine reads from.
-- Full spec (section 37) lists ~25 tables; this is the subset needed to make
-- Phase 1 (upload -> structure -> probability -> setup) actually work.
-- Later phases (backtesting, Monte Carlo, model versioning, audit trail) can
-- add tables without touching these.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS assets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT UNIQUE NOT NULL,       -- e.g. XAUUSD
    market      TEXT,                       -- forex / crypto / equity / index
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chart_images (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id        INTEGER NOT NULL REFERENCES assets(id),
    timeframe       TEXT NOT NULL,          -- 1D, 4H, 30M, etc.
    lower_timeframe TEXT,
    image_path      TEXT NOT NULL,
    is_historical   INTEGER DEFAULT 0,      -- 1 = training example with known outcome
    uploaded_at     TEXT DEFAULT CURRENT_TIMESTAMP,
    notes           TEXT
);

-- One row per AI analysis run on a chart_image. This is the structured
-- extraction from section 4 (market structure / trend / S&D / liquidity /
-- candlesticks), stored as JSON so the schema doesn't need to change every
-- time a new feature is added to the extraction prompt.
CREATE TABLE IF NOT EXISTS chart_analysis (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    chart_image_id       INTEGER NOT NULL REFERENCES chart_images(id),
    model                TEXT NOT NULL,      -- e.g. claude-sonnet-4-6
    prompt_version       TEXT NOT NULL,
    trend                TEXT,               -- bullish / bearish / neutral / transitional
    market_regime        TEXT,
    structure_json        TEXT,               -- HH/HL/LH/LL, BOS, MSS, CHOCH
    supply_demand_json    TEXT,
    liquidity_json        TEXT,
    candlestick_json      TEXT,
    candle_psychology_json TEXT,
    data_quality_score    INTEGER,            -- 0-100, section 31
    raw_response          TEXT,               -- full model output, for audit
    created_at            TEXT DEFAULT CURRENT_TIMESTAMP
);

-- A concrete conditional trade plan generated from an analysis (section 14-18).
CREATE TABLE IF NOT EXISTS trade_setups (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    chart_analysis_id INTEGER NOT NULL REFERENCES chart_analysis(id),
    direction         TEXT NOT NULL,          -- long / short
    status            TEXT NOT NULL,          -- observational / executable / no_trade
    entry_zone_low    REAL,
    entry_zone_high   REAL,
    confirmation       TEXT,
    stop_loss          REAL,
    tp1               REAL,
    tp2               REAL,
    tp3               REAL,
    risk_reward       REAL,
    invalidation       TEXT,
    historical_probability REAL,   -- % from probability_models, not invented here
    sample_size        INTEGER,
    confidence          TEXT,               -- low / moderate / high
    created_at          TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Realized result of a trade_setup, once the user closes it out (section 8, 43).
CREATE TABLE IF NOT EXISTS trade_outcomes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_setup_id   INTEGER NOT NULL REFERENCES trade_setups(id),
    actual_direction TEXT,
    actual_entry     REAL,
    exit_price       REAL,
    r_multiple       REAL,
    mfe              REAL,       -- max favorable excursion
    mae              REAL,       -- max adverse excursion
    result           TEXT,       -- win / loss / breakeven
    error_category   TEXT,       -- section 34, nullable
    closed_at        TEXT DEFAULT CURRENT_TIMESTAMP
);

-- The historical case library the similarity/probability engine (sections
-- 9-10) queries against. Populated from past chart_analysis + trade_outcomes
-- pairs once an outcome is known.
CREATE TABLE IF NOT EXISTS historical_cases (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    chart_analysis_id    INTEGER NOT NULL REFERENCES chart_analysis(id),
    trade_outcome_id      INTEGER REFERENCES trade_outcomes(id),
    setup_type            TEXT,   -- e.g. "bearish BOS + retest of supply"
    outcome_label          TEXT,   -- bullish_continuation / bearish_continuation / reversal / range / false_breakout
    feature_vector_json    TEXT,   -- compact features used for similarity search
    created_at             TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Cached empirical probability lookups (section 10), so every analysis
-- doesn't have to recompute from scratch. One row per (setup_type, outcome).
CREATE TABLE IF NOT EXISTS probability_models (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    setup_type   TEXT NOT NULL,
    outcome_label TEXT NOT NULL,
    hits          INTEGER NOT NULL,
    sample_size   INTEGER NOT NULL,
    ci_low        REAL,
    ci_high       REAL,
    computed_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(setup_type, outcome_label)
);

CREATE INDEX IF NOT EXISTS idx_chart_images_asset ON chart_images(asset_id);
CREATE INDEX IF NOT EXISTS idx_analysis_chart ON chart_analysis(chart_image_id);
CREATE INDEX IF NOT EXISTS idx_setups_analysis ON trade_setups(chart_analysis_id);
CREATE INDEX IF NOT EXISTS idx_cases_setup_type ON historical_cases(setup_type);
