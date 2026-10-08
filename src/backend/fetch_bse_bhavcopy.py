#!/usr/bin/env python3
"""
MarketPulse - BSE Cash Market BhavCopy Loader

Purpose
-------
Download and ingest BSE Cash Market (CM) stock BhavCopy data.

Safety rules
------------
1. BSE ingestion uses ISIN as the primary identity key.
2. security_master is NEVER created or modified by this loader.
3. Only securities already classified as BSE-only are loaded into daily_prices.
4. Securities classified as BOTH are intentionally skipped because the
   MarketPulse price-source policy is:
       BOTH -> NSE prices
       BSE  -> BSE prices
5. BSE ISINs not found in security_master are written to an unmatched report.
6. Default mode is DRY-RUN. PostgreSQL writes require --apply.
7. This script is deliberately independent of the NSE scheduler for now.

Examples
--------
Download and validate only:
    python fetch_bse_bhavcopy.py --date 2026-10-01

Use an existing raw CSV:
    python fetch_bse_bhavcopy.py --file ^
        "data\\bhavcopy\\bse\\raw\\BhavCopy_BSE_CM_0_0_0_20261001_F_0000.CSV"

Actually load BSE-only prices:
    python fetch_bse_bhavcopy.py --file ^
        "data\\bhavcopy\\bse\\raw\\BhavCopy_BSE_CM_0_0_0_20261001_F_0000.CSV" ^
        --apply
"""

from __future__ import annotations

import argparse
import csv
import io
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import psycopg
import requests
from dotenv import load_dotenv


# ============================================================
# Environment / configuration
# ============================================================

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DB_CONFIG = {
    "host": os.getenv("MARKETPULSE_DB_HOST", "localhost"),
    "port": os.getenv("MARKETPULSE_DB_PORT", "5432"),
    "dbname": os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
    "user": os.getenv("MARKETPULSE_DB_USER", "postgres"),
    "password": os.getenv("MARKETPULSE_DB_PASSWORD", ""),
}

BSE_BASE_URL = "https://www.bseindia.com"
BSE_BHAVCOPY_URL = (
    BSE_BASE_URL
    + "/download/BhavCopy/Equity/"
    + "BhavCopy_BSE_CM_0_0_0_{yyyymmdd}_F_0000.CSV"
)

BSE_RAW_DIR = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "bse"
    / "raw"
)

BSE_UNMATCHED_DIR = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "bse"
    / "unmatched"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
    "Connection": "keep-alive",
}


# ============================================================
# BSE UDiFF columns
# ============================================================

COLUMN_MAP = {
    "TradDt": "trade_date",
    "BizDt": "business_date",
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

REQUIRED_BSE_COLUMNS = tuple(COLUMN_MAP.keys())


@dataclass
class MappingStats:
    source_rows: int = 0
    bse_stock_rows: int = 0
    bse_only_matched: int = 0
    both_skipped: int = 0
    unmatched_isin: int = 0
    ambiguous_isin: int = 0
    invalid_rows: int = 0
    prices_inserted: int = 0
    duplicate_prices: int = 0


# ============================================================
# Arguments
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download/validate/load BSE CM BhavCopy."
    )

    source = parser.add_mutually_exclusive_group(required=True)

    source.add_argument(
        "--date",
        help="BSE trading date YYYY-MM-DD.",
    )

    source.add_argument(
        "--file",
        help="Existing BSE BhavCopy CSV.",
    )

    parser.add_argument(
        "--output-dir",
        default=str(BSE_RAW_DIR),
        help="Directory for downloaded raw BSE BhavCopy files.",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write BSE-only prices to PostgreSQL.",
    )

    parser.add_argument(
        "--show-unmatched",
        action="store_true",
        help="Print unmatched ISINs.",
    )

    return parser.parse_args()


# ============================================================
# HTTP / download
# ============================================================

def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from exc


def build_bse_url(trade_date: date) -> str:
    return BSE_BHAVCOPY_URL.format(
        yyyymmdd=trade_date.strftime("%Y%m%d")
    )


def download_bhavcopy(
    trade_date: date,
    output_dir: Path,
) -> Path:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir
        / (
            "BhavCopy_BSE_CM_0_0_0_"
            f"{trade_date.strftime('%Y%m%d')}_F_0000.CSV"
        )
    )

    if output_path.exists() and output_path.stat().st_size > 0:
        print("Already downloaded:", output_path)
        return output_path

    url = build_bse_url(trade_date)

    print()
    print("=" * 72)
    print("BSE BHAVCOPY DOWNLOAD")
    print("=" * 72)
    print("Trade date :", trade_date)
    print("URL        :", url)

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=60,
    )

    print("HTTP status:", response.status_code)
    print(
        "Content-Type:",
        response.headers.get("Content-Type", "unknown"),
    )
    print("Bytes      :", len(response.content))

    if response.status_code == 404:
        raise RuntimeError(
            f"No BSE BhavCopy available for {trade_date}."
        )

    response.raise_for_status()

    if not response.content:
        raise RuntimeError(
            f"BSE returned an empty response for {trade_date}."
        )

    sample = response.content[:500].decode(
        "utf-8",
        errors="replace",
    )

    if "<html" in sample.lower() or "<!doctype" in sample.lower():
        raise RuntimeError(
            "BSE returned HTML instead of CSV."
        )

    output_path.write_bytes(response.content)

    print("Saved      :", output_path)

    return output_path


# ============================================================
# CSV loading / normalization
# ============================================================

def decode_bytes(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def read_csv(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        raise FileNotFoundError(
            f"BSE BhavCopy file not found: {csv_path}"
        )

    raw = csv_path.read_bytes()

    if not raw:
        raise ValueError("BSE BhavCopy is empty.")

    text = decode_bytes(raw)

    reader = csv.DictReader(
        io.StringIO(text)
    )

    if not reader.fieldnames:
        raise ValueError(
            "BSE BhavCopy header could not be read."
        )

    columns = {
        str(column).strip()
        for column in reader.fieldnames
        if column is not None
    }

    missing = [
        column
        for column in REQUIRED_BSE_COLUMNS
        if column not in columns
    ]

    if missing:
        raise ValueError(
            "Missing BSE columns: "
            + ", ".join(missing)
        )

    rows = []

    for raw_row in reader:
        row = {
            str(key).strip(): (
                value.strip()
                if isinstance(value, str)
                else ""
            )
            for key, value in raw_row.items()
            if key is not None
        }

        row = {
            COLUMN_MAP.get(key, key): value
            for key, value in row.items()
        }

        rows.append(row)

    return rows


def normalize_rows(
    rows: Iterable[dict[str, str]],
) -> tuple[list[dict[str, object]], MappingStats]:

    stats = MappingStats(
        source_rows=len(list(rows))
    )

    # The iterable is normally a list, but materialize safely.
    rows = list(rows)

    stats.source_rows = len(rows)

    normalized = []

    for row in rows:
        trade_date_raw = str(
            row.get("trade_date") or ""
        ).strip()

        if not trade_date_raw:
            stats.invalid_rows += 1
            continue

        try:
            trade_date = parse_date(trade_date_raw)
        except ValueError:
            stats.invalid_rows += 1
            continue

        item: dict[str, object] = {
            "trade_date": trade_date,
            "segment": str(
                row.get("segment") or ""
            ).strip(),
            "source": str(
                row.get("source") or ""
            ).strip(),
            "instrument_type": str(
                row.get("instrument_type") or ""
            ).strip(),
            "instrument_id": None,
            "isin": str(
                row.get("isin") or ""
            ).strip().upper(),
            "symbol": str(
                row.get("symbol") or ""
            ).strip(),
            "series": str(
                row.get("series") or ""
            ).strip(),
            "instrument_name": str(
                row.get("instrument_name") or ""
            ).strip(),
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "last_price": None,
            "previous_close": None,
            "volume": None,
            "turnover": None,
        }

        numeric_fields = (
            "instrument_id",
            "open",
            "high",
            "low",
            "close",
            "last_price",
            "previous_close",
            "volume",
            "turnover",
        )

        for field in numeric_fields:
            value = row.get(field)

            if value in (None, ""):
                continue

            try:
                if field in {"instrument_id", "volume"}:
                    item[field] = int(float(str(value)))
                else:
                    item[field] = float(str(value))
            except (TypeError, ValueError):
                item[field] = None

        if not item["symbol"]:
            stats.invalid_rows += 1
            continue

        normalized.append(item)

    return normalized, stats


def filter_bse_stock_rows(
    rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        row
        for row in rows
        if row["segment"] == "CM"
        and row["source"] == "BSE"
        and row["instrument_type"] == "STK"
    ]


# ============================================================
# Database
# ============================================================

def get_connection():
    return psycopg.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        dbname=DB_CONFIG["dbname"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )


def resolve_bse_security(
    cursor,
    isin: str,
) -> tuple[str, int | None]:
    """
    Resolve BSE ISIN to canonical security_master.

    Returns:
        ("BSE", security_id)       -> BSE-only
        ("BOTH", security_id)      -> NSE+BSE
        ("UNMATCHED", None)
        ("AMBIGUOUS", None)

    BSE prices are now allowed for BOTH securities because
    daily_prices stores exchange separately.
    """

    if not isin:
        return "UNMATCHED", None

    cursor.execute(
        """
        SELECT
            security_id,
            exchange,
            exchange_tag
        FROM security_master
        WHERE UPPER(TRIM(isin)) = UPPER(TRIM(%s))
        ORDER BY security_id
        """,
        (isin,),
    )

    matches = cursor.fetchall()

    if not matches:
        return "UNMATCHED", None

    if len(matches) > 1:
        return "AMBIGUOUS", None

    security_id, exchange, exchange_tag = matches[0]

    exchange_value = str(
        exchange or ""
    ).upper()

    tag_value = str(
        exchange_tag or ""
    ).upper()

    if tag_value == "BOTH":
        return "BOTH", int(security_id)

    if tag_value == "BSE":
        return "BSE", int(security_id)

    # Safety: do not load BSE price against NSE-only master.
    if exchange_value == "BSE":
        return "BSE", int(security_id)

    return "UNMATCHED", None


def insert_daily_price(
    cursor,
    security_id: int,
    row: dict[str, object],
) -> bool:

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
            turnover
        )
        VALUES (
            %s, %s, 'BSE',
            %s, %s, %s, %s,
            %s, %s, %s, %s
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
# Unmatched report
# ============================================================

def write_unmatched_report(
    trade_date: date,
    rows: list[dict[str, object]],
) -> Path:

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

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=[
                "trade_date",
                "instrument_id",
                "isin",
                "symbol",
                "series",
                "instrument_name",
                "close",
                "volume",
            ],
        )

        writer.writeheader()

        for row in rows:
            writer.writerow(
                {
                    key: row.get(key)
                    for key in writer.fieldnames
                }
            )

    return path


# ============================================================
# Ingestion
# ============================================================

def ingest_file(
    csv_path: Path,
    apply_changes: bool,
) -> MappingStats:

    print()
    print("=" * 72)
    print(
        "BSE BHAVCOPY INGESTION",
        "|",
        "APPLY" if apply_changes else "DRY-RUN",
    )
    print("=" * 72)
    print("CSV:", csv_path)

    raw_rows = read_csv(csv_path)

    rows, stats = normalize_rows(
        raw_rows
    )

    stats.bse_stock_rows = len(
        filter_bse_stock_rows(rows)
    )

    bse_rows = filter_bse_stock_rows(
        rows
    )

    if not bse_rows:
        raise ValueError(
            "No BSE CM/STK rows found."
        )

    trade_dates = sorted(
        {
            row["trade_date"]
            for row in bse_rows
        }
    )

    if len(trade_dates) != 1:
        raise ValueError(
            "Expected exactly one BSE trade date; "
            f"found: {trade_dates}"
        )

    trade_date = trade_dates[0]

    unmatched_rows = []
    ambiguous_rows = []

    print("Trade date       :", trade_date)
    print("Source rows      :", stats.source_rows)
    print("BSE CM/STK rows  :", stats.bse_stock_rows)
    print("Mode             :", "APPLY" if apply_changes else "DRY-RUN")

    conn = get_connection()

    try:
        with conn.cursor() as cursor:

            run_id = None

            if apply_changes:
                cursor.execute(
                    """
                    INSERT INTO bhavcopy_runs (
                        trade_date,
                        source_file,
                        downloaded_at,
                        total_rows,
                        valid_rows,
                        status
                    )
                    VALUES (
                        %s,
                        %s,
                        CURRENT_TIMESTAMP,
                        %s,
                        %s,
                        'RUNNING'
                    )
                    RETURNING run_id
                    """,
                    (
                        trade_date,
                        str(csv_path),
                        stats.source_rows,
                        stats.bse_stock_rows,
                    ),
                )

                run_id = cursor.fetchone()[0]

            try:
                for position, row in enumerate(
                    bse_rows,
                    start=1,
                ):

                    isin = str(
                        row.get("isin") or ""
                    ).strip()

                    resolution, security_id = (
                        resolve_bse_security(
                            cursor,
                            isin,
                        )
                    )

                    if resolution in {"BSE", "BOTH"}:
                        stats.bse_only_matched += 1

                        if apply_changes:
                            inserted = insert_daily_price(
                                cursor,
                                security_id,
                                row,
                            )

                            if inserted:
                                stats.prices_inserted += 1
                            else:
                                stats.duplicate_prices += 1

                    
                    elif resolution == "AMBIGUOUS":
                        stats.ambiguous_isin += 1
                        ambiguous_rows.append(row)

                    else:
                        stats.unmatched_isin += 1
                        unmatched_rows.append(row)

                    if position % 500 == 0:
                        print(
                            f"Processed {position:,} / "
                            f"{len(bse_rows):,}"
                        )

                if apply_changes:
                    cursor.execute(
                        """
                        UPDATE bhavcopy_runs
                        SET
                            processed_at = CURRENT_TIMESTAMP,
                            inserted_rows = %s,
                            updated_rows = 0,
                            duplicate_rows = %s,
                            status = 'SUCCESS'
                        WHERE run_id = %s
                        """,
                        (
                            stats.prices_inserted,
                            stats.duplicate_prices,
                            run_id,
                        ),
                    )

                    conn.commit()

            except Exception:
                if apply_changes and run_id is not None:
                    conn.rollback()

                    with conn.cursor() as status_cursor:
                        status_cursor.execute(
                            """
                            UPDATE bhavcopy_runs
                            SET
                                processed_at = CURRENT_TIMESTAMP,
                                status = 'FAILED'
                            WHERE run_id = %s
                            """,
                            (run_id,),
                        )

                    conn.commit()

                raise

    finally:
        conn.close()

    report_path = write_unmatched_report(
        trade_date,
        unmatched_rows,
    )

    print()
    print("=" * 72)
    print("BSE INGESTION SUMMARY")
    print("=" * 72)
    print("Trade date          :", trade_date)
    print("Source rows         :", stats.source_rows)
    print("BSE CM/STK rows     :", stats.bse_stock_rows)
    print("BSE-only matched    :", stats.bse_only_matched)
    print("BOTH skipped        :", stats.both_skipped)
    print("Unmatched ISIN      :", stats.unmatched_isin)
    print("Ambiguous ISIN      :", stats.ambiguous_isin)
    print("Invalid rows        :", stats.invalid_rows)
    print("Prices inserted     :", stats.prices_inserted)
    print("Duplicate prices    :", stats.duplicate_prices)
    print("Unmatched report    :", report_path)
    print("=" * 72)

    if ambiguous_rows:
        print()
        print(
            "WARNING: ambiguous ISINs:",
            len(ambiguous_rows),
        )

    if not apply_changes:
        print()
        print(
            "DRY-RUN ONLY: no PostgreSQL changes were made."
        )

    return stats


# ============================================================
# Main
# ============================================================

def main() -> int:
    args = parse_args()

    try:
        if args.date:
            trade_date = parse_date(
                args.date
            )

            csv_path = download_bhavcopy(
                trade_date,
                Path(args.output_dir),
            )

        else:
            csv_path = Path(
                args.file
            ).expanduser().resolve()

        ingest_file(
            csv_path,
            apply_changes=args.apply,
        )

        return 0

    except requests.RequestException as exc:
        print()
        print("BSE HTTP ERROR")
        print("-" * 72)
        print(exc)
        return 1

    except Exception as exc:
        print()
        print("BSE INGESTION ERROR")
        print("-" * 72)
        print(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
