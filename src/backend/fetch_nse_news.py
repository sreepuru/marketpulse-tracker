import os
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv


# ============================================================
# ENVIRONMENT
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(
    PROJECT_ROOT / ".env"
)


# ============================================================
# NSE CONFIGURATION
# ============================================================

BASE_URL = "https://www.nseindia.com"

RSS_URL = os.getenv(
    "MARKETPULSE_NSE_NEWS_RSS_URL",
    "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"
)


# ============================================================
# OUTPUT
# ============================================================

OUTPUT_FOLDER = PROJECT_ROOT / "data" / "news"

OUTPUT_FILE = (
    OUTPUT_FOLDER /
    "nse-corporate-announcements.xml"
)


# ============================================================
# HTTP HEADERS
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),

    "Accept": (
        "application/rss+xml, "
        "application/xml, "
        "text/xml, "
        "*/*"
    ),

    "Accept-Language": (
        "en-US,en;q=0.9"
    ),

    "Referer": (
        "https://www.nseindia.com/"
    ),

    "Connection": "keep-alive",
}


# ============================================================
# CREATE NSE SESSION
# ============================================================

def create_session():

    session = requests.Session()

    session.headers.update(
        HEADERS
    )

    print("Creating NSE Session...")

    response = session.get(
        BASE_URL,
        timeout=30
    )

    print(
        "NSE Homepage Status :",
        response.status_code
    )

    response.raise_for_status()

    time.sleep(1)

    return session


# ============================================================
# FETCH RSS
# ============================================================

def fetch_rss(session):

    print()
    print("Fetching NSE News RSS...")
    print(
        "RSS URL :",
        RSS_URL
    )

    response = session.get(
        RSS_URL,
        timeout=30
    )

    print(
        "RSS Status :",
        response.status_code
    )

    response.raise_for_status()

    if not response.content:
        raise ValueError(
            "NSE RSS response is empty."
        )

    return response.content


# ============================================================
# VALIDATE RSS
# ============================================================

def validate_rss(content):

    text = content.decode(
        "utf-8",
        errors="replace"
    ).lstrip()

    if not text.startswith(
        "<?xml"
    ) and not text.startswith(
        "<rss"
    ):

        raise ValueError(
            "NSE response does not appear to be RSS/XML."
        )

    if "<channel>" not in text:
        raise ValueError(
            "NSE RSS does not contain <channel>."
        )

    if "<item>" not in text:
        raise ValueError(
            "NSE RSS does not contain any <item> records."
        )

    return text


# ============================================================
# SAVE RSS
# ============================================================

def save_rss(content):

    OUTPUT_FOLDER.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        OUTPUT_FILE,
        "wb"
    ) as file:

        file.write(
            content
        )

    print()
    print("=" * 70)
    print("NSE NEWS RSS SAVED")
    print("=" * 70)

    print(
        "File :",
        OUTPUT_FILE
    )

    print(
        "Size :",
        len(content),
        "bytes"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    try:

        session = create_session()

        content = fetch_rss(
            session
        )

        validate_rss(
            content
        )

        save_rss(
            content
        )

        print()
        print(
            "Fetched At :",
            datetime.now().strftime(
                "%d-%b-%Y %I:%M:%S"
            )
        )

        print()
        print(
            "NSE News RSS fetch completed successfully."
        )

        return True


    except requests.exceptions.HTTPError as err:

        print()
        print("HTTP ERROR")
        print(err)

        return False


    except requests.exceptions.ConnectionError as err:

        print()
        print("CONNECTION ERROR")
        print(err)

        return False


    except requests.exceptions.Timeout as err:

        print()
        print("TIMEOUT")
        print(err)

        return False


    except Exception as err:

        print()
        print("UNEXPECTED ERROR")
        print(err)

        return False


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    success = main()

    raise SystemExit(
        0 if success else 1
    )