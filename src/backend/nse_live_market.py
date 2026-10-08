import json
import time
from datetime import datetime
from pathlib import Path

import requests


# ==========================================================
# NSE CONFIGURATION
# ==========================================================

BASE_URL = "https://www.nseindia.com"

MARKET_STATUS_URL = (
    f"{BASE_URL}/api/marketStatus"
)

ALL_INDICES_URL = (
    f"{BASE_URL}/api/allIndices"
)


# ==========================================================
# HTTP HEADERS
# ==========================================================

HEADERS = {

    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    ),

    "Accept": (
        "application/json,"
        "text/plain,"
        "*/*"
    ),

    "Accept-Language":
        "en-US,en;q=0.9",

    "Referer":
        "https://www.nseindia.com/",

    "Connection":
        "keep-alive",
}


# ==========================================================
# NSE SESSION
# ==========================================================

def create_session():

    session = requests.Session()

    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/139.0.0.0 Safari/537.36"
        ),

        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,"
            "*/*;q=0.8"
        ),

        "Accept-Language":
            "en-US,en;q=0.9",

        "Accept-Encoding":
            "gzip, deflate",

        "Connection":
            "keep-alive",

        "Upgrade-Insecure-Requests":
            "1",

        "Sec-Fetch-Dest":
            "document",

        "Sec-Fetch-Mode":
            "navigate",

        "Sec-Fetch-Site":
            "none",

        "Sec-Fetch-User":
            "?1",
    })

    print()
    print("=" * 70)
    print("Creating NSE Session")
    print("=" * 70)

    response = session.get(
        "https://www.nseindia.com/",
        timeout=30,
        allow_redirects=True
    )

    print(
        "NSE Homepage Status:",
        response.status_code
    )

    print(
        "NSE Cookies:",
        session.cookies.get_dict()
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"NSE homepage rejected request: "
            f"HTTP {response.status_code}"
        )

    time.sleep(2)

    return session


# ==========================================================
# FETCH JSON
# ==========================================================

def fetch_json(
    session,
    url
):

    print()
    print("Fetching:")
    print(url)

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
        response.headers.get("Content-Type")
    )

    print(
        "Content-Encoding:",
        response.headers.get("Content-Encoding")
    )

    print(
        "Response Length:",
        len(response.content)
    )

    print(
        "First 100 Bytes:"
    )

    print(
        response.content[:100]
    )

    print(
        "First 100 Hex:"
    )

    print(
        response.content[:100].hex()
    )

    response.raise_for_status()

    return response.json()


# ==========================================================
# MARKET STATUS
# ==========================================================

def fetch_market_status(
    session
):

    return fetch_json(
        session,
        MARKET_STATUS_URL
    )


# ==========================================================
# ALL INDICES
# ==========================================================

def fetch_all_indices(
    session
):

    return fetch_json(
        session,
        ALL_INDICES_URL
    )


# ==========================================================
# SAVE TEST RESPONSE
# ==========================================================

def save_debug_response(
    name,
    data
):

    project_root = (
        Path(__file__)
        .resolve()
        .parents[2]
    )

    output_dir = (
        project_root /
        "data" /
        "live_test"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file = (
        output_dir /
        name
    )

    with open(
        output_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False,
            default=str
        )

    print()
    print(
        "Saved:",
        output_file
    )


# ==========================================================
# MAIN TEST
# ==========================================================

def main():

    try:

        session = create_session()


        # --------------------------------------------------
        # MARKET STATUS
        # --------------------------------------------------

        market_status = (
            fetch_market_status(
                session
            )
        )

        print()
        print("=" * 70)
        print("MARKET STATUS")
        print("=" * 70)

        print(
            json.dumps(
                market_status,
                indent=2,
                ensure_ascii=False
            )
        )


        # --------------------------------------------------
        # ALL INDICES
        # --------------------------------------------------

        all_indices = (
            fetch_all_indices(
                session
            )
        )

        print()
        print("=" * 70)
        print("ALL INDICES")
        print("=" * 70)

        if isinstance(
            all_indices,
            dict
        ):

            records = (
                all_indices.get(
                    "data",
                    []
                )
            )

        else:

            records = all_indices


        print(
            "Index records:",
            len(records)
        )


        # Display the first few records
        for record in records[:10]:

            print(
                record
            )


        # --------------------------------------------------
        # SAVE RAW RESPONSES
        # --------------------------------------------------

        save_debug_response(
            "market-status.json",
            market_status
        )

        save_debug_response(
            "all-indices.json",
            all_indices
        )


        print()
        print("=" * 70)
        print("NSE LIVE TEST COMPLETED")
        print("=" * 70)


        return True


    except requests.exceptions.HTTPError as error:

        print()
        print("NSE HTTP ERROR")
        print(error)

        return False


    except requests.exceptions.ConnectionError as error:

        print()
        print("NSE CONNECTION ERROR")
        print(error)

        return False


    except requests.exceptions.Timeout as error:

        print()
        print("NSE TIMEOUT")
        print(error)

        return False


    except Exception as error:

        print()
        print("UNEXPECTED ERROR")
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