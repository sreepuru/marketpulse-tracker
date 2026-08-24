import os
from dotenv import load_dotenv
import sys
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

DEFAULT_CSV = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "test_20260529.csv"
)


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
# Main ingestion
# ==========================================================

def main():

    csv_path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else DEFAULT_CSV
    )

    if not csv_path.exists():

        raise FileNotFoundError(
            f"CSV not found: {csv_path}"
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

    trade_dates = df[
        "trade_date"
    ].unique()

    if len(trade_dates) != 1:

        raise ValueError(
            "Expected exactly one trading date, "
            f"found: {trade_dates}"
        )

    trade_date = trade_dates[0]

    print()
    print(
        "Processing trade date:",
        trade_date
    )

    conn = get_connection()

    inserted_security_count = 0
    updated_security_count = 0
    inserted_price_count = 0
    duplicate_price_count = 0

    try:

        with conn.cursor() as cursor:

            # --------------------------------------------------
            # Start ingestion record
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

            # --------------------------------------------------
            # Process rows
            # --------------------------------------------------

            for index, row in df.iterrows():

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

                if (
                    (index + 1) % 500 == 0
                ):

                    print(
                        f"Processed {index + 1} / {len(df)}"
                    )

            # --------------------------------------------------
            # Complete ingestion record
            # --------------------------------------------------

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

        print()
        print(
            "ERROR:",
            error
        )

        raise

    finally:

        conn.close()

    # ----------------------------------------------------------
    # Summary
    # ----------------------------------------------------------

    print()
    print("=" * 70)
    print("INGESTION SUCCESSFUL")
    print("=" * 70)

    print(
        "Trade date:",
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

    print("=" * 70)


# ==========================================================
# Run
# ==========================================================

if __name__ == "__main__":
    main()