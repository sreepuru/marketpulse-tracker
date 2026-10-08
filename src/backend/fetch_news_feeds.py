import feedparser
import requests
from datetime import datetime

from news_feeds import RSS_FEEDS


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    )
}


def parse_date(entry):

    if getattr(entry, "published_parsed", None):

        return datetime(
            *entry.published_parsed[:6]
        )

    if getattr(entry, "updated_parsed", None):

        return datetime(
            *entry.updated_parsed[:6]
        )

    return None


def fetch_feed(
    exchange,
    category,
    url
):

    print()
    print("=" * 80)
    print(
        f"{exchange} / {category}"
    )
    print("=" * 80)

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()

    feed = feedparser.parse(
        response.content
    )

    print(
        "Entries:",
        len(feed.entries)
    )

    records = []

    for entry in feed.entries:

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

        published = parse_date(
            entry
        )

        record = {

            "exchange":
                exchange,

            "category":
                category,

            "title":
                title,

            "description":
                description,

            "published_at":
                published,

            "source_url":
                link,

            "external_id":
                link or title,
        }

        records.append(
            record
        )

    return records


def fetch_all_feeds():

    all_records = []

    for exchange, categories in RSS_FEEDS.items():

        for category, url in categories.items():

            try:

                records = fetch_feed(
                    exchange,
                    category,
                    url
                )

                all_records.extend(
                    records
                )

            except Exception as exc:

                print()
                print(
                    f"ERROR: "
                    f"{exchange} "
                    f"{category}"
                )

                print(
                    repr(exc)
                )

    return all_records


if __name__ == "__main__":

    records = fetch_all_feeds()

    print()
    print("=" * 80)
    print("TOTAL RSS RECORDS")
    print("=" * 80)

    print(
        len(records)
    )

    for record in records[:10]:

        print()
        print(
            record["exchange"],
            record["category"]
        )

        print(
            record["title"]
        )

        print(
            record["published_at"]
        )

        print(
            record["source_url"]
        )