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

FEATURE_TABLE = "market_news_ml_features"
TARGET = "direction_1d"
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "ml_models")

RESULTS_PATH = os.path.join(
    OUTPUT_DIR, "marketpulse_lightgbm_1d_feature_ablation.json"
)
FOLD_PATH = os.path.join(
    OUTPUT_DIR, "marketpulse_lightgbm_1d_feature_ablation.csv"
)

LABEL_MAP = {"NEGATIVE": 0, "NEUTRAL": 1, "POSITIVE": 2}

# Keep this list identical to the current production feature matrix.
NUMERIC_FEATURES = [
    "publication_hour", "publication_minute", "publication_weekday",
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
    "volume_trend_20d", "sequence_rows", "sequence_length",
]

CATEGORICAL_FEATURES = [
    "feed_category", "market_news_category", "ai_event_type",
    "ai_event_status", "ai_sentiment", "is_pre_market", "is_post_market",
]

FEATURE_GROUPS = {
    "technical": [
        "rsi_14", "macd", "macd_signal", "macd_hist", "bb_position_20",
        "sma_5", "sma_10", "sma_20", "ema_5", "ema_10", "ema_20",
        "atr_14", "volatility_20d", "close_vs_sma20",
    ],
    "price_volume": [
        "close", "open", "high", "low", "volume", "turnover", "daily_return",
        "volume_ratio_5d", "range_pct", "momentum_5d", "momentum_10d",
        "momentum_20d", "return_mean_5d", "return_std_5d",
        "return_mean_10d", "return_std_10d", "return_mean_20d",
        "return_std_20d", "volatility_mean_5d", "volatility_mean_10d",
        "volatility_mean_20d", "volume_ratio_mean_5d",
        "volume_ratio_mean_10d", "volume_ratio_mean_20d", "volume_mean_5d",
        "volume_mean_20d", "high_20d", "low_20d", "distance_from_high_20d",
        "distance_from_low_20d", "max_drawdown_20d", "price_trend_20d",
        "volume_trend_20d",
    ],
    "event": [
        "feed_category", "market_news_category", "ai_event_type",
        "ai_event_status", "ai_sentiment",
    ],
    "timing": [
        "publication_hour", "publication_minute", "publication_weekday",
        "is_pre_market", "is_post_market",
    ],
    "sequence_meta": [
        "sequence_rows", "sequence_length",
    ],
}

# Nested feature sets: each experiment adds one meaningful information family.
EXPERIMENTS = {
    "A_technical_only": ["technical"],
    "B_price_volume_only": ["price_volume"],
    "C_technical_plus_price_volume": ["technical", "price_volume"],
    "D_technical_price_volume_event": ["technical", "price_volume", "event"],
    "E_all_features": [
        "technical", "price_volume", "event", "timing", "sequence_meta"
    ],
}


def get_connection():
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
    columns = ["event_trade_date"] + NUMERIC_FEATURES + CATEGORICAL_FEATURES + [TARGET]
    sql = f"""
        SELECT {", ".join(columns)}
        FROM {FEATURE_TABLE}
        WHERE {TARGET} IS NOT NULL
          AND event_trade_date IS NOT NULL
        ORDER BY event_trade_date ASC
    """
    print("=" * 70)
    print("MARKETPULSE - LIGHTGBM 1D FEATURE-GROUP ABLATION")
    print("=" * 70)
    print("Loading event-level feature matrix...")
    df = pd.read_sql_query(sql, conn)
    df["event_trade_date"] = pd.to_datetime(df["event_trade_date"]).dt.normalize()
    print(f"Rows loaded: {len(df):,}")
    print(
        f"Date range: {df['event_trade_date'].min().date()} -> "
        f"{df['event_trade_date'].max().date()}"
    )
    return df


def prepare_data(df):
    unknown = sorted(set(df[TARGET].dropna().unique()) - set(LABEL_MAP))
    if unknown:
        raise RuntimeError(f"Unknown target values: {unknown}")

    for col in CATEGORICAL_FEATURES:
        df[col] = df[col].astype("string").fillna("__MISSING__").astype("category")

    for col in NUMERIC_FEATURES:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["target"] = df[TARGET].map(LABEL_MAP).astype(int)
    return df


def make_folds(df, n_folds=5, test_months=2, min_train_months=6):
    dates = pd.Series(sorted(df["event_trade_date"].dropna().unique()))
    if len(dates) < 10:
        raise RuntimeError("Not enough distinct event dates for walk-forward validation.")

    min_test_start = dates.min() + pd.DateOffset(months=min_train_months)
    first_month = min_test_start.to_period("M").to_timestamp()
    last_month = dates.max().to_period("M").to_timestamp()

    candidates = []
    current = first_month
    while current < last_month:
        candidates.append(current)
        current += pd.DateOffset(months=test_months)

    folds = []
    for start in candidates:
        end_exclusive = start + pd.DateOffset(months=test_months)
        if end_exclusive - pd.Timedelta(days=1) > dates.max():
            continue

        test_dates = dates[(dates >= start) & (dates < end_exclusive)]
        if len(test_dates) == 0:
            continue

        test_start = test_dates.iloc[0]
        test_end = test_dates.iloc[-1]

        prior_dates = dates[dates < test_start]
        if len(prior_dates) < 2:
            continue

        # One-session embargo.
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

    if len(folds) > n_folds:
        folds = folds[-n_folds:]
        for i, fold in enumerate(folds, 1):
            fold["fold"] = i

    if len(folds) < 3:
        raise RuntimeError(f"Only {len(folds)} usable folds were created.")

    return folds


def feature_columns_for(experiment_name):
    groups = EXPERIMENTS[experiment_name]
    cols = []
    for group in groups:
        for col in FEATURE_GROUPS[group]:
            if col not in cols:
                cols.append(col)
    return cols


def train_model(X_train, y_train, categorical):
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
    model.fit(X_train, y_train, categorical_feature=categorical)
    return model


def evaluate(model, X_test, y_test):
    pred = model.predict(X_test)
    return {
        "accuracy": float(accuracy_score(y_test, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_test, pred)),
        "macro_f1": float(f1_score(y_test, pred, average="macro", zero_division=0)),
    }


def main():
    conn = None
    try:
        conn = get_connection()
        print("\nDatabase connection: OK")

        df = prepare_data(load_data(conn))
        folds = make_folds(df)

        print("\n" + "-" * 70)
        print("FEATURE GROUPS")
        print("-" * 70)
        for name, groups in EXPERIMENTS.items():
            cols = feature_columns_for(name)
            categorical = [c for c in CATEGORICAL_FEATURES if c in cols]
            print(
                f"{name}: {len(cols)} features "
                f"({len(categorical)} categorical)"
            )

        all_results = []

        for experiment_name in EXPERIMENTS:
            feature_cols = feature_columns_for(experiment_name)
            categorical = [
                c for c in CATEGORICAL_FEATURES if c in feature_cols
            ]

            print("\n" + "=" * 70)
            print(experiment_name)
            print("=" * 70)

            fold_results = []

            for fold in folds:
                train_mask = df["event_trade_date"] <= fold["train_end"]
                test_mask = (
                    (df["event_trade_date"] >= fold["test_start"])
                    & (df["event_trade_date"] <= fold["test_end"])
                )

                X_train = df.loc[train_mask, feature_cols].copy()
                y_train = df.loc[train_mask, "target"].copy()
                X_test = df.loc[test_mask, feature_cols].copy()
                y_test = df.loc[test_mask, "target"].copy()

                model = train_model(X_train, y_train, categorical)
                metrics = evaluate(model, X_test, y_test)

                result = {
                    "experiment": experiment_name,
                    "fold": fold["fold"],
                    "feature_count": len(feature_cols),
                    "train_start": fold["train_start"].date().isoformat(),
                    "train_end": fold["train_end"].date().isoformat(),
                    "test_start": fold["test_start"].date().isoformat(),
                    "test_end": fold["test_end"].date().isoformat(),
                    "train_rows": int(len(X_train)),
                    "test_rows": int(len(X_test)),
                    **metrics,
                }
                fold_results.append(result)
                all_results.append(result)

                print(
                    f"Fold {fold['fold']}: "
                    f"Acc={metrics['accuracy']:.4f}, "
                    f"BalAcc={metrics['balanced_accuracy']:.4f}, "
                    f"F1={metrics['macro_f1']:.4f}"
                )

            acc = [r["accuracy"] for r in fold_results]
            bal = [r["balanced_accuracy"] for r in fold_results]
            f1 = [r["macro_f1"] for r in fold_results]

            print(
                f"Mean: Acc={np.mean(acc):.4f}, "
                f"BalAcc={np.mean(bal):.4f}, "
                f"F1={np.mean(f1):.4f}"
            )

        result_df = pd.DataFrame(all_results)

        summary_rows = []
        for experiment_name, group in result_df.groupby("experiment"):
            summary_rows.append({
                "experiment": experiment_name,
                "feature_count": int(group["feature_count"].iloc[0]),
                "mean_accuracy": float(group["accuracy"].mean()),
                "std_accuracy": float(group["accuracy"].std(ddof=1)),
                "mean_balanced_accuracy": float(group["balanced_accuracy"].mean()),
                "std_balanced_accuracy": float(
                    group["balanced_accuracy"].std(ddof=1)
                ),
                "mean_macro_f1": float(group["macro_f1"].mean()),
                "std_macro_f1": float(group["macro_f1"].std(ddof=1)),
            })

        summary_df = pd.DataFrame(summary_rows).sort_values(
            "mean_macro_f1", ascending=False
        )

        print("\n" + "=" * 70)
        print("FEATURE ABLATION SUMMARY")
        print("=" * 70)
        print(summary_df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

        os.makedirs(OUTPUT_DIR, exist_ok=True)
        result_df.to_csv(FOLD_PATH, index=False)

        payload = {
            "model": "LightGBM",
            "target": TARGET,
            "lightgbm_version": lgb.__version__,
            "validation": {
                "method": "expanding_window_walk_forward",
                "folds": len(folds),
                "test_months": 2,
                "min_train_months": 6,
                "one_trading_session_embargo": True,
            },
            "experiments": {
                name: feature_columns_for(name)
                for name in EXPERIMENTS
            },
            "summary": summary_rows,
            "fold_results": all_results,
            "created_at": datetime.now().isoformat(),
        }

        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        print("\n" + "-" * 70)
        print("ARTIFACTS SAVED")
        print("-" * 70)
        print(f"JSON: {RESULTS_PATH}")
        print(f"CSV:  {FOLD_PATH}")

        print("\n" + "=" * 70)
        print("SUCCESS")
        print("=" * 70)

    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()