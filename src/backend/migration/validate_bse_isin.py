import os
import pandas as pd
import psycopg
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"
# Load the project's .env file from the current working directory
load_dotenv(ENV_FILE)

# Update this to the BSE CSV location on your laptop
BSE_FILE = r"D:\Dashboard\nse-dashboard\src\backend\migration\BhavCopy_BSE_CM_0_0_0_20261001_F_0000.CSV"

# Update these names if your .env uses different variable names
DB_CONFIG = {
    "host": os.getenv("MARKETPULSE_DB_HOST", "localhost"),
    "port": os.getenv("MARKETPULSE_DB_PORT", "5432"),
    "dbname": os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
    "user": os.getenv("MARKETPULSE_DB_USER"),
    "password": os.getenv("MARKETPULSE_DB_PASSWORD"),
}

def main():
    if not os.path.exists(BSE_FILE):
        raise FileNotFoundError(f"BSE file not found: {BSE_FILE}")

    if not DB_CONFIG["user"] or not DB_CONFIG["password"]:
        raise ValueError(
            "DB_USER or DB_PASSWORD is missing. "
            "Check the variable names in your project's .env file."
        )

    # Read the BSE file; do not modify it
    df = pd.read_csv(BSE_FILE, dtype=str)
    df.columns = df.columns.str.strip()

    if "ISIN" not in df.columns:
        raise ValueError(f"ISIN column not found. Columns: {df.columns.tolist()}")

    file_isins = (
        df["ISIN"]
        .fillna("")
        .str.strip()
    )
    file_isins = sorted(set(x for x in file_isins if x))

    print(f"BSE file rows: {len(df)}")
    print(f"Unique nonblank ISINs: {len(file_isins)}")

    # Read-only database query
    with psycopg.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT isin, security_id, symbol, exchange
                FROM security_master
                WHERE isin = ANY(%s)
                """,
                (file_isins,),
            )
            db_rows = cur.fetchall()

    matched = {row[0]: row for row in db_rows if row[0]}
    matched_bse = {
        isin: row for isin, row in matched.items()
        if row[3] == "BSE"
    }
    matched_nse = {
        isin: row for isin, row in matched.items()
        if row[3] == "NSE"
    }

    unmatched = sorted(set(file_isins) - set(matched))

    print("\n--- ISIN match summary ---")
    print(f"Matched to BSE security: {len(matched_bse)}")
    print(f"Matched to NSE security: {len(matched_nse)}")
    print(f"Not found in security_master: {len(unmatched)}")

    if unmatched:
        print("\nSample unmatched ISINs:")
        for isin in unmatched[:20]:
            print(isin)

    if matched_nse:
        print("\nSample BSE file ISINs currently mapped to NSE:")
        for isin, row in list(matched_nse.items())[:20]:
            print(f"ISIN={isin}, security_id={row[1]}, symbol={row[2]}")

    print("\nValidation complete. No database rows were changed.")

if __name__ == "__main__":
    main()