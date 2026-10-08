"""
MarketPulse - Exchange-Aware Event-Level Feature Engineering

Grain
-----
One feature row per:
    (news_id, security_id, exchange)

PIT
---
Reads only market_news_ml_samples, which is already PIT-safe.
Future labels are targets only and are never used as features.

Important
---------
NSE and BSE sequences are NEVER mixed. Every window, aggregation,
label join, stale check and UPSERT uses:
    news_id + security_id + exchange

Usage
-----
Test:
    python marketpulse_build_event_features_exchange_aware.py --limit 100

Incremental:
    python marketpulse_build_event_features_exchange_aware.py --new

Full rebuild:
    python marketpulse_build_event_features_exchange_aware.py --rebuild

Exact events:
    python marketpulse_build_event_features_exchange_aware.py --news-ids-file ids.txt
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[4]
ENV_PATH = PROJECT_ROOT / ".env"
load_dotenv(ENV_PATH)

DB_HOST = os.getenv("MARKETPULSE_DB_HOST", "localhost")
DB_PORT = os.getenv("MARKETPULSE_DB_PORT", "5432")
DB_NAME = os.getenv("MARKETPULSE_DB_NAME", "marketpulse")
DB_USER = os.getenv("MARKETPULSE_DB_USER", "postgres")
DB_PASSWORD = os.getenv("MARKETPULSE_DB_PASSWORD")

OUTPUT_TABLE = "market_news_ml_features"
TRAINING_START = "2025-01-01"
TRAINING_END = "2026-09-01"

SHORT_HISTORY_PREDICTION_NOTE = (
    "Prediction uses limited historical price data and available event/sentiment information"
)


def get_connection():
    if not DB_PASSWORD:
        raise RuntimeError("MARKETPULSE_DB_PASSWORD is not set in .env")

    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


# ---------------------------------------------------------------------
# Output table
# ---------------------------------------------------------------------

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {OUTPUT_TABLE} (
    news_id BIGINT NOT NULL,
    security_id BIGINT NOT NULL,
    exchange VARCHAR(10) NOT NULL,

    event_trade_date DATE,
    published_at TIMESTAMP,
    prediction_cutoff_ts TIMESTAMP,
    cutoff_trade_date DATE,

    feed_category TEXT,
    market_news_category TEXT,
    ai_event_type TEXT,
    ai_event_status TEXT,
    ai_sentiment TEXT,

    publication_hour INTEGER,
    publication_minute INTEGER,
    publication_weekday INTEGER,
    is_pre_market BOOLEAN,
    is_post_market BOOLEAN,

    close DOUBLE PRECISION,
    open DOUBLE PRECISION,
    high DOUBLE PRECISION,
    low DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    turnover DOUBLE PRECISION,
    daily_return DOUBLE PRECISION,

    rsi_14 DOUBLE PRECISION,
    macd DOUBLE PRECISION,
    macd_signal DOUBLE PRECISION,
    macd_hist DOUBLE PRECISION,
    bb_position_20 DOUBLE PRECISION,
    sma_5 DOUBLE PRECISION,
    sma_10 DOUBLE PRECISION,
    sma_20 DOUBLE PRECISION,
    ema_5 DOUBLE PRECISION,
    ema_10 DOUBLE PRECISION,
    ema_20 DOUBLE PRECISION,
    atr_14 DOUBLE PRECISION,
    volatility_20d DOUBLE PRECISION,
    relative_volume_20 DOUBLE PRECISION,
    close_vs_sma20 DOUBLE PRECISION,
    volume_ratio_5d DOUBLE PRECISION,
    range_pct DOUBLE PRECISION,
    momentum_5d DOUBLE PRECISION,
    momentum_10d DOUBLE PRECISION,
    momentum_20d DOUBLE PRECISION,

    return_mean_5d DOUBLE PRECISION,
    return_std_5d DOUBLE PRECISION,
    return_mean_10d DOUBLE PRECISION,
    return_std_10d DOUBLE PRECISION,
    return_mean_20d DOUBLE PRECISION,
    return_std_20d DOUBLE PRECISION,
    volatility_mean_5d DOUBLE PRECISION,
    volatility_mean_10d DOUBLE PRECISION,
    volatility_mean_20d DOUBLE PRECISION,
    volume_ratio_mean_5d DOUBLE PRECISION,
    volume_ratio_mean_10d DOUBLE PRECISION,
    volume_ratio_mean_20d DOUBLE PRECISION,
    volume_mean_5d DOUBLE PRECISION,
    volume_mean_20d DOUBLE PRECISION,
    high_20d DOUBLE PRECISION,
    low_20d DOUBLE PRECISION,
    distance_from_high_20d DOUBLE PRECISION,
    distance_from_low_20d DOUBLE PRECISION,
    max_drawdown_20d DOUBLE PRECISION,
    price_trend_20d DOUBLE PRECISION,
    volume_trend_20d DOUBLE PRECISION,

    sequence_rows INTEGER,
    sequence_length INTEGER,
    prediction_eligible BOOLEAN,
    prediction_note TEXT,

    has_1d_label BOOLEAN,
    has_3d_label BOOLEAN,
    has_5d_label BOOLEAN,
    has_10d_label BOOLEAN,

    backward_return_1d DOUBLE PRECISION,
    backward_return_5d DOUBLE PRECISION,
    backward_return_10d DOUBLE PRECISION,

    forward_return_1d DOUBLE PRECISION,
    forward_return_3d DOUBLE PRECISION,
    forward_return_5d DOUBLE PRECISION,
    forward_return_10d DOUBLE PRECISION,

    direction_1d TEXT,
    direction_3d TEXT,
    direction_5d TEXT,
    direction_10d TEXT,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (news_id, security_id, exchange)
);
"""

MIGRATE_SQL = f"""
ALTER TABLE {OUTPUT_TABLE}
    ADD COLUMN IF NOT EXISTS exchange VARCHAR(10);

ALTER TABLE {OUTPUT_TABLE}
    ADD COLUMN IF NOT EXISTS prediction_eligible BOOLEAN;

ALTER TABLE {OUTPUT_TABLE}
    ADD COLUMN IF NOT EXISTS prediction_note TEXT;
"""

INDEXES_SQL = f"""
CREATE INDEX IF NOT EXISTS idx_ml_features_security_exchange
    ON {OUTPUT_TABLE}(security_id, exchange);

CREATE INDEX IF NOT EXISTS idx_ml_features_event_date
    ON {OUTPUT_TABLE}(event_trade_date);

CREATE INDEX IF NOT EXISTS idx_ml_features_published
    ON {OUTPUT_TABLE}(published_at);

CREATE INDEX IF NOT EXISTS idx_ml_features_exchange
    ON {OUTPUT_TABLE}(exchange);
"""


def prepare_output_table(conn, rebuild=False):
    with conn.cursor() as cur:
        if rebuild:
            # Rebuild only the derived feature layer.
            # PIT samples and labels are untouched.
            cur.execute(f"DROP TABLE IF EXISTS {OUTPUT_TABLE};")
            cur.execute(CREATE_TABLE_SQL)

        else:
            # Create the table if it does not already exist.
            cur.execute(CREATE_TABLE_SQL)

            # Check whether an existing primary key is already present.
            cur.execute(
                f"""
                SELECT
                    conname,
                    pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = '{OUTPUT_TABLE}'::regclass
                  AND contype = 'p';
                """
            )

            existing_pk = cur.fetchone()

            if existing_pk is None:
                # No primary key exists — create the required exchange-aware PK.
                cur.execute(
                    f"""
                    ALTER TABLE {OUTPUT_TABLE}
                    ADD CONSTRAINT pk_{OUTPUT_TABLE}
                    PRIMARY KEY (news_id, security_id, exchange);
                    """
                )

            else:
                pk_name, pk_definition = existing_pk

                # The database already has a primary key.
                # Do not create another one if it is already exchange-aware.
                expected_pk = (
                    "PRIMARY KEY (news_id, security_id, exchange)"
                )

                if pk_definition.strip().upper() != expected_pk.upper():
                    print(
                        f"  Existing primary key detected: "
                        f"{pk_name} -> {pk_definition}"
                    )
                    print(
                        "  Existing PK is not exchange-aware; "
                        "migrating it."
                    )

                    cur.execute(
                        f"""
                        ALTER TABLE {OUTPUT_TABLE}
                        DROP CONSTRAINT "{pk_name}";
                        """
                    )

                    cur.execute(
                        f"""
                        ALTER TABLE {OUTPUT_TABLE}
                        ADD CONSTRAINT pk_{OUTPUT_TABLE}
                        PRIMARY KEY (news_id, security_id, exchange);
                        """
                    )
                else:
                    print(
                        f"  Existing PK is correct: "
                        f"{pk_name} -> {pk_definition}"
                    )

        # Create indexes safely.
        cur.execute(INDEXES_SQL)

    conn.commit()

# ---------------------------------------------------------------------
# Source / target discovery
# ---------------------------------------------------------------------

def source_grain_counts(conn):
    sql = """
    SELECT
        s.exchange,
        COUNT(*) AS sample_rows,
        COUNT(DISTINCT s.news_id) AS events,
        COUNT(DISTINCT s.security_id) AS securities
    FROM market_news_ml_samples s
    JOIN market_news mn ON mn.news_id = s.news_id
    WHERE s.security_id IS NOT NULL
      AND s.exchange IS NOT NULL
      AND mn.published_at IS NOT NULL
    GROUP BY s.exchange
    ORDER BY s.exchange;
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def feature_grain_counts(conn):
    sql = f"""
    SELECT
        exchange,
        COUNT(*) AS feature_rows,
        COUNT(DISTINCT news_id) AS events,
        COUNT(DISTINCT security_id) AS securities
    FROM {OUTPUT_TABLE}
    GROUP BY exchange
    ORDER BY exchange;
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def get_target_news_ids(conn, limit=None, exact_ids=None):
    """
    Select event IDs whose exchange-grain feature rows are missing/stale.

    A news_id is processed once, but its complete NSE/BSE population is
    rebuilt together. This is intentional: the SQL inside the batch keeps
    exchange separate.
    """
    if exact_ids is not None:
        return sorted(set(int(x) for x in exact_ids))

    sql = f"""
    WITH source_grain AS (
        SELECT
            s.news_id,
            s.security_id,
            s.exchange,
            COUNT(*) AS sample_rows
        FROM market_news_ml_samples s
        JOIN market_news mn ON mn.news_id = s.news_id
        WHERE s.security_id IS NOT NULL
          AND s.exchange IS NOT NULL
          AND mn.published_at IS NOT NULL
        GROUP BY s.news_id, s.security_id, s.exchange
    ),
    missing_grain AS (
        SELECT sg.news_id
        FROM source_grain sg
        LEFT JOIN {OUTPUT_TABLE} f
          ON f.news_id = sg.news_id
         AND f.security_id = sg.security_id
         AND f.exchange = sg.exchange
        WHERE f.news_id IS NULL
           OR f.sequence_rows IS DISTINCT FROM sg.sample_rows
           OR f.sequence_length IS DISTINCT FROM sg.sample_rows
           OR f.prediction_eligible IS NULL
        GROUP BY sg.news_id
    )
    SELECT news_id
    FROM missing_grain
    ORDER BY news_id
    """

    if limit is not None:
        sql += " LIMIT %s"

    with conn.cursor() as cur:
        cur.execute(sql, (limit,) if limit is not None else ())
        return [int(row[0]) for row in cur.fetchall()]


# ---------------------------------------------------------------------
# Exchange-aware feature SQL
# ---------------------------------------------------------------------

FEATURE_SQL = f"""
WITH base AS (
    SELECT
        s.*,

        ROW_NUMBER() OVER (
            PARTITION BY s.news_id, s.security_id, s.exchange
            ORDER BY s.trade_date DESC
        ) AS reverse_row_number

    FROM market_news_ml_samples s
    JOIN market_news mn
      ON mn.news_id = s.news_id

    WHERE s.news_id = ANY(%s::BIGINT[])
      AND s.security_id IS NOT NULL
      AND s.exchange IS NOT NULL
      AND mn.published_at IS NOT NULL
      AND mn.published_at >= TIMESTAMP '2025-01-01'
      AND mn.published_at < TIMESTAMP '2026-09-01' + INTERVAL '1 day'
),

event_rows AS (
    SELECT *
    FROM base
),

latest AS (
    SELECT *
    FROM event_rows
    WHERE reverse_row_number = 1
),

recent AS (
    SELECT
        news_id,
        security_id,
        exchange,

        COUNT(*) AS sequence_rows,

        AVG(daily_return)
            FILTER (WHERE reverse_row_number <= 5) AS return_mean_5d,

        STDDEV_SAMP(daily_return)
            FILTER (WHERE reverse_row_number <= 5) AS return_std_5d,

        AVG(daily_return)
            FILTER (WHERE reverse_row_number <= 10) AS return_mean_10d,

        STDDEV_SAMP(daily_return)
            FILTER (WHERE reverse_row_number <= 10) AS return_std_10d,

        AVG(daily_return)
            FILTER (WHERE reverse_row_number <= 20) AS return_mean_20d,

        STDDEV_SAMP(daily_return)
            FILTER (WHERE reverse_row_number <= 20) AS return_std_20d,

        AVG(volatility_5d)
            FILTER (WHERE reverse_row_number <= 5) AS volatility_mean_5d,

        AVG(volatility_5d)
            FILTER (WHERE reverse_row_number <= 10) AS volatility_mean_10d,

        AVG(volatility_20d)
            FILTER (WHERE reverse_row_number <= 20) AS volatility_mean_20d,

        AVG(volume_ratio_5d)
            FILTER (WHERE reverse_row_number <= 5) AS volume_ratio_mean_5d,

        AVG(volume_ratio_5d)
            FILTER (WHERE reverse_row_number <= 10) AS volume_ratio_mean_10d,

        AVG(volume_ratio_5d)
            FILTER (WHERE reverse_row_number <= 20) AS volume_ratio_mean_20d,

        AVG(volume)
            FILTER (WHERE reverse_row_number <= 5) AS volume_mean_5d,

        AVG(volume)
            FILTER (WHERE reverse_row_number <= 20) AS volume_mean_20d,

        CASE
            WHEN MAX(close) FILTER (WHERE reverse_row_number = 2) IS NOT NULL
             AND MAX(close) FILTER (WHERE reverse_row_number = 2) <> 0
            THEN
                MAX(close) FILTER (WHERE reverse_row_number = 1)
                / MAX(close) FILTER (WHERE reverse_row_number = 2) - 1.0
        END AS backward_return_1d,

        CASE
            WHEN MAX(close) FILTER (WHERE reverse_row_number = 6) IS NOT NULL
             AND MAX(close) FILTER (WHERE reverse_row_number = 6) <> 0
            THEN
                MAX(close) FILTER (WHERE reverse_row_number = 1)
                / MAX(close) FILTER (WHERE reverse_row_number = 6) - 1.0
        END AS backward_return_5d,

        CASE
            WHEN MAX(close) FILTER (WHERE reverse_row_number = 11) IS NOT NULL
             AND MAX(close) FILTER (WHERE reverse_row_number = 11) <> 0
            THEN
                MAX(close) FILTER (WHERE reverse_row_number = 1)
                / MAX(close) FILTER (WHERE reverse_row_number = 11) - 1.0
        END AS backward_return_10d,

        MAX(high)
            FILTER (WHERE reverse_row_number <= 20) AS high_20d,

        MIN(low)
            FILTER (WHERE reverse_row_number <= 20) AS low_20d,

        -REGR_SLOPE(close, reverse_row_number)
            FILTER (WHERE reverse_row_number <= 20) AS price_trend_20d,

        -REGR_SLOPE(volume, reverse_row_number)
            FILTER (WHERE reverse_row_number <= 20) AS volume_trend_20d

    FROM event_rows
    GROUP BY news_id, security_id, exchange
),

drawdown_rows AS (
    SELECT
        news_id,
        security_id,
        exchange,
        trade_date,
        close,
        reverse_row_number,

        MAX(close) OVER (
            PARTITION BY news_id, security_id, exchange
            ORDER BY trade_date
            ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
        ) AS rolling_high_20d

    FROM event_rows
    WHERE reverse_row_number <= 20
),

drawdown_summary AS (
    SELECT
        news_id,
        security_id,
        exchange,

        MIN(
            CASE
                WHEN rolling_high_20d > 0
                THEN close / rolling_high_20d - 1.0
            END
        ) AS max_drawdown_20d

    FROM drawdown_rows
    GROUP BY news_id, security_id, exchange
)

SELECT
    l.news_id,
    l.security_id,
    l.exchange,

    l.event_trade_date,
    mn.published_at,
    l.prediction_cutoff_ts,
    l.cutoff_trade_date,

    l.feed_category,
    mn.category AS market_news_category,

    l.ai_event_type,
    l.ai_event_status,
    l.ai_sentiment,

    EXTRACT(HOUR FROM mn.published_at)::INTEGER AS publication_hour,
    EXTRACT(MINUTE FROM mn.published_at)::INTEGER AS publication_minute,
    EXTRACT(DOW FROM mn.published_at)::INTEGER AS publication_weekday,

    CASE
        WHEN mn.published_at::time < TIME '09:15:00'
        THEN TRUE ELSE FALSE
    END AS is_pre_market,

    CASE
        WHEN mn.published_at::time > TIME '15:30:00'
        THEN TRUE ELSE FALSE
    END AS is_post_market,

    l.close,
    l.open,
    l.high,
    l.low,
    l.volume,
    l.turnover,
    l.daily_return,

    l.rsi_14,
    l.macd,
    l.macd_signal,
    l.macd_hist,
    l.bb_position_20,
    l.sma_5,
    l.sma_10,
    l.sma_20,
    l.ema_5,
    l.ema_10,
    l.ema_20,
    l.atr_14,
    l.volatility_20d,
    l.relative_volume_20,
    l.close_vs_sma20,
    l.volume_ratio_5d,
    l.range_pct,
    l.momentum_5d,
    l.momentum_10d,
    l.momentum_20d,

    r.return_mean_5d,
    r.return_std_5d,
    r.return_mean_10d,
    r.return_std_10d,
    r.return_mean_20d,
    r.return_std_20d,
    r.volatility_mean_5d,
    r.volatility_mean_10d,
    r.volatility_mean_20d,
    r.volume_ratio_mean_5d,
    r.volume_ratio_mean_10d,
    r.volume_ratio_mean_20d,
    r.volume_mean_5d,
    r.volume_mean_20d,
    r.high_20d,
    r.low_20d,

    CASE
        WHEN r.high_20d IS NOT NULL AND r.high_20d <> 0
        THEN l.close / r.high_20d - 1.0
    END AS distance_from_high_20d,

    CASE
        WHEN r.low_20d IS NOT NULL AND r.low_20d <> 0
        THEN l.close / r.low_20d - 1.0
    END AS distance_from_low_20d,

    d.max_drawdown_20d,

    r.price_trend_20d,
    r.volume_trend_20d,

    r.sequence_rows,
    r.sequence_rows AS sequence_length,

    CASE
        WHEN r.sequence_rows >= 20
        THEN TRUE
        ELSE FALSE
    END AS prediction_eligible,

    CASE
        WHEN r.sequence_rows < 20
        THEN %s
        ELSE NULL
    END AS prediction_note,

    CASE WHEN lab.forward_return_1d IS NOT NULL THEN TRUE ELSE FALSE END AS has_1d_label,
    CASE WHEN lab.forward_return_3d IS NOT NULL THEN TRUE ELSE FALSE END AS has_3d_label,
    CASE WHEN lab.forward_return_5d IS NOT NULL THEN TRUE ELSE FALSE END AS has_5d_label,
    CASE WHEN lab.forward_return_10d IS NOT NULL THEN TRUE ELSE FALSE END AS has_10d_label,

    r.backward_return_1d,
    r.backward_return_5d,
    r.backward_return_10d,

    lab.forward_return_1d,
    lab.forward_return_3d,
    lab.forward_return_5d,
    lab.forward_return_10d,

    lab.direction_1d,
    lab.direction_3d,
    lab.direction_5d,
    lab.direction_10d

FROM latest l

JOIN recent r
  ON r.news_id = l.news_id
 AND r.security_id = l.security_id
 AND r.exchange = l.exchange

LEFT JOIN drawdown_summary d
  ON d.news_id = l.news_id
 AND d.security_id = l.security_id
 AND d.exchange = l.exchange

JOIN market_news mn
  ON mn.news_id = l.news_id

LEFT JOIN market_news_ml_labels lab
  ON lab.news_id = l.news_id
 AND lab.security_id = l.security_id
 AND lab.exchange = l.exchange

ORDER BY l.news_id, l.security_id, l.exchange;
"""


INSERT_COLUMNS = [
    "news_id", "security_id", "exchange",
    "event_trade_date", "published_at", "prediction_cutoff_ts", "cutoff_trade_date",
    "feed_category", "market_news_category", "ai_event_type", "ai_event_status",
    "ai_sentiment", "publication_hour", "publication_minute", "publication_weekday",
    "is_pre_market", "is_post_market",
    "close", "open", "high", "low", "volume", "turnover", "daily_return",
    "rsi_14", "macd", "macd_signal", "macd_hist", "bb_position_20",
    "sma_5", "sma_10", "sma_20", "ema_5", "ema_10", "ema_20", "atr_14",
    "volatility_20d", "relative_volume_20", "close_vs_sma20", "volume_ratio_5d",
    "range_pct", "momentum_5d", "momentum_10d", "momentum_20d",
    "return_mean_5d", "return_std_5d", "return_mean_10d", "return_std_10d",
    "return_mean_20d", "return_std_20d",
    "volatility_mean_5d", "volatility_mean_10d", "volatility_mean_20d",
    "volume_ratio_mean_5d", "volume_ratio_mean_10d", "volume_ratio_mean_20d",
    "volume_mean_5d", "volume_mean_20d", "high_20d", "low_20d",
    "distance_from_high_20d", "distance_from_low_20d", "max_drawdown_20d",
    "price_trend_20d", "volume_trend_20d",
    "sequence_rows", "sequence_length", "prediction_eligible", "prediction_note",
    "has_1d_label", "has_3d_label", "has_5d_label", "has_10d_label",
    "backward_return_1d", "backward_return_5d", "backward_return_10d",
    "forward_return_1d", "forward_return_3d", "forward_return_5d",
    "forward_return_10d",
    "direction_1d", "direction_3d", "direction_5d", "direction_10d",
]

UPDATE_COLUMNS = [c for c in INSERT_COLUMNS if c not in {"news_id", "security_id", "exchange"}]

INSERT_SQL = f"""
INSERT INTO {OUTPUT_TABLE} (
    {", ".join(INSERT_COLUMNS)}
)
VALUES %s
ON CONFLICT (news_id, security_id, exchange)
DO UPDATE SET
    {", ".join(f"{c}=EXCLUDED.{c}" for c in UPDATE_COLUMNS)},
    updated_at=CURRENT_TIMESTAMP;
"""


def build_batch(conn, news_ids):
    with conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '600000'")
        cur.execute(FEATURE_SQL, (list(news_ids), SHORT_HISTORY_PREDICTION_NOTE))
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()

    if not rows:
        return 0

    idx = {name: i for i, name in enumerate(columns)}
    values = [
        tuple(row[idx[col]] for col in INSERT_COLUMNS)
        for row in rows
    ]

    with conn.cursor() as cur:
        execute_values(cur, INSERT_SQL, values, page_size=1000)

    conn.commit()
    return len(values)


# ---------------------------------------------------------------------
# Audits
# ---------------------------------------------------------------------

def audit_exchange_grain(conn):
    print("\nExchange feature coverage:")
    for row in feature_grain_counts(conn):
        print(
            f"  {row[0]:<5} "
            f"feature_rows={row[1]:,} "
            f"events={row[2]:,} "
            f"securities={row[3]:,}"
        )

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT news_id, security_id, exchange, COUNT(*) AS n
                FROM {OUTPUT_TABLE}
                GROUP BY news_id, security_id, exchange
                HAVING COUNT(*) > 1
            ) x;
            """
        )
        duplicate_grain = cur.fetchone()[0]

        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT news_id, security_id, exchange
                FROM {OUTPUT_TABLE}
                GROUP BY news_id, security_id, exchange
            ) x;
            """
        )
        unique_grain = cur.fetchone()[0]

    print(f"  Duplicate exchange-grain keys: {duplicate_grain:,}")
    print(f"  Unique exchange-grain keys     : {unique_grain:,}")

    if duplicate_grain:
        raise RuntimeError("Duplicate feature grain detected.")


def main():
    parser = argparse.ArgumentParser(
        description="Build exchange-aware MarketPulse event-level features."
    )

    parser.add_argument("--limit", type=int, default=None,
                        help="Number of event IDs to process.")
    parser.add_argument("--new", action="store_true",
                        help="Process missing/stale exchange-grain events.")
    parser.add_argument("--rebuild", action="store_true",
                        help="Drop and recreate only the derived feature table.")
    parser.add_argument("--news-ids-file", type=str,
                        help="Process exactly the news_id values listed in this file.")
    parser.add_argument("--batch-size", type=int, default=1000)

    args = parser.parse_args()

    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be > 0")

    if args.batch_size <= 0:
        parser.error("--batch-size must be > 0")

    modes = sum([
        bool(args.new),
        bool(args.rebuild),
        bool(args.news_ids_file),
    ])

    if modes > 1:
        parser.error("--new, --rebuild and --news-ids-file are mutually exclusive.")

    if args.news_ids_file and args.limit:
        parser.error("--limit cannot be combined with --news-ids-file.")

    print("=" * 72)
    print("MarketPulse - Exchange-Aware Event-Level Feature Engineering")
    print("=" * 72)
    print(f"Database     : {DB_NAME}")
    print(f"Output table : {OUTPUT_TABLE}")
    print(f"Grain        : (news_id, security_id, exchange)")
    print(f"Date range   : {TRAINING_START} -> {TRAINING_END}")
    print(f"Batch size   : {args.batch_size:,}")

    conn = None

    try:
        conn = get_connection()
        print("\nDatabase connection: OK")

        if args.rebuild:
            print("\nREBUILD MODE: dropping derived feature table only.")
            prepare_output_table(conn, rebuild=True)
        else:
            prepare_output_table(conn, rebuild=False)

        print("\nSource coverage:")
        for row in source_grain_counts(conn):
            print(
                f"  {row[0]:<5} "
                f"sample_rows={row[1]:,} "
                f"events={row[2]:,} "
                f"securities={row[3]:,}"
            )

        exact_ids = None
        if args.news_ids_file:
            exact_ids = [
                int(x.strip())
                for x in Path(args.news_ids_file).read_text(
                    encoding="utf-8"
                ).splitlines()
                if x.strip() and not x.lstrip().startswith("#")
            ]

        if args.rebuild:
            target_ids = get_target_news_ids(
                conn,
                limit=args.limit,
                exact_ids=exact_ids,
            )
        elif args.news_ids_file:
            target_ids = get_target_news_ids(conn, exact_ids=exact_ids)
        elif args.new:
            target_ids = get_target_news_ids(conn, limit=args.limit)
        elif args.limit is not None:
            # Safe limited test: choose event IDs first.
            target_ids = get_target_news_ids(conn, limit=args.limit)
        else:
            # No explicit mode means full exchange-grain recovery.
            target_ids = get_target_news_ids(conn)

        print(f"\nTarget event IDs: {len(target_ids):,}")

        if not target_ids:
            print("Nothing to build.")
            audit_exchange_grain(conn)
            return 0

        total_rows = 0

        for start in range(0, len(target_ids), args.batch_size):
            batch = target_ids[start:start + args.batch_size]

            print(
                f"\nProcessing events "
                f"{start + 1:,}-{start + len(batch):,} "
                f"of {len(target_ids):,}"
            )

            rows = build_batch(conn, batch)
            total_rows += rows

            print(f"  Feature rows written: {rows:,}")

        print("\n" + "=" * 72)
        print("FINAL EXCHANGE-GRAIN AUDIT")
        print("=" * 72)

        audit_exchange_grain(conn)

        print("\n" + "=" * 72)
        print("SUCCESS")
        print("=" * 72)
        print(f"Feature rows written this run: {total_rows:,}")

        return 0

    except Exception:
        if conn:
            conn.rollback()
        traceback.print_exc()
        return 1

    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
