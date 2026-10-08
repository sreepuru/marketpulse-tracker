"""
MarketPulse - Historical BSE BhavCopy Backfill (optimized)

Period:
    01-Jan-2025 through 06-Oct-2026

Purpose:
    Download/reuse BSE CM BhavCopy files and load historical BSE prices
    into daily_prices.

Rules:
    1. security_master is canonical.
    2. ISIN is the primary identity key.
    3. BSE-only securities receive BSE prices.
    4. BOTH securities receive BSE prices as well.
    5. NSE-only securities do NOT receive BSE prices.
    6. Existing daily_prices rows are preserved.
    7. daily_prices exchange = 'BSE'.
    8. Unique key: (security_id, trade_date, exchange).
    9. One trading day is committed independently.
   10. Missing BSE files are skipped.
   11. HTML responses are rejected.
   12. Default mode is DRY-RUN.
   13. --apply writes to PostgreSQL.

Optimization:
    security_master is loaded once into an in-memory ISIN map instead of
    querying PostgreSQL once per BSE row.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import psycopg
import requests
from dotenv import load_dotenv


# ============================================================
# PROJECT / ENVIRONMENT
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

if not ENV_FILE.exists():
    raise FileNotFoundError(f".env not found: {ENV_FILE}")

load_dotenv(ENV_FILE)

DB_CONFIG = {
    "host": os.getenv("MARKETPULSE_DB_HOST", "localhost"),
    "port": os.getenv("MARKETPULSE_DB_PORT", "5432"),
    "dbname": os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
    "user": os.getenv("MARKETPULSE_DB_USER", "postgres"),
    "password": os.getenv("MARKETPULSE_DB_PASSWORD", ""),
}


# ============================================================
# BSE CONFIGURATION
# ============================================================

BSE_BASE_URL = "https://www.bseindia.com"

BSE_BHAVCOPY_URL = (
    BSE_BASE_URL
    + "/download/BhavCopy/Equity/"
    + "BhavCopy_BSE_CM_0_0_0_{yyyymmdd}_F_0000.CSV"
)

BSE_RAW_DIR = (
    PROJECT_ROOT / "data" / "bhavcopy" / "bse" / "raw"
)

BSE_UNMATCHED_DIR = (
    PROJECT_ROOT / "data" / "bhavcopy" / "bse" / "unmatched"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}


# ============================================================
# BSE COLUMNS
# ============================================================

COLUMN_MAP = {
    "TradDt": "trade_date",
    "Sgmt": "segment",
    "Src": "source",
    "FinInstrmTp": "instrument_type",
    "FinInstrmId": "instrument_id",
    "ISIN": "isin",
    "TckrSymb": "symbol",
    "SctySrs": "series",
    "FinInstrmNm": "instrument_name",
    "OpnPric": "open",
    "HghPric": "high",
    "LwPric": "low",
    "ClsPric": "close",
    "LastPric": "last_price",
    "PrvsClsgPric": "previous_close",
    "TtlTradgVol": "volume",
    "TtlTrfVal": "turnover",
}


# ============================================================
# STATISTICS
# ============================================================

@dataclass
class DayStats:
    source_rows: int = 0
    bse_rows: int = 0
    matched_bse: int = 0
    matched_both: int = 0
    unmatched: int = 0
    ambiguous: int = 0
    invalid: int = 0
    inserted: int = 0
    duplicates: int = 0


@dataclass
class OverallStats:
    dates_checked: int = 0
    files_downloaded: int = 0
    files_existing: int = 0
    files_missing: int = 0
    files_invalid: int = 0
    days_processed: int = 0
    days_failed: int = 0
    source_rows: int = 0
    bse_rows: int = 0
    matched_bse: int = 0
    matched_both: int = 0
    unmatched: int = 0
    ambiguous: int = 0
    invalid: int = 0
    inserted: int = 0
    duplicates: int = 0


# ============================================================
# CLI
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Backfill historical BSE CM BhavCopy data."
    )

    parser.add_argument(
        "--start",
        default="2025-01-01",
        help="Start date YYYY-MM-DD",
    )

    parser.add_argument(
        "--end",
        default="2026-10-06",
        help="End date YYYY-MM-DD",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write BSE prices to PostgreSQL.",
    )

    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="Seconds between BSE requests.",
    )

    return parser.parse_args()


# ============================================================
# DATE
# ============================================================

def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def daterange(start: date, end: date):
    current = start

    while current <= end:
        yield current
        current += timedelta(days=1)


# ============================================================
# DOWNLOAD / REUSE
# ============================================================

def build_url(trade_date: date) -> str:
    return BSE_BHAVCOPY_URL.format(
        yyyymmdd=trade_date.strftime("%Y%m%d")
    )


def raw_path(trade_date: date) -> Path:
    return (
        BSE_RAW_DIR
        / (
            "BhavCopy_BSE_CM_0_0_0_"
            f"{trade_date.strftime('%Y%m%d')}"
            "_F_0000.CSV"
        )
    )


def download_file(
    session: requests.Session,
    trade_date: date,
) -> tuple[str, bytes | None]:

    output_path = raw_path(trade_date)

    BSE_RAW_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Reuse existing non-empty file.
    if output_path.exists() and output_path.stat().st_size > 0:
        return "EXISTING", output_path.read_bytes()

    url = build_url(trade_date)

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=60,
        )
    except requests.RequestException as exc:
        print(
            f"[ERROR] {trade_date} request failed: {exc}"
        )
        return "ERROR", None

    if response.status_code == 404:
        return "MISSING", None

    if response.status_code != 200:
        print(
            f"[ERROR] {trade_date} HTTP "
            f"{response.status_code}"
        )
        return "ERROR", None

    content = response.content

    if not content:
        return "INVALID", None

    sample = content[:1000].decode(
        "utf-8",
        errors="replace",
    ).lower()

    if "<html" in sample or "<!doctype" in sample:
        print(
            f"[INVALID] {trade_date}: "
            "BSE returned HTML"
        )
        return "INVALID", None

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode(
            "cp1252",
            errors="replace",
        )

    first_line = (
        text.splitlines()[0]
        if text.splitlines()
        else ""
    )

    if "TradDt" not in first_line:
        print(
            f"[INVALID] {trade_date}: "
            "unexpected CSV header"
        )
        return "INVALID", None

    output_path.write_bytes(content)

    return "DOWNLOADED", content


# ============================================================
# CSV PARSING
# ============================================================

def parse_csv(content: bytes) -> list[dict[str, object]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode(
            "cp1252",
            errors="replace",
        )

    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        raise ValueError("Missing CSV header.")

    required = set(COLUMN_MAP.keys())
    available = {
        column.strip()
        for column in reader.fieldnames
        if column
    }

    missing = required - available

    if missing:
        raise ValueError(
            "Missing columns: "
            + ", ".join(sorted(missing))
        )

    rows = []

    for raw in reader:
        row = {
            COLUMN_MAP[key]: (
                value.strip()
                if isinstance(value, str)
                else ""
            )
            for key, value in raw.items()
            if key in COLUMN_MAP
        }
        rows.append(row)

    return rows


# ============================================================
# VALUE CONVERSION
# ============================================================

def to_float(value):
    if value in (None, "", "-"):
        return None

    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def to_int(value):
    if value in (None, "", "-"):
        return None

    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_rows(raw_rows, expected_date):
    rows = []

    stats = DayStats(
        source_rows=len(raw_rows)
    )

    for raw in raw_rows:
        segment = str(
            raw.get("segment") or ""
        ).strip().upper()

        source = str(
            raw.get("source") or ""
        ).strip().upper()

        instrument_type = str(
            raw.get("instrument_type") or ""
        ).strip().upper()

        # BSE CM Stock only.
        if (
            segment != "CM"
            or source != "BSE"
            or instrument_type != "STK"
        ):
            continue

        stats.bse_rows += 1

        isin = str(
            raw.get("isin") or ""
        ).strip().upper()

        symbol = str(
            raw.get("symbol") or ""
        ).strip()

        if not isin or not symbol:
            stats.invalid += 1
            continue

        trade_date = str(
            raw.get("trade_date") or ""
        ).strip()

        try:
            trade_date = parse_date(trade_date)
        except ValueError:
            stats.invalid += 1
            continue

        if trade_date != expected_date:
            stats.invalid += 1
            continue

        rows.append(
            {
                "trade_date": trade_date,
                "instrument_id": to_int(
                    raw.get("instrument_id")
                ),
                "isin": isin,
                "symbol": symbol,
                "series": str(
                    raw.get("series") or ""
                ).strip(),
                "instrument_name": str(
                    raw.get("instrument_name") or ""
                ).strip(),
                "open": to_float(raw.get("open")),
                "high": to_float(raw.get("high")),
                "low": to_float(raw.get("low")),
                "close": to_float(raw.get("close")),
                "last_price": to_float(
                    raw.get("last_price")
                ),
                "previous_close": to_float(
                    raw.get("previous_close")
                ),
                "volume": to_int(raw.get("volume")),
                "turnover": to_float(
                    raw.get("turnover")
                ),
            }
        )

    return rows, stats


# ============================================================
# DATABASE
# ============================================================

def get_connection():
    return psycopg.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        dbname=DB_CONFIG["dbname"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )


def load_security_map(cursor):
    """
    Load canonical ISIN resolution once.

    Returns:
        dict[str, tuple[str, int]]

    Value:
        (resolution, security_id)

    resolution:
        BSE
        BOTH
        NSE
        AMBIGUOUS
    """

    cursor.execute(
        """
        SELECT
            security_id,
            isin,
            exchange_tag
        FROM security_master
        WHERE isin IS NOT NULL
          AND TRIM(isin) <> ''
        ORDER BY security_id
        """
    )

    security_map = {}
    ambiguous_isins = set()

    for security_id, isin, exchange_tag in cursor.fetchall():
        normalized_isin = str(isin).strip().upper()

        if not normalized_isin:
            continue

        if normalized_isin in security_map:
            ambiguous_isins.add(normalized_isin)
            continue

        tag = str(exchange_tag or "").strip().upper()

        if tag in {"BSE", "BOTH", "NSE"}:
            security_map[normalized_isin] = (
                tag,
                int(security_id),
            )
        else:
            # Preserve the old behavior: an unsupported/blank
            # exchange tag is treated as NSE-only for BSE loading.
            security_map[normalized_isin] = (
                "NSE",
                int(security_id),
            )

    # Mark all duplicate ISINs as ambiguous.
    for isin in ambiguous_isins:
        security_map[isin] = ("AMBIGUOUS", None)

    return security_map


# ============================================================
# INSERT BSE PRICE
# ============================================================

def insert_bse_price(cursor, security_id, row):
    cursor.execute(
        """
        INSERT INTO daily_prices (
            security_id,
            trade_date,
            exchange,
            open,
            high,
            low,
            close,
            last_price,
            previous_close,
            volume,
            turnover,
            created_at
        )
        VALUES (
            %s,
            %s,
            'BSE',
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT (
            security_id,
            trade_date,
            exchange
        )
        DO NOTHING
        RETURNING price_id
        """,
        (
            security_id,
            row["trade_date"],
            row["open"],
            row["high"],
            row["low"],
            row["close"],
            row["last_price"],
            row["previous_close"],
            row["volume"],
            row["turnover"],
        ),
    )

    return cursor.fetchone() is not None


# ============================================================
# UNMATCHED REPORT
# ============================================================

def write_unmatched(trade_date, rows):
    if not rows:
        return None

    BSE_UNMATCHED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        BSE_UNMATCHED_DIR
        / (
            "BSE_unmatched_"
            f"{trade_date.strftime('%Y%m%d')}.csv"
        )
    )

    fieldnames = [
        "trade_date",
        "instrument_id",
        "isin",
        "symbol",
        "series",
        "instrument_name",
        "close",
        "volume",
    ]

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )

        writer.writeheader()

        for row in rows:
            writer.writerow(
                {
                    field: row.get(field)
                    for field in fieldnames
                }
            )

    return path


# ============================================================
# PROCESS ONE DAY
# ============================================================

def process_day(
    csv_path,
    trade_date,
    apply_changes,
    security_map,
):
    content = csv_path.read_bytes()

    raw_rows = parse_csv(content)

    rows, stats = normalize_rows(
        raw_rows,
        trade_date,
    )

    unmatched = []
    ambiguous = []

    conn = get_connection()

    try:
        with conn.cursor() as cursor:
            for row in rows:
                resolution, security_id = security_map.get(
                    row["isin"],
                    ("UNMATCHED", None),
                )

                if resolution == "BSE":
                    stats.matched_bse += 1

                elif resolution == "BOTH":
                    stats.matched_both += 1

                elif resolution == "NSE":
                    # BSE price deliberately not loaded against
                    # an NSE-only canonical security.
                    continue

                elif resolution == "AMBIGUOUS":
                    stats.ambiguous += 1
                    ambiguous.append(row)
                    continue

                else:
                    stats.unmatched += 1
                    unmatched.append(row)
                    continue

                if apply_changes:
                    inserted = insert_bse_price(
                        cursor,
                        security_id,
                        row,
                    )

                    if inserted:
                        stats.inserted += 1
                    else:
                        stats.duplicates += 1

            if apply_changes:
                conn.commit()

    except Exception:
        if apply_changes:
            conn.rollback()
        raise

    finally:
        conn.close()

    report = write_unmatched(
        trade_date,
        unmatched,
    )

    return stats, report, ambiguous


# ============================================================
# MAIN BACKFILL
# ============================================================

def main():
    args = parse_args()

    start_date = parse_date(args.start)
    end_date = parse_date(args.end)

    if start_date > end_date:
        raise ValueError(
            "--start cannot be after --end"
        )

    overall = OverallStats()

    session = requests.Session()

    # Load security_master once.
    print()
    print("Loading security master ISIN map...")

    conn = get_connection()

    try:
        with conn.cursor() as cursor:
            security_map = load_security_map(cursor)
    finally:
        conn.close()

    print(
        f"Security map loaded : {len(security_map):,} ISINs"
    )

    print()
    print("=" * 72)
    print("MARKETPULSE BSE HISTORICAL BACKFILL")
    print("=" * 72)
    print(
        f"Period : {start_date} -> {end_date}"
    )
    print(
        "Mode   :",
        "APPLY" if args.apply else "DRY-RUN",
    )
    print(
        "Raw    :",
        BSE_RAW_DIR,
    )
    print("=" * 72)

    for trade_date in daterange(
        start_date,
        end_date,
    ):
        overall.dates_checked += 1

        # Skip weekends before making HTTP request.
        if trade_date.weekday() >= 5:
            continue

        print()
        print(
            f"[{trade_date}] "
            "Checking BSE BhavCopy..."
        )

        status, content = download_file(
            session,
            trade_date,
        )

        if status == "MISSING":
            overall.files_missing += 1
            print(
                f"[{trade_date}] "
                "No BSE file - skipped."
            )
            continue

        if status == "INVALID":
            overall.files_invalid += 1
            print(
                f"[{trade_date}] "
                "Invalid BSE response - skipped."
            )
            continue

        if status == "ERROR":
            overall.days_failed += 1
            print(
                f"[{trade_date}] "
                "Download failed - continuing."
            )
            continue

        if status == "DOWNLOADED":
            overall.files_downloaded += 1
        elif status == "EXISTING":
            overall.files_existing += 1

        csv_path = raw_path(trade_date)

        try:
            stats, report, ambiguous = process_day(
                csv_path,
                trade_date,
                args.apply,
                security_map,
            )

            overall.days_processed += 1
            overall.source_rows += stats.source_rows
            overall.bse_rows += stats.bse_rows
            overall.matched_bse += stats.matched_bse
            overall.matched_both += stats.matched_both
            overall.unmatched += stats.unmatched
            overall.ambiguous += stats.ambiguous
            overall.invalid += stats.invalid
            overall.inserted += stats.inserted
            overall.duplicates += stats.duplicates

            print(
                f"[{trade_date}] "
                f"BSE={stats.bse_rows:,} "
                f"BSE-only={stats.matched_bse:,} "
                f"BOTH={stats.matched_both:,} "
                f"Inserted={stats.inserted:,} "
                f"Duplicates={stats.duplicates:,} "
                f"Unmatched={stats.unmatched:,} "
                f"Ambiguous={stats.ambiguous:,}"
            )

            if report:
                print(
                    "Unmatched report:",
                    report,
                )

        except Exception as exc:
            overall.days_failed += 1

            print()
            print(
                f"[{trade_date}] "
                f"PROCESSING ERROR: {exc}"
            )

        # Be polite to BSE endpoint.
        if args.sleep > 0:
            time.sleep(args.sleep)

    print()
    print("=" * 72)
    print("BSE HISTORICAL BACKFILL SUMMARY")
    print("=" * 72)

    print(
        "Period checked       :",
        start_date,
        "->",
        end_date,
    )
    print(
        "Dates checked        :",
        overall.dates_checked,
    )
    print(
        "Files downloaded     :",
        overall.files_downloaded,
    )
    print(
        "Files already present:",
        overall.files_existing,
    )
    print(
        "Files missing        :",
        overall.files_missing,
    )
    print(
        "Invalid files        :",
        overall.files_invalid,
    )
    print(
        "Days processed       :",
        overall.days_processed,
    )
    print(
        "Days failed          :",
        overall.days_failed,
    )
    print(
        "Source rows          :",
        f"{overall.source_rows:,}",
    )
    print(
        "BSE CM/STK rows      :",
        f"{overall.bse_rows:,}",
    )
    print(
        "BSE-only matched     :",
        f"{overall.matched_bse:,}",
    )
    print(
        "BOTH matched         :",
        f"{overall.matched_both:,}",
    )
    print(
        "Inserted BSE prices  :",
        f"{overall.inserted:,}",
    )
    print(
        "Duplicate prices     :",
        f"{overall.duplicates:,}",
    )
    print(
        "Unmatched ISIN       :",
        f"{overall.unmatched:,}",
    )
    print(
        "Ambiguous ISIN       :",
        f"{overall.ambiguous:,}",
    )
    print(
        "Invalid rows         :",
        f"{overall.invalid:,}",
    )
    print("=" * 72)

    if not args.apply:
        print()
        print("DRY-RUN ONLY.")
        print("No database changes were made.")


if __name__ == "__main__":
    main()
