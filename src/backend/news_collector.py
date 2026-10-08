import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import fitz
import requests


# ==========================================================
# CONFIGURATION
# ==========================================================

RSS_FEEDS = {

    "NSE": {
        "ANNOUNCEMENTS":
            "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml",

        "BOARD_MEETINGS":
            "https://nsearchives.nseindia.com/content/RSS/Board_Meetings.xml",

        "CORPORATE_ACTIONS":
            "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml",

        "FINANCIAL_RESULTS":
            "https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml",
    },

    "BSE": {
        "ANNOUNCEMENTS":
            "https://beta.bseindia.com/data/xml/announcements.xml",

        "BOARD_MEETINGS":
            "https://beta.bseindia.com/Data/XML/BoardMeetingsFeed.xml",

        "CORPORATE_ACTIONS":
            "https://beta.bseindia.com/data/XML/CorpActionFeed.xml",

        "FINANCIAL_RESULTS":
            "https://beta.bseindia.com/Data/XML/FinancialResultsFeed.xml",

        "NOTICES":
            "https://beta.bseindia.com/data/xml/notices.xml",
    }
}


# ==========================================================
# DIRECTORIES
# ==========================================================

BASE_DIR = Path("data")

RAW_DIR = BASE_DIR / "news-raw"

ATTACHMENT_DIR = BASE_DIR / "attachments"

EXTRACTED_DIR = BASE_DIR / "extracted"

OUTPUT_FILE = BASE_DIR / "news-collection.json"


for directory in [
    RAW_DIR,
    ATTACHMENT_DIR,
    EXTRACTED_DIR
]:

    directory.mkdir(
        parents=True,
        exist_ok=True
    )


# ==========================================================
# HTTP
# ==========================================================

HEADERS = {

    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),

    "Accept": (
        "application/rss+xml,"
        "application/xml,"
        "text/xml,"
        "application/pdf,"
        "*/*;q=0.8"
    )
}


# ==========================================================
# HELPERS
# ==========================================================

def classify_url(url):

    if not url:
        return "NONE"

    path = urlparse(url).path.lower()

    if path.endswith(".pdf"):
        return "PDF"

    if path.endswith(".xml"):
        return "XML"

    if (
        path.endswith(".html")
        or path.endswith(".htm")
        or "bseindia.com/corporates/" in url.lower()
        or "nseindia.com/companies-" in url.lower()
    ):
        return "HTML"

    return "OTHER"


def safe_filename(value):

    value = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        value
    )

    return value[:120]


def calculate_sha256(content):

    return hashlib.sha256(
        content
    ).hexdigest()


def parse_published(entry):

    value = entry.get(
        "published",
        entry.get(
            "updated",
            ""
        )
    )

    return value


def extract_pdf_text(pdf_path):

    document = fitz.open(
        pdf_path
    )

    text_parts = []

    for page in document:

        text = page.get_text(
            "text"
        )

        if text:
            text_parts.append(
                text
            )

    document.close()

    return "\n".join(
        text_parts
    ).strip()


# ==========================================================
# DOWNLOAD ATTACHMENT
# ==========================================================

def download_attachment(
    url,
    exchange,
    category,
    feed_index,
    title
):

    attachment_type = classify_url(
        url
    )

    if attachment_type not in [
        "PDF",
        "XML"
    ]:

        return {

            "attachment_type":
                attachment_type,

            "source_url":
                url,

            "download_status":
                "NOT_DOWNLOADED"
        }


    print()
    print(
        "Attachment:",
        attachment_type
    )

    print(
        "URL:",
        url
    )


    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=60
        )

        response.raise_for_status()

        content = response.content

        sha256 = calculate_sha256(
            content
        )

        extension = (
            ".pdf"
            if attachment_type == "PDF"
            else ".xml"
        )

        filename = (
            sha256
            + extension
        )

        exchange_dir = (
            ATTACHMENT_DIR
            / exchange
            / category
        )

        exchange_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        file_path = (
            exchange_dir
            / filename
        )


        # --------------------------------------------------
        # ATTACHMENT DEDUPLICATION
        # --------------------------------------------------

        already_exists = (
            file_path.exists()
        )


        if not already_exists:

            file_path.write_bytes(
                content
            )

            download_status = (
                "DOWNLOADED"
            )

        else:

            download_status = (
                "DEDUPLICATED"
            )


        result = {

            "attachment_type":
                attachment_type,

            "source_url":
                url,

            "sha256":
                sha256,

            "file_size":
                len(content),

            "local_path":
                str(file_path),

            "download_status":
                download_status
        }


        # --------------------------------------------------
        # PDF EXTRACTION
        # --------------------------------------------------

        if attachment_type == "PDF":

            extracted_dir = (
                EXTRACTED_DIR
                / exchange
                / category
            )

            extracted_dir.mkdir(
                parents=True,
                exist_ok=True
            )

            text_path = (
                extracted_dir
                / f"{sha256}.txt"
            )


            if text_path.exists():

                result[
                    "extraction_status"
                ] = "DEDUPLICATED"

                result[
                    "extracted_text_path"
                ] = str(
                    text_path
                )

            else:

                try:

                    text = extract_pdf_text(
                        file_path
                    )

                    text_path.write_text(
                        text,
                        encoding="utf-8"
                    )

                    result[
                        "extraction_status"
                    ] = (
                        "SUCCESS"
                        if text
                        else "NO_TEXT"
                    )

                    result[
                        "extracted_characters"
                    ] = len(text)

                    result[
                        "extracted_text_path"
                    ] = str(
                        text_path
                    )

                except Exception as exc:

                    result[
                        "extraction_status"
                    ] = "FAILED"

                    result[
                        "extraction_error"
                    ] = str(exc)


        return result


    except Exception as exc:

        return {

            "attachment_type":
                attachment_type,

            "source_url":
                url,

            "download_status":
                "FAILED",

            "error":
                str(exc)
        }


# ==========================================================
# FETCH ONE FEED
# ==========================================================

def collect_feed(
    exchange,
    category,
    feed_url
):

    print()
    print("=" * 90)
    print(
        f"{exchange} / {category}"
    )
    print("=" * 90)

    print(
        "Feed:",
        feed_url
    )


    response = requests.get(
        feed_url,
        headers=HEADERS,
        timeout=60
    )

    response.raise_for_status()


    feed = feedparser.parse(
        response.content
    )


    print(
        "Records:",
        len(feed.entries)
    )


    records = []


    # IMPORTANT:
    # No deduplication of feed records.

    for feed_index, entry in enumerate(
        feed.entries,
        start=1
    ):

        title = entry.get(
            "title",
            ""
        ).strip()

        description = entry.get(
            "description",
            entry.get(
                "summary",
                ""
            )
        )

        link = entry.get(
            "link",
            ""
        )

        published = parse_published(
            entry
        )


        record = {

            "exchange":
                exchange,

            "category":
                category,

            "feed_url":
                feed_url,

            "feed_index":
                feed_index,

            "title":
                title,

            "description":
                description,

            "published":
                published,

            "source_url":
                link,

            "attachment":
                None,

            "raw_data":
                dict(entry)
        }


        # --------------------------------------------------
        # ATTACHMENT
        # --------------------------------------------------

        if link:

            record[
                "attachment"
            ] = download_attachment(

                url=link,

                exchange=exchange,

                category=category,

                feed_index=feed_index,

                title=title
            )


        records.append(
            record
        )


    return records


# ==========================================================
# COLLECT EVERYTHING
# ==========================================================

def collect_all():

    print("=" * 90)
    print("NSE / BSE PRODUCTION NEWS COLLECTION")
    print("=" * 90)

    print()
    print("Feed deduplication: DISABLED")
    print("Attachment deduplication: SHA-256")


    result = {

        "status":
            "success",

        "collected_at":
            datetime.now().isoformat(),

        "feed_deduplication":
            False,

        "attachment_deduplication":
            "SHA-256",

        "exchanges": {}
    }


    total_records = 0

    attachment_downloaded = 0

    attachment_deduplicated = 0

    attachment_failed = 0

    pdf_extracted = 0

    pdf_no_text = 0

    pdf_extraction_failed = 0


    for exchange, feeds in RSS_FEEDS.items():

        result[
            "exchanges"
        ][exchange] = {}


        for category, feed_url in feeds.items():

            try:

                records = collect_feed(

                    exchange,

                    category,

                    feed_url
                )


                result[
                    "exchanges"
                ][exchange][category] = {

                    "feed_url":
                        feed_url,

                    "count":
                        len(records),

                    "records":
                        records
                }


                total_records += len(
                    records
                )


                for record in records:

                    attachment = record.get(
                        "attachment"
                    )

                    if not attachment:
                        continue


                    status = attachment.get(
                        "download_status"
                    )

                    if status == "DOWNLOADED":

                        attachment_downloaded += 1

                    elif status == "DEDUPLICATED":

                        attachment_deduplicated += 1

                    elif status == "FAILED":

                        attachment_failed += 1


                    extraction = attachment.get(
                        "extraction_status"
                    )

                    if extraction in [
                        "SUCCESS",
                        "DEDUPLICATED"
                    ]:

                        pdf_extracted += 1

                    elif extraction == "NO_TEXT":

                        pdf_no_text += 1

                    elif extraction == "FAILED":

                        pdf_extraction_failed += 1


            except Exception as exc:

                print()
                print(
                    "FEED ERROR:",
                    exchange,
                    category
                )

                print(
                    repr(exc)
                )


                result[
                    "exchanges"
                ][exchange][category] = {

                    "feed_url":
                        feed_url,

                    "count":
                        0,

                    "records":
                        [],

                    "error":
                        str(exc)
                }


    # ======================================================
    # SUMMARY
    # ======================================================

    result[
        "summary"
    ] = {

        "total_feed_records":
            total_records,

        "attachments_downloaded":
            attachment_downloaded,

        "attachments_deduplicated":
            attachment_deduplicated,

        "attachments_failed":
            attachment_failed,

        "pdf_extracted":
            pdf_extracted,

        "pdf_no_text":
            pdf_no_text,

        "pdf_extraction_failed":
            pdf_extraction_failed
    }


    # ======================================================
    # SAVE
    # ======================================================

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            result,
            file,
            indent=2,
            ensure_ascii=False,
            default=str
        )


    print()
    print()
    print("=" * 90)
    print("COLLECTION SUMMARY")
    print("=" * 90)

    print(
        "Total feed records:",
        total_records
    )

    print(
        "Attachments downloaded:",
        attachment_downloaded
    )

    print(
        "Attachments deduplicated:",
        attachment_deduplicated
    )

    print(
        "Attachments failed:",
        attachment_failed
    )

    print(
        "PDF extracted:",
        pdf_extracted
    )

    print(
        "PDF no text:",
        pdf_no_text
    )

    print(
        "PDF extraction failed:",
        pdf_extraction_failed
    )

    print()
    print(
        "Saved:",
        OUTPUT_FILE
    )

    print()
    print("=" * 90)
    print("COLLECTION COMPLETE")
    print("=" * 90)


# ==========================================================
# ENTRY POINT
# ==========================================================

if __name__ == "__main__":

    collect_all()