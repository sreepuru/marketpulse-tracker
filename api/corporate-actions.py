import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from zoneinfo import ZoneInfo

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
# NSE Headers
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
# Fetch NSE Data
# ==========================================================

def fetch_nse_data():

    session = requests.Session()

    session.headers.update(HEADERS)

    # ------------------------------------------------------
    # Open NSE homepage first
    # ------------------------------------------------------

    homepage = session.get(
        BASE_URL,
        timeout=30
    )

    homepage.raise_for_status()

    # ------------------------------------------------------
    # Equity
    # ------------------------------------------------------

    equity_response = session.get(
        EQUITY_API,
        timeout=30
    )

    equity_response.raise_for_status()

    equity_records = equity_response.json()

    # ------------------------------------------------------
    # SME
    # ------------------------------------------------------

    sme_response = session.get(
        SME_API,
        timeout=30
    )

    sme_response.raise_for_status()

    sme_records = sme_response.json()

    # ------------------------------------------------------
    # Make sure responses are lists
    # ------------------------------------------------------

    if not isinstance(equity_records, list):

        equity_records = []

    if not isinstance(sme_records, list):

        sme_records = []

    # ------------------------------------------------------
    # Merge
    # ------------------------------------------------------

    merged_records = (
        equity_records +
        sme_records
    )

    # ------------------------------------------------------
    # IST timestamp
    # ------------------------------------------------------

    last_updated = datetime.now(
        ZoneInfo("Asia/Kolkata")
    ).strftime(
        "%d-%b-%Y %I:%M:%S %p"
    )

    # ------------------------------------------------------
    # Response
    # ------------------------------------------------------

    result = {

        "lastUpdated": last_updated,

        "recordCount": len(merged_records),

        "equityCount": len(equity_records),

        "smeCount": len(sme_records),

        "source": "NSE",

        "data": merged_records

    }

    return result


# ==========================================================
# Vercel API Handler
# ==========================================================

class handler(BaseHTTPRequestHandler):

    def do_GET(self):

        try:

            result = fetch_nse_data()

            response = json.dumps(
                result,
                ensure_ascii=False
            ).encode("utf-8")

            self.send_response(200)

            # ------------------------------------------------
            # Response headers
            # ------------------------------------------------

            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8"
            )

            # ------------------------------------------------
            # Cache for one day
            #
            # This prevents every page load from hitting NSE.
            # ------------------------------------------------

            self.send_header(
                "Cache-Control",
                "public, s-maxage=86400, stale-while-revalidate=3600"
            )

            self.send_header(
                "Content-Length",
                str(len(response))
            )

            self.end_headers()

            self.wfile.write(response)

        except Exception as error:

            print("NSE API Error:", error)

            error_response = json.dumps({

                "error": "Unable to fetch NSE data",

                "message": str(error)

            }).encode("utf-8")

            self.send_response(500)

            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8"
            )

            self.send_header(
                "Content-Length",
                str(len(error_response))
            )

            self.end_headers()

            self.wfile.write(error_response)