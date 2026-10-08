"""
MarketPulse - Pipeline Coverage / Reason Reconciler V2

Purpose
-------
Create a durable one-row-per-market_news audit showing exactly where each
event is in the PIT -> Features -> LightGBM pipeline.

This is NOT a model and does NOT retrain anything.

It is safe to rerun. It updates only market_news_ml_pipeline_audit.

Reason hierarchy
----------------
1. NOT_APPLICABLE      : non-stock feed
2. NO_PUBLISHED_AT     : no publication timestamp
3. NOT_MAPPED          : no mapped security
4. NO_HISTORY          : no completed price rows before PIT cutoff
5. INSUFFICIENT_HISTORY: fewer than 20 completed rows
6. FEATURES_MISSING    : enough history but no feature row
7. NOT_ELIGIBLE        : feature row exists but prediction_eligible=false
8. PREDICTION_PENDING  : eligible feature exists but one or more horizons absent
9. SCORED              : all three LightGBM horizons exist

The audit deliberately distinguishes:
- mapping state
- PIT/feature state
- prediction state
- observed outcome state

Run:
    python src/backend/marketpulse_pipeline_coverage.py --all
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv

IST_CLOSE_HOUR = 15
IST_CLOSE_MINUTE = 30


def load_environment() -> None:
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]
    for candidate in candidates:
        if candidate.exists():
            load_dotenv(candidate)
            return
    load_dotenv()


def db_config() -> dict[str, Any]:
    cfg = {
        "host": os.getenv("MARKETPULSE_DB_HOST", "localhost"),
        "port": int(os.getenv("MARKETPULSE_DB_PORT", "5432")),
        "dbname": os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
        "user": os.getenv("MARKETPULSE_DB_USER", "postgres"),
        "password": os.getenv("MARKETPULSE_DB_PASSWORD", ""),
    }
    if not cfg["password"]:
        raise RuntimeError("MARKETPULSE_DB_PASSWORD is not configured.")
    return cfg


def get_connection():
    return psycopg.connect(**db_config())


def ensure_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS market_news_ml_pipeline_audit (
                news_id BIGINT PRIMARY KEY REFERENCES market_news(news_id) ON DELETE CASCADE,
                mapping_status TEXT,
                asset_category TEXT,
                pit_status TEXT,
                pit_reason TEXT,
                pit_reason_detail TEXT,
                feature_status TEXT,
                feature_reason TEXT,
                feature_reason_detail TEXT,
                prediction_1d_status TEXT,
                prediction_1d_reason TEXT,
                prediction_5d_status TEXT,
                prediction_5d_reason TEXT,
                prediction_10d_status TEXT,
                prediction_10d_reason TEXT,
                actual_1d_status TEXT,
                actual_5d_status TEXT,
                actual_10d_status TEXT,
                last_stage TEXT,
                checked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ml_pipeline_audit_pit_status
            ON market_news_ml_pipeline_audit(pit_status);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ml_pipeline_audit_feature_status
            ON market_news_ml_pipeline_audit(feature_status);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_ml_pipeline_audit_mapping
            ON market_news_ml_pipeline_audit(mapping_status, asset_category);
        """)
    conn.commit()


def cutoff_date_expr() -> str:
    return """
        CASE
            WHEN (mn.published_at AT TIME ZONE 'Asia/Kolkata')::time > TIME '15:30'
                THEN (mn.published_at AT TIME ZONE 'Asia/Kolkata')::date
            ELSE ((mn.published_at AT TIME ZONE 'Asia/Kolkata')::date - INTERVAL '1 day')::date
        END
    """


def reconcile(conn, start_id: int | None, end_id: int | None) -> dict[str, int]:
    conditions = []
    params: list[Any] = []

    if start_id is not None:
        conditions.append("mn.news_id >= %s")
        params.append(start_id)
    if end_id is not None:
        conditions.append("mn.news_id <= %s")
        params.append(end_id)

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
        WITH base AS (
            SELECT
                mn.news_id,
                mn.news_scope,
                mn.mapping_status,
                mn.asset_category,
                mn.security_id,
                mn.published_at,
                f.news_id AS feature_news_id,
                f.prediction_eligible,
                f.sequence_length,
                f.forward_return_1d,
                f.forward_return_5d,
                f.forward_return_10d,
                p1.news_id AS p1_news_id,
                p5.news_id AS p5_news_id,
                p10.news_id AS p10_news_id,
                (
                    SELECT COUNT(*)
                    FROM daily_prices dp
                    WHERE dp.security_id = mn.security_id
                    AND mn.published_at IS NOT NULL
                    AND dp.trade_date BETWEEN
                        ({cutoff_date_expr()} - INTERVAL '140 days')
                        AND {cutoff_date_expr()}
                ) AS history_rows
            FROM market_news mn
            LEFT JOIN market_news_ml_features f
                ON f.news_id = mn.news_id
            LEFT JOIN market_news_ml_predictions p1
                ON p1.news_id = mn.news_id AND p1.horizon = 1
            LEFT JOIN market_news_ml_predictions p5
                ON p5.news_id = mn.news_id AND p5.horizon = 5
            LEFT JOIN market_news_ml_predictions p10
                ON p10.news_id = mn.news_id AND p10.horizon = 10
            {where_sql}
        ),
        classified AS (
            SELECT *,
                CASE
                    WHEN news_scope IS DISTINCT FROM 'STOCK'
                        THEN 'NOT_APPLICABLE'
                    WHEN published_at IS NULL
                        THEN 'NO_PUBLISHED_AT'
                    WHEN COALESCE(UPPER(TRIM(mapping_status)), '') <> 'MAPPED'
                         OR security_id IS NULL
                        THEN 'NOT_MAPPED'
                    WHEN history_rows = 0
                        THEN 'NO_HISTORY'
                    WHEN history_rows < 20
                        THEN 'INSUFFICIENT_HISTORY'
                    WHEN feature_news_id IS NULL
                        THEN 'FEATURES_MISSING'
                    WHEN prediction_eligible IS FALSE
                        THEN 'NOT_ELIGIBLE'
                    WHEN p1_news_id IS NULL
                      OR p5_news_id IS NULL
                      OR p10_news_id IS NULL
                        THEN 'PREDICTION_PENDING'
                    ELSE 'SCORED'
                END AS overall_reason
            FROM base
        )
        SELECT * FROM classified
        ORDER BY news_id;
    """

    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        columns = [d.name for d in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]

    upsert = """
        INSERT INTO market_news_ml_pipeline_audit (
            news_id, mapping_status, asset_category,
            pit_status, pit_reason, pit_reason_detail,
            feature_status, feature_reason, feature_reason_detail,
            prediction_1d_status, prediction_1d_reason,
            prediction_5d_status, prediction_5d_reason,
            prediction_10d_status, prediction_10d_reason,
            actual_1d_status, actual_5d_status, actual_10d_status,
            last_stage, checked_at, updated_at
        )
        VALUES (
            %s,%s,%s,
            %s,%s,%s,
            %s,%s,%s,
            %s,%s,
            %s,%s,
            %s,%s,
            %s,%s,%s,
            %s,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP
        )
        ON CONFLICT (news_id) DO UPDATE SET
            mapping_status = EXCLUDED.mapping_status,
            asset_category = EXCLUDED.asset_category,
            pit_status = EXCLUDED.pit_status,
            pit_reason = EXCLUDED.pit_reason,
            pit_reason_detail = EXCLUDED.pit_reason_detail,
            feature_status = EXCLUDED.feature_status,
            feature_reason = EXCLUDED.feature_reason,
            feature_reason_detail = EXCLUDED.feature_reason_detail,
            prediction_1d_status = EXCLUDED.prediction_1d_status,
            prediction_1d_reason = EXCLUDED.prediction_1d_reason,
            prediction_5d_status = EXCLUDED.prediction_5d_status,
            prediction_5d_reason = EXCLUDED.prediction_5d_reason,
            prediction_10d_status = EXCLUDED.prediction_10d_status,
            prediction_10d_reason = EXCLUDED.prediction_10d_reason,
            actual_1d_status = EXCLUDED.actual_1d_status,
            actual_5d_status = EXCLUDED.actual_5d_status,
            actual_10d_status = EXCLUDED.actual_10d_status,
            last_stage = EXCLUDED.last_stage,
            checked_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
    """

    counts: dict[str, int] = {}

    with conn.cursor() as cur:
        for r in rows:
            reason = r["overall_reason"]

            if reason == "NOT_APPLICABLE":
                pit_status, pit_reason = "EXCLUDED", "NOT_APPLICABLE"
                feature_status, feature_reason = "NOT_APPLICABLE", "NOT_STOCK"
                p1 = p5 = p10 = ("NOT_AVAILABLE", "NOT_APPLICABLE")
                last_stage = "ROUTING"
            elif reason == "NO_PUBLISHED_AT":
                pit_status, pit_reason = "EXCLUDED", "NO_PUBLISHED_AT"
                feature_status, feature_reason = "NOT_AVAILABLE", "NO_PUBLISHED_AT"
                p1 = p5 = p10 = ("NOT_AVAILABLE", "NO_PUBLISHED_AT")
                last_stage = "PIT"
            elif reason == "NOT_MAPPED":
                pit_status, pit_reason = "EXCLUDED", "NOT_MAPPED"
                feature_status, feature_reason = "NOT_AVAILABLE", "NOT_MAPPED"
                p1 = p5 = p10 = ("NOT_AVAILABLE", "NOT_MAPPED")
                last_stage = "MAPPING"
            elif reason == "NO_HISTORY":
                pit_status, pit_reason = "EXCLUDED", "NO_HISTORY"
                feature_status, feature_reason = "NOT_AVAILABLE", "NO_HISTORY"
                p1 = p5 = p10 = ("NOT_AVAILABLE", "NO_HISTORY")
                last_stage = "PIT"
            elif reason == "INSUFFICIENT_HISTORY":
                pit_status, pit_reason = "EXCLUDED", "INSUFFICIENT_HISTORY"
                feature_status, feature_reason = "NOT_AVAILABLE", "INSUFFICIENT_HISTORY"
                p1 = p5 = p10 = ("NOT_AVAILABLE", "INSUFFICIENT_HISTORY")
                last_stage = "PIT"
            elif reason == "FEATURES_MISSING":
                pit_status, pit_reason = "READY", "HISTORY_AVAILABLE"
                detail = f"{r['history_rows']} completed price rows before PIT cutoff"
                feature_status, feature_reason = "MISSING", "FEATURES_NOT_BUILT"
                p1 = p5 = p10 = ("NOT_AVAILABLE", "NO_FEATURES")
                last_stage = "FEATURES"
            elif reason == "NOT_ELIGIBLE":
                pit_status, pit_reason = "READY", "HISTORY_AVAILABLE"
                feature_status, feature_reason = "AVAILABLE", "PREDICTION_INELIGIBLE"
                detail = f"sequence_length={r['sequence_length']}"
                p1 = p5 = p10 = ("NOT_AVAILABLE", "NOT_ELIGIBLE")
                last_stage = "FEATURES"
            elif reason == "PREDICTION_PENDING":
                pit_status, pit_reason = "READY", "HISTORY_AVAILABLE"
                feature_status, feature_reason = "AVAILABLE", "READY_FOR_SCORING"
                detail = None
                p1 = (
                    ("AVAILABLE", None) if r["p1_news_id"] else
                    ("NOT_AVAILABLE", "NO_PREDICTION")
                )
                p5 = (
                    ("AVAILABLE", None) if r["p5_news_id"] else
                    ("NOT_AVAILABLE", "NO_PREDICTION")
                )
                p10 = (
                    ("AVAILABLE", None) if r["p10_news_id"] else
                    ("NOT_AVAILABLE", "NO_PREDICTION")
                )
                last_stage = "SCORING"
            else:
                pit_status, pit_reason = "READY", "HISTORY_AVAILABLE"
                feature_status, feature_reason = "AVAILABLE", "READY_FOR_SCORING"
                detail = None
                p1 = p5 = p10 = ("AVAILABLE", None)
                last_stage = "SCORING"

            # Actual outcome availability is independent of prediction.
            actual1 = "AVAILABLE" if r["forward_return_1d"] is not None else "PENDING"
            actual5 = "AVAILABLE" if r["forward_return_5d"] is not None else "PENDING"
            actual10 = "AVAILABLE" if r["forward_return_10d"] is not None else "PENDING"

            if reason == "FEATURES_MISSING":
                detail = f"{r['history_rows']} completed price rows before PIT cutoff"
            elif reason == "NOT_ELIGIBLE":
                detail = f"sequence_length={r['sequence_length']}"
            elif reason in {"NO_HISTORY", "INSUFFICIENT_HISTORY"}:
                detail = f"completed price rows before PIT cutoff={r['history_rows']}"
            else:
                detail = None

            cur.execute(
                upsert,
                (
                    int(r["news_id"]),
                    r["mapping_status"],
                    r["asset_category"],
                    pit_status,
                    pit_reason,
                    detail,
                    feature_status,
                    feature_reason,
                    detail,
                    p1[0], p1[1],
                    p5[0], p5[1],
                    p10[0], p10[1],
                    actual1, actual5, actual10,
                    last_stage,
                ),
            )

            counts[reason] = counts.get(reason, 0) + 1

    conn.commit()
    return counts


def main() -> int:
    load_environment()

    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--start-id", type=int)
    ap.add_argument("--end-id", type=int)
    args = ap.parse_args()

    if not (args.all or args.start_id is not None or args.end_id is not None):
        ap.error("Use --all or --start-id/--end-id.")

    with get_connection() as conn:
        ensure_table(conn)
        counts = reconcile(conn, args.start_id, args.end_id)

    print("=" * 82)
    print("MARKETPULSE PIPELINE COVERAGE / REASON AUDIT")
    print("=" * 82)
    total = sum(counts.values())
    print(f"Events accounted for: {total:,}")
    print()
    for key in sorted(counts, key=lambda k: (-counts[k], k)):
        print(f"{key:24s} {counts[key]:10,}")
    print()
    print("Invariant: every selected market_news event has exactly one overall reason.")
    print("Database writes: audit table only.")
    print("=" * 82)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())