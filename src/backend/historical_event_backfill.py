import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import psycopg2
import requests
from dotenv import load_dotenv
from psycopg2.extras import execute_values


# =====================================================
# CONFIG
# =====================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

START_DATE = "2025-01-01"
END_DATE = "2026-08-31"

WINDOW_DAYS = 7

# Pause between NSE requests.
# Helps avoid hammering the endpoint during a long run.
REQUEST_DELAY_SECONDS = 2

NSE_BASE_URL = "https://www.nseindia.com"

NSE_PAGE_URL = (
    "https://www.nseindia.com/companies-listing/"
    "corporate-filings-announcements"
)

NSE_ANNOUNCEMENTS_URL = (
    "https://www.nseindia.com/api/"
    "corporate-announcements?index=equities"
)

DB_CONFIG = {
    "host": os.getenv("MARKETPULSE_DB_HOST"),
    "port": os.getenv("MARKETPULSE_DB_PORT"),
    "dbname": os.getenv("MARKETPULSE_DB_NAME"),
    "user": os.getenv("MARKETPULSE_DB_USER"),
    "password": os.getenv("MARKETPULSE_DB_PASSWORD"),
}


# =====================================================
# DATABASE
# =====================================================

def get_connection():
    return psycopg2.connect(**DB_CONFIG)


# =====================================================
# NSE SESSION
# =====================================================

def get_nse_session():
    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": NSE_PAGE_URL,
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        }
    )

    # NSE may return 403 here while the API itself
    # remains accessible.
    try:
        response = session.get(
            NSE_BASE_URL,
            timeout=30,
        )

        print(
            f"NSE Homepage Status: "
            f"{response.status_code}"
        )

    except requests.RequestException as exc:
        print(
            f"NSE Homepage Warning: {exc}"
        )

    return session


# =====================================================
# DATE HELPERS
# =====================================================

def parse_date(value):
    return datetime.strptime(
        value,
        "%Y-%m-%d",
    ).date()


def format_nse_date(value):
    return value.strftime(
        "%d-%m-%Y"
    )


def generate_windows(start_date, end_date):
    """
    Generate inclusive 7-day date windows.
    """

    start = parse_date(start_date)
    end = parse_date(end_date)

    current = start

    while current <= end:

        window_end = min(
            current + timedelta(
                days=WINDOW_DAYS - 1
            ),
            end,
        )

        yield current, window_end

        current = window_end + timedelta(
            days=1
        )


# =====================================================
# NSE FETCH
# =====================================================

def fetch_nse_announcements(
    session,
    start_date,
    end_date,
):

    from_date = format_nse_date(
        start_date
    )

    to_date = format_nse_date(
        end_date
    )

    url = (
        f"{NSE_ANNOUNCEMENTS_URL}"
        f"&from_date={from_date}"
        f"&to_date={to_date}"
    )

    response = session.get(
        url,
        timeout=120,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, list):
        raise RuntimeError(
            "Unexpected NSE response type: "
            f"{type(data).__name__}"
        )

    return data


# =====================================================
# DATE PARSING
# =====================================================

def parse_nse_datetime(value):

    if not value:
        return None

    try:

        return datetime.strptime(
            value,
            "%d-%b-%Y %H:%M:%S",
        )

    except ValueError:

        return None


# =====================================================
# NORMALIZATION
# =====================================================

def normalize_nse_record(record):

    seq_id = record.get("seq_id")

    if not seq_id:
        raise ValueError(
            "NSE announcement has no seq_id"
        )

    return {
        "exchange": "NSE",

        # NSE-native unique event identifier.
        "external_id": str(seq_id),

        "symbol": record.get(
            "symbol"
        ),

        "isin": record.get(
            "sm_isin"
        ),

        "company_name": record.get(
            "sm_name"
        ),

        "category": record.get(
            "desc"
        ),

        "title": record.get(
            "desc"
        ),

        "description": record.get(
            "attchmntText"
        ),

        "published_at": parse_nse_datetime(
            record.get("an_dt")
        ),

        "source_url": record.get(
            "attchmntFile"
        ),
    }


def normalize_nse_announcements(records):

    events = []

    for record in records:

        events.append(
            normalize_nse_record(
                record
            )
        )

    return events


# =====================================================
# SECURITY MASTER
# =====================================================

def load_nse_security_master():

    conn = get_connection()

    try:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    security_id,
                    isin,
                    symbol
                FROM security_master
                WHERE exchange = %s
                """,
                ("NSE",),
            )

            rows = cur.fetchall()

    finally:

        conn.close()

    by_isin = {}
    by_symbol = {}

    for security_id, isin, symbol in rows:

        if isin:
            by_isin[isin] = security_id

        if symbol:
            by_symbol[symbol] = security_id

    return by_isin, by_symbol


# =====================================================
# SECURITY MAPPING
# =====================================================

def map_security(
    events,
    by_isin,
    by_symbol,
):

    mapped_by_isin = 0
    mapped_by_symbol = 0
    unmatched = 0

    for event in events:

        isin = event.get("isin")
        symbol = event.get("symbol")

        security_id = None
        mapping_method = None
        mapping_confidence = None

        # ---------------------------------------------
        # PRIMARY: ISIN
        # ---------------------------------------------

        if isin and isin in by_isin:

            security_id = by_isin[isin]

            mapping_method = "ISIN"

            mapping_confidence = 1.0

            mapped_by_isin += 1

        # ---------------------------------------------
        # FALLBACK: SYMBOL
        # ---------------------------------------------

        elif symbol and symbol in by_symbol:

            security_id = by_symbol[symbol]

            mapping_method = "SYMBOL"

            mapping_confidence = 0.95

            mapped_by_symbol += 1

        # ---------------------------------------------
        # UNMATCHED
        # ---------------------------------------------

        else:

            unmatched += 1

        event["security_id"] = security_id

        event["mapping_status"] = (
            "MAPPED"
            if security_id is not None
            else "PENDING"
        )

        event["mapping_method"] = (
            mapping_method
        )

        event["mapping_confidence"] = (
            mapping_confidence
        )

    return (
        mapped_by_isin,
        mapped_by_symbol,
        unmatched,
    )


# =====================================================
# DATABASE INSERT
# =====================================================

INSERT_SQL = """
INSERT INTO market_news (
    exchange,
    symbol,
    security_id,
    company_name,
    category,
    title,
    description,
    published_at,
    source_url,
    external_id,
    news_scope,
    mapping_status,
    mapping_method,
    mapping_confidence,
    created_at
)
VALUES %s
ON CONFLICT (exchange, external_id)
DO NOTHING;
"""


def save_events(events):

    if not events:
        return 0

    rows = []

    for event in events:

        rows.append(
            (
                event["exchange"],
                event.get("symbol"),
                event.get("security_id"),
                event.get("company_name"),
                event.get("category"),
                event.get("title"),
                event.get("description"),
                event.get("published_at"),
                event.get("source_url"),
                event["external_id"],
                "STOCK",
                event["mapping_status"],
                event.get("mapping_method"),
                event.get("mapping_confidence"),
                datetime.now(),
            )
        )

    conn = get_connection()

    try:

        with conn:

            with conn.cursor() as cur:

                # Capture existing IDs before insertion.
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM market_news
                    WHERE exchange = %s
                      AND external_id = ANY(%s)
                    """,
                    (
                        "NSE",
                        [
                            event["external_id"]
                            for event in events
                        ],
                    ),
                )

                existing_before = (
                    cur.fetchone()[0]
                )

                execute_values(
                    cur,
                    INSERT_SQL,
                    rows,
                    page_size=500,
                )

        # We intentionally do not use cursor.rowcount.
        # PostgreSQL/psycopg2 rowcount is not reliable
        # for this multi-row ON CONFLICT operation.
        #
        # Instead, the caller verifies the resulting
        # database state.

        return existing_before

    finally:

        conn.close()


# =====================================================
# WINDOW VERIFICATION
# =====================================================

def count_window_rows(
    start_date,
    end_date,
):

    start_datetime = datetime.combine(
        start_date,
        datetime.min.time(),
    )

    end_datetime = datetime.combine(
        end_date + timedelta(days=1),
        datetime.min.time(),
    )

    conn = get_connection()

    try:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT COUNT(*)
                FROM market_news
                WHERE exchange = %s
                  AND published_at >= %s
                  AND published_at < %s
                """,
                (
                    "NSE",
                    start_datetime,
                    end_datetime,
                ),
            )

            return cur.fetchone()[0]

    finally:

        conn.close()


# =====================================================
# MAIN
# =====================================================

def main():

    print("=" * 70)
    print("MarketPulse NSE HISTORICAL EVENT BACKFILL")
    print("=" * 70)

    print(
        f"Date Range : "
        f"{START_DATE} → {END_DATE}"
    )

    print(
        f"Window     : "
        f"{WINDOW_DAYS} days"
    )

    print(
        "Exchange   : NSE ONLY"
    )

    print(
        "Target     : market_news"
    )

    print(
        "Mode       : HISTORICAL BACKFILL"
    )

    print("=" * 70)

    # -------------------------------------------------
    # Load security master ONCE.
    # -------------------------------------------------

    print()
    print(
        "Loading NSE security master..."
    )

    by_isin, by_symbol = (
        load_nse_security_master()
    )

    print(
        f"ISIN lookup entries   : "
        f"{len(by_isin):,}"
    )

    print(
        f"Symbol lookup entries : "
        f"{len(by_symbol):,}"
    )

    # -------------------------------------------------
    # Generate windows.
    # -------------------------------------------------

    windows = list(
        generate_windows(
            START_DATE,
            END_DATE,
        )
    )

    print(
        f"Windows                : "
        f"{len(windows):,}"
    )

    # -------------------------------------------------
    # NSE session.
    # -------------------------------------------------

    session = get_nse_session()

    # -------------------------------------------------
    # Totals.
    # -------------------------------------------------

    total_fetched = 0
    total_mapped_isin = 0
    total_mapped_symbol = 0
    total_unmatched = 0
    total_existing = 0
    total_verified = 0
    failed_windows = []

    # -------------------------------------------------
    # Process each window.
    # -------------------------------------------------

    for index, (
        window_start,
        window_end,
    ) in enumerate(
        windows,
        start=1,
    ):

        print()
        print("=" * 70)
        print(
            f"[{index}/{len(windows)}] "
            f"{window_start} → {window_end}"
        )
        print("=" * 70)

        try:

            # -----------------------------------------
            # FETCH
            # -----------------------------------------

            raw_records = (
                fetch_nse_announcements(
                    session,
                    window_start,
                    window_end,
                )
            )

            fetched = len(raw_records)

            total_fetched += fetched

            print(
                f"Fetched             : "
                f"{fetched:,}"
            )

            # -----------------------------------------
            # NORMALIZE
            # -----------------------------------------

            events = (
                normalize_nse_announcements(
                    raw_records
                )
            )

            # -----------------------------------------
            # Check duplicate seq_id inside response.
            # -----------------------------------------

            unique_ids = {
                event["external_id"]
                for event in events
            }

            if len(unique_ids) != len(events):

                raise RuntimeError(
                    "Duplicate NSE seq_id values "
                    "found inside API response."
                )

            # -----------------------------------------
            # MAP
            # -----------------------------------------

            (
                mapped_isin,
                mapped_symbol,
                unmatched,
            ) = map_security(
                events,
                by_isin,
                by_symbol,
            )

            total_mapped_isin += (
                mapped_isin
            )

            total_mapped_symbol += (
                mapped_symbol
            )

            total_unmatched += (
                unmatched
            )

            print(
                f"Mapped by ISIN      : "
                f"{mapped_isin:,}"
            )

            print(
                f"Mapped by SYMBOL    : "
                f"{mapped_symbol:,}"
            )

            print(
                f"Unmatched           : "
                f"{unmatched:,}"
            )

            # -----------------------------------------
            # INSERT
            # -----------------------------------------

            existing_before = (
                save_events(events)
            )

            total_existing += (
                existing_before
            )

            # -----------------------------------------
            # VERIFY DATABASE
            # -----------------------------------------

            verified = count_window_rows(
                window_start,
                window_end,
            )

            total_verified += verified

            print(
                f"Existing before     : "
                f"{existing_before:,}"
            )

            print(
                f"DB rows in window   : "
                f"{verified:,}"
            )

            # -----------------------------------------
            # Sanity check
            # -----------------------------------------

            if verified < fetched:

                print()
                print(
                    "WARNING: Database row count "
                    "is lower than API record count."
                )

                print(
                    "The window will be marked "
                    "for review."
                )

                failed_windows.append(
                    (
                        window_start,
                        window_end,
                        "DB count lower than fetched",
                    )
                )

            else:

                print(
                    "Window status       : OK"
                )

        except Exception as exc:

            print()
            print(
                f"WINDOW FAILED: {exc}"
            )

            failed_windows.append(
                (
                    window_start,
                    window_end,
                    str(exc),
                )
            )

        # ---------------------------------------------
        # Delay between requests.
        # ---------------------------------------------

        if index < len(windows):

            print(
                f"Waiting "
                f"{REQUEST_DELAY_SECONDS}s..."
            )

            time.sleep(
                REQUEST_DELAY_SECONDS
            )

    # =================================================
    # FINAL SUMMARY
    # =================================================

    print()
    print("=" * 70)
    print("FINAL NSE HISTORICAL BACKFILL SUMMARY")
    print("=" * 70)

    print(
        f"Date range            : "
        f"{START_DATE} → {END_DATE}"
    )

    print(
        f"Windows processed      : "
        f"{len(windows):,}"
    )

    print(
        f"Windows failed         : "
        f"{len(failed_windows):,}"
    )

    print(
        f"Records fetched        : "
        f"{total_fetched:,}"
    )

    print(
        f"Mapped by ISIN         : "
        f"{total_mapped_isin:,}"
    )

    print(
        f"Mapped by SYMBOL       : "
        f"{total_mapped_symbol:,}"
    )

    print(
        f"Unmatched              : "
        f"{total_unmatched:,}"
    )

    print(
        f"Existing before insert : "
        f"{total_existing:,}"
    )

    print(
        f"Verified DB rows       : "
        f"{total_verified:,}"
    )

    # -------------------------------------------------
    # Failed windows
    # -------------------------------------------------

    if failed_windows:

        print()
        print("=" * 70)
        print("FAILED / REVIEW WINDOWS")
        print("=" * 70)

        for (
            window_start,
            window_end,
            reason,
        ) in failed_windows:

            print(
                f"{window_start} → "
                f"{window_end} : "
                f"{reason}"
            )

    else:

        print()
        print(
            "All historical windows completed "
            "successfully."
        )

    print()
    print("=" * 70)
    print("BACKFILL COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()