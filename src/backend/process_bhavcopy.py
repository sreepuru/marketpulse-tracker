import pandas as pd
from pathlib import Path


# ==========================================================
# Configuration
# ==========================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

EXTRACT_FOLDER = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "extracted"
)

PROCESSED_FOLDER = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "processed"
)

OUTPUT_FILE = (
    PROCESSED_FOLDER
    / "price-history.csv"
)


# ==========================================================
# Find latest CSV
# ==========================================================

def find_latest_csv():

    files = list(
        EXTRACT_FOLDER.rglob("*.csv")
    )

    if not files:

        raise FileNotFoundError(
            "No Bhavcopy CSV found."
        )

    return max(
        files,
        key=lambda file: file.stat().st_mtime
    )


# ==========================================================
# Main
# ==========================================================

def main():

    csv_file = find_latest_csv()

    print()
    print("=" * 70)
    print("MarketPulse - Bhavcopy Processor")
    print("=" * 70)

    print()
    print("Input:")
    print(csv_file)

    df = pd.read_csv(
        csv_file
    )

    df.columns = [
        str(column).strip().upper()
        for column in df.columns
    ]

    # ------------------------------------------------------
    # Keep MarketPulse equity universe
    # ------------------------------------------------------

    target_series = [
        "EQ",
        "SM",
        "BE"
    ]

    df = df[
        df["SCTYSRS"].isin(
            target_series
        )
    ].copy()

    print()
    print(
        "Rows after EQ/SM/BE filter:",
        len(df)
    )

    # ------------------------------------------------------
    # Rename fields
    # ------------------------------------------------------

    df = df.rename(
        columns={
            "TRADDT": "trade_date",
            "TCKRSYMB": "symbol",
            "SCTYSRS": "series",
            "ISIN": "isin",
            "FININSTRMNM": "instrument_name",
            "OPNPRIC": "open",
            "HGHPRIC": "high",
            "LWPRIC": "low",
            "CLSPRIC": "close",
            "LASTPRIC": "last_price",
            "PRVSCLSGPRIC": "previous_close",
            "TTLTRADGVOL": "volume",
            "TTLTRFVAL": "turnover"
        }
    )

    # ------------------------------------------------------
    # Keep required columns
    # ------------------------------------------------------

    columns = [
        "trade_date",
        "symbol",
        "isin",
        "series",
        "instrument_name",
        "open",
        "high",
        "low",
        "close",
        "last_price",
        "previous_close",
        "volume",
        "turnover"
    ]

    df = df[columns]

    # ------------------------------------------------------
    # Convert date
    # ------------------------------------------------------

    df["trade_date"] = pd.to_datetime(
        df["trade_date"],
        errors="coerce"
    )

    # ------------------------------------------------------
    # Convert numeric fields
    # ------------------------------------------------------

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "last_price",
        "previous_close",
        "volume",
        "turnover"
    ]

    for column in numeric_columns:

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    # ------------------------------------------------------
    # Validation
    # ------------------------------------------------------

    print()
    print("NULL COUNTS")
    print("-" * 40)

    print(
        df.isna()
        .sum()
        .to_string()
    )

    print()
    print("INVALID PRICE ROWS")
    print("-" * 40)

    invalid_prices = df[
        (df["high"] <= 0)
        | (df["low"] <= 0)
        | (df["close"] <= 0)
    ]

    print(
        "Invalid rows:",
        len(invalid_prices)
    )

    # ------------------------------------------------------
    # Remove rows without essential identity/price
    # ------------------------------------------------------

    df = df.dropna(
        subset=[
            "trade_date",
            "symbol",
            "isin",
            "close"
        ]
    )

    # ------------------------------------------------------
    # Remove invalid prices
    # ------------------------------------------------------

    df = df[
        (df["high"] > 0)
        & (df["low"] > 0)
        & (df["close"] > 0)
    ]

    # ------------------------------------------------------
    # Remove duplicates
    # ------------------------------------------------------

    before = len(df)

    df = df.drop_duplicates(
        subset=[
            "trade_date",
            "isin"
        ]
    )

    duplicates_removed = (
        before - len(df)
    )

    # ------------------------------------------------------
    # Create output folder
    # ------------------------------------------------------

    PROCESSED_FOLDER.mkdir(
        parents=True,
        exist_ok=True
    )

    df.to_csv(
        OUTPUT_FILE,
        index=False
    )

    # ------------------------------------------------------
    # Final statistics
    # ------------------------------------------------------

    print()
    print("=" * 70)
    print("PROCESSING COMPLETE")
    print("=" * 70)

    print()
    print(
        "Final records:",
        len(df)
    )

    print(
        "Duplicates removed:",
        duplicates_removed
    )

    print(
        "Unique symbols:",
        df["symbol"].nunique()
    )

    print(
        "Unique ISINs:",
        df["isin"].nunique()
    )

    print()
    print(
        "Series distribution:"
    )

    print(
        df["series"]
        .value_counts()
        .to_string()
    )

    print()
    print(
        "Output:"
    )

    print(
        OUTPUT_FILE
    )

    print()
    print("First 10 records:")

    print(
        df.head(10)
        .to_string(index=False)
    )

    print()
    print("=" * 70)


# ==========================================================
# Start
# ==========================================================

if __name__ == "__main__":
    main()