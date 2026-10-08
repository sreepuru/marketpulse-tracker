import os
from dotenv import load_dotenv
import sys
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import psycopg
import requests
import zipfile

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

HISTORICAL_DIR = (
    BHAVCOPY_DIR
    / "historical"
)

NSE_HISTORICAL_URL = (
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
# Historical file discovery
# ==========================================================

DEFAULT_HISTORICAL_DIR = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "historical"
)


def discover_input_files(path):

    path = Path(path)

    if path.is_file():

        return [
            path
        ]

    if path.is_dir():

        files = sorted(
            p
            for p in path.rglob("*")
            if p.is_file()
            and (
                p.suffix.lower() == ".csv"
                or p.suffix.lower() == ".zip"
            )
        )

        if not files:

            raise FileNotFoundError(
                f"No CSV or ZIP files found under: {path}"
            )

        return files

    raise FileNotFoundError(
        f"Path not found: {path}"
    )


# ==========================================================
# Extract ZIP
# ==========================================================

def extract_csv_from_zip(
    zip_path
):

    import zipfile

    zip_path = Path(zip_path)

    extract_dir = (
        zip_path.parent
        / "extracted"
    )

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
                f"No CSV found inside: {zip_path}"
            )

        # The final Bhavcopy CSV is normally the primary/shortest path.
        csv_name = sorted(
            csv_names,
            key=lambda name: (
                name.count("/"),
                len(name)
            )
        )[0]

        csv_path = (
            extract_dir
            / Path(csv_name).name
        )

        if not csv_path.exists():

            with archive.open(
                csv_name
            ) as source_file:

                csv_path.write_bytes(
                    source_file.read()
                )

    return csv_path


# ==========================================================
# Resolve input to CSV
# ==========================================================

def resolve_csv(
    path
):

    path = Path(path)

    if path.suffix.lower() == ".csv":

        return path

    if path.suffix.lower() == ".zip":

        return extract_csv_from_zip(
            path
        )

    raise ValueError(
        f"Unsupported input type: {path}"
    )


# ==========================================================
# Ingest one CSV
# ==========================================================

def ingest_file(
    conn,
    csv_path
):

    print()
    print("=" * 70)
    print("Loading historical Bhavcopy")
    print("=" * 70)
    print(
        "CSV:",
        csv_path
    )

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
            f"Expected exactly one trade date in "
            f"{csv_path.name}; found: {trade_dates}"
        )

    trade_date = trade_dates[0]

    print(
        "Trade date:",
        trade_date
    )

    inserted_security_count = 0
    updated_security_count = 0
    inserted_price_count = 0
    duplicate_price_count = 0

    with conn.cursor() as cursor:

        # --------------------------------------------------
        # Record the ingestion run.
        # --------------------------------------------------

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

                if position % 1000 == 0:

                    print(
                        f"Processed "
                        f"{position:,} / "
                        f"{len(df):,}"
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

        except Exception as error:

            conn.rollback()

            print(
                "Ingestion error:",
                error
            )

            raise

    print()
    print(
        "SUCCESS:",
        trade_date
    )

    print(
        "Source rows:",
        len(df)
    )

    print(
        "New securities:",
        inserted_security_count
    )

    print(
        "Existing securities updated:",
        updated_security_count
    )

    print(
        "Prices inserted:",
        inserted_price_count
    )

    print(
        "Duplicate prices skipped:",
        duplicate_price_count
    )

    return {
        "trade_date": trade_date,
        "source_rows": len(df),
        "new_securities": inserted_security_count,
        "updated_securities": updated_security_count,
        "prices_inserted": inserted_price_count,
        "duplicates": duplicate_price_count,
    }


# ==========================================================
# Load all downloaded files
# ==========================================================

def load_downloaded_files(
    input_path
):

    input_files = discover_input_files(
        input_path
    )

    print()
    print("=" * 70)
    print("MarketPulse Historical Bhavcopy DB Loader")
    print("=" * 70)

    print(
        "Input:",
        input_path
    )

    print(
        "Files found:",
        len(input_files)
    )

    print("=" * 70)

    stats = {
        "files_found": len(input_files),
        "files_loaded": 0,
        "files_failed": 0,
        "source_rows": 0,
        "new_securities": 0,
        "updated_securities": 0,
        "prices_inserted": 0,
        "duplicate_prices": 0,
    }

    conn = get_connection()

    try:

        for index, input_file in enumerate(
            input_files,
            start=1
        ):

            print()
            print(
                f"[{index}/{len(input_files)}]"
            )

            print(
                "Input file:",
                input_file
            )

            try:

                csv_path = resolve_csv(
                    input_file
                )

                result = ingest_file(
                    conn,
                    csv_path
                )

                stats["files_loaded"] += 1
                stats["source_rows"] += result[
                    "source_rows"
                ]
                stats["new_securities"] += result[
                    "new_securities"
                ]
                stats["updated_securities"] += result[
                    "updated_securities"
                ]
                stats["prices_inserted"] += result[
                    "prices_inserted"
                ]
                stats["duplicate_prices"] += result[
                    "duplicates"
                ]

            except Exception as error:

                stats["files_failed"] += 1

                print()
                print(
                    "FAILED:",
                    input_file
                )

                print(
                    "Reason:",
                    error
                )

                # The failed file is isolated. Continue with
                # the remaining historical files.
                continue

    finally:

        conn.close()

    print()
    print("=" * 70)
    print("HISTORICAL DB LOAD COMPLETE")
    print("=" * 70)

    for key, value in stats.items():

        print(
            f"{key}:",
            value
        )

    print("=" * 70)


# ==========================================================
# Main
# ==========================================================

def main():

    args = sys.argv[1:]

    # ------------------------------------------------------
    # New explicit mode:
    #
    # python fetch_bhavcopy.py --load-directory
    # python fetch_bhavcopy.py --load-directory <path>
    #
    # The default directory is:
    # data/bhavcopy/historical
    # ------------------------------------------------------

    if not args:

        input_path = (
            DEFAULT_HISTORICAL_DIR
        )

        load_downloaded_files(
            input_path
        )

        return

    if args[0] == "--load-directory":

        if len(args) > 2:

            raise ValueError(
                "Usage: "
                "fetch_bhavcopy.py "
                "--load-directory [PATH]"
            )

        input_path = (
            Path(args[1])
            if len(args) == 2
            else DEFAULT_HISTORICAL_DIR
        )

        load_downloaded_files(
            input_path
        )

        return

    if args[0] == "--load-file":

        if len(args) != 2:

            raise ValueError(
                "Usage: "
                "fetch_bhavcopy.py "
                "--load-file FILE"
            )

        input_path = Path(
            args[1]
        )

        files = discover_input_files(
            input_path
        )

        if len(files) != 1:

            raise ValueError(
                "--load-file expects exactly "
                "one CSV or ZIP file."
            )

        conn = get_connection()

        try:

            csv_path = resolve_csv(
                files[0]
            )

            ingest_file(
                conn,
                csv_path
            )

        finally:

            conn.close()

        return

    # ------------------------------------------------------
    # Backward compatibility:
    #
    # python fetch_bhavcopy.py file.csv
    # python fetch_bhavcopy.py directory
    # ------------------------------------------------------

    input_path = Path(
        args[0]
    )

    load_downloaded_files(
        input_path
    )


# ==========================================================
# Run
# ==========================================================

if __name__ == "__main__":
    main()