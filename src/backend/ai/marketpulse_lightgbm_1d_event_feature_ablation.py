import os
import json
from datetime import datetime

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv
import lightgbm as lgb
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

DB_HOST = os.getenv("MARKETPULSE_DB_HOST", "localhost")
DB_PORT = os.getenv("MARKETPULSE_DB_PORT", "5432")
DB_NAME = os.getenv("MARKETPULSE_DB_NAME", "marketpulse")
DB_USER = os.getenv("MARKETPULSE_DB_USER", "postgres")
DB_PASSWORD = os.getenv("MARKETPULSE_DB_PASSWORD")

TABLE = "market_news_ml_features"
TARGET = "direction_1d"
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "ml_models")

JSON_PATH = os.path.join(
    OUTPUT_DIR, "marketpulse_lightgbm_1d_event_feature_ablation.json"
)
CSV_PATH = os.path.join(
    OUTPUT_DIR, "marketpulse_lightgbm_1d_event_feature_ablation.csv"
)

LABEL_MAP = {"NEGATIVE": 0, "NEUTRAL": 1, "POSITIVE": 2}

BASE_FEATURES = [
    "close", "open", "high", "low", "volume", "turnover", "daily_return",
    "rsi_14", "macd", "macd_signal", "macd_hist", "bb_position_20",
    "sma_5", "sma_10", "sma_20", "ema_5", "ema_10", "ema_20", "atr_14",
    "volatility_20d", "relative_volume_20", "close_vs_sma20",
    "volume_ratio_5d", "range_pct", "momentum_5d", "momentum_10d",
    "momentum_20d", "return_mean_5d", "return_std_5d",
    "return_mean_10d", "return_std_10d", "return_mean_20d",
    "return_std_20d", "volatility_mean_5d", "volatility_mean_10d",
    "volatility_mean_20d", "volume_ratio_mean_5d", "volume_ratio_mean_10d",
    "volume_ratio_mean_20d", "volume_mean_5d", "volume_mean_20d",
    "high_20d", "low_20d", "distance_from_high_20d",
    "distance_from_low_20d", "max_drawdown_20d", "price_trend_20d",
    "volume_trend_20d",
]

EVENT_FEATURES = [
    "feed_category",
    "market_news_category",
    "ai_event_type",
    "ai_event_status",
    "ai_sentiment",
]

# One-at-a-time tests plus combinations of the strongest individual features.
EXPERIMENTS = {
    "BASE_no_event": [],
    "PLUS_feed_category": ["feed_category"],
    "PLUS_market_news_category": ["market_news_category"],
    "PLUS_ai_event_type": ["ai_event_type"],
    "PLUS_ai_event_status": ["ai_event_status"],
    "PLUS_ai_sentiment": ["ai_sentiment"],
    "PLUS_event_type_sentiment": ["ai_event_type", "ai_sentiment"],
    "PLUS_category_event_type": ["market_news_category", "ai_event_type"],
    "PLUS_all_event_features": EVENT_FEATURES,
}

CATEGORICAL = set(EVENT_FEATURES)


def connect():
    if not DB_PASSWORD:
        raise RuntimeError("MARKETPULSE_DB_PASSWORD is not set in .env")
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def load_data(conn):
    columns = ["event_trade_date"] + BASE_FEATURES + EVENT_FEATURES + [TARGET]
    sql = f"""
        SELECT {", ".join(columns)}
        FROM {TABLE}
        WHERE {TARGET} IS NOT NULL
          AND event_trade_date IS NOT NULL
        ORDER BY event_trade_date ASC
    """
    df = pd.read_sql_query(sql, conn)
    df["event_trade_date"] = pd.to_datetime(df["event_trade_date"]).dt.normalize()

    for col in BASE_FEATURES:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in EVENT_FEATURES:
        df[col] = df[col].astype("string").fillna("__MISSING__").astype("category")

    unknown = sorted(set(df[TARGET].dropna().unique()) - set(LABEL_MAP))
    if unknown:
        raise RuntimeError(f"Unknown target values: {unknown}")

    df["target"] = df[TARGET].map(LABEL_MAP).astype(int)
    return df


def make_folds(df):
    dates = pd.Series(sorted(df["event_trade_date"].unique()))

    # Same expanding-window design as the completed walk-forward validation:
    # 2-month test windows, minimum 6 months history, 1-session embargo.
    min_test_start = dates.min() + pd.DateOffset(months=6)
    first_month = min_test_start.to_period("M").to_timestamp()
    last_month = dates.max().to_period("M").to_timestamp()

    starts = []
    current = first_month
    while current < last_month:
        starts.append(current)
        current += pd.DateOffset(months=2)

    folds = []
    for start in starts:
        end_exclusive = start + pd.DateOffset(months=2)
        test_dates = dates[(dates >= start) & (dates < end_exclusive)]
        if len(test_dates) == 0:
            continue

        test_start = test_dates.iloc[0]
        test_end = test_dates.iloc[-1]

        prior_dates = dates[dates < test_start]
        if len(prior_dates) < 2:
            continue

        train_end = prior_dates.iloc[-2]
        train_dates = dates[dates <= train_end]

        if len(train_dates) < 60:
            continue

        folds.append({
            "fold": len(folds) + 1,
            "train_start": train_dates.iloc[0],
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
        })

    if len(folds) > 5:
        folds = folds[-5:]
        for i, f in enumerate(folds, 1):
            f["fold"] = i

    if len(folds) != 5:
        raise RuntimeError(f"Expected 5 folds, got {len(folds)}")

    return folds


def train(X, y, categorical):
    model = lgb.LGBMClassifier(
        objective="multiclass",
        num_class=3,
        n_estimators=500,
        learning_rate=0.03,
        num_leaves=31,
        min_child_samples=50,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=0.1,
        random_state=42,
        n_jobs=-1,
        verbosity=-1,
    )
    model.fit(X, y, categorical_feature=categorical)
    return model


def metrics(model, X, y):
    pred = model.predict(X)
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
    }


def main():
    conn = connect()
    print("Database connection: OK")
    print("=" * 70)
    print("MARKETPULSE - LIGHTGBM 1D EVENT-FEATURE ABLATION")
    print("=" * 70)

    try:
        df = load_data(conn)
        folds = make_folds(df)

        print(f"Rows loaded: {len(df):,}")
        print(
            f"Date range: {df['event_trade_date'].min().date()} -> "
            f"{df['event_trade_date'].max().date()}"
        )
        print("\nUsing same 5 folds and 1-session embargo as walk-forward validation.")

        results = []

        for experiment, event_cols in EXPERIMENTS.items():
            feature_cols = BASE_FEATURES + event_cols
            categorical = [c for c in event_cols if c in CATEGORICAL]

            print("\n" + "=" * 70)
            print(f"{experiment}")
            print(f"Features: {len(feature_cols)} | Event features: {event_cols or 'NONE'}")
            print("=" * 70)

            for fold in folds:
                train_mask = df["event_trade_date"] <= fold["train_end"]
                test_mask = (
                    (df["event_trade_date"] >= fold["test_start"])
                    & (df["event_trade_date"] <= fold["test_end"])
                )

                X_train = df.loc[train_mask, feature_cols]
                y_train = df.loc[train_mask, "target"]
                X_test = df.loc[test_mask, feature_cols]
                y_test = df.loc[test_mask, "target"]

                model = train(X_train, y_train, categorical)
                m = metrics(model, X_test, y_test)

                row = {
                    "experiment": experiment,
                    "event_features": ",".join(event_cols),
                    "feature_count": len(feature_cols),
                    "fold": fold["fold"],
                    "train_start": fold["train_start"].date().isoformat(),
                    "train_end": fold["train_end"].date().isoformat(),
                    "test_start": fold["test_start"].date().isoformat(),
                    "test_end": fold["test_end"].date().isoformat(),
                    "train_rows": len(X_train),
                    "test_rows": len(X_test),
                    **m,
                }
                results.append(row)

                print(
                    f"Fold {fold['fold']}: "
                    f"Acc={m['accuracy']:.4f}, "
                    f"BalAcc={m['balanced_accuracy']:.4f}, "
                    f"F1={m['macro_f1']:.4f}"
                )

        result_df = pd.DataFrame(results)

        summary = (
            result_df.groupby(["experiment", "event_features", "feature_count"])
            .agg(
                mean_accuracy=("accuracy", "mean"),
                std_accuracy=("accuracy", "std"),
                mean_balanced_accuracy=("balanced_accuracy", "mean"),
                std_balanced_accuracy=("balanced_accuracy", "std"),
                mean_macro_f1=("macro_f1", "mean"),
                std_macro_f1=("macro_f1", "std"),
            )
            .reset_index()
        )

        base = summary[summary["experiment"] == "BASE_no_event"].iloc[0]

        summary["accuracy_delta_vs_base"] = (
            summary["mean_accuracy"] - base["mean_accuracy"]
        )
        summary["balanced_accuracy_delta_vs_base"] = (
            summary["mean_balanced_accuracy"] - base["mean_balanced_accuracy"]
        )
        summary["macro_f1_delta_vs_base"] = (
            summary["mean_macro_f1"] - base["mean_macro_f1"]
        )

        summary = summary.sort_values(
            "mean_macro_f1", ascending=False
        )

        print("\n" + "=" * 70)
        print("EVENT-FEATURE ABLATION SUMMARY")
        print("=" * 70)
        display_cols = [
            "experiment", "mean_accuracy", "accuracy_delta_vs_base",
            "mean_balanced_accuracy", "balanced_accuracy_delta_vs_base",
            "mean_macro_f1", "macro_f1_delta_vs_base",
        ]
        print(
            summary[display_cols].to_string(
                index=False,
                float_format=lambda x: f"{x:.4f}"
            )
        )

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        result_df.to_csv(CSV_PATH, index=False)

        payload = {
            "model": "LightGBM",
            "target": TARGET,
            "lightgbm_version": lgb.__version__,
            "validation": {
                "method": "same expanding-window walk-forward validation",
                "folds": 5,
                "test_window_months": 2,
                "minimum_training_history_months": 6,
                "one_trading_session_embargo": True,
            },
            "base_features": BASE_FEATURES,
            "event_features": EVENT_FEATURES,
            "summary": summary.to_dict(orient="records"),
            "fold_results": result_df.to_dict(orient="records"),
            "created_at": datetime.now().isoformat(),
        }

        with open(JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        print("\n" + "-" * 70)
        print("ARTIFACTS SAVED")
        print("-" * 70)
        print(f"JSON: {JSON_PATH}")
        print(f"CSV:  {CSV_PATH}")
        print("\nSUCCESS")

    finally:
        conn.close()


if __name__ == "__main__":
    main()