import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


PAGES = {
    "NSE": "https://www.nseindia.com/static/rss-feed",
    "BSE": "https://beta.bseindia.com/rss-feed.html",
}


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
}


def extract_feed_links(name, page_url):

    print()
    print("=" * 80)
    print(name)
    print("=" * 80)

    try:

        response = requests.get(
            page_url,
            headers=HEADERS,
            timeout=30
        )

        print(
            "HTTP:",
            response.status_code
        )

        soup = BeautifulSoup(
            response.content,
            "html.parser"
        )

        links = []

        # --------------------------------------------------
        # NORMAL LINKS
        # --------------------------------------------------

        for tag in soup.find_all("a"):

            href = tag.get("href")

            if not href:
                continue

            absolute_url = urljoin(
                page_url,
                href
            )

            text = tag.get_text(
                " ",
                strip=True
            )

            value = (
                absolute_url.lower()
                + " "
                + text.lower()
            )

            if (
                "rss" in value
                or ".xml" in value
                or "feed" in value
                or "atom" in value
            ):

                links.append(
                    (
                        text,
                        absolute_url
                    )
                )

        # --------------------------------------------------
        # LINK TAGS
        # --------------------------------------------------

        for tag in soup.find_all("link"):

            href = tag.get("href")

            if not href:
                continue

            absolute_url = urljoin(
                page_url,
                href
            )

            rel = " ".join(
                tag.get("rel", [])
            )

            type_value = tag.get(
                "type",
                ""
            )

            value = (
                absolute_url.lower()
                + " "
                + rel.lower()
                + " "
                + type_value.lower()
            )

            if (
                "rss" in value
                or "xml" in value
                or "atom" in value
                or "feed" in value
            ):

                links.append(
                    (
                        rel,
                        absolute_url
                    )
                )

        # --------------------------------------------------
        # UNIQUE
        # --------------------------------------------------

        unique = {}

        for text, url in links:

            unique[url] = text

        print()
        print(
            "Possible feed URLs:",
            len(unique)
        )

        if not unique:

            print(
                "No feed URLs found in static HTML."
            )

        else:

            for url, text in unique.items():

                print()
                print(
                    "Label:",
                    text
                )

                print(
                    "URL:",
                    url
                )

    except Exception as exc:

        print()
        print(
            "ERROR:",
            repr(exc)
        )


def main():

    print("=" * 80)
    print("BSE / NSE RSS URL DISCOVERY")
    print("=" * 80)

    for name, url in PAGES.items():

        extract_feed_links(
            name,
            url
        )


if __name__ == "__main__":
    main()