import json
from datetime import datetime
from pathlib import Path

import feedparser
import requests


# ==========================================================
# RSS FEEDS
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
        "*/*;q=0.8"
    )
}


# ==========================================================
# OUTPUT
# ==========================================================

OUTPUT_DIR = Path("data")
OUTPUT_FILE = OUTPUT_DIR / "news-feed-verification.json"

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ==========================================================
# DATE
# ==========================================================

def get_published(entry):

    value = entry.get(
        "published",
        entry.get(
            "updated",
            ""
        )
    )

    return value


# ==========================================================
# FETCH
# ==========================================================

def fetch_feed(
    exchange,
    category,
    url
):

    print()
    print("=" * 90)
    print(f"{exchange} - {category}")
    print("=" * 90)

    print("URL:")
    print(url)

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    print(
        "HTTP Status:",
        response.status_code
    )

    print(
        "Content-Type:",
        response.headers.get(
            "Content-Type",
            ""
        )
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

    # ------------------------------------------------------
    # IMPORTANT:
    # NO DEDUPLICATION
    # ------------------------------------------------------

    for index, entry in enumerate(
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

        published = get_published(
            entry
        )

        record = {

            "exchange":
                exchange,

            "category":
                category,

            "feed_index":
                index,

            "title":
                title,

            "description":
                description,

            "published":
                published,

            "link":
                link
        }

        records.append(
            record
        )

    return records


# ==========================================================
# MAIN
# ==========================================================

def main():

    print("=" * 90)
    print("NSE / BSE NEWS FEED COLLECTION VERIFICATION")
    print("=" * 90)

    print()
    print("IMPORTANT:")
    print("NSE and BSE are collected separately.")
    print("NO DUPLICATE REMOVAL IS PERFORMED.")

    all_data = {}

    total_records = 0

    for exchange, feeds in RSS_FEEDS.items():

        all_data[exchange] = {}

        for category, url in feeds.items():

            try:

                records = fetch_feed(
                    exchange,
                    category,
                    url
                )

                all_data[exchange][category] = {
                    "feed_url": url,
                    "count": len(records),
                    "records": records
                }

                total_records += len(
                    records
                )

            except Exception as exc:

                print()
                print(
                    "ERROR:",
                    repr(exc)
                )

                all_data[exchange][category] = {
                    "feed_url": url,
                    "count": 0,
                    "error": str(exc),
                    "records": []
                }


    # ======================================================
    # SAVE
    # ======================================================

    output = {

        "status":
            "success",

        "collected_at":
            datetime.now().isoformat(),

        "deduplication":
            False,

        "total_records":
            total_records,

        "exchanges":
            all_data
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
    # SUMMARY
    # ======================================================

    print()
    print()
    print("=" * 90)
    print("COLLECTION SUMMARY")
    print("=" * 90)

    for exchange, categories in all_data.items():

        print()
        print(exchange)

        print("-" * 50)

        for category, data in categories.items():

            print(
                f"{category:<25}"
                f"{data.get('count', 0):>6}"
            )


    print()
    print("-" * 50)

    print(
        f"{'TOTAL':<25}"
        f"{total_records:>6}"
    )

    print()
    print("Deduplication: DISABLED")

    print()
    print("Saved:")
    print(
        OUTPUT_FILE
    )

    print()
    print("=" * 90)
    print("VERIFICATION COMPLETE")
    print("=" * 90)


if __name__ == "__main__":
    main()