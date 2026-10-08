import os
from dotenv import load_dotenv
import sys
import requests
from pathlib import Path
from datetime import datetime

import pandas as pd
import psycopg

load_dotenv()

# ==========================================================
# Configuration
# ==========================================================

DB_CONFIG = {
    "host": os.getenv("MARKETPULSE_DB_HOST", "localhost"),
    "port": os.getenv("MARKETPULSE_DB_PORT", "5432"),
    "dbname": os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
    "user": os.getenv("MARKETPULSE_DB_USER", "postgres"),
    "password": os.getenv("MARKETPULSE_DB_PASSWORD", ""),
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]

BHAVCOPY_DIR = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
)

DEFAULT_CSV = BHAVCOPY_DIR / "test_20260529.csv"


# ==========================================================
# Read CSV
# ==========================================================

def load_csv(csv_path):

    print()
    print("=" * 70)
    print("Loading Bhavcopy")
    print("=" * 70)

    print("File:", csv_path)

    df = pd.read_csv(csv_path)

    print("Rows:", len(df))

    return df


# ==========================================================
# Normalize column names
# ==========================================================

def normalize_columns(df):

    column_mapping = {
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

    missing = [
        column
        for column in column_mapping
        if column not in df.columns
    ]

    if missing:

        raise ValueError(
            f"Missing required Bhavcopy columns: {missing}"
        )

    df = df.rename(
        columns=column_mapping
    )

    return df


# ==========================================================
# Clean data
# ==========================================================

def clean_data(df):

    df["trade_date"] = pd.to_datetime(
        df["trade_date"],
        errors="coerce"
    ).dt.date

    string_columns = [
        "isin",
        "symbol",
        "series",
        "instrument_type",
        "instrument_name",
    ]

    for column in string_columns:

        df[column] = (
            df[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    numeric_columns = [
        "instrument_id",
        "open",
        "high",
        "low",
        "close",
        "last_price",
        "previous_close",
        "volume",
        "turnover",
    ]

    for column in numeric_columns:

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    # Remove rows without a trade date
    df = df[
        df["trade_date"].notna()
    ].copy()

    # Remove rows without symbol
    df = df[
        df["symbol"] != ""
    ].copy()

    print()
    print("Valid rows:", len(df))

    print(
        "Trade dates:",
        df["trade_date"].unique()
    )

    return df


# ==========================================================
# Database connection
# ==========================================================

def get_connection():

    return psycopg.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        dbname=DB_CONFIG["dbname"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )


# ==========================================================
# Upsert Security Master
# ==========================================================

def get_or_create_security(
    cursor,
    row
):

    cursor.execute(
        """
        SELECT security_id
        FROM security_master
        WHERE
            (
                isin <> ''
                AND isin = %s
            )
            OR
            (
                isin = ''
                AND symbol = %s
                AND series = %s
            )
        ORDER BY security_id
        LIMIT 1
        """,
        (
            row["isin"],
            row["symbol"],
            row["series"],
        )
    )

    result = cursor.fetchone()

    if result:

        security_id = result[0]

        cursor.execute(
            """
            UPDATE security_master
            SET
                symbol = %s,
                series = %s,
                instrument_id = %s,
                instrument_type = %s,
                instrument_name = %s,
                exchange = 'NSE',
                segment = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE security_id = %s
            """,
            (
                row["symbol"],
                row["series"],
                (
                    int(row["instrument_id"])
                    if pd.notna(row["instrument_id"])
                    else None
                ),
                row["instrument_type"],
                row["instrument_name"],
                row.get("segment", "CM"),
                security_id,
            )
        )

        return security_id, False

    cursor.execute(
        """
        INSERT INTO security_master (
            isin,
            symbol,
            series,
            instrument_id,
            instrument_type,
            instrument_name,
            exchange,
            segment,
            is_active
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, 'NSE', %s, TRUE
        )
        RETURNING security_id
        """,
        (
            row["isin"],
            row["symbol"],
            row["series"],
            (
                int(row["instrument_id"])
                if pd.notna(row["instrument_id"])
                else None
            ),
            row["instrument_type"],
            row["instrument_name"],
            row.get("segment", "CM"),
        )
    )

    security_id = cursor.fetchone()[0]

    return security_id, True


# ==========================================================
# Insert Daily Price
# ==========================================================

def insert_daily_price(
    cursor,
    security_id,
    row
):

    cursor.execute(
        """
        INSERT INTO daily_prices (
            security_id,
            trade_date,
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
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s
        )
        ON CONFLICT (
            security_id,
            trade_date
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
            (
                int(row["volume"])
                if pd.notna(row["volume"])
                else None
            ),
            row["turnover"],
        )
    )

    result = cursor.fetchone()

    return result is not None


# ==========================================================
# File / historical helpers
# ==========================================================

NSE_UDIFF_URL = (
    "https://nsearchives.nseindia.com/content/cm/"
    "BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"
)

DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept": "application/zip,application/octet-stream,*/*",
    "Referer": "https://www.nseindia.com/",
}


def discover_csv_files(path):
    """Accept a single CSV or a directory containing CSV files."""
    path = Path(path)

    if path.is_file():
        return [path]

    if path.is_dir():
        files = sorted(
            p for p in path.rglob("*.csv")
            if p.is_file()
        )
        if not files:
            raise FileNotFoundError(
                f"No CSV files found in directory: {path}"
            )
        return files

    raise FileNotFoundError(
        f"Bhavcopy path not found: {path}"
    )


def parse_date_argument(value):
    return datetime.strptime(
        value,
        "%Y-%m-%d"
    ).date()


def is_weekend(value):
    return value.weekday() >= 5


def build_udiff_url(trade_date):
    return NSE_UDIFF_URL.format(
        date=trade_date.strftime("%Y%m%d")
    )


def download_historical_bhavcopy(
    session,
    trade_date,
    output_dir
):
    """
    Download one NSE CM UDiFF Bhavcopy ZIP.

    Returns:
        Path to ZIP on success/reuse.
        None when NSE has no file for that date.
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    zip_path = (
        output_dir
        / (
            "BhavCopy_NSE_CM_0_0_0_"
            f"{trade_date.strftime('%Y%m%d')}_F_0000.csv.zip"
        )
    )

    if zip_path.exists() and zip_path.stat().st_size > 0:
        print("Already downloaded:", zip_path)
        return zip_path

    url = build_udiff_url(trade_date)

    print("Downloading:", trade_date)
    print("URL:", url)

    response = session.get(
        url,
        timeout=45
    )

    if response.status_code == 404:
        print("No Bhavcopy available:", trade_date)
        return None

    response.raise_for_status()

    if not response.content:
        raise ValueError(
            f"Empty NSE response for {trade_date}"
        )

    zip_path.write_bytes(
        response.content
    )

    print(
        "Downloaded:",
        zip_path.name,
        "| bytes:",
        len(response.content)
    )

    return zip_path


def extract_udiff_csv(
    zip_path,
    extract_dir
):
    """Extract the primary CSV from a UDiFF ZIP."""

    import zipfile

    extract_dir = Path(extract_dir)
    extract_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    with zipfile.ZipFile(
        zip_path,
        "r"
    ) as archive:

        csv_names = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".csv")
        ]

        if not csv_names:
            raise ValueError(
                f"No CSV found inside {zip_path}"
            )

        csv_name = sorted(
            csv_names,
            key=lambda value: (
                value.count("/"),
                len(value)
            )
        )[0]

        target = (
            extract_dir
            / Path(csv_name).name
        )

        if not target.exists():

            with archive.open(
                csv_name
            ) as source_file, open(
                target,
                "wb"
            ) as target_file:

                target_file.write(
                    source_file.read()
                )

    print(
        "Extracted:",
        target
    )

    return target


# ==========================================================
# Ingest one Bhavcopy file
# ==========================================================

def ingest_file(
    conn,
    csv_path
):

    print()
    print("=" * 70)
    print("Loading Bhavcopy")
    print("=" * 70)
    print("File:", csv_path)

    df = load_csv(
        csv_path
    )

    df = normalize_columns(
        df
    )

    df = clean_data(
        df
    )

    trade_dates = (
        df["trade_date"]
        .dropna()
        .unique()
    )

    if len(trade_dates) != 1:

        raise ValueError(
            f"Expected exactly one trading date in "
            f"{csv_path.name}, found: {trade_dates}"
        )

    trade_date = trade_dates[0]

    inserted_security_count = 0
    updated_security_count = 0
    inserted_price_count = 0
    duplicate_price_count = 0

    with conn.cursor() as cursor:

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
                len(df),
                len(df),
            )
        )

        run_id = cursor.fetchone()[0]

        try:

            for position, (_, row) in enumerate(
                df.iterrows(),
                start=1
            ):

                security_id, created = (
                    get_or_create_security(
                        cursor,
                        row
                    )
                )

                if created:
                    inserted_security_count += 1
                else:
                    updated_security_count += 1

                inserted = insert_daily_price(
                    cursor,
                    security_id,
                    row
                )

                if inserted:
                    inserted_price_count += 1
                else:
                    duplicate_price_count += 1

                if position % 500 == 0:

                    print(
                        f"Processed {position} / {len(df)}"
                    )

            cursor.execute(
                """
                UPDATE bhavcopy_runs
                SET
                    processed_at = CURRENT_TIMESTAMP,
                    inserted_rows = %s,
                    updated_rows = %s,
                    duplicate_rows = %s,
                    status = 'SUCCESS'
                WHERE run_id = %s
                """,
                (
                    inserted_price_count,
                    updated_security_count,
                    duplicate_price_count,
                    run_id,
                )
            )

            conn.commit()

        except Exception:

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
                    (run_id,)
                )

            conn.commit()

            raise

    print()
    print("Trade date:", trade_date)
    print("Source rows:", len(df))
    print("New securities:", inserted_security_count)
    print("Existing securities updated:", updated_security_count)
    print("Prices inserted:", inserted_price_count)
    print("Duplicate prices skipped:", duplicate_price_count)

    return {
        "trade_date": trade_date,
        "source_rows": len(df),
        "new_securities": inserted_security_count,
        "updated_securities": updated_security_count,
        "prices_inserted": inserted_price_count,
        "duplicates": duplicate_price_count,
    }


# ==========================================================
# Historical date-range downloader + ingestion
# ==========================================================

def ingest_historical_range(
    start_date,
    end_date
):
    """
    Download and ingest one NSE CM trading day at a time.

    Files are stored under:
        data/bhavcopy/historical/YYYY/MM/

    A missing date (weekend/holiday) is logged and skipped.
    Existing ZIPs are reused.
    Database writes remain idempotent via the existing
    (security_id, trade_date) unique key.
    """

    start_date = (
        parse_date_argument(start_date)
        if isinstance(start_date, str)
        else start_date
    )

    end_date = (
        parse_date_argument(end_date)
        if isinstance(end_date, str)
        else end_date
    )

    if start_date > end_date:
        raise ValueError(
            "Start date cannot be after end date."
        )

    download_root = (
        BHAVCOPY_DIR
        / "historical"
    )

    session = requests.Session()

    session.headers.update(
        DOWNLOAD_HEADERS
    )

    stats = {
        "dates_checked": 0,
        "weekends_skipped": 0,
        "files_downloaded_or_reused": 0,
        "dates_missing": 0,
        "dates_ingested": 0,
        "prices_inserted": 0,
        "duplicate_prices": 0,
        "failed": 0,
    }

    conn = get_connection()

    try:

        current_date = start_date

        while current_date <= end_date:

            stats["dates_checked"] += 1

            print()
            print("#" * 70)
            print(
                "Historical date:",
                current_date
            )
            print("#" * 70)

            if is_weekend(current_date):

                stats["weekends_skipped"] += 1

                print(
                    "Weekend - skipped"
                )

                current_date += pd.Timedelta(
                    days=1
                ).to_pytimedelta()

                continue

            day_dir = (
                download_root
                / current_date.strftime("%Y")
                / current_date.strftime("%m")
            )

            try:

                zip_path = download_historical_bhavcopy(
                    session,
                    current_date,
                    day_dir
                )

                if zip_path is None:

                    stats["dates_missing"] += 1

                    current_date += pd.Timedelta(
                        days=1
                    ).to_pytimedelta()

                    continue

                stats[
                    "files_downloaded_or_reused"
                ] += 1

                csv_path = extract_udiff_csv(
                    zip_path,
                    day_dir / "extracted"
                )

                result = ingest_file(
                    conn,
                    csv_path
                )

                stats["dates_ingested"] += 1
                stats["prices_inserted"] += result[
                    "prices_inserted"
                ]
                stats["duplicate_prices"] += result[
                    "duplicates"
                ]

            except Exception as error:

                conn.rollback()

                stats["failed"] += 1

                print(
                    "FAILED:",
                    current_date,
                    "|",
                    error
                )

            current_date += pd.Timedelta(
                days=1
            ).to_pytimedelta()

    finally:

        conn.close()
        session.close()

    print()
    print("=" * 70)
    print("HISTORICAL BHAVCOPY LOAD COMPLETE")
    print("=" * 70)

    for key, value in stats.items():
        print(
            f"{key}:",
            value
        )

    print("=" * 70)


# ==========================================================
# Main ingestion
# ==========================================================

def main():

    args = sys.argv[1:]

    # Historical mode:
    #
    #   python fetch_bhavcopy.py \
    #       --historical 2025-01-01 2026-09-04
    #
    # Existing ZIP/CSV files are reused.

    if args and args[0] == "--historical":

        if len(args) != 3:

            raise ValueError(
                "Usage: fetch_bhavcopy.py "
                "--historical YYYY-MM-DD YYYY-MM-DD"
            )

        ingest_historical_range(
            args[1],
            args[2]
        )

        return

    # Existing compatibility:
    #
    #   python fetch_bhavcopy.py file.csv
    #
    # or
    #
    #   python fetch_bhavcopy.py directory

    input_path = (
        Path(args[0])
        if args
        else DEFAULT_CSV
    )

    csv_files = discover_csv_files(
        input_path
    )

    print()
    print("=" * 70)
    print("MarketPulse NSE Bhavcopy Loader")
    print("=" * 70)
    print("Input:", input_path)
    print("Files discovered:", len(csv_files))
    print("=" * 70)

    conn = get_connection()

    totals = {
        "files_success": 0,
        "files_failed": 0,
        "source_rows": 0,
        "new_securities": 0,
        "updated_securities": 0,
        "prices_inserted": 0,
        "duplicates": 0,
    }

    try:

        for index, csv_path in enumerate(
            csv_files,
            start=1
        ):

            print()
            print(
                f"[{index}/{len(csv_files)}]",
                csv_path.name
            )

            try:

                result = ingest_file(
                    conn,
                    csv_path
                )

                totals["files_success"] += 1
                totals["source_rows"] += result[
                    "source_rows"
                ]
                totals["new_securities"] += result[
                    "new_securities"
                ]
                totals["updated_securities"] += result[
                    "updated_securities"
                ]
                totals["prices_inserted"] += result[
                    "prices_inserted"
                ]
                totals["duplicates"] += result[
                    "duplicates"
                ]

            except Exception as error:

                totals["files_failed"] += 1

                print(
                    "ERROR:",
                    error
                )

    finally:

        conn.close()

    print()
    print("=" * 70)
    print("BHAVCOPY LOAD COMPLETE")
    print("=" * 70)

    print(
        "Files successful:",
        totals["files_success"]
    )
    print(
        "Files failed:",
        totals["files_failed"]
    )
    print(
        "Source rows:",
        totals["source_rows"]
    )
    print(
        "New securities:",
        totals["new_securities"]
    )
    print(
        "Existing securities updated:",
        totals["updated_securities"]
    )
    print(
        "Prices inserted:",
        totals["prices_inserted"]
    )
    print(
        "Duplicate prices skipped:",
        totals["duplicates"]
    )

    print("=" * 70)


# ==========================================================
# Run
# ==========================================================

if __name__ == "__main__":
    main()