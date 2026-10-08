"""
Classify securities found in the BSE cash-market bhavcopy.

Default mode is a read-only preview. Pass --apply to persist the change.
Only exact, nonblank ISIN matches from the supplied BSE CM STK CSV are used.

Rules:
- security_master.exchange = 'NSE' and exchange_tag is NULL/'NSE' -> 'BOTH'
- exchange_tag already 'BOTH' -> unchanged
- exchange = 'BSE' -> unchanged
- unmatched ISINs -> unchanged
- canonical exchange and price data are never modified
"""

import argparse
import csv
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv


def find_project_root(script_dir: Path) -> Path:
    # Expected location: project/src/backend/migration
    candidate = script_dir.parents[2]
    if (candidate / ".env").exists():
        return candidate
    raise FileNotFoundError(
        f"Could not find project .env at expected location: {candidate / '.env'}"
    )


def find_bse_csv(script_dir: Path, explicit_path: str | None) -> Path:
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"CSV not found: {path}")
        return path

    matches = sorted(script_dir.glob("BhavCopy_BSE_CM_*_F_*.CSV"))
    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one BhavCopy_BSE_CM_*_F_*.CSV file in "
            f"{script_dir}, found {len(matches)}. Pass --csv explicitly."
        )
    return matches[0]


def read_bse_isins(csv_path: Path) -> set[str]:
    isins = set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"ISIN", "Sgmt", "FinInstrmTp"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

        for row in reader:
            # Restrict to BSE cash-market equity stock rows.
            if (row.get("Sgmt") or "").strip().upper() != "CM":
                continue
            if (row.get("FinInstrmTp") or "").strip().upper() != "STK":
                continue
            isin = (row.get("ISIN") or "").strip().upper()
            if isin:
                isins.add(isin)
    if not isins:
        raise ValueError("No valid BSE CM STK ISINs found in the CSV.")
    return isins


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", help="Optional explicit BSE bhavcopy CSV path")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist the exchange_tag update. Without this, only preview.",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = find_project_root(script_dir)
    load_dotenv(project_root / ".env")

    csv_path = find_bse_csv(script_dir, args.csv)
    bse_isins = sorted(read_bse_isins(csv_path))

    db_config = {
        "host": os.getenv("MARKETPULSE_DB_HOST", "localhost"),
        "port": os.getenv("MARKETPULSE_DB_PORT", "5432"),
        "dbname": os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
        "user": os.getenv("MARKETPULSE_DB_USER"),
        "password": os.getenv("MARKETPULSE_DB_PASSWORD"),
    }
    if not db_config["user"] or not db_config["password"]:
        raise ValueError(
            "MARKETPULSE_DB_USER or MARKETPULSE_DB_PASSWORD is missing. "
            "Check the project's .env file."
        )

    print(f"CSV: {csv_path}")
    print(f"Unique BSE CM STK ISINs: {len(bse_isins)}")
    print(f"Mode: {'APPLY' if args.apply else 'PREVIEW ONLY'}")

    with psycopg.connect(**db_config) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    sm.exchange,
                    COALESCE(sm.exchange_tag, '<NULL>') AS exchange_tag,
                    COUNT(*) AS securities
                FROM security_master sm
                WHERE UPPER(TRIM(sm.isin)) = ANY(%s)
                GROUP BY sm.exchange, sm.exchange_tag
                ORDER BY sm.exchange, sm.exchange_tag
                """,
                (bse_isins,),
            )
            print("\nMatched BSE-file ISINs by current classification:")
            rows = cur.fetchall()
            for row in rows:
                print(f"  exchange={row[0]!r}, exchange_tag={row[1]!r}: {row[2]}")

            cur.execute(
                """
                SELECT COUNT(*)
                FROM security_master sm
                WHERE UPPER(TRIM(sm.isin)) = ANY(%s)
                  AND sm.exchange = 'NSE'
                  AND (sm.exchange_tag IS NULL OR UPPER(TRIM(sm.exchange_tag)) = 'NSE')
                """,
                (bse_isins,),
            )
            to_update = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM security_master sm
                WHERE UPPER(TRIM(sm.isin)) = ANY(%s)
                """,
                (bse_isins,),
            )
            matched = cur.fetchone()[0]

            print(f"\nExact ISIN matches in security_master: {matched}")
            print(f"NSE rows eligible to change to BOTH: {to_update}")
            print("BSE rows, existing BOTH tags, and unmatched ISINs will be unchanged.")

            if not args.apply:
                conn.rollback()
                print("\nPreview complete. No database changes were made.")
                print("Review the counts, then rerun with --apply to persist.")
                return 0

            cur.execute(
                """
                UPDATE security_master
                SET exchange_tag = 'BOTH',
                    updated_at = CURRENT_TIMESTAMP
                WHERE UPPER(TRIM(isin)) = ANY(%s)
                  AND exchange = 'NSE'
                  AND (exchange_tag IS NULL OR UPPER(TRIM(exchange_tag)) = 'NSE')
                """,
                (bse_isins,),
            )
            changed = cur.rowcount
        conn.commit()

    print(f"\nCommitted. Rows changed to BOTH: {changed}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
