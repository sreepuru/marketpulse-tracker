import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime

import pandas as pd
import psycopg2
from dotenv import load_dotenv


# ==========================================================
# PROJECT CONFIGURATION
# ==========================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

BACKEND_DIR = PROJECT_ROOT / "src" / "backend"

DATA_DIR = PROJECT_ROOT / "data"
BHAVCOPY_DIR = DATA_DIR / "bhavcopy"
EXTRACTED_DIR = BHAVCOPY_DIR / "extracted"

PUBLIC_DIR = PROJECT_ROOT / "public"

LOG_DIR = PROJECT_ROOT / "logs"


# ==========================================================
# BACKEND SCRIPTS
# ==========================================================

FETCH_BHAVCOPY = BACKEND_DIR / "fetch_bhavcopy.py"

LOAD_BHAVCOPY = BACKEND_DIR / "load_bhavcopy_to_db.py"

FETCH_NSE = BACKEND_DIR / "fetch_nse.py"

LOAD_CORPORATE_ACTIONS = (
    BACKEND_DIR / "load_corporate_actions.py"
)


# ==========================================================
# ENVIRONMENT
# ==========================================================

load_dotenv(PROJECT_ROOT / ".env")


DB_CONFIG = {
    "host": os.getenv(
        "MARKETPULSE_DB_HOST",
        "localhost"
    ),

    "port": int(
        os.getenv(
            "MARKETPULSE_DB_PORT",
            "5432"
        )
    ),

    "dbname": os.getenv(
        "MARKETPULSE_DB_NAME",
        "marketpulse"
    ),

    "user": os.getenv(
        "MARKETPULSE_DB_USER",
        "postgres"
    ),

    "password": os.getenv(
        "MARKETPULSE_DB_PASSWORD",
        ""
    ),
}


# ==========================================================
# LOGGING
# ==========================================================

class Tee:
    """
    Writes output to multiple streams.

    This allows the ingestion output to remain visible
    in PowerShell while simultaneously being written
    to the daily log file.
    """

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()

    def flush(self):
        for stream in self.streams:
            stream.flush()


# ==========================================================
# CONSOLE HELPERS
# ==========================================================

def separator():
    print("-" * 70)


def title(text):
    print()
    print("=" * 70)
    print(text)
    print("=" * 70)


def fail(message):
    """
    Fail the pipeline.

    SystemExit is intentionally used so the Windows
    Task Scheduler receives a non-zero exit code.
    """

    print()
    print("=" * 70)
    print("INGESTION FAILED")
    print("=" * 70)
    print(message)
    print("=" * 70)

    raise SystemExit(1)


# ==========================================================
# RUN PYTHON SCRIPT
# ==========================================================

def run_script(script_path, *args):
    """
    Run another backend Python script using the same
    Python interpreter that is running this orchestrator.
    """

    if not script_path.exists():

        fail(
            f"Required script does not exist:\n"
            f"{script_path}"
        )

    command = [
        sys.executable,
        str(script_path),
        *[str(arg) for arg in args],
    ]

    print()
    print(f"Running: {script_path.name}")
    separator()

    print(
        "Command:",
        " ".join(command)
    )

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
    )

    if result.returncode != 0:

        fail(
            f"{script_path.name} exited with "
            f"code {result.returncode}."
        )

    print()
    print(
        f"{script_path.name} "
        f"completed successfully."
    )


# ==========================================================
# FIND LATEST EXTRACTED CSV
# ==========================================================

def find_latest_bhavcopy():
    """
    Find the newest valid NSE Bhavcopy CSV.

    Searches recursively because the NSE ZIP extraction
    currently creates a directory containing the CSV.

    Test files are deliberately ignored.
    """

    if not EXTRACTED_DIR.exists():

        fail(
            "Bhavcopy extraction directory does "
            "not exist:\n"
            f"{EXTRACTED_DIR}"
        )

    csv_files = []

    for path in EXTRACTED_DIR.rglob("*.csv"):

        if not path.is_file():
            continue

        # Ignore test files.
        if path.name.lower().startswith("test_"):
            continue

        csv_files.append(path)

    if not csv_files:

        fail(
            "No Bhavcopy CSV was found after "
            "download/extraction."
        )

    csv_files.sort(
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    selected = csv_files[0]

    print()
    print("Latest Bhavcopy CSV:")
    print(selected)

    return selected


# ==========================================================
# DETECT TRADE DATE
# ==========================================================

def detect_trade_date(csv_path):
    """
    Detect the actual trade date from the downloaded
    NSE Bhavcopy.

    Handles:
    - UTF-8 BOM
    - whitespace in headers
    - column-case differences
    - empty files
    """

    print()
    print("Reading Bhavcopy header...")
    print(f"File: {csv_path}")

    try:

        header_df = pd.read_csv(
            csv_path,
            nrows=0,
            encoding="utf-8-sig",
        )

    except Exception as exc:

        fail(
            "Unable to read Bhavcopy CSV header:\n"
            f"{exc}"
        )

    original_columns = list(
        header_df.columns
    )

    normalized_columns = {
        str(column).strip().upper(): column
        for column in original_columns
    }

    print()
    print("Columns detected:")

    for column in original_columns:
        print(f" - {column}")

    # ------------------------------------------------------
    # Find trade-date column
    # ------------------------------------------------------

    trade_date_column = None

    for candidate in [
        "TRADDT",
        "TRADE_DATE",
        "TRADEDATE",
        "BIZDT",
    ]:

        if candidate in normalized_columns:

            trade_date_column = (
                normalized_columns[candidate]
            )

            break

    if trade_date_column is None:

        fail(
            "No trade-date column was found in "
            "the downloaded Bhavcopy.\n\n"
            f"File: {csv_path}\n"
            f"Columns detected: {original_columns}"
        )

    print()
    print(
        "Trade-date column detected:",
        trade_date_column
    )

    # ------------------------------------------------------
    # Read trade-date column
    # ------------------------------------------------------

    try:

        df = pd.read_csv(
            csv_path,
            usecols=[trade_date_column],
            encoding="utf-8-sig",
        )

    except Exception as exc:

        fail(
            "Unable to read Bhavcopy trade date:\n"
            f"{exc}"
        )

    if df.empty:

        fail(
            "Bhavcopy CSV contains no records."
        )

    # ------------------------------------------------------
    # Convert dates
    # ------------------------------------------------------

    parsed_dates = pd.to_datetime(
        df[trade_date_column],
        errors="coerce",
    )

    trade_dates = (
        parsed_dates
        .dropna()
        .dt.date
        .unique()
    )

    if len(trade_dates) == 0:

        fail(
            f"No valid trade date could be read "
            f"from {trade_date_column}."
        )

    if len(trade_dates) > 1:

        fail(
            "Bhavcopy contains multiple trade dates: "
            f"{list(trade_dates)}"
        )

    trade_date = trade_dates[0]

    print()
    print(
        f"Detected trade date: {trade_date}"
    )

    return trade_date


# ==========================================================
# DATABASE CONNECTION
# ==========================================================

def get_db_connection():

    try:

        return psycopg2.connect(
            **DB_CONFIG
        )

    except Exception as exc:

        fail(
            "Could not connect to PostgreSQL.\n"
            f"{exc}"
        )


# ==========================================================
# DATABASE VALIDATION
# ==========================================================

def validate_bhavcopy(trade_date):

    title(
        "Validating PostgreSQL"
    )

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # --------------------------------------------------
            # Daily price count
            # --------------------------------------------------

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM daily_prices
                WHERE trade_date = %s
                """,
                (trade_date,),
            )

            price_rows = cursor.fetchone()[0]

            # --------------------------------------------------
            # Latest DB date
            # --------------------------------------------------

            cursor.execute(
                """
                SELECT MAX(trade_date)
                FROM daily_prices
                """
            )

            latest_date = (
                cursor.fetchone()[0]
            )

            # --------------------------------------------------
            # Bhavcopy run
            # --------------------------------------------------

            cursor.execute(
                """
                SELECT
                    run_id,
                    total_rows,
                    valid_rows,
                    inserted_rows,
                    updated_rows,
                    duplicate_rows,
                    status
                FROM bhavcopy_runs
                WHERE trade_date = %s
                ORDER BY run_id DESC
                LIMIT 1
                """,
                (trade_date,),
            )

            run = cursor.fetchone()

    finally:

        connection.close()

    print(
        f"Expected trade date : {trade_date}"
    )

    print(
        f"Daily price rows    : {price_rows}"
    )

    print(
        f"Latest DB date      : {latest_date}"
    )

    if run:

        print(
            "Ingestion run found : YES"
        )

        print(
            f"Run ID              : {run[0]}"
        )

        print(
            f"Source rows         : {run[1]}"
        )

        print(
            f"Valid rows          : {run[2]}"
        )

        print(
            f"Inserted rows       : {run[3]}"
        )

        print(
            f"Updated rows        : {run[4]}"
        )

        print(
            f"Duplicate rows      : {run[5]}"
        )

        print(
            f"Status              : {run[6]}"
        )

    else:

        print(
            "Ingestion run found : NO"
        )

    # ----------------------------------------------------------
    # Critical validation
    # ----------------------------------------------------------

    if price_rows == 0:

        fail(
            f"No daily_prices records found "
            f"for {trade_date}."
        )

    if latest_date != trade_date:

        fail(
            f"Database latest trade date is "
            f"{latest_date}, but expected "
            f"{trade_date}."
        )

    if not run:

        fail(
            f"No bhavcopy_runs record found "
            f"for {trade_date}."
        )

    if run[6] != "SUCCESS":

        fail(
            f"Bhavcopy ingestion status is "
            f"{run[6]}."
        )

    print()
    print(
        "Bhavcopy database validation: PASSED"
    )


# ==========================================================
# CORPORATE ACTIONS VALIDATION
# ==========================================================

def validate_corporate_actions_file():

    print()
    print(
        "Validating corporate actions file..."
    )

    separator()

    file_path = (
        PUBLIC_DIR /
        "corporate-actions.json"
    )

    if not file_path.exists():

        fail(
            "corporate-actions.json was "
            "not created."
        )

    size = file_path.stat().st_size

    if size == 0:

        fail(
            "corporate-actions.json exists "
            "but is empty."
        )

    print(
        "Corporate actions JSON:",
        file_path
    )

    print(
        f"File size: {size:,} bytes"
    )

    print(
        "Corporate actions file "
        "validation: PASSED"
    )


# ==========================================================
# CORPORATE ACTION DATABASE VALIDATION
# ==========================================================

def validate_corporate_actions_database():

    print()
    print(
        "Validating corporate actions "
        "in PostgreSQL..."
    )

    separator()

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM corporate_actions
                """
            )

            total_records = (
                cursor.fetchone()[0]
            )

            cursor.execute(
                """
                SELECT COUNT(DISTINCT symbol)
                FROM corporate_actions
                """
            )

            unique_symbols = (
                cursor.fetchone()[0]
            )

    finally:

        connection.close()

    print(
        f"Corporate action records : "
        f"{total_records}"
    )

    print(
        f"Unique symbols           : "
        f"{unique_symbols}"
    )

    if total_records == 0:

        fail(
            "Corporate actions table "
            "contains zero records."
        )

    print()
    print(
        "Corporate actions database "
        "validation: PASSED"
    )


# ==========================================================
# START LOGGING
# ==========================================================

def start_logging():

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    log_file = (
        LOG_DIR /
        f"ingestion_"
        f"{datetime.now().strftime('%Y-%m-%d')}"
        f".log"
    )

    log_handle = open(
        log_file,
        "a",
        encoding="utf-8"
    )

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    sys.stdout = Tee(
        original_stdout,
        log_handle
    )

    sys.stderr = Tee(
        original_stderr,
        log_handle
    )

    print()
    print(
        "=" * 70
    )

    print(
        "MarketPulse ingestion log started"
    )

    print(
        "Log file:",
        log_file
    )

    print(
        "Started:",
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    print(
        "=" * 70
    )

    return (
        log_handle,
        original_stdout,
        original_stderr,
        log_file
    )


# ==========================================================
# MAIN INGESTION
# ==========================================================

def main():

    (
        log_handle,
        original_stdout,
        original_stderr,
        log_file
    ) = start_logging()

    success = False

    try:

        title(
            "MarketPulse NSE Automatic Ingestion"
        )

        print(
            f"Project root: {PROJECT_ROOT}"
        )

        print(
            "Python:",
            sys.executable
        )

        print(
            "Started at :",
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        print(
            "Log file   :",
            log_file
        )

        # ==================================================
        # STEP 1
        # ==================================================

        title(
            "STEP 1 — DOWNLOAD NSE BHAVCOPY"
        )

        run_script(
            FETCH_BHAVCOPY
        )

        # ==================================================
        # STEP 2
        # ==================================================

        title(
            "STEP 2 — FIND DOWNLOADED BHAVCOPY"
        )

        csv_path = (
            find_latest_bhavcopy()
        )

        trade_date = (
            detect_trade_date(
                csv_path
            )
        )

        # ==================================================
        # STEP 3
        # ==================================================

        title(
            "STEP 3 — LOAD BHAVCOPY "
            "INTO POSTGRESQL"
        )

        run_script(
            LOAD_BHAVCOPY,
            csv_path,
        )

        # ==================================================
        # STEP 4
        # ==================================================

        title(
            "STEP 4 — VALIDATE BHAVCOPY"
        )

        validate_bhavcopy(
            trade_date
        )

        # ==================================================
        # STEP 5
        # ==================================================

        title(
            "STEP 5 — DOWNLOAD "
            "CORPORATE ACTIONS"
        )

        run_script(
            FETCH_NSE
        )

        # ==================================================
        # STEP 6
        # ==================================================

        title(
            "STEP 6 — LOAD CORPORATE ACTIONS "
            "INTO POSTGRESQL"
        )

        run_script(
            LOAD_CORPORATE_ACTIONS
        )

        # ==================================================
        # STEP 7
        # ==================================================

        title(
            "STEP 7 — VALIDATE CORPORATE "
            "ACTIONS FILE"
        )

        validate_corporate_actions_file()

        # ==================================================
        # STEP 8
        # ==================================================

        title(
            "STEP 8 — VALIDATE CORPORATE "
            "ACTIONS DATABASE"
        )

        validate_corporate_actions_database()

        # ==================================================
        # COMPLETE
        # ==================================================

        success = True

        title(
            "NSE INGESTION COMPLETED "
            "SUCCESSFULLY"
        )

        print(
            f"Trade date : {trade_date}"
        )

        print(
            "Completed at:",
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        print()
        print(
            "Pipeline:"
        )

        print(
            "NSE Bhavcopy"
            " -> PostgreSQL"
            " -> Validation"
            " -> Corporate Actions"
            " -> PostgreSQL"
            " -> Validation"
        )

        print()
        print(
            "Log file:",
            log_file
        )

        print()
        print(
            "=" * 70
        )

    except SystemExit:

        # fail() intentionally raises SystemExit(1).
        # Re-raise it so Task Scheduler receives failure.
        raise

    except Exception as exc:

        print()
        print(
            "=" * 70
        )

        print(
            "UNEXPECTED INGESTION ERROR"
        )

        print(
            "=" * 70
        )

        print(
            type(exc).__name__
        )

        print(
            str(exc)
        )

        print(
            "=" * 70
        )

        raise SystemExit(1)

    finally:

        print()
        print(
            "Final status:",
            "SUCCESS" if success else "FAILED"
        )

        print(
            "Finished:",
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        print(
            "Log file:",
            log_file
        )

        # Restore normal console streams.
        sys.stdout = original_stdout
        sys.stderr = original_stderr

        log_handle.close()


# ==========================================================
# ENTRY POINT
# ==========================================================

if __name__ == "__main__":
    main()