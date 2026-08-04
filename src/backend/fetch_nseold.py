import json
import time
import requests

BASE_URL = "https://www.nseindia.com"

EQUITY_API = "https://www.nseindia.com/api/corporates-corporateActions?index=equities"
SME_API = "https://www.nseindia.com/api/corporates-corporateActions?index=sme"

OUTPUT_FILE = "corporate-actions.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions",
}


def create_session():
    session = requests.Session()
    session.headers.update(HEADERS)

    print("Creating NSE session...")

    response = session.get(BASE_URL, timeout=30)
    print("Homepage Status :", response.status_code)

    time.sleep(1)

    return session


def fetch_data(session, url):
    print(f"Fetching : {url}")

    response = session.get(url, timeout=30)
    response.raise_for_status()

    return response.json()


def main():

    session = create_session()

    equity_records = fetch_data(session, EQUITY_API)
    sme_records = fetch_data(session, SME_API)

    print("Equity Records :", len(equity_records))
    print("SME Records    :", len(sme_records))

    merged = equity_records + sme_records

    print("Merged Records :", len(merged))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(
            merged,
            file,
            indent=4,
            ensure_ascii=False
        )

    print(f"\nSuccessfully saved {OUTPUT_FILE}")


if __name__ == "__main__":
    main()


print("Backend JSON:", BACKEND_JSON)
print("Exists:", BACKEND_JSON.exists())

print("Public JSON:", PUBLIC_JSON)
print("Exists:", PUBLIC_JSON.exists())
