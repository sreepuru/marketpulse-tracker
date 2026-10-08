"""
MarketPulse - LightGBM Multi-Horizon Direction Training

Supports:
    +1D  -> direction_1d
    +5D  -> direction_5d
    +10D -> direction_10d

Design:
    - Strict chronological calendar-date split.
    - All events on the same calendar date remain on the same side.
    - Only pre-event / event-time information is used as model features.
    - Future returns and future directions are NEVER model features.
    - Backward returns are allowed because they represent pre-event history.
    - prediction_eligible is a dataset-quality flag, not a predictive feature.
    - One canonical training script supports all horizons.
"""

from pathlib import Path
import argparse
import json
import warnings

import numpy as np
import pandas as pd
import psycopg2
from lightgbm import LGBMClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)


warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy",
)


# ============================================================
# CONFIG
# ============================================================

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "marketpulse",
    "user": "postgres",
    "password": "admin",
}

TABLE_NAME = "market_news_ml_features"

CATEGORICAL_FEATURES = [
    "feed_category",
    "market_news_category",
    "ai_event_type",
    "ai_event_status",
    "ai_sentiment",
    "prediction_note",
    "exchange",
]

MISSING_CATEGORY = "__MISSING__"

# Keep every event on the same calendar date on the same side.
CUTOFF_DATE = pd.Timestamp("2026-05-28")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = PROJECT_ROOT / "ml_models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# HORIZON CONFIGURATION
# ============================================================

HORIZON_CONFIG = {
    1: {
        "target": "direction_1d",
        "return_column": "forward_return_1d",
        "label_flag": "has_1d_label",
        "model_path": MODEL_DIR / "marketpulse_lightgbm_1d_v3.txt",
        "metrics_path": MODEL_DIR / "marketpulse_lightgbm_1d_v3_metrics.json",
        "importance_path": MODEL_DIR / "marketpulse_lightgbm_1d_v3_feature_importance.csv",
        "model_version": "MarketPulse-LightGBM-1D-v3",
    },
    5: {
        "target": "direction_5d",
        "return_column": "forward_return_5d",
        "label_flag": "has_5d_label",
        "model_path": MODEL_DIR / "marketpulse_lightgbm_5d_v1.txt",
        "metrics_path": MODEL_DIR / "marketpulse_lightgbm_5d_v1_metrics.json",
        "importance_path": MODEL_DIR / "marketpulse_lightgbm_5d_v1_feature_importance.csv",
        "model_version": "MarketPulse-LightGBM-5D-v1",
    },
    10: {
        "target": "direction_10d",
        "return_column": "forward_return_10d",
        "label_flag": "has_10d_label",
        "model_path": MODEL_DIR / "marketpulse_lightgbm_10d_v1.txt",
        "metrics_path": MODEL_DIR / "marketpulse_lightgbm_10d_v1_metrics.json",
        "importance_path": MODEL_DIR / "marketpulse_lightgbm_10d_v1_feature_importance.csv",
        "model_version": "MarketPulse-LightGBM-10D-v1",
    },
}


VALID_CLASSES = ["NEGATIVE", "NEUTRAL", "POSITIVE"]


# ============================================================
# ARGUMENTS
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Train MarketPulse LightGBM direction model."
    )

    parser.add_argument(
        "--horizon",
        type=int,
        choices=[1, 5, 10],
        required=True,
        help="Prediction horizon in trading sessions: 1, 5, or 10.",
    )

    return parser.parse_args()


# ============================================================
# LOAD DATA
# ============================================================

def load_data(target):
    conn = psycopg2.connect(**DB_CONFIG)

    query = f"""
        SELECT *
        FROM {TABLE_NAME}
        WHERE {target} IS NOT NULL
          AND prediction_eligible = TRUE
        ORDER BY event_trade_date, news_id
    """

    try:
        df = pd.read_sql_query(query, conn)
    finally:
        conn.close()

    if df.empty:
        raise RuntimeError(
            f"No rows found for training target: {target}"
        )

    return df

def load_category_vocab():
    conn = psycopg2.connect(**DB_CONFIG)

    try:
        vocab = {}

        for column in CATEGORICAL_FEATURES:
            query = f"""
                SELECT DISTINCT {column} AS value
                FROM {TABLE_NAME}
                WHERE {column} IS NOT NULL
                ORDER BY {column}
            """

            values = pd.read_sql_query(query, conn)["value"].tolist()
            categories = [str(value) for value in values]

            if MISSING_CATEGORY not in categories:
                categories.append(MISSING_CATEGORY)

            vocab[column] = categories

    finally:
        conn.close()

    return vocab

# ============================================================
# PREPARE FEATURES
# ============================================================

def prepare_features(df, target, category_vocab):
    """
    Build model inputs while explicitly excluding:

        - identifiers
        - timestamps used for splitting/reporting
        - every future return
        - every future direction
        - label availability flags
        - dataset eligibility flags

    Backward returns remain available because they represent
    information that existed before the event.
    """

    excluded = {
        # ----------------------------------------------------
        # Identifiers
        # ----------------------------------------------------
        "news_id",
        "security_id",

        # ----------------------------------------------------
        # Time/date identifiers
        # ----------------------------------------------------
        "event_trade_date",
        "published_at",
        "prediction_cutoff_ts",
        "cutoff_trade_date",
        "created_at",
        "updated_at",

        # ----------------------------------------------------
        # Future returns
        # ----------------------------------------------------
        "forward_return_1d",
        "forward_return_3d",
        "forward_return_5d",
        "forward_return_10d",

        # ----------------------------------------------------
        # Future directions / labels
        # ----------------------------------------------------
        "direction_1d",
        "direction_3d",
        "direction_5d",
        "direction_10d",

        # ----------------------------------------------------
        # Label availability indicators
        # ----------------------------------------------------
        "has_1d_label",
        "has_3d_label",
        "has_5d_label",
        "has_10d_label",

        # ----------------------------------------------------
        # Dataset quality / eligibility flag
        # ----------------------------------------------------
        "prediction_eligible",
        "prediction_note",
    }

    # Safety check: the requested target must exist.
    if target not in df.columns:
        raise RuntimeError(
            f"Target column '{target}' not found in feature table."
        )

    feature_columns = [
        column
        for column in df.columns
        if column not in excluded
    ]

    if not feature_columns:
        raise RuntimeError("No model features remain after exclusions.")

    X = df[feature_columns].copy()
    y = df[target].copy()

    categorical_columns = []

    # --------------------------------------------------------
    # Object/string -> pandas categorical
    # --------------------------------------------------------

    for column in X.columns:
        if (
            pd.api.types.is_object_dtype(X[column])
            or pd.api.types.is_string_dtype(X[column])
        ):
            if column not in category_vocab:
                raise RuntimeError(
                    f"Missing canonical categorical vocabulary for '{column}'."
                )

            categories = category_vocab[column]

            non_null_values = X[column].dropna().map(str)
            unknown_values = sorted(
                set(non_null_values) - set(categories)
            )

            if unknown_values:
                raise RuntimeError(
                    f"Unexpected categorical values found in '{column}': "
                    f"{unknown_values[:20]}"
                )

            X[column] = pd.Categorical(
                X[column].map(
                    lambda value: str(value)
                    if pd.notna(value)
                    else MISSING_CATEGORY
                ),
                categories=categories,
            )

            categorical_columns.append(column)

    # --------------------------------------------------------
    # Boolean -> integer
    # --------------------------------------------------------

    for column in X.columns:
        if pd.api.types.is_bool_dtype(X[column]):
            X[column] = X[column].astype(int)

    # --------------------------------------------------------
    # Safety check for accidental future columns
    # --------------------------------------------------------

    forbidden_fragments = (
        "forward_return",
        "direction_",
    )

    accidental_future_features = [
        column
        for column in feature_columns
        if column.startswith(forbidden_fragments)
    ]

    if accidental_future_features:
        raise RuntimeError(
            "TARGET LEAKAGE: future label/return columns remain "
            f"in model features: {accidental_future_features}"
        )

    return (
        X,
        y,
        feature_columns,
        categorical_columns,
    )


# ============================================================
# MAJORITY BASELINE
# ============================================================

def majority_baseline(y_train, y_test):
    majority_class = y_train.value_counts().idxmax()

    baseline_predictions = np.full(
        len(y_test),
        majority_class,
        dtype=object,
    )

    accuracy = accuracy_score(
        y_test,
        baseline_predictions,
    )

    balanced = balanced_accuracy_score(
        y_test,
        baseline_predictions,
    )

    macro_f1 = f1_score(
        y_test,
        baseline_predictions,
        average="macro",
        zero_division=0,
    )

    return (
        majority_class,
        accuracy,
        balanced,
        macro_f1,
    )


# ============================================================
# TARGET VALIDATION
# ============================================================

def validate_target(y, target):
    unexpected = (
        set(y.dropna().unique())
        - set(VALID_CLASSES)
    )

    if unexpected:
        raise RuntimeError(
            f"Unexpected target classes for {target}: "
            f"{sorted(unexpected)}"
        )


# ============================================================
# TRAINING
# ============================================================

def main():
    args = parse_args()

    horizon = args.horizon
    config = HORIZON_CONFIG[horizon]

    target = config["target"]

    print("=" * 70)
    print("MarketPulse - LightGBM Multi-Horizon Direction Training")
    print("=" * 70)

    print(f"Horizon       : +{horizon} trading day(s)")
    print(f"Target        : {target}")
    print(f"Database      : {DB_CONFIG['database']}")
    print(f"Feature table : {TABLE_NAME}")
    print(f"Cutoff date   : {CUTOFF_DATE.date()}")
    print(f"Model version : {config['model_version']}")
    print()

    # --------------------------------------------------------
    # Load
    # --------------------------------------------------------

    print("=== LOADING DATA ===")

    df = load_data(target)

    df["event_trade_date"] = pd.to_datetime(
        df["event_trade_date"]
    ).dt.normalize()

    validate_target(df[target], target)

    print(f"Rows loaded: {len(df):,}")

    # --------------------------------------------------------
    # Strict chronological split
    # --------------------------------------------------------

    train_mask = (
        df["event_trade_date"] < CUTOFF_DATE
    )

    test_mask = (
        df["event_trade_date"] >= CUTOFF_DATE
    )

    train_df = df.loc[train_mask].copy()
    test_df = df.loc[test_mask].copy()

    if train_df.empty:
        raise RuntimeError(
            "Training set is empty. Check CUTOFF_DATE."
        )

    if test_df.empty:
        raise RuntimeError(
            "Testing set is empty. Check CUTOFF_DATE."
        )

    print()
    print("=== DATA SPLIT ===")
    print(f"Cutoff date: {CUTOFF_DATE.date()}")
    print(f"Training rows: {len(train_df):,}")
    print(f"Testing rows:  {len(test_df):,}")

    print(
        f"Train period: "
        f"{train_df['event_trade_date'].min().date()} "
        f"-> "
        f"{train_df['event_trade_date'].max().date()}"
    )

    print(
        f"Test period:  "
        f"{test_df['event_trade_date'].min().date()} "
        f"-> "
        f"{test_df['event_trade_date'].max().date()}"
    )

    # --------------------------------------------------------
    # Date leakage safety assertion
    # --------------------------------------------------------

    train_max_date = train_df[
        "event_trade_date"
    ].max()

    test_min_date = test_df[
        "event_trade_date"
    ].min()

    if train_max_date >= test_min_date:
        raise RuntimeError(
            "DATE LEAKAGE: train and test dates overlap."
        )

    print()

    print("=== LOADING CATEGORICAL VOCABULARY ===")

    category_vocab = load_category_vocab()

    for column in CATEGORICAL_FEATURES:
        print(
            f"  {column}: "
            f"{len(category_vocab[column]) - 1:,} production values "
            f"+ {MISSING_CATEGORY}"
        )

    # --------------------------------------------------------
    # Features
    # --------------------------------------------------------

    (
        X_all,
        y_all,
        feature_columns,
        categorical_columns,
    ) = prepare_features(
        df,
        target,
        category_vocab,
    )

    X_train = X_all.loc[
        train_mask
    ].copy()

    X_test = X_all.loc[
        test_mask
    ].copy()

    y_train = y_all.loc[
        train_mask
    ].copy()

    y_test = y_all.loc[
        test_mask
    ].copy()

    print()
    print("=== FEATURES ===")
    print(f"Feature count: {len(feature_columns)}")
    print(
        f"Categorical features: "
        f"{len(categorical_columns)}"
    )

    print()
    print("Backward movement features retained:")

    backward_features = [
        "backward_return_1d",
        "backward_return_5d",
        "backward_return_10d",
    ]

    for feature in backward_features:
        if feature in feature_columns:
            print(f"  OK  {feature}")
        else:
            print(f"  --  {feature}")

    # --------------------------------------------------------
    # Explicit leakage audit
    # --------------------------------------------------------

    future_columns_present = [
        column
        for column in feature_columns
        if (
            column.startswith("forward_return")
            or column.startswith("direction_")
        )
    ]

    if future_columns_present:
        raise RuntimeError(
            "FEATURE LEAKAGE DETECTED. "
            f"Future columns present: {future_columns_present}"
        )

    print()
    print("=== FEATURE LEAKAGE AUDIT ===")
    print("Future return/direction columns in features: 0")
    print("prediction_eligible in features: 0")
    print("Backward return features allowed: YES")

    # --------------------------------------------------------
    # Target distribution
    # --------------------------------------------------------

    print()
    print("=== TARGET DISTRIBUTION ===")

    train_distribution = (
        y_train
        .value_counts()
        .reindex(VALID_CLASSES)
        .fillna(0)
        .astype(int)
    )

    test_distribution = (
        y_test
        .value_counts()
        .reindex(VALID_CLASSES)
        .fillna(0)
        .astype(int)
    )

    print("TRAIN:")

    for label, count in train_distribution.items():
        pct = (
            100.0 * count / len(y_train)
        )
        print(
            f"  {label:8s}: "
            f"{count:8,d} "
            f"({pct:6.2f}%)"
        )

    print("TEST:")

    for label, count in test_distribution.items():
        pct = (
            100.0 * count / len(y_test)
        )
        print(
            f"  {label:8s}: "
            f"{count:8,d} "
            f"({pct:6.2f}%)"
        )

    # --------------------------------------------------------
    # Majority baseline
    # --------------------------------------------------------

    (
        majority_class,
        baseline_accuracy,
        baseline_balanced,
        baseline_macro_f1,
    ) = majority_baseline(
        y_train,
        y_test,
    )

    print()
    print("=== MAJORITY BASELINE ===")
    print(f"Majority class: {majority_class}")
    print(
        f"Accuracy: {baseline_accuracy:.4f}"
    )
    print(
        f"Balanced Accuracy: {baseline_balanced:.4f}"
    )
    print(
        f"Macro F1: {baseline_macro_f1:.4f}"
    )

    # --------------------------------------------------------
    # LightGBM
    # --------------------------------------------------------

    model = LGBMClassifier(
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

    print()
    print("=== LIGHTGBM TRAINING ===")
    print(
        f"Target: {target}"
    )

    model.fit(
        X_train,
        y_train,
        categorical_feature=categorical_columns,
    )

    # --------------------------------------------------------
    # Predictions
    # --------------------------------------------------------

    predictions = model.predict(X_test)

    probabilities = model.predict_proba(X_test)

    # --------------------------------------------------------
    # Evaluation
    # --------------------------------------------------------

    accuracy = accuracy_score(
        y_test,
        predictions,
    )

    balanced = balanced_accuracy_score(
        y_test,
        predictions,
    )

    macro_f1 = f1_score(
        y_test,
        predictions,
        average="macro",
        zero_division=0,
    )

    labels = VALID_CLASSES

    cm = confusion_matrix(
        y_test,
        predictions,
        labels=labels,
    )

    report = classification_report(
        y_test,
        predictions,
        labels=labels,
        zero_division=0,
        output_dict=True,
    )

    print()
    print("=== LIGHTGBM RESULTS ===")
    print(
        f"Accuracy: {accuracy:.4f}"
    )
    print(
        f"Balanced Accuracy: {balanced:.4f}"
    )
    print(
        f"Macro F1: {macro_f1:.4f}"
    )

    print()
    print("=== IMPROVEMENT VS MAJORITY BASELINE ===")

    print(
        f"Accuracy improvement: "
        f"{accuracy - baseline_accuracy:+.4f}"
    )

    print(
        f"Balanced Accuracy improvement: "
        f"{balanced - baseline_balanced:+.4f}"
    )

    print(
        f"Macro F1 improvement: "
        f"{macro_f1 - baseline_macro_f1:+.4f}"
    )

    # --------------------------------------------------------
    # Classification report
    # --------------------------------------------------------

    print()
    print("=== CLASSIFICATION REPORT ===")

    print(
        classification_report(
            y_test,
            predictions,
            labels=labels,
            zero_division=0,
        )
    )

    # --------------------------------------------------------
    # Confusion matrix
    # --------------------------------------------------------

    print("=== CONFUSION MATRIX ===")
    print("Rows = actual, columns = predicted")

    print(
        "              "
        + " ".join(
            f"{x:>10s}"
            for x in labels
        )
    )

    for label, row in zip(labels, cm):
        print(
            f"{label:12s} "
            + " ".join(
                f"{int(x):10d}"
                for x in row
            )
        )

    # --------------------------------------------------------
    # Feature importance
    # --------------------------------------------------------

    importance = pd.DataFrame(
        {
            "feature": feature_columns,
            "importance": model.feature_importances_,
        }
    ).sort_values(
        "importance",
        ascending=False,
    )

    # --------------------------------------------------------
    # Save model
    # --------------------------------------------------------

    model.booster_.save_model(
        str(config["model_path"])
    )

    # --------------------------------------------------------
    # Probability summary
    # --------------------------------------------------------

    class_names = list(model.classes_)

    probability_summary = {}

    for index, class_name in enumerate(class_names):
        probability_summary[
            f"{class_name.lower()}_probability_mean"
        ] = float(
            probabilities[:, index].mean()
        )

    # --------------------------------------------------------
    # Metrics artifact
    # --------------------------------------------------------

    metrics = {
        "model": "LightGBM",
        "model_version": config["model_version"],
        "horizon_trading_days": horizon,
        "target": target,
        "return_column": config["return_column"],
        "label_flag": config["label_flag"],

        "split_type": "calendar_date",
        "cutoff_date": CUTOFF_DATE.date().isoformat(),

        "rows_loaded": int(len(df)),
        "training_rows": int(len(train_df)),
        "testing_rows": int(len(test_df)),

        "train_start": (
            train_df["event_trade_date"]
            .min()
            .date()
            .isoformat()
        ),

        "train_end": (
            train_df["event_trade_date"]
            .max()
            .date()
            .isoformat()
        ),

        "test_start": (
            test_df["event_trade_date"]
            .min()
            .date()
            .isoformat()
        ),

        "test_end": (
            test_df["event_trade_date"]
            .max()
            .date()
            .isoformat()
        ),

        "feature_count": int(
            len(feature_columns)
        ),

        "categorical_feature_count": int(
            len(categorical_columns)
        ),

        "features": feature_columns,

        "backward_features": [
            feature
            for feature in backward_features
            if feature in feature_columns
        ],

        "leakage_exclusions": [
            "news_id",
            "security_id",
            "event_trade_date",
            "published_at",
            "prediction_cutoff_ts",
            "cutoff_trade_date",
            "created_at",
            "updated_at",
            "forward_return_1d",
            "forward_return_3d",
            "forward_return_5d",
            "forward_return_10d",
            "direction_1d",
            "direction_3d",
            "direction_5d",
            "direction_10d",
            "has_1d_label",
            "has_3d_label",
            "has_5d_label",
            "has_10d_label",
            "prediction_eligible",

        ],

        "target_distribution": {
            "train": {
                label: int(
                    train_distribution[label]
                )
                for label in labels
            },
            "test": {
                label: int(
                    test_distribution[label]
                )
                for label in labels
            },
        },

        "majority_baseline": {
            "class": str(majority_class),
            "accuracy": float(
                baseline_accuracy
            ),
            "balanced_accuracy": float(
                baseline_balanced
            ),
            "macro_f1": float(
                baseline_macro_f1
            ),
        },

        "lightgbm": {
            "accuracy": float(accuracy),
            "balanced_accuracy": float(balanced),
            "macro_f1": float(macro_f1),
            "classification_report": report,
            "confusion_matrix": cm.tolist(),
            "classes": class_names,
            **probability_summary,
        },
    }

    # --------------------------------------------------------
    # Save metrics
    # --------------------------------------------------------

    with open(
        config["metrics_path"],
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            metrics,
            f,
            indent=2,
        )

    # --------------------------------------------------------
    # Save feature importance
    # --------------------------------------------------------

    importance.to_csv(
        config["importance_path"],
        index=False,
    )

    # --------------------------------------------------------
    # Final output
    # --------------------------------------------------------

    print()
    print("=== ARTIFACTS SAVED ===")

    print(
        f"Model:      "
        f"{config['model_path']}"
    )

    print(
        f"Metrics:    "
        f"{config['metrics_path']}"
    )

    print(
        f"Importance: "
        f"{config['importance_path']}"
    )

    print()
    print("=" * 70)
    print("TRAINING COMPLETED SUCCESSFULLY")
    print("=" * 70)
    print(
        f"Horizon: +{horizon} trading day(s)"
    )
    print(
        f"Target:  {target}"
    )
    print(
        f"Model:   {config['model_version']}"
    )
    print(
        f"Macro F1: {macro_f1:.4f}"
    )
    print(
        f"Balanced Accuracy: {balanced:.4f}"
    )
    print("=" * 70)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
