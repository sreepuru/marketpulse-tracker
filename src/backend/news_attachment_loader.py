import json
import mimetypes
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

def clean(value):
    if value is None:
        return None

    if not isinstance(value, str):
        value = str(value)

    value = value.strip()

    return value if value else None


def get_mime_type(
    attachment_type
):

    mapping = {
        "PDF": "application/pdf",
        "XML": "application/xml",
    }

    return mapping.get(
        attachment_type
    )


def find_news_id(
    cursor,
    record
):

    exchange = clean(
        record.get("exchange")
    )

    category = clean(
        record.get("category")
    )

    feed_index = record.get(
        "feed_index"
    )


    # ------------------------------------------------------
    # The loader uses the same external_id created by
    # news_loader.py:
    #
    # EXCHANGE|CATEGORY|FEED_INDEX
    # ------------------------------------------------------

    external_id = (
        f"{exchange}|"
        f"{category}|"
        f"{feed_index}"
    )


    cursor.execute(
        """
        SELECT news_id
        FROM market_news
        WHERE external_id = %s
        ORDER BY news_id DESC
        LIMIT 1
        """,
        (
            external_id,
        )
    )


    row = cursor.fetchone()

    if row:

        return row[0]


    return None


# ==========================================================
# FIND / CREATE ATTACHMENT
# ==========================================================

def get_or_create_attachment(
    cursor,
    attachment
):

    sha256 = clean(
        attachment.get("sha256")
    )

    if not sha256:

        return None, False


    # ------------------------------------------------------
    # CHECK EXISTING ATTACHMENT
    # ------------------------------------------------------

    cursor.execute(
        """
        SELECT attachment_id
        FROM market_attachments
        WHERE sha256 = %s
        """,
        (
            sha256,
        )
    )


    existing = cursor.fetchone()


    if existing:

        return existing[0], False


    # ------------------------------------------------------
    # INSERT NEW ATTACHMENT
    # ------------------------------------------------------

    attachment_type = clean(
        attachment.get(
            "attachment_type"
        )
    )

    source_url = clean(
        attachment.get(
            "source_url"
        )
    )

    local_path = clean(
        attachment.get(
            "local_path"
        )
    )

    file_size = attachment.get(
        "file_size"
    )

    mime_type = get_mime_type(
        attachment_type
    )


    if attachment_type == "PDF":

        extraction_method = (
            "PYMUPDF"
        )

        extraction_status = clean(
            attachment.get(
                "extraction_status"
            )
        )

    elif attachment_type == "XML":

        extraction_method = (
            "XML"
        )

        extraction_status = (
            "NOT_PROCESSED"
        )

    else:

        extraction_method = None

        extraction_status = (
            "NOT_PROCESSED"
        )


    extracted_text_path = clean(
        attachment.get(
            "extracted_text_path"
        )
    )

    extracted_characters = attachment.get(
        "extracted_characters"
    )


    cursor.execute(
        """
        INSERT INTO market_attachments (
            attachment_type,
            source_url,
            sha256,
            file_size,
            mime_type,
            local_path,
            extraction_method,
            extraction_status,
            extracted_text_path,
            extracted_characters
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
        RETURNING attachment_id
        """,
        (
            attachment_type,
            source_url,
            sha256,
            file_size,
            mime_type,
            local_path,
            extraction_method,
            extraction_status,
            extracted_text_path,
            extracted_characters
        )
    )


    attachment_id = cursor.fetchone()[0]

    return attachment_id, True


# ==========================================================
# CREATE NEWS ↔ ATTACHMENT LINK
# ==========================================================

def create_link(
    cursor,
    news_id,
    attachment_id
):

    cursor.execute(
        """
        INSERT INTO market_news_attachments (
            news_id,
            attachment_id
        )
        VALUES (
            %s,
            %s
        )
        ON CONFLICT (
            news_id,
            attachment_id
        )
        DO NOTHING
        """,
        (
            news_id,
            attachment_id
        )
    )

    return cursor.rowcount > 0


# ==========================================================
# MAIN
# ==========================================================

def load_attachments():

    print("=" * 80)
    print("NEWS ATTACHMENT DATABASE LOADER")
    print("=" * 80)

    print()
    print(
        "Input:",
        INPUT_FILE
    )


    # ------------------------------------------------------
    # LOAD COLLECTION
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

    connection = psycopg2.connect(
        **DB_CONFIG
    )

    cursor = connection.cursor()


    # ------------------------------------------------------
    # COUNTERS
    # ------------------------------------------------------

    total_feed_records = 0

    records_with_attachments = 0

    new_attachments = 0

    reused_attachments = 0

    links_created = 0

    news_not_found = 0

    failed = 0


    try:

        # --------------------------------------------------
        # PROCESS NSE + BSE
        # --------------------------------------------------

        for exchange, feeds in data[
            "exchanges"
        ].items():

            print()
            print(
                "=" * 80
            )

            print(
                exchange
            )

            print(
                "=" * 80
            )


            for category, feed_data in feeds.items():

                records = feed_data.get(
                    "records",
                    []
                )


                category_links = 0


                for record in records:

                    total_feed_records += 1


                    attachment = record.get(
                        "attachment"
                    )


                    if not isinstance(
                        attachment,
                        dict
                    ):

                        continue


                    attachment_type = attachment.get(
                        "attachment_type"
                    )


                    if attachment_type not in [
                        "PDF",
                        "XML"
                    ]:

                        continue


                    records_with_attachments += 1


                    # --------------------------------------
                    # FIND NEWS RECORD
                    # --------------------------------------

                    news_id = find_news_id(
                        cursor,
                        record
                    )


                    if not news_id:

                        news_not_found += 1

                        print()
                        print(
                            "NEWS NOT FOUND:"
                        )

                        print(
                            exchange,
                            category,
                            record.get(
                                "feed_index"
                            ),
                            record.get(
                                "title"
                            )
                        )

                        continue


                    try:

                        # ----------------------------------
                        # GET / CREATE ATTACHMENT
                        # ----------------------------------

                        attachment_id, created = (
                            get_or_create_attachment(
                                cursor,
                                attachment
                            )
                        )


                        if created:

                            new_attachments += 1

                        else:

                            reused_attachments += 1


                        # ----------------------------------
                        # CREATE RELATIONSHIP
                        # ----------------------------------

                        linked = create_link(
                            cursor,
                            news_id,
                            attachment_id
                        )


                        if linked:

                            links_created += 1

                            category_links += 1


                    except Exception as exc:

                        failed += 1

                        print()
                        print(
                            "ATTACHMENT ERROR:"
                        )

                        print(
                            record.get(
                                "title"
                            )
                        )

                        print(
                            repr(exc)
                        )


                print(
                    f"{category:<25}"
                    f"{category_links:>6} links"
                )


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
    print()
    print("=" * 80)
    print("ATTACHMENT LOAD SUMMARY")
    print("=" * 80)

    print(
        "Total feed records:",
        total_feed_records
    )

    print(
        "Records with PDF/XML:",
        records_with_attachments
    )

    print(
        "New attachments:",
        new_attachments
    )

    print(
        "Reused attachments:",
        reused_attachments
    )

    print(
        "Links created:",
        links_created
    )

    print(
        "News records not found:",
        news_not_found
    )

    print(
        "Failed:",
        failed
    )

    print()
    print("=" * 80)
    print("LOAD COMPLETE")
    print("=" * 80)


# ==========================================================
# ENTRY POINT
# ==========================================================

if __name__ == "__main__":

    load_attachments()