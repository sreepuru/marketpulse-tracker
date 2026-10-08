from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

# Allow imports from this directory.
AGENTS_DIR = Path(__file__).resolve().parent
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from evidence_validator import calculate_candidate_evidence, validate_candidate


NEWS_IDS = [4, 6, 7, 8, 11]


def get_connection():
    return psycopg2.connect(
        host=os.getenv("MARKETPULSE_DB_HOST", "localhost"),
        port=os.getenv("MARKETPULSE_DB_PORT", "5432"),
        dbname=os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
        user=os.getenv("MARKETPULSE_DB_USER", "postgres"),
        password=os.getenv("MARKETPULSE_DB_PASSWORD", ""),
    )


def get_news(conn, news_id):
    sql = """
        SELECT
            news_id,
            exchange,
            symbol,
            security_id,
            company_name,
            category,
            title,
            description,
            published_at,
            mapping_status,
            asset_category
        FROM market_news
        WHERE news_id = %s
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, (news_id,))
        return cur.fetchone()


def get_candidates(conn, event):
    company_name = event.get("company_name")
    exchange = event.get("exchange")

    sql = """
        SELECT
            security_id,
            isin,
            symbol,
            instrument_type,
            instrument_name,
            exchange,
            asset_category,
            nse_name,
            nse_short_name,
            nse_alias,
            nse_symbol,
            bse_name,
            bse_short_name,
            bse_alias,
            bse_symbol,
            bse_scrip_code
        FROM security_master
        WHERE exchange = %s
          AND (
                instrument_name ILIKE %s
                OR nse_name ILIKE %s
                OR bse_name ILIKE %s
              )
        ORDER BY security_id
    """

    search = f"%{company_name}%"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            sql,
            (
                exchange,
                search,
                search,
                search,
            ),
        )
        return cur.fetchall()


def get_name_similarity_candidates(conn, event, limit=10):
    """
    Retrieve candidates using significant words from the company name.

    This is READ ONLY and intentionally broad enough for shadow testing.
    It is not the production candidate generator.
    """

    company_name = event.get("company_name") or ""
    exchange = event.get("exchange")

    words = [
        word.strip(" ,.-")
        for word in company_name.upper().split()
        if len(word.strip(" ,.-")) >= 4
        and word.upper()
        not in {
            "LIMITED",
            "LTD",
            "PRIVATE",
            "PVT",
            "PUBLIC",
            "COMPANY",
            "INDIA",
            "INDIAN",
        }
    ]

    if not words:
        return []

    conditions = []
    params = [exchange]

    for word in words[:3]:
        conditions.append(
            """
            (
                instrument_name ILIKE %s
                OR nse_name ILIKE %s
                OR bse_name ILIKE %s
            )
            """
        )

        search = f"%{word}%"
        params.extend([search, search, search])

    sql = f"""
        SELECT
            security_id,
            isin,
            symbol,
            instrument_type,
            instrument_name,
            exchange,
            asset_category,
            nse_name,
            nse_short_name,
            nse_alias,
            nse_symbol,
            bse_name,
            bse_short_name,
            bse_alias,
            bse_symbol,
            bse_scrip_code
        FROM security_master
        WHERE exchange = %s
          AND (
              {" OR ".join(conditions)}
          )
        LIMIT 100
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return rows[:limit]


def print_evidence(event, candidate, evidence, result):
    print("-" * 90)

    print(
        f"news_id={event['news_id']} | "
        f"company={event.get('company_name')} | "
        f"exchange={event.get('exchange')}"
    )

    print(
        f"candidate={candidate['security_id']} | "
        f"name={candidate.get('instrument_name')} | "
        f"symbol={candidate.get('symbol')}"
    )

    print(f"name_similarity       = {evidence.name_similarity}")
    print(f"token_overlap         = {evidence.token_overlap}")
    print(f"distinctive_overlap   = {evidence.distinctive_overlap}")
    print(f"exchange_match        = {evidence.exchange_match}")
    print(f"symbol_match          = {evidence.symbol_match}")
    print(f"isin_match            = {evidence.isin_match}")
    print(f"bse_scrip_match       = {evidence.bse_scrip_match}")
    print(f"hard_conflicts        = {evidence.hard_conflicts}")
    print(f"supporting_evidence   = {evidence.supporting_evidence}")
    print(f"DECISION              = {result['decision']}")


def main():
    print("MarketPulse Evidence Validator - READ ONLY SHADOW TEST")
    print(f"Testing news IDs: {NEWS_IDS}")
    print()

    conn = get_connection()

    try:
        for news_id in NEWS_IDS:
            event = get_news(conn, news_id)

            if not event:
                print(f"news_id={news_id}: NOT FOUND")
                continue

            print("=" * 90)
            print(
                f"NEWS {news_id}: "
                f"{event.get('company_name')} | "
                f"status={event.get('mapping_status')} | "
                f"asset={event.get('asset_category')}"
            )

            candidates = get_candidates(conn, event)

            # If exact name retrieval finds nothing, use broad lexical retrieval.
            if not candidates:
                candidates = get_name_similarity_candidates(conn, event)

            if not candidates:
                print("No security_master candidates found.")
                continue

            print(f"Candidates evaluated: {len(candidates)}")

            results = []

            for candidate in candidates:
                evidence = calculate_candidate_evidence(
                    dict(event),
                    dict(candidate),
                )

                result = validate_candidate(evidence)

                results.append(
                    (
                        result["decision"],
                        evidence.name_similarity,
                        candidate,
                        evidence,
                        result,
                    )
                )

            # Show strongest candidates first.
            results.sort(
                key=lambda item: item[1],
                reverse=True,
            )

            for (
                _decision,
                _similarity,
                candidate,
                evidence,
                result,
            ) in results[:5]:
                print_evidence(
                    event,
                    candidate,
                    evidence,
                    result,
                )

        print()
        print("=" * 90)
        print("SHADOW TEST COMPLETE")
        print("Database writes: NONE")

    finally:
        conn.close()


if __name__ == "__main__":
    main()