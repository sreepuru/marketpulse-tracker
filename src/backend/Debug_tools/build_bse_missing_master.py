from pathlib import Path
from collections import Counter
from datetime import datetime
import csv


PROJECT_ROOT = Path(__file__).resolve().parents[3]

BSE_RAW_DIR = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "bse"
    / "raw"
)

BSE_UNMATCHED_DIR = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "bse"
    / "unmatched"
)

OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "bse"
    / "master_candidates"
)

OUTPUT_FILE = (
    OUTPUT_DIR
    / "BSE_missing_master_candidates.csv"
)


def clean(value):
    if value is None:
        return ""

    return str(value).strip()


def classify_asset(row):
    """
    Conservative classification.

    The historical BSE CM/STK files are already restricted
    to cash-market stock instruments, but we retain the
    classification logic so that the candidate master is
    explicit and reviewable.
    """

    fin_instrm_tp = clean(
        row.get("FinInstrmTp")
    ).upper()

    series = clean(
        row.get("SctySrs")
    ).upper()

    name = clean(
        row.get("FinInstrmNm")
    ).upper()

    # Explicit instrument type
    if fin_instrm_tp == "STK":
        # BSE equity groups / series.
        equity_series = {
            "A",
            "B",
            "X",
            "XT",
            "T",
            "Z",
            "M",
            "MT",
            "MS",
            "P",
            "Q",
            "R",
            "S",
            "E",
            "F",
            "G",
            "H",
            "I",
            "J",
            "K",
            "L",
            "N",
            "O",
            "U",
            "V",
            "W",
            "Y",
        }

        if series in equity_series:
            return "EQUITY"

        # Known ETF / fund naming indicators.
        if (
            "ETF" in name
            or "EXCHANGE TRADED FUND" in name
        ):
            return "ETF"

        # Conservative fallback for STK.
        return "EQUITY"

    # Defensive handling if future BSE files contain
    # additional instrument types.
    if fin_instrm_tp in {
        "ETF",
        "ETP",
    }:
        return "ETF"

    if fin_instrm_tp in {
        "MF",
        "MUTUAL",
    }:
        return "MUTUAL_FUND"

    if fin_instrm_tp in {
        "BOND",
        "DEBT",
        "DBT",
    }:
        return "BOND"

    return "OTHER"


def get_unmatched_isins():
    """
    Read all unmatched reports and return the unique ISIN set.
    """

    isins = set()

    files = sorted(
        BSE_UNMATCHED_DIR.glob(
            "BSE_unmatched_*.csv"
        )
    )

    for file in files:
        with file.open(
            "r",
            encoding="utf-8",
            newline="",
        ) as f:

            reader = csv.DictReader(f)

            for row in reader:
                isin = clean(
                    row.get("isin")
                ).upper()

                if isin:
                    isins.add(isin)

    return isins


def process_raw_files(target_isins):
    """
    Scan the downloaded BSE BhavCopy files and collect
    the best/latest metadata for each unmatched ISIN.
    """

    candidates = {}

    occurrence_count = Counter()
    first_seen = {}
    last_seen = {}

    files = sorted(
        BSE_RAW_DIR.glob(
            "BhavCopy_BSE_CM_0_0_0_*_F_0000.CSV"
        )
    )

    print(
        f"Raw BSE files found: {len(files):,}"
    )

    for file in files:

        try:
            with file.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as f:

                reader = csv.DictReader(f)

                for row in reader:

                    segment = clean(
                        row.get("Sgmt")
                    ).upper()

                    source = clean(
                        row.get("Src")
                    ).upper()

                    instrument_type = clean(
                        row.get("FinInstrmTp")
                    ).upper()

                    if segment != "CM":
                        continue

                    if source != "BSE":
                        continue

                    if instrument_type != "STK":
                        continue

                    isin = clean(
                        row.get("ISIN")
                    ).upper()

                    if not isin:
                        continue

                    if isin not in target_isins:
                        continue

                    trade_date = clean(
                        row.get("TradDt")
                    )

                    occurrence_count[isin] += 1

                    if (
                        isin not in first_seen
                        or trade_date < first_seen[isin]
                    ):
                        first_seen[isin] = trade_date

                    if (
                        isin not in last_seen
                        or trade_date > last_seen[isin]
                    ):
                        last_seen[isin] = trade_date

                    # Keep the latest available metadata.
                    candidates[isin] = {
                        "isin": isin,
                        "bse_fin_instrm_id": clean(
                            row.get("FinInstrmId")
                        ),
                        "symbol": clean(
                            row.get("TckrSymb")
                        ),
                        "series": clean(
                            row.get("SctySrs")
                        ),
                        "instrument_type": clean(
                            row.get("FinInstrmTp")
                        ),
                        "instrument_name": clean(
                            row.get("FinInstrmNm")
                        ),
                    }

        except Exception as exc:
            print(
                f"ERROR reading {file.name}: {exc}"
            )

    return (
        candidates,
        occurrence_count,
        first_seen,
        last_seen,
    )


def main():

    print("=" * 72)
    print("BSE MISSING SECURITY MASTER CANDIDATES")
    print("=" * 72)

    target_isins = get_unmatched_isins()

    print(
        f"Unique unmatched ISINs : "
        f"{len(target_isins):,}"
    )

    (
        candidates,
        occurrence_count,
        first_seen,
        last_seen,
    ) = process_raw_files(target_isins)

    print(
        f"Candidates recovered    : "
        f"{len(candidates):,}"
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    fieldnames = [
        "isin",
        "bse_fin_instrm_id",
        "symbol",
        "series",
        "instrument_type",
        "instrument_name",
        "asset_category",
        "first_seen_date",
        "last_seen_date",
        "occurrences",
    ]

    category_counts = Counter()

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for isin in sorted(candidates):

            row = candidates[isin]

            category = classify_asset(row)

            category_counts[category] += 1

            writer.writerow(
                {
                    "isin": isin,
                    "bse_fin_instrm_id":
                        row["bse_fin_instrm_id"],
                    "symbol":
                        row["symbol"],
                    "series":
                        row["series"],
                    "instrument_type":
                        row["instrument_type"],
                    "instrument_name":
                        row["instrument_name"],
                    "asset_category":
                        category,
                    "first_seen_date":
                        first_seen.get(isin, ""),
                    "last_seen_date":
                        last_seen.get(isin, ""),
                    "occurrences":
                        occurrence_count.get(
                            isin,
                            0,
                        ),
                }
            )

    print()
    print("Asset category")
    print("-" * 72)

    for category, count in sorted(
        category_counts.items()
    ):
        print(
            f"{category:<20} : {count:>8,}"
        )

    print()
    print(
        f"Candidate file:"
    )
    print(OUTPUT_FILE)

    print("=" * 72)
    print("NO DATABASE CHANGES WERE MADE")
    print("=" * 72)


if __name__ == "__main__":
    main()