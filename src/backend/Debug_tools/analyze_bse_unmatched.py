from pathlib import Path
import csv
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parents[2]

UNMATCHED_DIR = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "bse"
    / "unmatched"
)

files = sorted(
    UNMATCHED_DIR.glob("BSE_unmatched_*.csv")
)

isin_counts = Counter()
total_rows = 0

for file in files:
    with file.open(
        "r",
        encoding="utf-8",
        newline="",
    ) as f:
        reader = csv.DictReader(f)

        for row in reader:
            total_rows += 1

            isin = (
                row.get("isin") or ""
            ).strip().upper()

            if isin:
                isin_counts[isin] += 1

print("=" * 70)
print("BSE UNMATCHED ISIN ANALYSIS")
print("=" * 70)

print(f"Unmatched files       : {len(files):,}")
print(f"Unmatched rows        : {total_rows:,}")
print(f"Unique unmatched ISIN : {len(isin_counts):,}")

print()
print("Frequency distribution")
print("-" * 70)

frequency = Counter(
    isin_counts.values()
)

for occurrences, count in sorted(
    frequency.items()
):
    print(
        f"{occurrences:>6} occurrence(s) : "
        f"{count:>8,} ISINs"
    )

print()
print("Top 50 unmatched ISINs")
print("-" * 70)

for isin, count in isin_counts.most_common(50):
    print(
        f"{isin:<15} {count:>8,}"
    )