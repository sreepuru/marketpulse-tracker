import json
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]

CA_FILE = (
    PROJECT_ROOT
    / "public"
    / "corporate-actions.json"
)

EXTRACT_FOLDER = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "extracted"
)


def main():

    # ------------------------------------------------------
    # Load Corporate Actions
    # ------------------------------------------------------

    with open(
        CA_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        ca = pd.DataFrame(
            json.load(file)["data"]
        )

    # ------------------------------------------------------
    # Load latest raw Bhavcopy
    # ------------------------------------------------------

    files = list(
        EXTRACT_FOLDER.rglob("*.csv")
    )

    raw_file = max(
        files,
        key=lambda x: x.stat().st_mtime
    )

    bhav = pd.read_csv(
        raw_file
    )

    bhav.columns = [
        str(c).strip().upper()
        for c in bhav.columns
    ]

    # ------------------------------------------------------
    # The four unmatched records
    # ------------------------------------------------------

    symbols = [
        "INDUSINVIT",
        "DCCL",
        "MAHICKRA",
        "PHOGLOBAL"
    ]

    print()
    print("=" * 80)
    print("MARKETPULSE - UNMATCHED SECURITY INVESTIGATION")
    print("=" * 80)

    print()
    print(
        "Bhavcopy:",
        raw_file
    )

    for symbol in symbols:

        print()
        print("-" * 80)
        print(
            "SEARCHING:",
            symbol
        )
        print("-" * 80)

        result = bhav[
            bhav["TCKRSYMB"]
            .astype(str)
            .str.strip()
            .str.upper()
            == symbol
        ]

        if result.empty:

            print(
                "NOT FOUND in 07-Aug-2026 Bhavcopy"
            )

            continue

        print(
            "FOUND:",
            len(result),
            "record(s)"
        )

        columns = [
            "TCKRSYMB",
            "ISIN",
            "SCTYSRS",
            "FININSTRMID",
            "FININSTRMNM",
            "OPNPRIC",
            "HGHPRIC",
            "LWPRIC",
            "CLSPRIC"
        ]

        print(
            result[columns]
            .to_string(index=False)
        )

    print()
    print("=" * 80)
    print("INVESTIGATION COMPLETED")
    print("=" * 80)


if __name__ == "__main__":
    main()