"""
MarketPulse AI Batch Runner

Runs the existing Gemma-based MarketPulse prediction service against
market_news records and stores predictions in PostgreSQL.

Design goals:
- Resumable: already-created predictions for the same model/version are skipped.
- Safe: never overwrites market_news or human feedback.
- Processes ALL news, including market-level notices.
- Stock outcomes are calculated only where the existing AI service can resolve
  a security and news_scope is STOCK.
- Default is sequential because the user's machine has 16 GB RAM / 2 GB VRAM.
- --limit can be used for a controlled test.
- --delay can reduce CPU pressure between filings.

Usage:

    python src\\backend\\marketpulse_ai_batch_runner.py --limit 10

    python src\\backend\\marketpulse_ai_batch_runner.py --all

    python src\\backend\\marketpulse_ai_batch_runner.py --all --delay 1

    python src\\backend\\marketpulse_ai_batch_runner.py --start-id 1 --end-id 2367

The runner imports the working ai_prediction_service, so there is only one
source of truth for AI prediction behavior.
"""

from __future__ import annotations

import argparse
import time
from typing import Iterable

import psycopg

from dotenv import load_dotenv

# Load the project .env before importing the AI service.
load_dotenv(
    r"D:\Dashboard\nse-dashboard\.env"
)


from ai_prediction_service import (
    DB_CONFIG,
    OLLAMA_MODEL,
    build_prompt,
    call_ollama,
    calculate_outcome,
    load_news,
    resolve_security,
    assess_outcome,
    store_outcome,
    store_prediction,
    update_auto_assessment,
)


MODEL_VERSION = "MarketPulse-V1"


def get_connection():
    return psycopg.connect(**DB_CONFIG)


def get_news_ids(
    start_id: int | None,
    end_id: int | None,
    limit: int | None,
) -> list[int]:
    conditions = []
    params = []

    if start_id is not None:
        conditions.append("news_id >= %s")
        params.append(start_id)

    if end_id is not None:
        conditions.append("news_id <= %s")
        params.append(end_id)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT %s"
        params.append(limit)

    query = f"""
        SELECT news_id
        FROM market_news
        {where}
        ORDER BY news_id ASC
        {limit_sql};
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, tuple(params))
            return [row[0] for row in cur.fetchall()]


def already_processed(news_id: int) -> bool:
    query = """
        SELECT 1
        FROM market_news_ai_predictions
        WHERE news_id = %s
          AND model_name = %s
          AND model_version = %s
        LIMIT 1;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    news_id,
                    OLLAMA_MODEL,
                    MODEL_VERSION,
                ),
            )
            return cur.fetchone() is not None


def process_news(news_id: int) -> dict:
    news = load_news(news_id)
    security = resolve_security(news)

    news_scope = str(
        news.get("news_scope") or "STOCK"
    ).upper()

    prompt = build_prompt(
        news,
        security,
    )

    prediction = call_ollama(prompt)

    stored = store_prediction(
        news,
        prediction,
        prompt,
    )

    outcome = None
    assessment = None

    published_at = news.get("published_at")

    stock_outcome_enabled = (
        security is not None
        and news_scope == "STOCK"
        and published_at is not None
    )

    if stock_outcome_enabled:
        outcome = calculate_outcome(
            stored["prediction_id"],
            news_id,
            security,
            published_at,
        )

        outcome = store_outcome(outcome)

        assessment = assess_outcome(
            prediction,
            outcome,
        )

        update_auto_assessment(
            outcome["outcome_id"],
            assessment,
        )

    return {
        "news_id": news_id,
        "company_name": news.get("company_name"),
        "exchange": news.get("exchange"),
        "category": news.get("category"),
        "security_id": (
            security["security_id"]
            if security
            else None
        ),
        "stock_outcome_enabled": stock_outcome_enabled,
        "prediction_id": stored["prediction_id"],
        "event_type": prediction["event_type"],
        "event_status": prediction["event_status"],
        "direction": prediction["direction"],
        "impact_level": prediction["impact_level"],
        "confidence": prediction["confidence"],
        "outcome": outcome,
        "assessment": assessment,
    }


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all market_news records.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only this many records.",
    )

    parser.add_argument(
        "--start-id",
        type=int,
        default=None,
        help="First news_id to process.",
    )

    parser.add_argument(
        "--end-id",
        type=int,
        default=None,
        help="Last news_id to process.",
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Seconds to wait between records.",
    )

    args = parser.parse_args()

    if (
        not args.all
        and args.limit is None
        and args.start_id is None
        and args.end_id is None
    ):
        parser.error(
            "Use --all, --limit, or --start-id/--end-id."
        )

    news_ids = get_news_ids(
        args.start_id,
        args.end_id,
        args.limit,
    )

    print("=" * 78)
    print("MarketPulse AI Batch Runner")
    print("=" * 78)
    print(f"Model       : {OLLAMA_MODEL}")
    print(f"Version     : {MODEL_VERSION}")
    print(f"Records     : {len(news_ids)}")
    print("Mode        : sequential / resumable")
    print("=" * 78)
    print()

    processed = 0
    skipped = 0
    failed = 0

    for index, news_id in enumerate(
        news_ids,
        start=1,
    ):
        try:
            if already_processed(news_id):
                skipped += 1

                print(
                    f"[{index:04d}/{len(news_ids):04d}] "
                    f"SKIP news_id={news_id} "
                    f"(already predicted)"
                )

                continue

            started = time.time()

            result = process_news(
                news_id
            )

            elapsed = time.time() - started

            processed += 1

            print(
                f"[{index:04d}/{len(news_ids):04d}] "
                f"news_id={news_id} | "
                f"{result['exchange']} | "
                f"{result['event_type']} | "
                f"{result['direction']} | "
                f"{result['impact_level']} | "
                f"confidence={result['confidence']:.1f} | "
                f"{elapsed:.1f}s"
            )

            if args.delay > 0:
                time.sleep(args.delay)

        except KeyboardInterrupt:
            print()
            print("Stopped by user.")
            print(
                f"Processed={processed}, "
                f"Skipped={skipped}, "
                f"Failed={failed}"
            )
            return

        except Exception as exc:
            failed += 1

            print(
                f"[{index:04d}/{len(news_ids):04d}] "
                f"ERROR news_id={news_id}: {exc}"
            )

    print()
    print("=" * 78)
    print("BATCH COMPLETE")
    print("=" * 78)
    print(f"Processed : {processed}")
    print(f"Skipped   : {skipped}")
    print(f"Failed    : {failed}")
    print(f"Total     : {len(news_ids)}")


if __name__ == "__main__":
    main()