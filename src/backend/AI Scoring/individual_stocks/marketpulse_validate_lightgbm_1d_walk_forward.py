import os
import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
from dotenv import load_dotenv
import lightgbm as lgb
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)

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
RESULTS_PATH = os.path.join(OUTPUT_DIR, "marketpulse_lightgbm_1d_walk_forward.json")
FOLD_PATH = os.path.join(OUTPUT_DIR, "marketpulse_lightgbm_1d_walk_forward_folds.csv")

LABEL_MAP = {"NEGATIVE": 0, "NEUTRAL": 1, "POSITIVE": 2}

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
    print("MARKETPULSE - LIGHTGBM 1D WALK-FORWARD VALIDATION")
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
    features = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    return df, df[features].copy(), df["target"].copy(), features


def make_folds(df, n_folds=5, test_months=2, min_train_months=6):
    """
    Expanding-window walk-forward folds.

    The test windows are consecutive two-month calendar windows ending at the
    end of the dataset. A one-trading-session embargo is enforced: training
    events stop at least one trading session before the test window. This
    prevents a 1D training label from using the first test-session outcome.
    """
    dates = pd.Series(sorted(df["event_trade_date"].dropna().unique()))
    if len(dates) < 10:
        raise RuntimeError("Not enough distinct event dates for walk-forward validation.")

    min_test_start = dates.min() + pd.DateOffset(months=min_train_months)

    # Candidate test starts every two months, aligned to calendar month starts.
    first_month = min_test_start.to_period("M").to_timestamp()
    last_month = dates.max().to_period("M").to_timestamp()

    candidates = []
    current = first_month
    while current < last_month:
        candidates.append(current)
        current = current + pd.DateOffset(months=test_months)

    # Keep only complete two-month test windows inside the available period.
    folds = []
    for start in candidates:
        end_exclusive = start + pd.DateOffset(months=test_months)
        if end_exclusive - pd.Timedelta(days=1) > dates.max():
            continue

        # Test starts at the first available event date on/after calendar start.
        test_dates = dates[(dates >= start) & (dates < end_exclusive)]
        if len(test_dates) == 0:
            continue

        test_start = test_dates.iloc[0]
        test_end = test_dates.iloc[-1]

        # One-session embargo: training must end before the immediately
        # preceding trading/event date, because a 1D label from that date
        # can use the first test-session return.
        prior_dates = dates[dates < test_start]
        if len(prior_dates) < 2:
            continue
        train_end = prior_dates.iloc[-2]

        train_dates = dates[dates <= train_end]
        if len(train_dates) < 60:
            continue

        folds.append(
            {
                "fold": len(folds) + 1,
                "train_start": train_dates.iloc[0],
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
            }
        )

    if n_folds and len(folds) > n_folds:
        folds = folds[-n_folds:]
        for i, fold in enumerate(folds, 1):
            fold["fold"] = i

    if len(folds) < 3:
        raise RuntimeError(
            f"Only {len(folds)} usable folds were created. "
            "Need at least 3 for meaningful walk-forward validation."
        )

    return folds


def train_model(X_train, y_train):
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
    model.fit(X_train, y_train, categorical_feature=CATEGORICAL_FEATURES)
    return model


def evaluate_fold(model, X_test, y_test):
    pred = model.predict(X_test)
    labels = [0, 1, 2]
    metrics = {
        "accuracy": float(accuracy_score(y_test, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_test, pred)),
        "macro_f1": float(f1_score(y_test, pred, average="macro", zero_division=0)),
        "classification_report": classification_report(
            y_test,
            pred,
            labels=labels,
            target_names=["NEGATIVE", "NEUTRAL", "POSITIVE"],
            zero_division=0,
            output_dict=True,
        ),
        "confusion_matrix": confusion_matrix(y_test, pred, labels=labels).tolist(),
    }
    return metrics, pred


def print_fold_result(fold, train_df, test_df, metrics):
    print("\n" + "-" * 70)
    print(f"FOLD {fold['fold']}")
    print("-" * 70)
    print(
        f"Train: {fold['train_start'].date()} -> {fold['train_end'].date()} "
        f"({len(train_df):,} rows)"
    )
    print(
        f"Test : {fold['test_start'].date()} -> {fold['test_end'].date()} "
        f"({len(test_df):,} rows)"
    )
    print(f"Accuracy:          {metrics['accuracy']:.4f}")
    print(f"Balanced Accuracy: {metrics['balanced_accuracy']:.4f}")
    print(f"Macro F1:          {metrics['macro_f1']:.4f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--test-months", type=int, default=2)
    parser.add_argument("--min-train-months", type=int, default=6)
    args = parser.parse_args()

    if args.folds < 3:
        raise ValueError("--folds must be at least 3")
    if args.test_months < 1:
        raise ValueError("--test-months must be at least 1")
    if args.min_train_months < 3:
        raise ValueError("--min-train-months must be at least 3")

    conn = None
    try:
        conn = get_connection()
        print("\nDatabase connection: OK")

        df = load_data(conn)
        df, X, y, feature_columns = prepare_data(df)

        print("\n" + "-" * 70)
        print("CREATING WALK-FORWARD FOLDS")
        print("-" * 70)

        folds = make_folds(
            df,
            n_folds=args.folds,
            test_months=args.test_months,
            min_train_months=args.min_train_months,
        )

        print(f"Usable folds: {len(folds)}")
        for fold in folds:
            print(
                f"  Fold {fold['fold']}: "
                f"train {fold['train_start'].date()} -> {fold['train_end'].date()}, "
                f"test {fold['test_start'].date()} -> {fold['test_end'].date()}"
            )

        fold_results = []

        for fold in folds:
            train_mask = df["event_trade_date"] <= fold["train_end"]
            test_mask = (
                (df["event_trade_date"] >= fold["test_start"])
                & (df["event_trade_date"] <= fold["test_end"])
            )

            X_train = X.loc[train_mask].copy()
            y_train = y.loc[train_mask].copy()
            X_test = X.loc[test_mask].copy()
            y_test = y.loc[test_mask].copy()

            if len(X_train) == 0 or len(X_test) == 0:
                raise RuntimeError(f"Fold {fold['fold']} has an empty train or test set.")

            model = train_model(X_train, y_train)
            metrics, pred = evaluate_fold(model, X_test, y_test)

            train_df = df.loc[train_mask]
            test_df = df.loc[test_mask]
            print_fold_result(fold, train_df, test_df, metrics)

            fold_results.append(
                {
                    "fold": fold["fold"],
                    "train_start": fold["train_start"].date().isoformat(),
                    "train_end": fold["train_end"].date().isoformat(),
                    "test_start": fold["test_start"].date().isoformat(),
                    "test_end": fold["test_end"].date().isoformat(),
                    "train_rows": int(len(X_train)),
                    "test_rows": int(len(X_test)),
                    "metrics": metrics,
                }
            )

        accuracies = [x["metrics"]["accuracy"] for x in fold_results]
        balanced = [x["metrics"]["balanced_accuracy"] for x in fold_results]
        macro_f1 = [x["metrics"]["macro_f1"] for x in fold_results]

        summary = {
            "mean_accuracy": float(np.mean(accuracies)),
            "std_accuracy": float(np.std(accuracies, ddof=1)),
            "mean_balanced_accuracy": float(np.mean(balanced)),
            "std_balanced_accuracy": float(np.std(balanced, ddof=1)),
            "mean_macro_f1": float(np.mean(macro_f1)),
            "std_macro_f1": float(np.std(macro_f1, ddof=1)),
            "min_accuracy": float(np.min(accuracies)),
            "max_accuracy": float(np.max(accuracies)),
            "min_balanced_accuracy": float(np.min(balanced)),
            "max_balanced_accuracy": float(np.max(balanced)),
            "min_macro_f1": float(np.min(macro_f1)),
            "max_macro_f1": float(np.max(macro_f1)),
        }

        print("\n" + "=" * 70)
        print("WALK-FORWARD SUMMARY")
        print("=" * 70)
        print(f"Mean Accuracy:          {summary['mean_accuracy']:.4f}")
        print(f"Std Accuracy:           {summary['std_accuracy']:.4f}")
        print(f"Mean Balanced Accuracy: {summary['mean_balanced_accuracy']:.4f}")
        print(f"Std Balanced Accuracy:  {summary['std_balanced_accuracy']:.4f}")
        print(f"Mean Macro F1:          {summary['mean_macro_f1']:.4f}")
        print(f"Std Macro F1:           {summary['std_macro_f1']:.4f}")
        print(
            f"Accuracy range:         "
            f"{summary['min_accuracy']:.4f} -> {summary['max_accuracy']:.4f}"
        )

        os.makedirs(OUTPUT_DIR, exist_ok=True)

        payload = {
            "model": "LightGBM",
            "lightgbm_version": lgb.__version__,
            "target": TARGET,
            "classes": LABEL_MAP,
            "feature_count": len(feature_columns),
            "features": feature_columns,
            "validation": {
                "method": "expanding_window_walk_forward",
                "folds": len(fold_results),
                "test_months": args.test_months,
                "min_train_months": args.min_train_months,
                "one_trading_session_embargo": True,
            },
            "summary": summary,
            "folds": fold_results,
            "created_at": datetime.now().isoformat(),
        }

        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        fold_rows = []
        for item in fold_results:
            row = {
                "fold": item["fold"],
                "train_start": item["train_start"],
                "train_end": item["train_end"],
                "test_start": item["test_start"],
                "test_end": item["test_end"],
                "train_rows": item["train_rows"],
                "test_rows": item["test_rows"],
                "accuracy": item["metrics"]["accuracy"],
                "balanced_accuracy": item["metrics"]["balanced_accuracy"],
                "macro_f1": item["metrics"]["macro_f1"],
            }
            fold_rows.append(row)

        pd.DataFrame(fold_rows).to_csv(FOLD_PATH, index=False)

        print("\n" + "-" * 70)
        print("ARTIFACTS SAVED")
        print("-" * 70)
        print(f"Summary JSON: {RESULTS_PATH}")
        print(f"Fold CSV:     {FOLD_PATH}")

        print("\n" + "=" * 70)
        print("SUCCESS")
        print("=" * 70)

    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()