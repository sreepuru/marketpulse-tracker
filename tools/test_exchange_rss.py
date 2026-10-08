import requests
import feedparser


FEEDS = {

    "NSE_ANNOUNCEMENTS":
        "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml",

    "NSE_BOARD_MEETINGS":
        "https://nsearchives.nseindia.com/content/RSS/Board_Meetings.xml",

    "NSE_CORPORATE_ACTIONS":
        "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml",

    "NSE_FINANCIAL_RESULTS":
        "https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml",

    "BSE_ANNOUNCEMENTS":
        "https://beta.bseindia.com/data/xml/announcements.xml",

    "BSE_BOARD_MEETINGS":
        "https://beta.bseindia.com/Data/XML/BoardMeetingsFeed.xml",

    "BSE_CORPORATE_ACTIONS":
        "https://beta.bseindia.com/data/XML/CorpActionFeed.xml",

    "BSE_FINANCIAL_RESULTS":
        "https://beta.bseindia.com/Data/XML/FinancialResultsFeed.xml",

    "BSE_NOTICES":
        "https://beta.bseindia.com/data/xml/notices.xml",
}


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
        "text/html;q=0.9,"
        "*/*;q=0.8"
    ),
}


def test_feed(name, url):

    print()
    print("=" * 90)
    print(name)
    print("=" * 90)

    print("URL:")
    print(url)

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30
        )

        print()
        print(
            "HTTP Status:",
            response.status_code
        )

        print(
            "Content-Type:",
            response.headers.get(
                "Content-Type"
            )
        )

        print(
            "Content Length:",
            len(response.content)
        )

        if response.status_code != 200:

            print(
                "ERROR: HTTP request failed"
            )

            return


        # --------------------------------------------------
        # Parse RSS
        # --------------------------------------------------

        feed = feedparser.parse(
            response.content
        )

        print()
        print(
            "Feed Title:",
            feed.feed.get(
                "title",
                "N/A"
            )
        )

        print(
            "Entries:",
            len(feed.entries)
        )


        # --------------------------------------------------
        # Show first 5
        # --------------------------------------------------

        for index, item in enumerate(
            feed.entries[:5],
            start=1
        ):

            print()
            print(
                f"[{index}]"
            )

            print(
                "Title:",
                item.get(
                    "title",
                    ""
                )
            )

            print(
                "Published:",
                item.get(
                    "published",
                    item.get(
                        "updated",
                        ""
                    )
                )
            )

            print(
                "Link:",
                item.get(
                    "link",
                    ""
                )
            )

            description = item.get(
                "description",
                item.get(
                    "summary",
                    ""
                )
            )

            if description:

                print(
                    "Description:",
                    description[:500]
                )


        # --------------------------------------------------
        # Feed parser errors
        # --------------------------------------------------

        if feed.bozo:

            print()
            print(
                "Parser Warning:"
            )

            print(
                feed.bozo_exception
            )


    except Exception as exc:

        print()
        print(
            "ERROR:",
            repr(exc)
        )


def main():

    print("=" * 90)
    print("NSE / BSE RSS FEED VERIFICATION")
    print("=" * 90)

    for name, url in FEEDS.items():

        test_feed(
            name,
            url
        )


if __name__ == "__main__":

    main()