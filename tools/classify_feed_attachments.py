import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


INPUT_FILE = Path(
    "data/news-feed-verification.json"
)


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


def main():

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        data = json.load(file)


    overall = Counter()

    by_exchange = {}

    by_feed = {}


    for exchange, feeds in data["exchanges"].items():

        by_exchange[exchange] = Counter()

        for category, feed_data in feeds.items():

            counter = Counter()

            for record in feed_data.get(
                "records",
                []
            ):

                url = record.get(
                    "link",
                    ""
                )

                classification = classify_url(
                    url
                )

                counter[classification] += 1
                by_exchange[exchange][classification] += 1
                overall[classification] += 1


            by_feed[
                f"{exchange} / {category}"
            ] = counter


    print("=" * 80)
    print("FEED ATTACHMENT / LINK CLASSIFICATION")
    print("=" * 80)

    print()
    print("OVERALL")
    print("-" * 50)

    for key, count in overall.items():

        print(
            f"{key:<15} {count:>6}"
        )


    print()
    print("BY EXCHANGE")
    print("-" * 50)

    for exchange, counter in by_exchange.items():

        print()
        print(exchange)

        for key, count in counter.items():

            print(
                f"  {key:<13} {count:>6}"
            )


    print()
    print("BY FEED")
    print("-" * 70)

    for feed, counter in by_feed.items():

        print()
        print(feed)

        for key, count in counter.items():

            print(
                f"  {key:<13} {count:>6}"
            )


if __name__ == "__main__":
    main()