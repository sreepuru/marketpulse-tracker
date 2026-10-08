import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


URL = "https://www.bseindia.com/markets/MarketInfo/DownloadAttach.aspx"


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    )
}


def main():

    print("=" * 80)
    print("BSE SCRIP MASTER DISCOVERY")
    print("=" * 80)

    response = requests.get(
        URL,
        headers=HEADERS,
        timeout=30
    )

    print(
        "HTTP Status:",
        response.status_code
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    found = []

    for link in soup.find_all("a"):

        text = link.get_text(
            " ",
            strip=True
        )

        href = link.get(
            "href",
            ""
        )

        combined = (
            text + " " + href
        ).lower()

        if (
            "scrip" in combined
            or "security master" in combined
            or "bse_eq_scrip" in combined
        ):

            full_url = urljoin(
                URL,
                href
            )

            found.append({
                "text": text,
                "url": full_url
            })


    print()
    print(
        "Possible Scrip Master links:",
        len(found)
    )

    print()

    for item in found:

        print(
            "Label:",
            item["text"]
        )

        print(
            "URL:",
            item["url"]
        )

        print("-" * 80)


if __name__ == "__main__":
    main()