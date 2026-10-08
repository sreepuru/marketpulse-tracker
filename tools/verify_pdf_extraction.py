import json
import re
from pathlib import Path

import requests
import fitz


# ==========================================================
# CONFIG
# ==========================================================

INPUT_FILE = Path(
    "data/news-feed-verification.json"
)

OUTPUT_DIR = Path(
    "data/pdf-verification"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    )
}

SAMPLE_SIZE = 5


# ==========================================================
# HELPERS
# ==========================================================

def safe_filename(value):
    value = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        value
    )

    return value[:120]


def extract_pdf_text(pdf_path):

    document = fitz.open(
        pdf_path
    )

    pages = len(document)

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

    text = "\n".join(
        text_parts
    ).strip()

    return pages, text


# ==========================================================
# LOAD NEWS
# ==========================================================

print("=" * 80)
print("PDF ATTACHMENT EXTRACTION VERIFICATION")
print("=" * 80)

with open(
    INPUT_FILE,
    "r",
    encoding="utf-8"
) as file:

    data = json.load(file)


# ==========================================================
# FIND BSE PDF ATTACHMENTS
# ==========================================================

pdf_records = []

bse_data = data["exchanges"].get(
    "BSE",
    {}
)

announcements = bse_data.get(
    "ANNOUNCEMENTS",
    {}
).get(
    "records",
    []
)

for record in announcements:

    url = record.get(
        "link",
        ""
    )

    if not url:
        continue

    if ".pdf" not in url.lower():
        continue

    pdf_records.append(
        record
    )


print()
print(
    "BSE announcement records:",
    len(announcements)
)

print(
    "PDF attachments found:",
    len(pdf_records)
)


if not pdf_records:

    print()
    print(
        "No PDF attachments found."
    )

    raise SystemExit(0)


# ==========================================================
# SAMPLE
# ==========================================================

samples = pdf_records[
    :SAMPLE_SIZE
]


print()
print(
    "Testing first",
    len(samples),
    "PDF attachments"
)


results = []


# ==========================================================
# DOWNLOAD + EXTRACT
# ==========================================================

for index, record in enumerate(
    samples,
    start=1
):

    url = record.get(
        "link",
        ""
    )

    title = record.get(
        "title",
        ""
    )

    filename = (
        f"{index:02d}_"
        + safe_filename(title)
        + ".pdf"
    )

    pdf_path = (
        OUTPUT_DIR /
        filename
    )

    print()
    print("=" * 80)
    print(
        f"[{index}/{len(samples)}]"
    )
    print("=" * 80)

    print(
        "Title:",
        title
    )

    print(
        "URL:",
        url
    )

    try:

        # --------------------------------------------------
        # DOWNLOAD
        # --------------------------------------------------

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=60
        )

        print(
            "HTTP Status:",
            response.status_code
        )

        response.raise_for_status()

        pdf_path.write_bytes(
            response.content
        )

        size_kb = (
            len(response.content)
            / 1024
        )

        print(
            f"Downloaded: "
            f"{size_kb:.1f} KB"
        )


        # --------------------------------------------------
        # VERIFY PDF
        # --------------------------------------------------

        pages, text = extract_pdf_text(
            pdf_path
        )

        print(
            "Pages:",
            pages
        )

        print(
            "Extracted characters:",
            len(text)
        )


        # --------------------------------------------------
        # SAVE TEXT
        # --------------------------------------------------

        text_path = pdf_path.with_suffix(
            ".txt"
        )

        text_path.write_text(
            text,
            encoding="utf-8"
        )


        # --------------------------------------------------
        # PREVIEW
        # --------------------------------------------------

        print()
        print("TEXT PREVIEW:")
        print("-" * 60)

        if text:

            print(
                text[:1500]
            )

        else:

            print(
                "[NO TEXT EXTRACTED]"
            )


        results.append({

            "title":
                title,

            "url":
                url,

            "pdf_file":
                str(pdf_path),

            "pages":
                pages,

            "characters":
                len(text),

            "extraction_status":
                "SUCCESS"
                if text
                else "NO_TEXT"

        })


    except Exception as exc:

        print()
        print(
            "ERROR:",
            repr(exc)
        )

        results.append({

            "title":
                title,

            "url":
                url,

            "pdf_file":
                str(pdf_path),

            "extraction_status":
                "FAILED",

            "error":
                str(exc)

        })


# ==========================================================
# SAVE VERIFICATION RESULT
# ==========================================================

output_file = (
    OUTPUT_DIR /
    "verification-results.json"
)

with open(
    output_file,
    "w",
    encoding="utf-8"
) as file:

    json.dump(
        results,
        file,
        indent=2,
        ensure_ascii=False
    )


# ==========================================================
# SUMMARY
# ==========================================================

print()
print()
print("=" * 80)
print("PDF EXTRACTION SUMMARY")
print("=" * 80)

successful = sum(
    1
    for result in results
    if result.get(
        "extraction_status"
    ) == "SUCCESS"
)

no_text = sum(
    1
    for result in results
    if result.get(
        "extraction_status"
    ) == "NO_TEXT"
)

failed = sum(
    1
    for result in results
    if result.get(
        "extraction_status"
    ) == "FAILED"
)

print(
    "Tested:",
    len(results)
)

print(
    "Successful:",
    successful
)

print(
    "No text:",
    no_text
)

print(
    "Failed:",
    failed
)

print()
print(
    "Files saved to:"
)

print(
    OUTPUT_DIR
)

print()
print(
    "Verification results:"
)

print(
    output_file
)

print()
print("=" * 80)
print("VERIFICATION COMPLETE")
print("=" * 80)