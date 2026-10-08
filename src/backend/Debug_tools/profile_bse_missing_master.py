from pathlib import Path
from collections import Counter
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


# ------------------------------------------------------------
# 1. Get unique unmatched ISINs
# ------------------------------------------------------------

unmatched_isins = set()

for file in UNMATCHED_DIR.glob("BSE_unmatched_*.csv"):

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
print("BSE MISSING MASTER FIELD PROFILE")
print("=" * 72)

print(
    f"Unique unmatched ISINs : {len(unmatched_isins):,}"
)


# ------------------------------------------------------------
# 2. Profile actual BSE fields
# ------------------------------------------------------------

instrument_types = Counter()
series = Counter()
symbols = Counter()
names = Counter()

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

                instrument_type = clean(
                    row.get("FinInstrmTp")
                )

                security_series = clean(
                    row.get("SctySrs")
                )

                symbol = clean(
                    row.get("TckrSymb")
                )

                name = str(
                    row.get("FinInstrmNm") or ""
                ).strip()

                instrument_types[instrument_type] += 1
                series[security_series] += 1

                if symbol:
                    symbols[symbol] += 1

                if name:
                    names[name] += 1

                # Keep one representative row
                if isin not in records:
                    records[isin] = {
                        "isin": isin,
                        "FinInstrmId":
                            row.get("FinInstrmId"),
                        "TckrSymb":
                            row.get("TckrSymb"),
                        "SctySrs":
                            row.get("SctySrs"),
                        "FinInstrmTp":
                            row.get("FinInstrmTp"),
                        "FinInstrmNm":
                            row.get("FinInstrmNm"),
                    }

    except Exception as exc:

        print(
            f"ERROR: {file.name}: {exc}"
        )


# ------------------------------------------------------------
# 3. Print profile
# ------------------------------------------------------------

print()
print("FinInstrmTp")
print("-" * 72)

for value, count in instrument_types.most_common():

    print(
        f"{value or '<BLANK>':<20} "
        f"{count:>10,}"
    )


print()
print("SctySrs")
print("-" * 72)

for value, count in series.most_common():

    print(
        f"{value or '<BLANK>':<20} "
        f"{count:>10,}"
    )


print()
print("Unique symbols")
print("-" * 72)

print(
    f"{len(symbols):,}"
)


print()
print("Unique instrument names")
print("-" * 72)

print(
    f"{len(names):,}"
)


# ------------------------------------------------------------
# 4. Representative records
# ------------------------------------------------------------

print()
print("Representative unmatched securities")
print("-" * 72)

for isin in sorted(records)[:100]:

    row = records[isin]

    print(
        f"{row['isin']:<16} | "
        f"{str(row['FinInstrmId']):<12} | "
        f"{str(row['TckrSymb']):<15} | "
        f"{str(row['SctySrs']):<8} | "
        f"{str(row['FinInstrmTp']):<8} | "
        f"{str(row['FinInstrmNm'])[:60]}"
    )


print()
print("=" * 72)
print(
    f"Records profiled: {len(records):,}"
)
print("=" * 72)