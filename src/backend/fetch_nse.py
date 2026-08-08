import json
import time
from datetime import datetime
from pathlib import Path

import requests

# ==========================================================
# NSE URLs
# ==========================================================

BASE_URL = "https://www.nseindia.com"

EQUITY_API = (
    "https://www.nseindia.com/api/corporates-corporateActions?index=equities"
)

SME_API = (
    "https://www.nseindia.com/api/corporates-corporateActions?index=sme"
)

# ==========================================================
# HTTP Headers
# ==========================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# ==========================================================
# Output Location
# ==========================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

OUTPUT_FOLDER = PROJECT_ROOT / "public"

OUTPUT_FILE = OUTPUT_FOLDER / "corporate-actions.json"

# ==========================================================
# Create NSE Session
# ==========================================================


def create_session():

    session = requests.Session()

    session.headers.update(HEADERS)

    print("Creating NSE Session...")

    response = session.get(BASE_URL, timeout=30)

    print("Homepage Status :", response.status_code)

    time.sleep(1)

    return session


# ==========================================================
# Fetch Data
# ==========================================================

def fetch_data(session, url):

    print(f"\nFetching : {url}")

    response = session.get(url, timeout=30)

    response.raise_for_status()

    return response.json()


# ==========================================================
# Save JSON
# ==========================================================

def save_json(output):

    OUTPUT_FOLDER.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            indent=4,
            ensure_ascii=False
        )

    print("\n=======================================")
    print("JSON Saved Successfully")
    print("=======================================")

    print(OUTPUT_FILE)


# ==========================================================
# Main
# ==========================================================

def main():

    try:

        session = create_session()

        equity_records = fetch_data(
            session,
            EQUITY_API
        )

        sme_records = fetch_data(
            session,
            SME_API
        )

        print("\n=======================================")

        print(
            "Equity Records :",
            len(equity_records)
        )

        print(
            "SME Records    :",
            len(sme_records)
        )

        merged = equity_records + sme_records

        print(
            "Merged Records :",
            len(merged)
        )

        # ==================================================
        # Create Output Object
        # ==================================================

        output = {

            "lastUpdated":
                datetime.now().strftime(
                    "%d-%b-%Y %I:%M:%S %p"
                ),

            "recordCount":
                len(merged),

            "equityCount":
                len(equity_records),

            "smeCount":
                len(sme_records),

            "source":
                "NSE",

            "data":
                merged

        }

        save_json(output)

        print("\nCompleted Successfully")

    except requests.exceptions.HTTPError as err:

        print("\nHTTP Error")

        print(err)

    except requests.exceptions.ConnectionError as err:

        print("\nConnection Error")

        print(err)

    except requests.exceptions.Timeout as err:

        print("\nTimeout")

        print(err)

    except Exception as err:

        print("\nUnexpected Error")

        print(err)

# ==========================================================
# Start
# ==========================================================

if __name__ == "__main__":

    main()