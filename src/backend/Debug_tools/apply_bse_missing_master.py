"""
MarketPulse - Apply validated missing BSE security master candidates

Purpose
-------
Apply the already validated BSE missing-master candidate file.

IMPORTANT
---------
This script does NOT classify securities.
It trusts the validated asset_category from the candidate file.

Validated candidate counts:
    BOND             2475
    EQUITY            833
    OTHER_INVESTMENT    4
    TOTAL            3312

Rules
-----
1. ISIN is the canonical identity.
2. Existing ISIN:
       - DO NOT create another security_id.
       - Enrich BSE fields.
       - NSE -> BOTH.
3. Missing ISIN:
       - Insert new BSE security.
4. BSE FinInstrmId -> bse_fin_instrm_id
5. BSE symbol -> bse_symbol
6. BSE name -> bse_name
7. BSE scrip code -> bse_scrip_code
8. Preserve validated asset_category.
9. Dry-run is default.
10. --apply commits the transaction.
"""

import argparse
import csv
import os
import sys
from collections import Counter
from pathlib import Path

import psycopg2
from dotenv import load_dotenv


# ============================================================
# CONFIGURATION
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(PROJECT_ROOT / ".env")

DB_CONFIG = {
    "host": os.getenv("MARKETPULSE_DB_HOST", "localhost"),
    "port": int(os.getenv("MARKETPULSE_DB_PORT", "5432")),
    "dbname": os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
    "user": os.getenv("MARKETPULSE_DB_USER", "postgres"),
    "password": os.getenv("MARKETPULSE_DB_PASSWORD", ""),
}

DEFAULT_CANDIDATE_FILE = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "bse"
    / "master_candidates"
    / "BSE_missing_master_final.csv"
)

VALID_CATEGORIES = {
    "BOND",
    "EQUITY",
    "OTHER_INVESTMENT",
}


# ============================================================
# HELPERS
# ============================================================

def clean(value):
    if value is None:
        return ""

    return str(value).strip()


def upper(value):
    return clean(value).upper()


def normalize_isin(value):
    value = upper(value)

    if not value:
        return ""

    if value in {"NA", "N/A", "NULL", "-", "NONE"}:
        return ""

    return value


def normalize_id(value):
    value = clean(value)

    if not value:
        return ""

    try:
        return str(int(float(value)))
    except Exception:
        return value


def get_value(row, *names):
    """
    Return first available non-empty value from candidate CSV.
    """

    for name in names:
        if name in row:
            value = clean(row.get(name))

            if value:
                return value

    return ""


# ============================================================
# READ CANDIDATES
# ============================================================

def read_candidates(path):

    if not path.exists():
        raise FileNotFoundError(
            f"Candidate file not found:\n{path}"
        )

    candidates = []

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise ValueError(
                "Candidate CSV does not contain a header row."
            )

        headers = {
            clean(x)
            for x in reader.fieldnames
        }

        required = {
            "isin",
            "asset_category",
        }

        missing = required - headers

        if missing:
            raise ValueError(
                "Candidate CSV is missing required columns: "
                + ", ".join(sorted(missing))
            )

        for raw in reader:

            isin = normalize_isin(
                get_value(raw, "isin", "ISIN")
            )

            if not isin:
                raise ValueError(
                    "Candidate row contains blank ISIN."
                )

            asset_category = upper(
                get_value(
                    raw,
                    "asset_category",
                    "Asset_Category",
                    "category",
                )
            )

            if asset_category not in VALID_CATEGORIES:
                raise ValueError(
                    f"Invalid asset_category for ISIN "
                    f"{isin}: {asset_category}"
                )

            row = {
                "isin": isin,

                "instrument_id": normalize_id(
                    get_value(
                        raw,
                        "instrument_id",
                        "FinInstrmId",
                        "bse_fin_instrm_id",
                    )
                ),

                "symbol": get_value(
                    raw,
                    "symbol",
                    "TckrSymb",
                    "bse_symbol",
                ),

                "series": upper(
                    get_value(
                        raw,
                        "series",
                        "SctySrs",
                    )
                ),

                "instrument_name": get_value(
                    raw,
                    "instrument_name",
                    "FinInstrmNm",
                    "bse_name",
                ),

                "bse_scrip_code": normalize_id(
                    get_value(
                        raw,
                        "bse_scrip_code",
                        "FinInstrmId",
                        "instrument_id",
                    )
                ),

                "asset_category": asset_category,
            }

            candidates.append(row)

    return candidates


# ============================================================
# DATABASE
# ============================================================

def get_connection():

    return psycopg2.connect(
        **DB_CONFIG
    )


def load_existing_master(conn):

    sql = """
        SELECT
            security_id,
            isin,
            exchange,
            exchange_tag,
            asset_category
        FROM security_master
        WHERE isin IS NOT NULL
          AND TRIM(isin) <> '';
    """

    result = {}

    with conn.cursor() as cur:

        cur.execute(sql)

        for row in cur.fetchall():

            security_id = row[0]
            isin = normalize_isin(row[1])

            if not isin:
                continue

            if isin in result:

                raise RuntimeError(
                    f"DUPLICATE ISIN FOUND IN security_master: {isin}"
                )

            result[isin] = {
                "security_id": int(security_id),
                "exchange": upper(row[2]),
                "exchange_tag": upper(row[3]),
                "asset_category": upper(row[4]),
            }

    return result


# ============================================================
# UPDATE EXISTING SECURITY
# ============================================================

def update_existing_security(
    cur,
    security_id,
    exchange_tag,
    row,
):

    exchange_tag = upper(exchange_tag)

    if exchange_tag == "NSE":
        new_exchange_tag = "BOTH"
    elif exchange_tag == "BOTH":
        new_exchange_tag = "BOTH"
    elif exchange_tag == "BSE":
        new_exchange_tag = "BSE"
    else:
        new_exchange_tag = "BSE"

    sql = """
        UPDATE security_master
        SET
            bse_fin_instrm_id = %s,
            bse_symbol = %s,
            bse_name = %s,
            bse_scrip_code = %s,
            exchange_tag = %s,
            asset_category = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE security_id = %s;
    """

    cur.execute(
        sql,
        (
            row["instrument_id"] or None,
            row["symbol"] or None,
            row["instrument_name"] or None,
            row["bse_scrip_code"] or None,
            new_exchange_tag,
            row["asset_category"],
            security_id,
        ),
    )


# ============================================================
# INSERT NEW BSE SECURITY
# ============================================================

def insert_new_security(cur, row):

    sql = """
        INSERT INTO security_master (
            isin,
            symbol,
            series,
            instrument_type,
            instrument_name,
            exchange,
            segment,

            bse_fin_instrm_id,
            bse_symbol,
            bse_name,
            bse_scrip_code,

            exchange_tag,
            asset_category,

            is_active,
            created_at,
            updated_at
        )
        VALUES (
            %s,
            %s,
            %s,
            'STK',
            %s,
            'BSE',
            'CM',

            %s,
            %s,
            %s,
            %s,

            'BSE',
            %s,

            TRUE,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        )
        RETURNING security_id;
    """

    cur.execute(
        sql,
        (
            row["isin"],
            row["symbol"] or None,
            row["series"] or None,
            row["instrument_name"] or None,

            row["instrument_id"] or None,
            row["symbol"] or None,
            row["instrument_name"] or None,
            row["bse_scrip_code"] or None,

            row["asset_category"],
        ),
    )

    result = cur.fetchone()

    if not result:
        raise RuntimeError(
            f"Insert failed for ISIN {row['isin']}"
        )

    return int(result[0])


# ============================================================
# MAIN
# ============================================================

def process(candidate_file, apply_changes=False):

    print()
    print("=" * 72)
    print("MARKETPULSE - APPLY BSE MISSING MASTER")
    print("=" * 72)

    print(f"Candidate file : {candidate_file}")
    print(
        "Mode           : "
        + ("APPLY" if apply_changes else "DRY-RUN")
    )

    candidates = read_candidates(candidate_file)

    print(f"Candidate rows : {len(candidates)}")

    # --------------------------------------------------------
    # Validate candidate count
    # --------------------------------------------------------

    if len(candidates) != 3312:

        raise RuntimeError(
            "Expected exactly 3312 validated candidates. "
            f"Found {len(candidates)}."
        )

    # --------------------------------------------------------
    # Duplicate candidate ISIN check
    # --------------------------------------------------------

    candidate_isins = [
        row["isin"]
        for row in candidates
    ]

    duplicate_isins = [
        isin
        for isin, count in Counter(
            candidate_isins
        ).items()
        if count > 1
    ]

    if duplicate_isins:

        raise RuntimeError(
            "Duplicate ISINs found in candidate file: "
            + ", ".join(duplicate_isins[:20])
        )

    # --------------------------------------------------------
    # Category validation
    # --------------------------------------------------------

    category_counts = Counter(
        row["asset_category"]
        for row in candidates
    )

    print()
    print("Candidate categories")
    print("-" * 40)

    for category in sorted(category_counts):
        print(
            f"{category:<20}: "
            f"{category_counts[category]}"
        )

    expected = {
        "BOND": 2475,
        "EQUITY": 833,
        "OTHER_INVESTMENT": 4,
    }

    if dict(category_counts) != expected:

        raise RuntimeError(
            "Candidate category counts do not match "
            f"validated counts.\n"
            f"Expected : {expected}\n"
            f"Actual   : {dict(category_counts)}"
        )

    # --------------------------------------------------------
    # Connect
    # --------------------------------------------------------

    conn = get_connection()

    try:

        existing = load_existing_master(conn)

        print()
        print(
            f"Existing security_master rows : "
            f"{len(existing)}"
        )

        stats = Counter()

        planned = []

        # ----------------------------------------------------
        # Build execution plan
        # ----------------------------------------------------

        for row in candidates:

            isin = row["isin"]

            master = existing.get(isin)

            if master:

                stats["existing"] += 1

                if master["exchange_tag"] == "NSE":
                    stats["existing_nse"] += 1

                elif master["exchange_tag"] == "BOTH":
                    stats["existing_both"] += 1

                elif master["exchange_tag"] == "BSE":
                    stats["existing_bse"] += 1

                planned.append(
                    (
                        "UPDATE",
                        master["security_id"],
                        row,
                        master,
                    )
                )

            else:

                stats["new"] += 1

                planned.append(
                    (
                        "INSERT",
                        None,
                        row,
                        None,
                    )
                )

        # ----------------------------------------------------
        # Report
        # ----------------------------------------------------

        print()
        print("Execution plan")
        print("-" * 40)

        print(
            f"Existing canonical securities : "
            f"{stats['existing']}"
        )

        print(
            f"  Existing NSE -> BOTH        : "
            f"{stats['existing_nse']}"
        )

        print(
            f"  Existing BOTH                : "
            f"{stats['existing_both']}"
        )

        print(
            f"  Existing BSE                : "
            f"{stats['existing_bse']}"
        )

        print(
            f"New BSE securities            : "
            f"{stats['new']}"
        )

        print(
            f"Total planned                 : "
            f"{len(planned)}"
        )

        # ----------------------------------------------------
        # Dry-run
        # ----------------------------------------------------

        if not apply_changes:

            print()
            print("=" * 72)
            print("DRY-RUN COMPLETE")
            print("=" * 72)
            print("No database changes were made.")

            conn.rollback()
            return

        # ----------------------------------------------------
        # APPLY
        # ----------------------------------------------------

        print()
        print("Applying changes...")

        update_count = 0
        insert_count = 0

        with conn.cursor() as cur:

            for action, security_id, row, master in planned:

                if action == "UPDATE":

                    update_existing_security(
                        cur,
                        security_id,
                        master["exchange_tag"],
                        row,
                    )

                    update_count += 1

                else:

                    insert_new_security(
                        cur,
                        row,
                    )

                    insert_count += 1

        conn.commit()

        print()
        print("=" * 72)
        print("APPLY COMPLETE")
        print("=" * 72)

        print(
            f"Existing securities updated : "
            f"{update_count}"
        )

        print(
            f"New BSE securities inserted  : "
            f"{insert_count}"
        )

        print(
            f"Total processed              : "
            f"{update_count + insert_count}"
        )

    except Exception:

        conn.rollback()

        print()
        print("=" * 72)
        print("ERROR - TRANSACTION ROLLED BACK")
        print("=" * 72)

        raise

    finally:

        conn.close()


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Apply validated BSE missing security-master "
            "candidates."
        )
    )

    parser.add_argument(
        "--file",
        default=str(DEFAULT_CANDIDATE_FILE),
        help="Validated BSE candidate CSV",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually commit database changes",
    )

    args = parser.parse_args()

    candidate_file = (
        Path(args.file)
        .expanduser()
        .resolve()
    )

    try:

        process(
            candidate_file,
            apply_changes=args.apply,
        )

        return 0

    except Exception as exc:

        print()
        print("FAILED:")
        print(str(exc))

        return 1


if __name__ == "__main__":
    sys.exit(main())