import json
from pathlib import Path

import pandas as pd


# ==========================================================
# Paths
# ==========================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CORPORATE_ACTIONS_FILE = (
    PROJECT_ROOT
    / "public"
    / "corporate-actions.json"
)

PRICE_HISTORY_FILE = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "processed"
    / "price-history.csv"
)


# ==========================================================
# Load Corporate Actions
# ==========================================================

def load_corporate_actions():

    with open(
        CORPORATE_ACTIONS_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        json_data = json.load(file)

    return pd.DataFrame(
        json_data.get("data", [])
    )


# ==========================================================
# Load Bhavcopy
# ==========================================================

def load_price_history():

    return pd.read_csv(
        PRICE_HISTORY_FILE
    )


# ==========================================================
# Main
# ==========================================================

def main():

    print()
    print("=" * 70)
    print("MarketPulse - ISIN + Symbol Join Test")
    print("=" * 70)

    ca = load_corporate_actions()
    price = load_price_history()

    print()
    print(
        "Corporate action records:",
        len(ca)
    )

    print(
        "Price history records:",
        len(price)
    )

    # ------------------------------------------------------
    # Normalize identifiers
    # ------------------------------------------------------

    ca["join_isin"] = (
        ca["isin"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    ca["join_symbol"] = (
        ca["symbol"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    price["join_isin"] = (
        price["isin"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    price["join_symbol"] = (
        price["symbol"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    # ------------------------------------------------------
    # Identify actual ISINs
    # ------------------------------------------------------

    ca["is_real_isin"] = (
        ca["join_isin"].str.startswith("IN")
        & (ca["join_isin"].str.len() == 12)
    )

    print()
    print(
        "Corporate actions with actual ISIN:",
        ca["is_real_isin"].sum()
    )

    print(
        "Corporate actions with non-ISIN identifier:",
        (~ca["is_real_isin"]).sum()
    )

    # ------------------------------------------------------
    # PASS 1 — ISIN match
    # ------------------------------------------------------

    price_isins = set(
        price["join_isin"]
    )

    ca["matched_by_isin"] = (
        ca["is_real_isin"]
        & ca["join_isin"].isin(price_isins)
    )

    # ------------------------------------------------------
    # PASS 2 — Symbol fallback
    # ------------------------------------------------------

    price_symbols = set(
        price["join_symbol"]
    )

    ca["matched_by_symbol"] = (
        ~ca["matched_by_isin"]
        & ca["join_symbol"].isin(price_symbols)
    )

    # ------------------------------------------------------
    # Final match
    # ------------------------------------------------------

    ca["matched"] = (
        ca["matched_by_isin"]
        | ca["matched_by_symbol"]
    )

    # ------------------------------------------------------
    # Statistics
    # ------------------------------------------------------

    matched_isin = ca[
        ca["matched_by_isin"]
    ]

    matched_symbol = ca[
        ca["matched_by_symbol"]
    ]

    unmatched = ca[
        ~ca["matched"]
    ]

    print()
    print("=" * 70)
    print("MATCH RESULTS")
    print("=" * 70)

    print()
    print(
        "Total corporate actions:",
        len(ca)
    )

    print(
        "Matched by ISIN:",
        len(matched_isin)
    )

    print(
        "Matched by Symbol:",
        len(matched_symbol)
    )

    print(
        "Still unmatched:",
        len(unmatched)
    )

    print()

    match_percentage = (
        ca["matched"].sum()
        / len(ca)
        * 100
    )

    print(
        "Overall match percentage:",
        round(
            match_percentage,
            2
        ),
        "%"
    )

    # ------------------------------------------------------
    # Detailed matched records
    # ------------------------------------------------------

    print()
    print("=" * 70)
    print("MATCHED RECORDS")
    print("=" * 70)

    matched_output = ca[
        ca["matched"]
    ][
        [
            "isin",
            "symbol",
            "subject",
            "exDate",
            "matched_by_isin",
            "matched_by_symbol"
        ]
    ]

    print(
        matched_output
        .to_string(index=False)
    )

    # ------------------------------------------------------
    # Unmatched records
    # ------------------------------------------------------

    if len(unmatched) > 0:

        print()
        print("=" * 70)
        print("UNMATCHED RECORDS")
        print("=" * 70)

        print(
            unmatched[
                [
                    "isin",
                    "symbol",
                    "subject",
                    "exDate"
                ]
            ]
            .to_string(index=False)
        )

    # ------------------------------------------------------
    # Resolve symbol → ISIN for symbol matches
    # ------------------------------------------------------

    if len(matched_symbol) > 0:

        print()
        print("=" * 70)
        print("SYMBOL → ISIN RESOLUTION")
        print("=" * 70)

        symbol_mapping = (
            price[
                [
                    "join_symbol",
                    "join_isin",
                    "series",
                    "instrument_name"
                ]
            ]
            .drop_duplicates(
                subset=["join_symbol"]
            )
        )

        resolved = matched_symbol.merge(
            symbol_mapping,
            left_on="join_symbol",
            right_on="join_symbol",
            how="left"
        )

        print(
            resolved[
                [
                    "symbol",
                    "isin",
                    "join_isin",
                    "series",
                    "instrument_name"
                ]
            ]
            .to_string(index=False)
        )

    print()
    print("=" * 70)
    print("TEST COMPLETED")
    print("=" * 70)


# ==========================================================
# Start
# ==========================================================

if __name__ == "__main__":
    main()