"""
MarketPulse - BSE Security Master Loader

Purpose
-------
Load/enrich security_master using BSE BhavCopy data.

Rules
-----
1. ISIN is the primary identity key.
2. Existing NSE security with same ISIN:
      - enrich BSE fields
      - exchange_tag -> BOTH
      - DO NOT create another security_id
3. Existing BSE security:
      - enrich/update BSE fields
4. Unmatched ISIN:
      - create a new BSE security_master row
5. BSE FinInstrmId is stored in bse_fin_instrm_id.
6. asset_category must be classified using the MarketPulse rules.
7. Dry-run is the default.
8. --apply performs the database transaction.

Usage
-----
Dry run:

python load_bse_security_master.py ^
  --file "D:\\Dashboard\\nse-dashboard\\data\\bhavcopy\\bse\\raw\\BhavCopy_BSE_CM_0_0_0_20261006_F_0000.CSV"

Apply:

python load_bse_security_master.py ^
  --file "D:\\Dashboard\\nse-dashboard\\data\\bhavcopy\\bse\\raw\\BhavCopy_BSE_CM_0_0_0_20261006_F_0000.CSV" ^
  --apply
"""

import argparse
import csv
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

import os
import psycopg2

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
# EXPECTED BSE COLUMNS
# ============================================================

REQUIRED_COLUMNS = {
    "TradDt",
    "Sgmt",
    "Src",
    "FinInstrmTp",
    "FinInstrmId",
    "ISIN",
    "TckrSymb",
    "SctySrs",
    "FinInstrmNm",
}


# ============================================================
# BSE -> SECURITY MASTER FIELD MAPPING
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
        return None

    if value in {"NA", "N/A", "NULL", "-", "NONE"}:
        return None

    return value


def normalize_instrument_id(value):
    value = clean(value)

    if not value:
        return None

    # BSE FinInstrmId should normally be numeric.
    try:
        return str(int(float(value)))
    except Exception:
        return value


def parse_date(value):
    value = clean(value)

    if not value:
        return None

    for fmt in (
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass

    raise ValueError(f"Unable to parse date: {value}")


def valid_isin(isin):
    """
    Basic ISIN validation.

    Indian securities generally use IN + 9 alphanumeric chars + 1 check digit.
    """

    if not isin:
        return False

    return bool(re.fullmatch(r"IN[A-Z0-9]{10}", isin))


# ============================================================
# ASSET CLASSIFICATION
# ============================================================

def classify_asset_category(row):
    """
    MarketPulse Phase-2 classification rules.

    IMPORTANT:
    Keep this logic aligned with the project's existing
    security_master asset-category classifier.
    """

    isin = upper(row.get("isin"))
    symbol = upper(row.get("symbol"))
    series = upper(row.get("series"))
    instrument_name = upper(row.get("instrument_name"))
    instrument_type = upper(row.get("instrument_type"))

    bse_scrip_code = clean(row.get("bse_scrip_code"))

    searchable = " ".join(
        [
            isin,
            symbol,
            series,
            instrument_name,
            instrument_type,
        ]
    )

    # --------------------------------------------------------
    # PROJECT EXPLICIT OVERRIDES
    # --------------------------------------------------------

    if instrument_name == "360 ONE ASSET MANAGEMENT LIMITED":
        return "MUTUAL_FUND"

    if instrument_name == "WATERMARKE ESTATES PVT LTD":
        return "OTHER"

    # --------------------------------------------------------
    # ETF MUST BE CHECKED BEFORE MUTUAL FUND
    # --------------------------------------------------------

    if (
        "ETF" in instrument_name
        or " ETF " in f" {instrument_name} "
        or "ETF" in symbol
    ):
        return "ETF"

    # --------------------------------------------------------
    # MUTUAL FUND
    # --------------------------------------------------------

    if bse_scrip_code.startswith("9"):
        return "MUTUAL_FUND"

    if isin.startswith("INF"):
        return "MUTUAL_FUND"

    if "MUTUAL FUND" in instrument_name:
        return "MUTUAL_FUND"

    # --------------------------------------------------------
    # BOND / DEBT
    # --------------------------------------------------------

    debt_series = {
        "G",
        "GS",
        "SG",
        "TB",
        "GB",
    }

    if series in debt_series:
        return "BOND"

    # Existing MarketPulse debt-series pattern.
    if re.fullmatch(r"^(N|Y|Z|A|B|D)[0-9A-Z]*$", series):
        return "BOND"

    debt_keywords = [
        "BOND",
        "NCD",
        "DEBENTURE",
        "TAX FREE",
        "TFB",
    ]

    if any(keyword in instrument_name for keyword in debt_keywords):
        return "BOND"

    # Numeric coupon/year style debt names.
    if re.search(r"\b\d+(?:\.\d+)?%\b", instrument_name):
        return "BOND"

    # BSE government-security naming convention.
    if instrument_name.startswith("GS"):
        return "BOND"

    explicit_debt_names = {
        "GS19SEP2058",
        "AEL 0% 2027 SR II",
        "SCL 8.88% 2028 SR V",
        "PFCL 7.05% 2041 SR IV",
    }

    if instrument_name in explicit_debt_names:
        return "BOND"

    # --------------------------------------------------------
    # EQUITY
    # --------------------------------------------------------

    equity_series = {
        "EQ",
        "BE",
        "BZ",
        "SM",
        "ST",
        "SZ",
        "E1",
        "P1",
        "X1",
    }

    if series in equity_series:
        return "EQUITY"

    # BSE equity identification using Indian ISIN + valid scrip.
    if (
        isin.startswith("INE")
        and bse_scrip_code
        and bse_scrip_code.isdigit()
        and instrument_name
    ):
        return "EQUITY"

    if (
        symbol.endswith("PP")
        or symbol.endswith("PP1")
    ) and bse_scrip_code:
        return "EQUITY"

    # --------------------------------------------------------
    # OTHER
    # --------------------------------------------------------

    if series in {"IV", "RR"}:
        return "OTHER"

    if (
        "WARRANT" in instrument_name
        or "RIGHTS" in instrument_name
    ):
        return "OTHER"

    # --------------------------------------------------------
    # UNKNOWN
    # --------------------------------------------------------

    return None


# ============================================================
# READ BSE CSV
# ============================================================

def read_bse_csv(file_path):

    if not os.path.exists(file_path):
        raise FileNotFoundError(
            f"BSE file not found: {file_path}"
        )

    rows = []

    with open(
        file_path,
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        reader = csv.DictReader(f)

        if not reader.fieldnames:
            raise ValueError(
                "CSV does not contain a header row."
            )

        available = {
            clean(x)
            for x in reader.fieldnames
        }

        missing = REQUIRED_COLUMNS - available

        if missing:
            raise ValueError(
                "BSE CSV is missing required columns: "
                + ", ".join(sorted(missing))
            )

        for raw in reader:

            segment = upper(raw.get("Sgmt"))
            source = upper(raw.get("Src"))
            instrument_type = upper(
                raw.get("FinInstrmTp")
            )

            # ------------------------------------------------
            # Keep BSE Cash Market / Stock rows only.
            # ------------------------------------------------

            if segment != "CM":
                continue

            if source != "BSE":
                continue

            if instrument_type != "STK":
                continue

            isin = normalize_isin(
                raw.get("ISIN")
            )

            instrument_id = normalize_instrument_id(
                raw.get("FinInstrmId")
            )

            symbol = clean(
                raw.get("TckrSymb")
            )

            series = clean(
                raw.get("SctySrs")
            )

            instrument_name = clean(
                raw.get("FinInstrmNm")
            )

            row = {
                "trade_date": parse_date(
                    raw.get("TradDt")
                ),

                "segment": segment,

                "source": source,

                "instrument_type": instrument_type,

                "instrument_id": instrument_id,

                "isin": isin,

                "symbol": symbol,

                "series": series,

                "instrument_name": instrument_name,

                # ------------------------------------------------
                # BSE scrip code.
                #
                # If your CSV uses a different column for the
                # BSE scrip code, update this mapping here.
                # ------------------------------------------------
                "bse_scrip_code": normalize_instrument_id(
                    raw.get("FinInstrmId")
                ),
            }

            rows.append(row)

    return rows


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def load_existing_master(conn):

    sql = """
        SELECT
            security_id,
            isin,
            exchange_tag,
            exchange,
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

            # Multiple rows for the same ISIN should never
            # happen in the redesigned canonical master.
            if isin in result:
                result[isin]["ambiguous"] = True

            else:
                result[isin] = {
                    "security_id": security_id,
                    "exchange_tag": row[2],
                    "exchange": row[3],
                    "asset_category": row[4],
                    "ambiguous": False,
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
    asset_category,
):
    """
    Enrich an existing canonical security with BSE identity.
    """

    if exchange_tag == "NSE":
        new_exchange_tag = "BOTH"
    else:
        new_exchange_tag = exchange_tag or "BSE"

    sql = """
        UPDATE security_master
        SET
            bse_fin_instrm_id = %s,
            bse_symbol = %s,
            bse_name = %s,
            bse_scrip_code = %s,
            exchange_tag = %s,
            asset_category =
                COALESCE(asset_category, %s),
            updated_at = CURRENT_TIMESTAMP
        WHERE security_id = %s;
    """

    cur.execute(
        sql,
        (
            row["instrument_id"],
            row["symbol"],
            row["instrument_name"],
            row["bse_scrip_code"],
            new_exchange_tag,
            asset_category,
            security_id,
        ),
    )


# ============================================================
# INSERT NEW BSE SECURITY
# ============================================================

def insert_new_security(
    cur,
    row,
    asset_category,
):

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
            %s,
            %s,
            'BSE',
            %s,

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
            row["symbol"],
            row["series"],
            row["instrument_type"],
            row["instrument_name"],
            row["segment"],

            row["instrument_id"],
            row["symbol"],
            row["instrument_name"],
            row["bse_scrip_code"],

            asset_category,
        ),
    )

    return cur.fetchone()[0]


# ============================================================
# MAIN PROCESSING
# ============================================================

def process(file_path, apply_changes=False):

    print()
    print("=" * 60)
    print("BSE SECURITY MASTER LOAD")
    print("=" * 60)

    print(f"File              : {file_path}")

    # --------------------------------------------------------
    # Read source
    # --------------------------------------------------------

    rows = read_bse_csv(file_path)

    if not rows:
        print()
        print("No BSE CM/STK rows found.")
        return

    trade_dates = {
        row["trade_date"]
        for row in rows
        if row["trade_date"]
    }

    print(
        "Trade date        : "
        + ", ".join(
            str(x)
            for x in sorted(trade_dates)
        )
    )

    print(
        f"Source rows       : {len(rows)}"
    )

    print(
        f"BSE CM/STK rows   : {len(rows)}"
    )

    # --------------------------------------------------------
    # Connect DB
    # --------------------------------------------------------

    conn = get_connection()

    try:

        existing = load_existing_master(conn)

        # ----------------------------------------------------
        # Counters
        # ----------------------------------------------------

        stats = Counter()

        category_counts = Counter()

        unclassified_rows = []

        planned_updates = []
        planned_inserts = []

        # ----------------------------------------------------
        # Process each BSE row
        # ----------------------------------------------------

        for row in rows:

            isin = row["isin"]

            # ------------------------------------------------
            # Invalid / missing ISIN
            # ------------------------------------------------

            if not valid_isin(isin):

                stats["invalid"] += 1

                continue

            # ------------------------------------------------
            # Duplicate BSE rows for same ISIN
            # ------------------------------------------------

            if isin in existing:

                master = existing[isin]

                if master.get("ambiguous"):

                    stats["ambiguous"] += 1

                    continue

                asset_category = classify_asset_category(
                    row
                )

                if not asset_category:

                    stats["unclassified"] += 1

                    unclassified_rows.append({
                        "isin": row["isin"],
                        "symbol": row["symbol"],
                        "series": row["series"],
                        "instrument_name": row["instrument_name"],
                        "instrument_id": row["instrument_id"],
                    })

                    continue

                category_counts[
                    asset_category
                ] += 1

                exchange_tag = (
                    master["exchange_tag"]
                    or ""
                ).upper()

                if exchange_tag == "NSE":

                    stats["existing_nse"] += 1

                elif exchange_tag == "BSE":

                    stats["existing_bse"] += 1

                elif exchange_tag == "BOTH":

                    stats["existing_both"] += 1

                else:

                    stats["existing_other"] += 1

                planned_updates.append(
                    (
                        master["security_id"],
                        exchange_tag,
                        row,
                        asset_category,
                    )
                )

            else:

                asset_category = classify_asset_category(
                    row
                )

                if not asset_category:

                    stats["unclassified"] += 1

                    unclassified_rows.append(row)

                    continue

                category_counts[
                    asset_category
                ] += 1

                stats["new_bse"] += 1

                planned_inserts.append(
                    (
                        row,
                        asset_category,
                    )
                )

        # ----------------------------------------------------
        # Report
        # ----------------------------------------------------

        print()
        print(
            f"Existing NSE      : "
            f"{stats['existing_nse']}"
        )

        print(
            f"Existing BSE      : "
            f"{stats['existing_bse']}"
        )

        print(
            f"Existing BOTH     : "
            f"{stats['existing_both']}"
        )

        print(
            f"Existing Other    : "
            f"{stats['existing_other']}"
        )

        print(
            f"New BSE masters   : "
            f"{stats['new_bse']}"
        )

        print()

        print(
            f"EQUITY            : "
            f"{category_counts['EQUITY']}"
        )

        print(
            f"MUTUAL_FUND       : "
            f"{category_counts['MUTUAL_FUND']}"
        )

        print(
            f"ETF               : "
            f"{category_counts['ETF']}"
        )

        print(
            f"BOND              : "
            f"{category_counts['BOND']}"
        )

        print(
            f"OTHER             : "
            f"{category_counts['OTHER']}"
        )

        print()

        print(
            f"Ambiguous ISIN    : "
            f"{stats['ambiguous']}"
        )

        print(
            f"Invalid rows      : "
            f"{stats['invalid']}"
        )

        print(
            f"Unclassified      : "
            f"{stats['unclassified']}"
        )

        # --------------------------------------------------------
        # SAVE UNCLASSIFIED RECORDS FOR REVIEW
        # --------------------------------------------------------

        if unclassified_rows:

            output_file = (
                Path(file_path).parent.parent
                / "unclassified"
                / "BSE_unclassified_20261006.csv"
            )

            output_file.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with open(
                output_file,
                "w",
                newline="",
                encoding="utf-8",
            ) as f:

                fieldnames = [
                    "trade_date",
                    "instrument_id",
                    "isin",
                    "symbol",
                    "series",
                    "instrument_name",
                ]

                writer = csv.DictWriter(
                    f,
                    fieldnames=fieldnames,
                )

                writer.writeheader()

                for row in unclassified_rows:

                    writer.writerow({
                        field: row.get(field, "")
                        for field in fieldnames
                    })

            print()
            print(
                f"Unclassified report: {output_file}"
            )

        print()
        print("Sample unclassified records:")
        print("-" * 100)

        for row in unclassified_rows[:50]:
            print(
                f"ISIN={row['isin']} | "
                f"SYMBOL={row['symbol']} | "
                f"SERIES={row['series']} | "
                f"FININSTRMID={row['instrument_id']} | "
                f"NAME={row['instrument_name']}"
            )

        print()

        # ----------------------------------------------------
        # Safety stop
        # ----------------------------------------------------

        if stats["ambiguous"] > 0:

            print(
                "ERROR: Ambiguous ISINs detected."
            )

            print(
                "No database changes will be made."
            )

            conn.rollback()

            return

        if stats["unclassified"] > 0:

            print(
                "ERROR: Some BSE securities could "
                "not be classified."
            )

            print(
                "Review the classification rules "
                "before applying."
            )

            conn.rollback()

            return

        # ----------------------------------------------------
        # DRY RUN
        # ----------------------------------------------------

        if not apply_changes:

            print("=" * 60)
            print("DRY-RUN ONLY")
            print("No database changes made.")
            print("=" * 60)

            return

        # ----------------------------------------------------
        # APPLY
        # ----------------------------------------------------

        print()
        print(
            "Applying changes to security_master..."
        )

        with conn.cursor() as cur:

            # -----------------------------------------------
            # Existing securities
            # -----------------------------------------------

            for (
                security_id,
                exchange_tag,
                row,
                asset_category,
            ) in planned_updates:

                update_existing_security(
                    cur,
                    security_id,
                    exchange_tag,
                    row,
                    asset_category,
                )

            # -----------------------------------------------
            # New BSE securities
            # -----------------------------------------------

            inserted_ids = []

            for (
                row,
                asset_category,
            ) in planned_inserts:

                security_id = insert_new_security(
                    cur,
                    row,
                    asset_category,
                )

                inserted_ids.append(
                    security_id
                )

        conn.commit()

        print()
        print(
            "Database transaction committed successfully."
        )

        print(
            f"Existing records updated : "
            f"{len(planned_updates)}"
        )

        print(
            f"New BSE records inserted : "
            f"{len(planned_inserts)}"
        )

        print()
        print("=" * 60)
        print("BSE SECURITY MASTER LOAD COMPLETE")
        print("=" * 60)

    except Exception:

        conn.rollback()

        print()
        print(
            "ERROR: Transaction rolled back."
        )

        raise

    finally:

        conn.close()


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Load BSE BhavCopy securities "
            "into MarketPulse security_master."
        )
    )

    parser.add_argument(
        "--file",
        required=True,
        help="Path to BSE BhavCopy CSV",
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply changes to database. "
            "Without this flag the script is dry-run only."
        ),
    )

    args = parser.parse_args()

    process(
        file_path=args.file,
        apply_changes=args.apply,
    )


if __name__ == "__main__":
    main()