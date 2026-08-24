import json
import os
import re
from datetime import datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(
    Path(__file__).resolve().parents[2] / ".env"
)


# ============================================================
# CONFIGURATION
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

JSON_FILE = Path(
    os.getenv(
        "MARKETPULSE_CORPORATE_ACTIONS_JSON",
        str(PROJECT_ROOT / "public" / "corporate-actions.json"),
    )
)

DB_CONFIG = {
    "host": os.getenv("MARKETPULSE_DB_HOST", "localhost"),
    "port": int(os.getenv("MARKETPULSE_DB_PORT", "5432")),
    "dbname": os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
    "user": os.getenv("MARKETPULSE_DB_USER", "postgres"),
    "password": os.getenv("MARKETPULSE_DB_PASSWORD", ""),
}


# ============================================================
# HELPERS
# ============================================================

def parse_date(value):
    """
    Convert DD-MMM-YYYY or YYYY-MM-DD to date.
    Return None for '-', empty or null.
    """

    if value is None:
        return None

    value = str(value).strip()

    if not value or value == "-":
        return None

    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):

        try:
            return datetime.strptime(
                value,
                fmt
            ).date()

        except ValueError:
            pass

    raise ValueError(
        f"Unable to parse date: {value}"
    )


def parse_broadcast_date(value):
    """
    Convert broadcast timestamp to date.

    This field is retained for the existing
    broadcast_date column.

    It is NOT used for record_received_date.
    """

    if value is None:
        return None

    value = str(value).strip()

    if not value or value == "-":
        return None

    try:

        return datetime.strptime(
            value,
            "%d-%b-%Y %H:%M:%S"
        ).date()

    except ValueError:

        try:

            return datetime.strptime(
                value,
                "%Y-%m-%d %H:%M:%S"
            ).date()

        except ValueError:

            return parse_date(value)


def parse_face_value(value):
    """
    Convert face value to numeric.
    """

    if value is None:
        return None

    value = str(value).strip()

    if not value or value == "-":
        return None

    try:

        return float(value)

    except ValueError:

        return None


def determine_action_type(subject):
    """
    Determine corporate action category from subject.
    """

    if not subject:
        return "OTHER"

    text = subject.upper().strip()

    if "DIVIDEND" in text:
        return "DIVIDEND"

    if "BONUS" in text:
        return "BONUS"

    if "RIGHTS" in text:
        return "RIGHTS"

    if "BUY BACK" in text or "BUYBACK" in text:
        return "BUYBACK"

    if "BOARD" in text:
        return "BOARD_MEETING"

    if "SPLIT" in text:
        return "STOCK_SPLIT"

    if "MERGER" in text:
        return "MERGER"

    return "OTHER"


# ============================================================
# LOAD JSON
# ============================================================

print("=" * 70)
print("CORPORATE ACTION LOADER")
print("=" * 70)

print()
print("JSON file:")
print(JSON_FILE)

if not os.path.exists(JSON_FILE):

    raise FileNotFoundError(
        f"Corporate actions JSON not found: {JSON_FILE}"
    )


with open(
    JSON_FILE,
    "r",
    encoding="utf-8"
) as f:

    payload = json.load(f)


records = payload.get(
    "data",
    []
)


print()
print(
    "Records in JSON:",
    len(records)
)

print(
    "JSON record count:",
    payload.get("recordCount")
)

print(
    "Equity count:",
    payload.get("equityCount")
)

print(
    "SME count:",
    payload.get("smeCount")
)


# ============================================================
# RECORD RECEIVED DATE
# ============================================================

# IMPORTANT:
#
# This is the date on which our system processes/receives
# the corporate-action record.
#
# It is NOT:
# - caBroadcastDate
# - exDate
# - recDate
#
# Existing records retain their original date.
# New records get today's date.

record_received_date = datetime.now().date()


print()
print(
    "Record received date for new records:",
    record_received_date
)


# ============================================================
# DATABASE
# ============================================================

print()
print("Connecting to PostgreSQL...")

if not DB_CONFIG["password"]:
    raise RuntimeError(
        "MARKETPULSE_DB_PASSWORD is not configured."
    )

conn = psycopg.connect(
    **DB_CONFIG
)

print(
    "PostgreSQL connection successful."
)


# ============================================================
# STATISTICS
# ============================================================

matched_by_isin = 0
matched_by_symbol = 0
unmatched = 0

inserted = 0
updated = 0
skipped = 0


# ============================================================
# PROCESS
# ============================================================

with conn:

    with conn.cursor() as cur:

        for index, record in enumerate(
            records,
            start=1
        ):

            symbol = (
                str(
                    record.get("symbol") or ""
                )
                .strip()
                .upper()
            )

            raw_isin = (
                str(
                    record.get("isin") or ""
                )
                .strip()
                .upper()
            )

            series = (
                str(
                    record.get("series") or ""
                )
                .strip()
                .upper()
            )

            subject = (
                str(
                    record.get("subject") or ""
                )
                .strip()
            )


            # ------------------------------------------------
            # Determine whether JSON identifier is a real ISIN
            # ------------------------------------------------

            is_real_isin = bool(
                re.fullmatch(
                    r"INE[A-Z0-9]{9}",
                    raw_isin
                )
            )


            # ------------------------------------------------
            # Security matching
            # ------------------------------------------------

            security_id = None

            security_isin = None

            security_symbol = symbol

            security_series = series

            match_method = None


            # =================================================
            # 1. MATCH BY ISIN
            # =================================================

            if is_real_isin:

                cur.execute(
                    """
                    SELECT
                        security_id,
                        isin,
                        symbol,
                        series

                    FROM security_master

                    WHERE UPPER(isin) = %s

                    LIMIT 1
                    """,
                    (raw_isin,)
                )

                security = cur.fetchone()


                if security:

                    security_id = security[0]

                    security_isin = security[1]

                    security_symbol = security[2]

                    security_series = security[3]

                    match_method = "ISIN"

                    matched_by_isin += 1


            # =================================================
            # 2. MATCH BY SYMBOL
            # =================================================

            if (
                security_id is None
                and symbol
            ):

                cur.execute(
                    """
                    SELECT
                        security_id,
                        isin,
                        symbol,
                        series

                    FROM security_master

                    WHERE UPPER(symbol) = %s

                    AND (
                        %s = ''
                        OR UPPER(series) = %s
                    )

                    ORDER BY

                        CASE
                            WHEN UPPER(series) = %s
                            THEN 0
                            ELSE 1
                        END,

                        security_id

                    LIMIT 1
                    """,
                    (
                        symbol,
                        series,
                        series,
                        series
                    )
                )

                security = cur.fetchone()


                if security:

                    security_id = security[0]

                    security_isin = security[1]

                    security_symbol = security[2]

                    security_series = security[3]

                    match_method = "SYMBOL"

                    matched_by_symbol += 1


            # =================================================
            # 3. UNMATCHED
            # =================================================

            if security_id is None:

                unmatched += 1

                print()

                print(
                    "UNMATCHED:",
                    symbol,
                    "| identifier:",
                    raw_isin,
                    "| series:",
                    series
                )


            # =================================================
            # Dates
            # =================================================

            ex_date = parse_date(
                record.get("exDate")
            )

            record_date = parse_date(
                record.get("recDate")
            )

            bc_start_date = parse_date(
                record.get("bcStartDate")
            )

            bc_end_date = parse_date(
                record.get("bcEndDate")
            )

            nd_start_date = parse_date(
                record.get("ndStartDate")
            )

            nd_end_date = parse_date(
                record.get("ndEndDate")
            )

            broadcast_date = parse_broadcast_date(
                record.get("caBroadcastDate")
            )


            # =================================================
            # Other fields
            # =================================================

            face_value = parse_face_value(
                record.get("faceVal")
            )

            action_type = determine_action_type(
                subject
            )


            # =================================================
            # CHECK FOR EXISTING RECORD
            # =================================================

            cur.execute(
                """
                SELECT
                    corporate_action_id,
                    record_received_date

                FROM corporate_actions

                WHERE
                    symbol = %s

                    AND subject = %s

                    AND ex_date IS NOT DISTINCT FROM %s

                ORDER BY
                    corporate_action_id

                LIMIT 1
                """,
                (
                    symbol,
                    subject,
                    ex_date
                )
            )

            existing = cur.fetchone()


            # =================================================
            # EXISTING RECORD
            # =================================================

            if existing:

                corporate_action_id = existing[0]

                existing_received_date = existing[1]


                # --------------------------------------------
                # Preserve existing received date
                #
                # If it is NULL, populate it now.
                # --------------------------------------------

                final_received_date = (
                    existing_received_date
                    if existing_received_date is not None
                    else record_received_date
                )


                cur.execute(
                    """
                    UPDATE corporate_actions

                    SET
                        security_id = %s,
                        isin = %s,
                        series = %s,
                        subject = %s,
                        ex_date = %s,
                        record_date = %s,
                        bc_start_date = %s,
                        bc_end_date = %s,
                        nd_start_date = %s,
                        nd_end_date = %s,
                        face_value = %s,
                        broadcast_date = %s,
                        record_received_date = %s,
                        action_type = %s,
                        match_method = %s,
                        source = 'NSE',
                        updated_at = CURRENT_TIMESTAMP

                    WHERE
                        corporate_action_id = %s
                    """,
                    (
                        security_id,
                        raw_isin,
                        series,
                        subject,
                        ex_date,
                        record_date,
                        bc_start_date,
                        bc_end_date,
                        nd_start_date,
                        nd_end_date,
                        face_value,
                        broadcast_date,
                        final_received_date,
                        action_type,
                        match_method,
                        corporate_action_id
                    )
                )

                updated += 1


            # =================================================
            # NEW RECORD
            # =================================================

            else:

                cur.execute(
                    """
                    INSERT INTO corporate_actions
                    (
                        security_id,
                        symbol,
                        isin,
                        series,
                        subject,
                        ex_date,
                        record_date,
                        bc_start_date,
                        bc_end_date,
                        nd_start_date,
                        nd_end_date,
                        face_value,
                        broadcast_date,
                        record_received_date,
                        action_type,
                        match_method,
                        source
                    )

                    VALUES
                    (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, 'NSE'
                    )
                    """,
                    (
                        security_id,
                        symbol,
                        raw_isin,
                        series,
                        subject,
                        ex_date,
                        record_date,
                        bc_start_date,
                        bc_end_date,
                        nd_start_date,
                        nd_end_date,
                        face_value,
                        broadcast_date,
                        record_received_date,
                        action_type,
                        match_method
                    )
                )

                inserted += 1


            # =================================================
            # PROGRESS
            # =================================================

            if index % 10 == 0:

                print(
                    f"Processed {index} / {len(records)}"
                )


# ============================================================
# FINAL REPORT
# ============================================================

print()

print("=" * 70)
print("CORPORATE ACTION LOAD COMPLETE")
print("=" * 70)

print(
    "JSON records:",
    len(records)
)

print(
    "Inserted:",
    inserted
)

print(
    "Updated:",
    updated
)

print(
    "Matched by ISIN:",
    matched_by_isin
)

print(
    "Matched by Symbol:",
    matched_by_symbol
)

print(
    "Unmatched:",
    unmatched
)

print("=" * 70)