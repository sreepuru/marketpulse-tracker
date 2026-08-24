import json
from pathlib import Path
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]

CA_FILE = (
    PROJECT_ROOT
    / "public"
    / "corporate-actions.json"
)

PRICE_FILE = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "processed"
    / "price-history.csv"
)


def main():

    with open(
        CA_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        ca_json = json.load(f)

    ca = pd.DataFrame(
        ca_json["data"]
    )

    price = pd.read_csv(
        PRICE_FILE
    )

    # Corporate-action records whose "isin"
    # is NOT actually an ISIN
    unmatched_identifier = ca[
        ~ca["isin"]
        .astype(str)
        .str.upper()
        .str.startswith("INE")
    ].copy()

    print()
    print("=" * 70)
    print("SME IDENTIFIER → FININSTRMID TEST")
    print("=" * 70)

    print()
    print("Corporate action non-ISIN records:")
    print(
        unmatched_identifier[
            ["isin", "symbol", "subject", "exDate"]
        ]
        .to_string(index=False)
    )

    # Convert FININSTRMID to string
    price["FININSTRMID_TEST"] = (
        price["isin"]
        .astype(str)
        .str.strip()
    )

    # We don't have FININSTRMID in processed CSV,
    # so load the original Bhavcopy as well.

    raw_files = list(
        (
            PROJECT_ROOT
            / "data"
            / "bhavcopy"
            / "extracted"
        ).rglob("*.csv")
    )

    raw_file = max(
        raw_files,
        key=lambda x: x.stat().st_mtime
    )

    raw = pd.read_csv(
        raw_file
    )

    raw.columns = [
        str(c).strip().upper()
        for c in raw.columns
    ]

    raw["FININSTRMID"] = (
        raw["FININSTRMID"]
        .astype(str)
        .str.replace(
            ".0",
            "",
            regex=False
        )
        .str.strip()
    )

    # Only target EQ / SM / BE
    raw = raw[
        raw["SCTYSRS"].isin(
            ["EQ", "SM", "BE"]
        )
    ]

    # Test mapping
    merged = unmatched_identifier.merge(
        raw[
            [
                "FININSTRMID",
                "TCKRSYMB",
                "ISIN",
                "SCTYSRS",
                "FININSTRMNM"
            ]
        ],
        left_on="isin",
        right_on="FININSTRMID",
        how="left"
    )

    print()
    print("=" * 70)
    print("RESULT")
    print("=" * 70)

    print()

    print(
        merged[
            [
                "isin",
                "symbol",
                "TCKRSYMB",
                "ISIN",
                "SCTYSRS",
                "FININSTRMNM"
            ]
        ]
        .to_string(index=False)
    )

    matched = merged[
        merged["TCKRSYMB"].notna()
    ]

    print()
    print(
        "Matched through FININSTRMID:",
        len(matched)
    )

    print(
        "Total non-ISIN corporate actions:",
        len(unmatched_identifier)
    )


if __name__ == "__main__":
    main()