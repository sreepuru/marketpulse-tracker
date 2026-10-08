"""
MarketPulse - All Feed AI Prediction Runner

Runs the existing Gemma/Ollama AI prediction service for every market_news event,
regardless of mapping status or asset category.

Important:
- This is the LLM/event-interpretation layer, not the LightGBM price model.
- Mapping is NOT a prerequisite.
- Price outcomes are calculated only when a usable security/price history exists.
- The runner is resumable and processes only events without an existing AI prediction
  by default.

Run from project root:
    python src\\backend\\marketpulse_ai_predict_all_events.py --limit 100
    python src\\backend\\marketpulse_ai_predict_all_events.py --batch-size 100
    python src\\backend\\marketpulse_ai_predict_all_events.py --start-id 1 --end-id 10000

Before a large run, test with --limit 10.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

import psycopg
from dotenv import load_dotenv

# Direct execution puts src/backend on sys.path. Add the project root so
# src.backend.ai_prediction_service is importable on Windows and elsewhere.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# IMPORTANT: load .env BEFORE importing ai_prediction_service.
# ai_prediction_service reads DB/Ollama environment variables at import time.
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from src.backend.ai_prediction_service import predict_news

DB_CONFIG = {
    "host": os.getenv("MARKETPULSE_DB_HOST", "localhost"),
    "port": int(os.getenv("MARKETPULSE_DB_PORT", "5432")),
    "dbname": os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
    "user": os.getenv("MARKETPULSE_DB_USER", "postgres"),
    "password": os.getenv("MARKETPULSE_DB_PASSWORD", ""),
}


def get_connection():
    return psycopg.connect(**DB_CONFIG)


def load_ids(conn, start_id=None, end_id=None, limit=None):
    conditions = []
    params = []
    if start_id is not None:
        conditions.append("mn.news_id >= %s")
        params.append(start_id)
    if end_id is not None:
        conditions.append("mn.news_id <= %s")
        params.append(end_id)

    # A prior prediction is enough to consider the event processed. The latest
    # prediction remains available through the existing AI API.
    conditions.append("NOT EXISTS (SELECT 1 FROM market_news_ai_predictions p WHERE p.news_id = mn.news_id)")
    where_sql = "WHERE " + " AND ".join(conditions)
    limit_sql = "LIMIT %s" if limit else ""
    if limit:
        params.append(limit)

    sql = f"""
        SELECT mn.news_id
        FROM market_news mn
        {where_sql}
        ORDER BY mn.published_at ASC NULLS LAST, mn.news_id ASC
        {limit_sql};
    """
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        return [row[0] for row in cur.fetchall()]


def main():
    parser = argparse.ArgumentParser(description="Run MarketPulse AI prediction for every unpredicted feed event.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum events to process in this run.")
    parser.add_argument("--start-id", type=int, default=None)
    parser.add_argument("--end-id", type=int, default=None)
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to wait between events.")
    args = parser.parse_args()

    with get_connection() as conn:
        ids = load_ids(conn, args.start_id, args.end_id, args.limit)

    print("=" * 70)
    print("MARKETPULSE - ALL FEED AI PREDICTION RUNNER")
    print("=" * 70)
    print(f"Started: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"Queued events: {len(ids):,}")
    print("Mapping required: NO")
    print("Asset category required: NO")
    print("=" * 70)

    predicted = 0
    failed = 0

    for index, news_id in enumerate(ids, start=1):
        try:
            result = predict_news(news_id)
            predicted += 1
            prediction = result.get("prediction", {}) if isinstance(result, dict) else {}
            print(
                f"[{index:,}/{len(ids):,}] AI PREDICTED "
                f"news_id={news_id} "
                f"event={prediction.get('event_type', 'NOT_SURE')} "
                f"direction={prediction.get('direction', 'NOT_SURE')} "
                f"impact={prediction.get('impact_level', 'NOT_SURE')}"
            )
        except Exception as exc:
            failed += 1
            print(f"[{index:,}/{len(ids):,}] AI FAILED news_id={news_id}: {exc}")

        if args.sleep > 0 and index < len(ids):
            time.sleep(args.sleep)

    print("=" * 70)
    print("AI RUN COMPLETE")
    print(f"Predicted: {predicted:,}")
    print(f"Failed:    {failed:,}")
    print("=" * 70)

    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
