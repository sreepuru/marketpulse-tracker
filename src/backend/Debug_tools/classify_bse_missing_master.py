from pathlib import Path
from collections import Counter, defaultdict
import csv


PROJECT_ROOT = Path(__file__).resolve().parents[3]

UNMATCHED_DIR = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "bse"
    / "unmatched"
)

RAW_DIR = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "bse"
    / "raw"
)


def clean(value):
    return str(value or "").strip().upper()


def classify(row):
    series = clean(row.get("SctySrs"))
    symbol = clean(row.get("TckrSymb"))
    name = clean(row.get("FinInstrmNm"))
    isin = clean(row.get("ISIN"))

    # ---------------------------------------------------------
    # Government / debt instruments
    # ---------------------------------------------------------

    if series in {"F", "G"}:
        return "BOND"

    # P in this unmatched universe contains instruments such as
    # 73GS2053P / GSEC...P and is therefore treated as debt.
    if series == "P":

        if isin.startswith("IN00"):
            return "BOND"

        if isin.startswith("INE"):
            return "EQUITY"

        return "REVIEW"

    # ---------------------------------------------------------
    # Equity groups
    # ---------------------------------------------------------

    if series in {
        "A",
        "B",
        "M",
        "MT",
        "MS",
        "R",
        "T",
        "TS",
        "W",
        "X",
        "XT",
        "Z",
        "ZP",
    }:
        return "EQUITY"

    # ---------------------------------------------------------
    # IF requires explicit review
    # ---------------------------------------------------------

    if series == "IF":
        other_investment_isins = {
            "INE0JEI23010",  # ROADSTAR
            "INE0QSW23016",  # ISCITRUST
            "INE0M5S23019",  # MAPLE INFRASTRUCTURE TRUST
            "INE0MIZ23019",  # ANZEN INDIA ENERGY YIELD PLUS
        }

        if isin in other_investment_isins:
            return "OTHER_INVESTMENT"

        return "REVIEW"


# -------------------------------------------------------------
# Step 1: Get unique unmatched ISINs
# -------------------------------------------------------------

unmatched_isins = set()

for file in UNMATCHED_DIR.glob(
    "BSE_unmatched_*.csv"
):
    with file.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:
            isin = clean(row.get("isin"))

            if isin:
                unmatched_isins.add(isin)


print("=" * 72)
print("BSE MISSING MASTER CLASSIFICATION")
print("=" * 72)

print(
    f"Unique unmatched ISINs : "
    f"{len(unmatched_isins):,}"
)


# -------------------------------------------------------------
# Step 2: Build one representative row per ISIN
# -------------------------------------------------------------

records = {}

for file in RAW_DIR.glob(
    "BhavCopy_BSE_CM_0_0_0_*_F_0000.CSV"
):

    try:

        with file.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as f:

            reader = csv.DictReader(f)

            for row in reader:

                isin = clean(row.get("ISIN"))

                if isin not in unmatched_isins:
                    continue

                if isin not in records:
                    records[isin] = row

    except Exception as exc:
        print(
            f"ERROR: {file.name}: {exc}"
        )


# -------------------------------------------------------------
# Step 3: Count unique ISINs by series/category
# -------------------------------------------------------------

series_isins = defaultdict(set)
category_isins = defaultdict(set)

for isin, row in records.items():

    series = clean(
        row.get("SctySrs")
    )

    category = classify(row)

    series_isins[series].add(isin)
    category_isins[category].add(isin)


print()
print("UNIQUE ISINs BY BSE SERIES")
print("-" * 72)

for series in sorted(series_isins):

    print(
        f"{series or '<BLANK>':<10}"
        f"{len(series_isins[series]):>10,}"
    )


print()
print("PROPOSED ASSET CATEGORY")
print("-" * 72)

for category in sorted(category_isins):

    print(
        f"{category:<20}"
        f"{len(category_isins[category]):>10,}"
    )


# -------------------------------------------------------------
# Step 4: Show review records
# -------------------------------------------------------------

review_isins = category_isins.get(
    "REVIEW",
    set(),
)

print()
print(
    f"ISINs requiring review : "
    f"{len(review_isins):,}"
)

if review_isins:

    print()
    print("Review examples")
    print("-" * 72)

    for isin in sorted(review_isins)[:50]:

        row = records[isin]

        print(
            f"{isin:<16} | "
            f"Series={clean(row.get('SctySrs')):<5} | "
            f"Symbol={clean(row.get('TckrSymb')):<15} | "
            f"Name={clean(row.get('FinInstrmNm'))[:60]}"
        )


# -------------------------------------------------------------
# Step 5: Generate candidate classification CSV
# -------------------------------------------------------------

output_dir = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "bse"
    / "master_candidates"
)

output_dir.mkdir(
    parents=True,
    exist_ok=True,
)

output_file = (
    output_dir
    / "BSE_missing_master_final.csv"
)

fieldnames = [
    "isin",
    "bse_fin_instrm_id",
    "symbol",
    "series",
    "instrument_type",
    "instrument_name",
    "asset_category",
]

with output_file.open(
    "w",
    encoding="utf-8",
    newline="",
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fieldnames,
    )

    writer.writeheader()

    for isin in sorted(records):

        row = records[isin]

        writer.writerow(
            {
                "isin": isin,
                "bse_fin_instrm_id":
                    clean(row.get("FinInstrmId")),
                "symbol":
                    clean(row.get("TckrSymb")),
                "series":
                    clean(row.get("SctySrs")),
                "instrument_type":
                    clean(row.get("FinInstrmTp")),
                "instrument_name":
                    str(
                        row.get("FinInstrmNm") or ""
                    ).strip(),
                "asset_category":
                    classify(row),
            }
        )


print()
print("=" * 72)
print("CANDIDATE FILE")
print("=" * 72)

print(output_file)

print()
print("NO DATABASE CHANGES WERE MADE")
print("=" * 72)