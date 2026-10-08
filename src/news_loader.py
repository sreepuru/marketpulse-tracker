import json
import re
from datetime import datetime
from pathlib import Path

import psycopg2


# ==========================================================
# CONFIGURATION
# ==========================================================

INPUT_FILE = Path(
    "data/news-collection.json"
)


DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 5432,
    "database": "marketpulse",
    "user": "postgres",
    "password": "admin"
}


# ==========================================================
# HELPERS
# ==========================================================

def clean_text(value):

    if value is None:
        return None

    if not isinstance(value, str):
        value = str(value)

    value = value.strip()

    return value if value else None


def parse_published(value):

    if not value:
        return None

    value = value.strip()

    formats = [
        "%d-%b-%Y %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
    ]

    for fmt in formats:

        try:

            parsed = datetime.strptime(
                value,
                fmt
            )

            # Convert timezone-aware datetime
            # to naive datetime for PostgreSQL
            if parsed.tzinfo:

                parsed = parsed.replace(
                    tzinfo=None
                )

            return parsed

        except ValueError:
            continue

    return None


def extract_bse_scrip_code(title):

    if not title:
        return None

    match = re.search(
        r"\((\d{5,6})\)",
        title
    )

    if match:

        return match.group(1)

    return None


def extract_nse_symbol(
    title,
    description
):

    text = " ".join(
        value
        for value in [
            title,
            description
        ]
        if value
    )

    # Many NSE announcements use:
    #
    # SYMBOL : Company Name
    #
    match = re.search(
        r"^\s*([A-Z0-9&.-]{2,30})\s*:",
        text
    )

    if match:

        return match.group(1).strip()

    return None


def extract_company_name(
    exchange,
    title,
    description
):

    if exchange == "BSE":

        if title:

            # Example:
            # Zee Entertainment Enterprises Ltd (505537)

            match = re.match(
                r"^(.*?)\s*\(\d{5,6}\)",
                title
            )

            if match:

                return clean_text(
                    match.group(1)
                )


    if exchange == "NSE":

        if description:

            # Example:
            # LICMFGOLD : LIC Mutual Fund Asset Management Limited ...

            match = re.match(
                r"^\s*([A-Z0-9&.-]{2,30})\s*:\s*(.+?)\s+has informed",
                description,
                re.IGNORECASE
            )

            if match:

                return clean_text(
                    match.group(2)
                )


    return clean_text(title)


# ==========================================================
# DATABASE CONNECTION
# ==========================================================

def get_connection():

    return psycopg2.connect(
        **DB_CONFIG
    )


# ==========================================================
# INSERT NEWS
# ==========================================================

def insert_news(
    cursor,
    record
):

    exchange = clean_text(
        record.get("exchange")
    )

    category = clean_text(
        record.get("category")
    )

    title = clean_text(
        record.get("title")
    )

    description = clean_text(
        record.get("description")
    )

    source_url = clean_text(
        record.get("source_url")
    )

    published_at = parse_published(
        record.get("published")
    )


    # ------------------------------------------------------
    # SYMBOL / SCRIP CODE
    # ------------------------------------------------------

    symbol = None

    if exchange == "NSE":

        symbol = extract_nse_symbol(
            title,
            description
        )

    elif exchange == "BSE":

        # We don't have a BSE security master yet.
        # Therefore do NOT put the scrip code into
        # the symbol field.
        #
        # It remains NULL until BSE security mapping
        # is implemented.

        symbol = None


    # ------------------------------------------------------
    # COMPANY
    # ------------------------------------------------------

    company_name = extract_company_name(
        exchange,
        title,
        description
    )


    # ------------------------------------------------------
    # EXTERNAL ID
    # ------------------------------------------------------

    external_id = (
        f"{exchange}|"
        f"{category}|"
        f"{record.get('feed_index')}"
    )


    # ------------------------------------------------------
    # INSERT
    # ------------------------------------------------------

    cursor.execute(
        """
        INSERT INTO market_news (
            exchange,
            symbol,
            security_id,
            company_name,
            category,
            title,
            description,
            published_at,
            source_url,
            external_id
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        )
        RETURNING news_id
        """,
        (
            exchange,
            symbol,
            None,
            company_name,
            category,
            title,
            description,
            published_at,
            source_url,
            external_id
        )
    )


    result = cursor.fetchone()

    return result[0]


# ==========================================================
# MAIN LOADER
# ==========================================================

def load_news():

    print("=" * 80)
    print("NEWS DATABASE LOADER")
    print("=" * 80)

    print()
    print(
        "Input:",
        INPUT_FILE
    )


    # ------------------------------------------------------
    # LOAD JSON
    # ------------------------------------------------------

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        data = json.load(file)


    # ------------------------------------------------------
    # CONNECT
    # ------------------------------------------------------

    connection = get_connection()

    cursor = connection.cursor()


    counts = {}

    total_inserted = 0


    try:

        # --------------------------------------------------
        # INSERT EVERYTHING
        # --------------------------------------------------

        for exchange, feeds in data[
            "exchanges"
        ].items():

            counts[
                exchange
            ] = {}


            for category, feed_data in feeds.items():

                records = feed_data.get(
                    "records",
                    []
                )


                inserted = 0


                for record in records:

                    insert_news(
                        cursor,
                        record
                    )

                    inserted += 1

                    total_inserted += 1


                counts[
                    exchange
                ][category] = inserted


        # --------------------------------------------------
        # COMMIT
        # --------------------------------------------------

        connection.commit()


    except Exception:

        connection.rollback()

        raise


    finally:

        cursor.close()

        connection.close()


    # ======================================================
    # SUMMARY
    # ======================================================

    print()
    print("=" * 80)
    print("DATABASE LOAD SUMMARY")
    print("=" * 80)


    for exchange, categories in counts.items():

        print()
        print(exchange)

        print("-" * 50)

        for category, count in categories.items():

            print(
                f"{category:<25} {count:>6}"
            )


    print()
    print("-" * 50)

    print(
        f"{'TOTAL INSERTED':<25}"
        f"{total_inserted:>6}"
    )


    print()
    print("=" * 80)
    print("LOAD COMPLETE")
    print("=" * 80)


# ==========================================================
# ENTRY POINT
# ==========================================================

if __name__ == "__main__":

    load_news()