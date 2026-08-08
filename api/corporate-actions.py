import json
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from zoneinfo import ZoneInfo

import requests


# ==========================================================
# NSE URLs
# ==========================================================

BASE_URL = "https://www.nseindia.com"

EQUITY_API = (
    "https://www.nseindia.com/api/corporates-corporateActions"
    "?index=equities"
)

SME_API = (
    "https://www.nseindia.com/api/corporates-corporateActions"
    "?index=sme"
)


# ==========================================================
# Browser-like Headers
# ==========================================================

HEADERS = {

    "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36",

    "Accept":
        "application/json, text/plain, */*",

    "Accept-Language":
        "en-US,en;q=0.9",

    "Accept-Encoding":
        "gzip, deflate, br",

    "Connection":
        "keep-alive",

    "Referer":
        "https://www.nseindia.com/",

    "Sec-Fetch-Dest":
        "empty",

    "Sec-Fetch-Mode":
        "cors",

    "Sec-Fetch-Site":
        "same-origin",

}


# ==========================================================
# Fetch NSE Data
# ==========================================================

def fetch_nse_data():

    session = requests.Session()

    session.headers.update(HEADERS)

    # ------------------------------------------------------
    # Step 1: Open NSE homepage
    # ------------------------------------------------------

    homepage_response = session.get(
        BASE_URL,
        timeout=30
    )

    print(
        "NSE Homepage Status:",
        homepage_response.status_code
    )

    homepage_response.raise_for_status()

    # ------------------------------------------------------
    # Give NSE a small delay
    # ------------------------------------------------------

    time.sleep(1)

    # ------------------------------------------------------
    # Step 2: Equity
    # ------------------------------------------------------

    equity_response = session.get(
        EQUITY_API,
        timeout=30
    )

    print(
        "NSE Equity Status:",
        equity_response.status_code
    )

    equity_response.raise_for_status()

    equity_records = equity_response.json()

    # ------------------------------------------------------
    # Step 3: SME
    # ------------------------------------------------------

    time.sleep(1)

    sme_response = session.get(
        SME_API,
        timeout=30
    )

    print(
        "NSE SME Status:",
        sme_response.status_code
    )

    sme_response.raise_for_status()

    sme_records = sme_response.json()

    # ------------------------------------------------------
    # Validate response
    # ------------------------------------------------------

    if not isinstance(equity_records, list):

        raise ValueError(
            "NSE Equity response is not a list"
        )

    if not isinstance(sme_records, list):

        raise ValueError(
            "NSE SME response is not a list"
        )

    # ------------------------------------------------------
    # Merge
    # ------------------------------------------------------

    merged_records = (
        equity_records +
        sme_records
    )

    # ------------------------------------------------------
    # Timestamp
    # ------------------------------------------------------

    last_updated = datetime.now(
        ZoneInfo("Asia/Kolkata")
    ).strftime(
        "%d-%b-%Y %I:%M:%S %p"
    )

    # ------------------------------------------------------
    # Final response
    # ------------------------------------------------------

    return {

        "lastUpdated":
            last_updated,

        "recordCount":
            len(merged_records),

        "equityCount":
            len(equity_records),

        "smeCount":
            len(sme_records),

        "source":
            "NSE",

        "data":
            merged_records

    }


# ==========================================================
# Vercel Function
# ==========================================================

class handler(BaseHTTPRequestHandler):

    def do_GET(self):

        try:

            print(
                "MarketPulse NSE API request received"
            )

            result = fetch_nse_data()

            response = json.dumps(
                result,
                ensure_ascii=False
            ).encode("utf-8")

            self.send_response(200)

            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8"
            )

            self.send_header(
                "Cache-Control",
                "public, s-maxage=86400, "
                "stale-while-revalidate=3600"
            )

            self.send_header(
                "Content-Length",
                str(len(response))
            )

            self.end_headers()

            self.wfile.write(response)

        except requests.exceptions.HTTPError as error:

            print(
                "NSE HTTP Error:",
                error
            )

            error_response = json.dumps({

                "error":
                    "NSE rejected the request",

                "message":
                    str(error),

                "status":
                    getattr(
                        error.response,
                        "status_code",
                        None
                    )

            }).encode("utf-8")

            self.send_response(502)

            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8"
            )

            self.send_header(
                "Content-Length",
                str(len(error_response))
            )

            self.end_headers()

            self.wfile.write(
                error_response
            )

        except Exception as error:

            print(
                "MarketPulse API Error:",
                error
            )

            error_response = json.dumps({

                "error":
                    "Unable to fetch NSE data",

                "message":
                    str(error)

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

            self.wfile.write(
                error_response
            )