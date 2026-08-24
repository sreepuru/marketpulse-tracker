import pandas as pd
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

EXTRACT_FOLDER = (
    PROJECT_ROOT
    / "data"
    / "bhavcopy"
    / "extracted"
)


def main():

    csv_files = list(
        EXTRACT_FOLDER.rglob("*.csv")
    )

    if not csv_files:

        raise FileNotFoundError(
            "No Bhavcopy CSV found."
        )

    csv_file = max(
        csv_files,
        key=lambda file:
            file.stat().st_mtime
    )

    print()
    print("=" * 70)
    print("MarketPulse Bhavcopy Data Profile")
    print("=" * 70)

    print()
    print("File:")
    print(csv_file)

    df = pd.read_csv(
        csv_file
    )

    df.columns = [
        str(column).strip().upper()
        for column in df.columns
    ]

    print()
    print("Total Rows:", len(df))

    print()
    print("SEGMENT DISTRIBUTION")
    print("-" * 40)

    print(
        df["SGMT"]
        .value_counts(dropna=False)
        .to_string()
    )

    print()
    print("INSTRUMENT TYPE DISTRIBUTION")
    print("-" * 40)

    print(
        df["FININSTRMTP"]
        .value_counts(dropna=False)
        .to_string()
    )

    print()
    print("SECURITY SERIES DISTRIBUTION")
    print("-" * 40)

    print(
        df["SCTYSRS"]
        .value_counts(dropna=False)
        .to_string()
    )

    print()
    print("SYMBOL EXAMPLES")
    print("-" * 40)

    print(
        df[
            [
                "TCKRSYMB",
                "SCTYSRS",
                "FININSTRMTP",
                "FININSTRMNM"
            ]
        ]
        .head(30)
        .to_string(index=False)
    )

    print()
    print("=" * 70)
    print("Profile completed.")
    print("=" * 70)


if __name__ == "__main__":
    main()