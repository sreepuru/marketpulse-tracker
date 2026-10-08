import fitz
import pytesseract
from pathlib import Path


# ==========================================================
# TESSERACT
# ==========================================================

pytesseract.pytesseract.tesseract_cmd = (
    r"D:\deepseek\Trading_agent\Tesseract-OCR\tesseract.exe"
)


# ==========================================================
# FILES
# ==========================================================

PDF_FILES = [

    Path(
        "data/attachments/BSE/ANNOUNCEMENTS/"
        "9f8571498d027dcaf85464cd64782b7e4cda8e917e80a71b5086aadbdcccd6e9.pdf"
    ),

    Path(
        "data/attachments/BSE/ANNOUNCEMENTS/"
        "ac850aa74181a13b49af83e7bf69275f2a94f2e52309f8b561efea1722cb2768.pdf"
    )
]


OUTPUT_DIR = Path(
    "data/ocr-verification"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ==========================================================
# OCR
# ==========================================================

def ocr_pdf(pdf_path):

    print()
    print("=" * 80)
    print("PDF:")
    print(pdf_path.name)
    print("=" * 80)

    document = fitz.open(
        pdf_path
    )

    print(
        "Pages:",
        len(document)
    )

    all_text = []

    for page_number, page in enumerate(
        document,
        start=1
    ):

        print(
            f"OCR page {page_number}..."
        )

        # Render page at 200 DPI
        matrix = fitz.Matrix(
            200 / 72,
            200 / 72
        )

        pixmap = page.get_pixmap(
            matrix=matrix,
            alpha=False
        )

        image = pixmap.tobytes(
            "png"
        )

        text = pytesseract.image_to_string(
            image,
            lang="eng"
        )

        all_text.append(
            text
        )

    document.close()

    final_text = "\n".join(
        all_text
    ).strip()

    output_file = (
        OUTPUT_DIR
        / f"{pdf_path.stem}.txt"
    )

    output_file.write_text(
        final_text,
        encoding="utf-8"
    )

    print()
    print(
        "OCR characters:",
        len(final_text)
    )

    print()
    print("TEXT PREVIEW")
    print("-" * 60)

    print(
        final_text[:2000]
    )

    print()
    print(
        "Saved:",
        output_file
    )


# ==========================================================
# MAIN
# ==========================================================

def main():

    print("=" * 80)
    print("OCR FALLBACK VERIFICATION")
    print("=" * 80)

    for pdf_file in PDF_FILES:

        if not pdf_file.exists():

            print()
            print(
                "FILE NOT FOUND:"
            )

            print(
                pdf_file
            )

            continue

        try:

            ocr_pdf(
                pdf_file
            )

        except Exception as exc:

            print()
            print(
                "OCR ERROR:"
            )

            print(
                repr(exc)
            )


    print()
    print("=" * 80)
    print("OCR VERIFICATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":

    main()