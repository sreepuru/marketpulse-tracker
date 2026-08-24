import os
import sys
import time
import zipfile
from pathlib import Path
from datetime import datetime

import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ==========================================================
# Configuration
# ==========================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DOWNLOAD_FOLDER = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
)

EXTRACT_FOLDER = (
    DOWNLOAD_FOLDER
    / "extracted"
)

NSE_REPORTS_URL = (
    "https://www.nseindia.com/all-reports"
)

NSE_BHAVCOPY_BASE_URL = (
    "https://nsearchives.nseindia.com/content/cm/"
)


# ==========================================================
# Create folders
# ==========================================================

DOWNLOAD_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)

EXTRACT_FOLDER.mkdir(
    parents=True,
    exist_ok=True
)


# ==========================================================
# Get requested date
# ==========================================================

def get_requested_date():

    if len(sys.argv) <= 1:
        return None

    requested_date = sys.argv[1].strip()

    try:

        datetime.strptime(
            requested_date,
            "%Y-%m-%d"
        )

    except ValueError:

        raise ValueError(
            "Date must be in YYYY-MM-DD format. "
            "Example: 2026-06-23"
        )

    return requested_date


# ==========================================================
# Build historical Bhavcopy URL
# ==========================================================

def build_historical_bhavcopy_url(
    date_string
):

    date_obj = datetime.strptime(
        date_string,
        "%Y-%m-%d"
    )

    date_part = date_obj.strftime(
        "%Y%m%d"
    )

    filename = (
        f"BhavCopy_NSE_CM_0_0_0_"
        f"{date_part}_F_0000.csv.zip"
    )

    return (
        NSE_BHAVCOPY_BASE_URL
        + filename
    )


# ==========================================================
# Create Selenium driver
# ==========================================================

def create_driver():

    chrome_options = Options()

    chrome_options.add_experimental_option(
        "prefs",
        {
            "download.default_directory":
                str(
                    DOWNLOAD_FOLDER.resolve()
                ),

            "download.prompt_for_download":
                False,

            "download.directory_upgrade":
                True,

            "safebrowsing.enabled":
                True
        }
    )

    driver = webdriver.Chrome(
        options=chrome_options
    )

    driver.set_page_load_timeout(
        60
    )

    return driver


# ==========================================================
# Find latest Bhavcopy link
# ==========================================================

def find_bhavcopy_link(
    driver
):

    print()
    print(
        "Opening NSE Reports page..."
    )

    print(
        NSE_REPORTS_URL
    )

    driver.get(
        NSE_REPORTS_URL
    )

    wait = WebDriverWait(
        driver,
        60
    )

    wait.until(
        EC.presence_of_element_located(
            (
                By.TAG_NAME,
                "body"
            )
        )
    )

    time.sleep(5)

    print()
    print(
        "Searching for CM-UDiFF Bhavcopy..."
    )

    links = driver.find_elements(
        By.TAG_NAME,
        "a"
    )

    candidates = []

    for link in links:

        try:

            href = link.get_attribute(
                "href"
            )

            text = (
                link.text or ""
            ).strip()

            if not href:
                continue

            href_lower = (
                href.lower()
            )

            text_lower = (
                text.lower()
            )

            if (
                "bhavcopy_nse_cm"
                in href_lower

                and href_lower.endswith(
                    ".zip"
                )
            ):

                candidates.append(
                    {
                        "text": text,
                        "href": href
                    }
                )

            elif (
                "udiiff common bhavcopy final"
                in text_lower

                and href_lower.endswith(
                    ".zip"
                )
            ):

                candidates.append(
                    {
                        "text": text,
                        "href": href
                    }
                )

        except Exception:

            continue

    # ------------------------------------------------------
    # Remove duplicates
    # ------------------------------------------------------

    unique = {}

    for item in candidates:

        unique[
            item["href"]
        ] = item

    candidates = list(
        unique.values()
    )

    print()
    print(
        "Bhavcopy candidates found:",
        len(candidates)
    )

    for item in candidates[:10]:

        print()
        print(
            "Text :",
            item["text"]
        )

        print(
            "URL  :",
            item["href"]
        )

    if not candidates:

        raise RuntimeError(
            "Could not find CM-UDiFF Bhavcopy "
            "download link on NSE Reports page."
        )

    preferred = [

        item

        for item in candidates

        if (
            "bhavcopy_nse_cm"
            in item["href"].lower()
        )

    ]

    if preferred:

        selected = preferred[0]

    else:

        selected = candidates[0]

    print()
    print(
        "Selected Bhavcopy:"
    )

    print(
        selected["href"]
    )

    return selected["href"]


# ==========================================================
# Download Bhavcopy
# ==========================================================

def download_bhavcopy(
    driver,
    href
):

    print()
    print(
        "Starting Bhavcopy download..."
    )

    # ------------------------------------------------------
    # Capture files before download
    # ------------------------------------------------------

    before = {
        file.resolve()

        for file in DOWNLOAD_FOLDER.iterdir()

        if file.is_file()
    }

    driver.get(
        href
    )

    print(
        "Waiting for download..."
    )

    timeout = 90

    start_time = time.time()

    downloaded_file = None

    while (
        time.time() - start_time
        < timeout
    ):

        time.sleep(1)

        current = {
            file.resolve()

            for file in DOWNLOAD_FOLDER.iterdir()

            if file.is_file()
        }

        new_files = (
            current - before
        )

        completed = [

            file

            for file in new_files

            if not file.name.endswith(
                ".crdownload"
            )

            and file.suffix.lower()
            == ".zip"

        ]

        if completed:

            downloaded_file = max(
                completed,
                key=lambda file:
                    file.stat().st_mtime
            )

            break

    if not downloaded_file:

        raise RuntimeError(
            "Bhavcopy download did not "
            "complete within 90 seconds."
        )

    print()
    print(
        "Downloaded:",
        downloaded_file
    )

    print(
        "Size:",
        round(
            downloaded_file.stat().st_size
            / 1024,
            2
        ),
        "KB"
    )

    return downloaded_file


# ==========================================================
# Extract Bhavcopy
# ==========================================================

def extract_bhavcopy(
    zip_file
):

    print()
    print(
        "Extracting Bhavcopy..."
    )

    # ------------------------------------------------------
    # Create folder based on ZIP filename
    # ------------------------------------------------------

    folder_name = zip_file.stem

    extraction_path = (
        EXTRACT_FOLDER
        / folder_name
    )

    extraction_path.mkdir(
        parents=True,
        exist_ok=True
    )

    # ------------------------------------------------------
    # Extract
    # ------------------------------------------------------

    with zipfile.ZipFile(
        zip_file,
        "r"
    ) as archive:

        archive.extractall(
            extraction_path
        )

        files = archive.namelist()

    print()
    print(
        "Extraction folder:"
    )

    print(
        extraction_path
    )

    print()
    print(
        "Files inside ZIP:"
    )

    for file in files:

        print(
            " -",
            file
        )

    return extraction_path


# ==========================================================
# Find CSV belonging to this extraction
# ==========================================================

def find_csv(
    extraction_path
):

    csv_files = list(
        extraction_path.rglob(
            "*.csv"
        )
    )

    if not csv_files:

        raise RuntimeError(
            "No CSV file found inside "
            "Bhavcopy ZIP."
        )

    # ------------------------------------------------------
    # Prefer exact CSV matching ZIP folder
    # ------------------------------------------------------

    expected_name = (
        extraction_path.name
        + ".csv"
    )

    exact_matches = [

        file

        for file in csv_files

        if file.name
        == expected_name

    ]

    if exact_matches:

        csv_file = exact_matches[0]

    else:

        if len(csv_files) > 1:

            print()
            print(
                "Multiple CSV files found. "
                "Using first CSV."
            )

        csv_file = csv_files[0]

    print()
    print(
        "CSV selected:",
        csv_file
    )

    return csv_file


# ==========================================================
# Read CSV
# ==========================================================

def read_bhavcopy(
    csv_file
):

    print()
    print(
        "Reading CSV..."
    )

    try:

        df = pd.read_csv(
            csv_file
        )

    except Exception:

        df = pd.read_csv(
            csv_file,
            encoding="latin1"
        )

    df.columns = [

        str(column)
        .strip()
        .upper()

        for column in df.columns

    ]

    return df


# ==========================================================
# Display sample
# ==========================================================

def display_sample(
    df
):

    print()
    print(
        "=" * 70
    )

    print(
        "BHAVCOPY SUCCESSFULLY READ"
    )

    print(
        "=" * 70
    )

    print()

    print(
        "Rows:",
        len(df)
    )

    print()

    print(
        "Columns:"
    )

    for column in df.columns:

        print(
            " -",
            column
        )

    print()

    print(
        "First 10 records:"
    )

    print()

    print(
        df.head(10).to_string(
            index=False
        )
    )

    print()

    print(
        "=" * 70
    )


# ==========================================================
# Main
# ==========================================================

def main():

    driver = None

    try:

        print()
        print(
            "=" * 70
        )

        print(
            "       MarketPulse NSE Bhavcopy Downloader"
        )

        print(
            "=" * 70
        )

        # --------------------------------------------------
        # Determine requested date
        # --------------------------------------------------

        requested_date = (
            get_requested_date()
        )

        # --------------------------------------------------
        # Create driver
        # --------------------------------------------------

        driver = create_driver()

        # --------------------------------------------------
        # Select URL
        # --------------------------------------------------

        if requested_date:

            print()
            print(
                "Historical date requested:",
                requested_date
            )

            href = (
                build_historical_bhavcopy_url(
                    requested_date
                )
            )

            print()
            print(
                "Historical Bhavcopy URL:"
            )

            print(
                href
            )

        else:

            href = (
                find_bhavcopy_link(
                    driver
                )
            )

        # --------------------------------------------------
        # Download
        # --------------------------------------------------

        zip_file = (
            download_bhavcopy(
                driver,
                href
            )
        )

        # --------------------------------------------------
        # Extract into date-specific folder
        # --------------------------------------------------

        extraction_path = (
            extract_bhavcopy(
                zip_file
            )
        )

        # --------------------------------------------------
        # Find correct CSV
        # --------------------------------------------------

        csv_file = (
            find_csv(
                extraction_path
            )
        )

        # --------------------------------------------------
        # Read
        # --------------------------------------------------

        df = (
            read_bhavcopy(
                csv_file
            )
        )

        # --------------------------------------------------
        # Display
        # --------------------------------------------------

        display_sample(
            df
        )

        print()

        print(
            "Step 1 completed successfully."
        )

    except Exception as error:

        print()
        print(
            "=" * 70
        )

        print(
            "ERROR"
        )

        print(
            "=" * 70
        )

        print(
            error
        )

    finally:

        if driver:

            driver.quit()


# ==========================================================
# Start
# ==========================================================

if __name__ == "__main__":

    main()