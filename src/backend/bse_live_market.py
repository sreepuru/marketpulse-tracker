import json
from datetime import datetime
from pathlib import Path

import requests


# ==========================================================
# PROJECT CONFIGURATION
# ==========================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

OUTPUT_DIR = PROJECT_ROOT / "public"

OUTPUT_FILE = OUTPUT_DIR / "bse-live-market.json"


# ==========================================================
# BSE CONFIGURATION
# ==========================================================

BSE_BASE_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api"
)

INDEX_MOVERS_ENDPOINT = (
    "/IndexMovers/w"
)

BSE_HOME_URL = (
    "https://www.bseindia.com/"
)


# ==========================================================
# HTTP HEADERS
# ==========================================================

HEADERS = {

    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36"
    ),

    "Accept":
        "application/json, text/plain, */*",

    "Accept-Language":
        "en-US,en;q=0.9",

    "Referer":
        "https://www.bseindia.com/",

    "Origin":
        "https://www.bseindia.com",

    "Accept-Encoding":
        "gzip, deflate",

    "Connection":
        "keep-alive",
}


# ==========================================================
# CREATE BSE SESSION
# ==========================================================

def create_session():

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    print()
    print("=" * 70)
    print("Creating BSE Session")
    print("=" * 70)

    response = session.get(
        BSE_HOME_URL,
        timeout=30
    )

    print(
        "BSE Homepage Status:",
        response.status_code
    )

    response.raise_for_status()

    return session


# ==========================================================
# FETCH INDEX DATA
# ==========================================================

def fetch_index_data(session):

    url = (
        f"{BSE_BASE_URL}"
        f"{INDEX_MOVERS_ENDPOINT}"
    )

    print()
    print("=" * 70)
    print("Fetching BSE Index Data")
    print("=" * 70)

    print(
        "URL:",
        url
    )

    response = session.get(
        url,
        timeout=30
    )

    print(
        "HTTP Status:",
        response.status_code
    )

    print(
        "Content-Type:",
        response.headers.get(
            "Content-Type"
        )
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):

        raise ValueError(
            "Unexpected BSE response format."
        )

    table = data.get(
        "Table",
        []
    )

    if not isinstance(table, list):

        raise ValueError(
            "BSE Table is not a list."
        )

    print(
        "Records received:",
        len(table)
    )

    return table


# ==========================================================
# NORMALIZE INDEX DATA
# ==========================================================

def normalize_index_data(records):

    normalized = []

    for row in records:

        try:

            value = row.get("LTP")

            change = row.get("change")

            change_percent = row.get(
                "PERCENTCHG"
            )

            item = {

                "name":
                    row.get(
                        "indexName"
                    ),

                "symbol":
                    row.get(
                        "shortalias"
                    ),

                "value":
                    float(value)
                    if value is not None
                    else None,

                "change":
                    float(change)
                    if change is not None
                    else None,

                "change_percent":
                    float(change_percent)
                    if change_percent is not None
                    else None,

                "timestamp":
                    row.get(
                        "DT_TM"
                    ),

                "code":
                    row.get(
                        "code"
                    ),

                "category":
                    row.get(
                        "CategoryIndex"
                    ),

                "source_order":
                    row.get(
                        "TR"
                    ),
            }

            normalized.append(
                item
            )

        except (
            TypeError,
            ValueError
        ):

            continue

    return normalized


# ==========================================================
# SELECT IMPORTANT INDICES
# ==========================================================

def select_major_indices(records):

    preferred_symbols = {

        "SENSEX",

        "BSE-100",

        "SNSX50",

        "SNXT50",

        "BHRT22",

    }

    selected = []

    for row in records:

        if row.get(
            "symbol"
        ) in preferred_symbols:

            selected.append(
                row
            )

    return selected


# ==========================================================
# CREATE OUTPUT
# ==========================================================

def create_output(records):

    normalized = normalize_index_data(
        records
    )

    major_indices = select_major_indices(
        normalized
    )

    return {

        "status":
            "success",

        "source":
            "BSE",

        "last_updated":
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),

        "record_count":
            len(normalized),

        "major_indices":
            major_indices,

        "indices":
            normalized,

    }


# ==========================================================
# SAVE JSON
# ==========================================================

def save_json(data):

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            indent=4,
            ensure_ascii=False
        )

    print()
    print("=" * 70)
    print("BSE LIVE DATA SAVED")
    print("=" * 70)

    print(
        OUTPUT_FILE
    )


# ==========================================================
# DISPLAY SUMMARY
# ==========================================================

def display_summary(data):

    print()
    print("=" * 70)
    print("MAJOR INDICES")
    print("=" * 70)

    for index in data.get(
        "major_indices",
        []
    ):

        print(
            f"{index['name']:<30}"
            f"{index['value']:>12,.2f} "
            f"{index['change']:>10,.2f} "
            f"{index['change_percent']:>8.2f}%"
        )

    print()
    print(
        "Total BSE index records:",
        data.get(
            "record_count",
            0
        )
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    try:

        session = create_session()

        records = fetch_index_data(
            session
        )

        if not records:

            raise ValueError(
                "BSE returned zero index records."
            )

        output = create_output(
            records
        )

        save_json(
            output
        )

        display_summary(
            output
        )

        print()
        print(
            "BSE index collection completed successfully."
        )

        return True

    except requests.exceptions.RequestException as error:

        print()
        print("=" * 70)
        print("BSE HTTP ERROR")
        print("=" * 70)
        print(error)

        return False

    except Exception as error:

        print()
        print("=" * 70)
        print("BSE ERROR")
        print("=" * 70)
        print(error)

        return False


# ==========================================================
# START
# ==========================================================

if __name__ == "__main__":

    success = main()

    raise SystemExit(
        0 if success else 1
    )