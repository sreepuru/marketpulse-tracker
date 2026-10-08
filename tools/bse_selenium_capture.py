import json
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options


# ==========================================================
# CONFIG
# ==========================================================

BASE_URL = "https://www.bseindia.com/"

OUTPUT_DIR = Path("data")
OUTPUT_FILE = OUTPUT_DIR / "bse-network-capture.json"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ==========================================================
# CHROME CONFIG
# ==========================================================

options = Options()

# Show Chrome so we can see what is happening
# DO NOT use headless mode initially.

options.add_argument("--start-maximized")

# Selenium performance logging
options.set_capability(
    "goog:loggingPrefs",
    {
        "performance": "ALL",
        "browser": "ALL"
    }
)


# ==========================================================
# START BROWSER
# ==========================================================

print("=" * 70)
print("STARTING BSE SELENIUM NETWORK CAPTURE")
print("=" * 70)

driver = webdriver.Chrome(
    options=options
)

driver.set_page_load_timeout(60)


try:

    print()
    print("Opening:")
    print(BASE_URL)

    driver.get(BASE_URL)

    print()
    print("BSE page loaded.")
    print()

    print("=" * 70)
    print("NOW USE THE BSE WEBSITE")
    print("=" * 70)

    print("""
1. Navigate to Board Meetings / Announcements / Results.
2. Open the page that contains the data.
3. Wait for the data to load.
4. Leave the browser open.
5. Come back to this terminal.
6. Press ENTER.
""")

    input("Press ENTER after the BSE data has loaded... ")

    print()
    print("=" * 70)
    print("READING NETWORK LOGS")
    print("=" * 70)


    # ======================================================
    # READ PERFORMANCE LOGS
    # ======================================================

    logs = driver.get_log("performance")

    requests = []


    for entry in logs:

        try:

            message = json.loads(
                entry["message"]
            )["message"]

        except Exception:
            continue


        if message.get("method") != (
            "Network.requestWillBeSent"
        ):
            continue


        params = message.get(
            "params",
            {}
        )

        request = params.get(
            "request",
            {}
        )

        url = request.get(
            "url",
            ""
        )

        method = request.get(
            "method",
            ""
        )


        if not url:
            continue


        # ==================================================
        # ONLY INTERESTING REQUESTS
        # ==================================================

        url_lower = url.lower()

        interesting = (

            "api.bseindia.com" in url_lower

            or "/api/" in url_lower

            or "announcement" in url_lower

            or "board" in url_lower

            or "result" in url_lower

            or "corporate" in url_lower

            or "notice" in url_lower

            or "calendar" in url_lower

        )


        if not interesting:
            continue


        record = {
            "method": method,
            "url": url,
            "type": params.get(
                "type"
            ),
            "resourceType": params.get(
                "type"
            )
        }


        # ==================================================
        # REQUEST HEADERS
        # ==================================================

        headers = request.get(
            "headers",
            {}
        )

        if headers:

            record["headers"] = headers


        # ==================================================
        # POST DATA
        # ==================================================

        if "postData" in request:

            record["postData"] = (
                request["postData"]
            )


        requests.append(
            record
        )


    # ======================================================
    # REMOVE DUPLICATES
    # ======================================================

    unique_requests = {}

    for request in requests:

        key = (
            request["method"],
            request["url"]
        )

        unique_requests[key] = request


    requests = list(
        unique_requests.values()
    )


    # ======================================================
    # SAVE
    # ======================================================

    output = {
        "source": "BSE Selenium network capture",
        "captured_at": time.strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "count": len(requests),
        "requests": requests
    }


    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            output,
            file,
            indent=2,
            ensure_ascii=False
        )


    # ======================================================
    # PRINT SUMMARY
    # ======================================================

    print()
    print("=" * 70)
    print("CAPTURE COMPLETE")
    print("=" * 70)

    print(
        f"Requests captured: {len(requests)}"
    )

    print(
        f"Saved to: {OUTPUT_FILE}"
    )

    print()


    for index, request in enumerate(
        requests,
        start=1
    ):

        print("-" * 70)

        print(
            f"[{index}] "
            f"{request['method']}"
        )

        print(
            request["url"]
        )

        if request.get("postData"):

            print(
                "POST DATA:"
            )

            print(
                request["postData"]
            )


    print()
    print("=" * 70)
    print("DONE")
    print("=" * 70)


finally:

    print()
    print("Closing browser...")

    driver.quit()