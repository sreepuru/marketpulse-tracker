"""

MarketPulse - LightGBM Multi-Horizon Event Scoring



Purpose

-------

Score MarketPulse event-level features using the trained LightGBM

direction models for:



    +1 trading day

    +5 trading days

    +10 trading days



This is the canonical scoring script.



Important

---------

- Does NOT retrain models.

- Does NOT modify market_news.

- Does NOT modify market_news_ml_features.

- Does NOT modify market_news_ml_labels.

- Does NOT modify market_news_ai_predictions.

- Stores ML predictions separately in market_news_ml_predictions.

- Supports incremental scoring.

- Supports full re-scoring.

- Keeps each horizon/model/version independently identifiable.

- Uses the trained model's native feature order.

- Uses the trained model's pandas categorical metadata as the

  categorical source of truth.



Prediction classes

------------------

    NEGATIVE

    NEUTRAL

    POSITIVE



Prediction score

----------------

Highest class probability.



Usage

-----

Incremental 1D scoring:



    python srcbackendmarketpulse_score_lightgbm_1d.py --horizon 1



Incremental 5D scoring:



    python srcbackendmarketpulse_score_lightgbm_1d.py --horizon 5



Incremental 10D scoring:



    python srcbackendmarketpulse_score_lightgbm_1d.py --horizon 10



Incremental scoring for all three horizons:



    python srcbackendmarketpulse_score_lightgbm_1d.py --all



Full re-score for one horizon:



    python srcbackendmarketpulse_score_lightgbm_1d.py --horizon 1 --rerun-all



Full re-score for all horizons:



    python srcbackendmarketpulse_score_lightgbm_1d.py --all --rerun-all

"""



import os

import argparse

from datetime import datetime



import lightgbm as lgb

import pandas as pd

import psycopg2

from dotenv import load_dotenv

from psycopg2.extras import execute_values





# ---------------------------------------------------------------------

# Project configuration

# ---------------------------------------------------------------------



from pathlib import Path

from dotenv import load_dotenv



PROJECT_ROOT = Path(__file__).resolve().parents[4]

ENV_PATH = PROJECT_ROOT / ".env"



load_dotenv(ENV_PATH)





DB_HOST = os.getenv("MARKETPULSE_DB_HOST", "localhost")

DB_PORT = os.getenv("MARKETPULSE_DB_PORT", "5432")

DB_NAME = os.getenv("MARKETPULSE_DB_NAME", "marketpulse")

DB_USER = os.getenv("MARKETPULSE_DB_USER", "postgres")

DB_PASSWORD = os.getenv("MARKETPULSE_DB_PASSWORD")





MODEL_DIR = os.path.join(

    PROJECT_ROOT,

    "ml_models",

)





MODEL_NAME = "LightGBM"



FEATURE_TABLE = "market_news_ml_features"

OUTPUT_TABLE = "market_news_ml_predictions"





# ---------------------------------------------------------------------

# Horizon configuration

# ---------------------------------------------------------------------



HORIZON_CONFIG = {

    1: {

        "model_file": "marketpulse_lightgbm_1d_v3.txt",

        "model_version": "MarketPulse-LightGBM-1D-v3",

        "target_column": "direction_1d",

        "label_column": "has_1d_label",

    },

    5: {

        "model_file": "marketpulse_lightgbm_5d_v1.txt",

        "model_version": "MarketPulse-LightGBM-5D-v1",

        "target_column": "direction_5d",

        "label_column": "has_5d_label",

    },

    10: {

        "model_file": "marketpulse_lightgbm_10d_v1.txt",

        "model_version": "MarketPulse-LightGBM-10D-v1",

        "target_column": "direction_10d",

        "label_column": "has_10d_label",

    },

}





# ---------------------------------------------------------------------

# Feature definitions

#

# These MUST remain aligned with the multi-horizon training model.

#

# The model's native feature order remains authoritative and is applied

# again in validate_features().

# ---------------------------------------------------------------------



NUMERIC_FEATURES = [

    "publication_hour",

    "publication_minute",

    "publication_weekday",



    "close",

    "open",

    "high",

    "low",

    "volume",

    "turnover",

    "daily_return",



    "rsi_14",

    "macd",

    "macd_signal",

    "macd_hist",



    "bb_position_20",



    "sma_5",

    "sma_10",

    "sma_20",



    "ema_5",

    "ema_10",

    "ema_20",



    "atr_14",

    "volatility_20d",

    "relative_volume_20",

    "close_vs_sma20",



    "volume_ratio_5d",

    "range_pct",



    "momentum_5d",

    "momentum_10d",

    "momentum_20d",



    "return_mean_5d",

    "return_std_5d",

    "return_mean_10d",

    "return_std_10d",

    "return_mean_20d",

    "return_std_20d",



    "volatility_mean_5d",

    "volatility_mean_10d",

    "volatility_mean_20d",



    "volume_ratio_mean_5d",

    "volume_ratio_mean_10d",

    "volume_ratio_mean_20d",



    "volume_mean_5d",

    "volume_mean_20d",



    "high_20d",

    "low_20d",



    "distance_from_high_20d",

    "distance_from_low_20d",



    "max_drawdown_20d",



    "price_trend_20d",

    "volume_trend_20d",



    "sequence_rows",

    "sequence_length",



    # PIT-safe backward-looking event features.

    "backward_return_1d",

    "backward_return_5d",

    "backward_return_10d",

]





# The saved LightGBM model artifacts contain five categorical features.
# Exchange is retained as prediction identity/output metadata, not as a
# model input for these already-trained artifacts.

MODEL_CATEGORICAL_FEATURES = [
    "feed_category",
    "market_news_category",
    "ai_event_type",
    "ai_event_status",
    "ai_sentiment",
]





BOOLEAN_NUMERIC_FEATURES = [

    "is_pre_market",

    "is_post_market",

]





CATEGORICAL_FEATURES = MODEL_CATEGORICAL_FEATURES.copy()





FEATURES = (

    NUMERIC_FEATURES

    + MODEL_CATEGORICAL_FEATURES

    + BOOLEAN_NUMERIC_FEATURES

)





# Expected current model schema:

# 58 numeric + 5 categorical + 2 boolean/numeric = 65?

#

# Do not rely on this hard-coded number for inference.

# The native model.feature_name() is authoritative.

#

# This check is intentionally informational and will print the actual

# trained model feature count.





# ---------------------------------------------------------------------

# Database connection

# ---------------------------------------------------------------------



def get_connection():

    if not DB_PASSWORD:

        raise RuntimeError(

            "MARKETPULSE_DB_PASSWORD is not set in .env"

        )



    return psycopg2.connect(

        host=DB_HOST,

        port=DB_PORT,

        dbname=DB_NAME,

        user=DB_USER,

        password=DB_PASSWORD,

    )





# ---------------------------------------------------------------------

# Prediction table

# ---------------------------------------------------------------------



CREATE_TABLE_SQL = f"""

CREATE TABLE IF NOT EXISTS {OUTPUT_TABLE} (



    prediction_id BIGSERIAL PRIMARY KEY,



    news_id BIGINT NOT NULL,



    horizon INTEGER NOT NULL,



    predicted_direction TEXT NOT NULL,



    negative_probability DOUBLE PRECISION NOT NULL,



    neutral_probability DOUBLE PRECISION NOT NULL,



    positive_probability DOUBLE PRECISION NOT NULL,



    prediction_score DOUBLE PRECISION NOT NULL,



    event_trade_date DATE,



    prediction_cutoff_ts TIMESTAMP,



    predicted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,



    CONSTRAINT fk_ml_prediction_news

        FOREIGN KEY (news_id)

        REFERENCES market_news(news_id)

);

"""





# ---------------------------------------------------------------------

# Prediction table migration

#

# The existing table was originally unique on:

#

#     news_id

#

# Horizon must now be part of the identity.

#

# Existing predictions are assigned horizon = 1 because the old

# prediction table represented the 1D model.

# ---------------------------------------------------------------------



MIGRATE_TABLE_SQL = f"""
ALTER TABLE {OUTPUT_TABLE}
    ADD COLUMN IF NOT EXISTS security_id BIGINT;

ALTER TABLE {OUTPUT_TABLE}
    ADD COLUMN IF NOT EXISTS exchange VARCHAR(10);

ALTER TABLE {OUTPUT_TABLE}
    ADD COLUMN IF NOT EXISTS horizon INTEGER;

UPDATE {OUTPUT_TABLE}
SET horizon = 1
WHERE horizon IS NULL;

ALTER TABLE {OUTPUT_TABLE}
    ALTER COLUMN horizon SET NOT NULL;

ALTER TABLE {OUTPUT_TABLE}
    DROP CONSTRAINT IF EXISTS uq_market_news_ml_prediction;

DROP INDEX IF EXISTS uq_market_news_ml_prediction_horizon_idx;
DROP INDEX IF EXISTS uq_market_news_ml_prediction_event_horizon_idx;

CREATE UNIQUE INDEX IF NOT EXISTS
    uq_ml_prediction_event_security_exchange_horizon_idx
ON {OUTPUT_TABLE}
(
    news_id,
    security_id,
    exchange,
    horizon
);

CREATE INDEX IF NOT EXISTS
    idx_ml_predictions_news_id
ON {OUTPUT_TABLE}(news_id);

CREATE INDEX IF NOT EXISTS
    idx_ml_predictions_security_exchange
ON {OUTPUT_TABLE}(security_id, exchange);

CREATE INDEX IF NOT EXISTS
    idx_ml_predictions_horizon
ON {OUTPUT_TABLE}(horizon);

CREATE INDEX IF NOT EXISTS
    idx_ml_predictions_direction
ON {OUTPUT_TABLE}(predicted_direction);

CREATE INDEX IF NOT EXISTS
    idx_ml_predictions_score
ON {OUTPUT_TABLE}(prediction_score DESC);

CREATE INDEX IF NOT EXISTS
    idx_ml_predictions_predicted_at
ON {OUTPUT_TABLE}(predicted_at);
"""





# ---------------------------------------------------------------------

# Prepare output table

# ---------------------------------------------------------------------



def prepare_prediction_table(conn):

    print("nPreparing prediction table...")



    with conn.cursor() as cur:

        cur.execute(CREATE_TABLE_SQL)

        conn.commit()



        cur.execute(MIGRATE_TABLE_SQL)

        conn.commit()



    print("Prediction table: READY")





# ---------------------------------------------------------------------

# Load event feature matrix

# ---------------------------------------------------------------------



def load_features(

    conn,

    horizon,

    model_version,

    rerun_all=False,

    news_ids=None,

):

    columns = [

        "news_id",

        "security_id",

        "exchange",

        "event_trade_date",

        "prediction_cutoff_ts",

    ] + FEATURES



    if news_ids is not None:



        if not news_ids:

            return pd.DataFrame(columns=columns)



        sql = f"""

            SELECT

                {", ".join(columns)}

            FROM {FEATURE_TABLE} f

            WHERE f.news_id = ANY(%s)

              AND f.event_trade_date IS NOT NULL

              AND f.prediction_eligible = TRUE

            ORDER BY

                f.event_trade_date ASC,

                f.news_id ASC,

                f.security_id ASC,

                f.exchange ASC;

        """

        params = (list(news_ids),)



    elif rerun_all:



        sql = f"""

            SELECT

                {", ".join(columns)}

            FROM {FEATURE_TABLE} f

            WHERE f.event_trade_date IS NOT NULL

              AND f.prediction_eligible = TRUE

            ORDER BY

                f.event_trade_date ASC,

                f.news_id ASC,

                f.security_id ASC,

                f.exchange ASC;

        """



        params = None



    else:



        sql = f"""

            SELECT

                {", ".join(columns)}

            FROM {FEATURE_TABLE} f

            WHERE f.event_trade_date IS NOT NULL

              AND f.prediction_eligible = TRUE

              AND NOT EXISTS (

                  SELECT 1

                  FROM {OUTPUT_TABLE} p

                  WHERE p.news_id = f.news_id

                    AND p.security_id = f.security_id

                    AND p.exchange = f.exchange

                    AND p.horizon = %s

              )

            ORDER BY

                f.event_trade_date ASC,

                f.news_id ASC,

                f.security_id ASC,

                f.exchange ASC;

        """



        params = (

            horizon,

        )



    print("nLoading event feature matrix...")



    if news_ids is not None:

        print("Mode: EXACT-ID")

        print(f"Scoring exactly {len(news_ids):,} requested events for +{horizon}D.")

    elif rerun_all:

        print("Mode: FULL RE-SCORE")

        print(

            f"Recalculating all prediction-eligible events "

            f"for +{horizon}D."

        )

    else:

        print("Mode: INCREMENTAL")

        print(

            f"Scoring only events without an existing "

            f"+{horizon}D prediction."

        )



    df = pd.read_sql_query(

        sql,

        conn,

        params=params,

    )



    if rerun_all:

        label = "Prediction-eligible rows to re-score"

    else:

        label = "New rows eligible for scoring"



    print(f"{label}: {len(df):,}")



    return df





# ---------------------------------------------------------------------

# Prepare features

# ---------------------------------------------------------------------



def prepare_features(df, model):

    if df.empty:

        raise RuntimeError(

            f"No rows found in {FEATURE_TABLE}"

        )



    metadata = df[

        [

            "news_id",

            "security_id",

            "exchange",

            "event_trade_date",

            "prediction_cutoff_ts",

        ]

    ].copy()



    X = df[FEATURES].copy()



    # -------------------------------------------------------------

    # Model categorical metadata

    # -------------------------------------------------------------



    model_categories = getattr(

        model,

        "pandas_categorical",

        None,

    )



    if not model_categories:

        raise RuntimeError(

            "Loaded LightGBM model does not contain pandas "

            "categorical metadata."

        )



    expected_category_count = len(

        MODEL_CATEGORICAL_FEATURES

    )



    if len(model_categories) != expected_category_count:

        raise RuntimeError(

            "Categorical feature metadata mismatch. "

            f"Model has {len(model_categories)} categorical "

            f"definitions, but scoring expects "

            f"{expected_category_count}."

        )



    print(

        "nTrained model categorical metadata count: "

        f"{len(model_categories)}"

    )



    model_category_map = dict(

        zip(

            MODEL_CATEGORICAL_FEATURES,

            model_categories,

        )

    )



    # -------------------------------------------------------------

    # Categorical features

    # -------------------------------------------------------------



    for col in MODEL_CATEGORICAL_FEATURES:



        categories = model_category_map.get(col)



        if categories is None:

            raise RuntimeError(

                f"Model categorical metadata missing for '{col}'."

            )



        values = X[col].astype("string")



        unique_values = set(

            values.dropna().unique()

        )



        known_categories = set(categories)



        unknown = sorted(

            unique_values - known_categories

        )



        if unknown:

            raise RuntimeError(

                f"Unknown categorical values found in '{col}': "

                f"{unknown}. "

                "These values were not present during model "

                "training. The current model cannot safely "

                "score these events."

            )



        X[col] = pd.Categorical(

            values,

            categories=categories,

        )



        print(

            f"  {col}: {len(categories)} categories"

        )



    # -------------------------------------------------------------

    # Boolean/session features

    #

    # Training stores these as numeric features.

    # -------------------------------------------------------------



    for col in BOOLEAN_NUMERIC_FEATURES:



        X[col] = pd.to_numeric(

            X[col],

            errors="coerce",

        )



    # -------------------------------------------------------------

    # Numeric features

    # -------------------------------------------------------------



    for col in NUMERIC_FEATURES:



        X[col] = pd.to_numeric(

            X[col],

            errors="coerce",

        )



    return metadata, X





# ---------------------------------------------------------------------

# Validate feature matrix

# ---------------------------------------------------------------------



def validate_features(X, model):



    model_features = list(

        model.feature_name()

    )



    scoring_features = list(

        X.columns

    )



    missing = [

        col

        for col in model_features

        if col not in scoring_features

    ]



    if missing:

        raise RuntimeError(

            "Missing model features:n"

            + "n".join(

                f"  - {col}"

                for col in missing

            )

        )



    extra = [

        col

        for col in scoring_features

        if col not in model_features

    ]



    if extra:

        print(

            "nWarning: scoring matrix contains extra "

            "features not used by this model:"

        )



        for col in extra:

            print(f"  - {col}")



    # The native model feature order is authoritative.

    X = X[model_features].copy()



    print("nFeature validation: PASS")

    print(

        f"Trained model feature count: "

        f"{len(model_features)}"

    )

    print(

        f"Scoring matrix feature count: "

        f"{len(X.columns)}"

    )



    if model_features != list(X.columns):

        raise RuntimeError(

            "Feature ordering mismatch after reordering."

        )



    print("Feature order: PASS")



    return X





# ---------------------------------------------------------------------

# Score model

# ---------------------------------------------------------------------



def score_model(model, X):



    print("nRunning LightGBM inference...")



    probabilities = model.predict(X)



    if probabilities.ndim != 2:

        raise RuntimeError(

            "Unexpected prediction shape: "

            f"{probabilities.shape}"

        )



    if probabilities.shape[1] != 3:

        raise RuntimeError(

            "Expected 3 prediction classes, got "

            f"{probabilities.shape[1]}"

        )



    # LightGBM class order for the trained direction target is:

    #

    #   0 = NEGATIVE

    #   1 = NEUTRAL

    #   2 = POSITIVE

    #

    # This matches the training label encoding.



    negative_probability = probabilities[:, 0]

    neutral_probability = probabilities[:, 1]

    positive_probability = probabilities[:, 2]



    predicted_indexes = probabilities.argmax(

        axis=1

    )



    direction_map = {

        0: "NEGATIVE",

        1: "NEUTRAL",

        2: "POSITIVE",

    }



    predicted_direction = [

        direction_map[int(index)]

        for index in predicted_indexes

    ]



    prediction_score = probabilities.max(

        axis=1

    )



    # Basic probability sanity check.

    probability_sums = probabilities.sum(

        axis=1

    )



    if not (

        abs(probability_sums - 1.0) < 1e-5

    ).all():

        raise RuntimeError(

            "Prediction probabilities do not sum to 1 "

            "within tolerance."

        )



    return (

        predicted_direction,

        negative_probability,

        neutral_probability,

        positive_probability,

        prediction_score,

    )





# ---------------------------------------------------------------------

# Persist predictions

# ---------------------------------------------------------------------



def save_predictions(

    conn,

    metadata,

    horizon,

    predicted_direction,

    negative_probability,

    neutral_probability,

    positive_probability,

    prediction_score,

):



    predicted_at = datetime.now()



    rows = []



    for i in range(len(metadata)):



        rows.append(

            (

                int(

                    metadata.iloc[i]["news_id"]

                ),




                int(metadata.iloc[i]["security_id"]),

                str(metadata.iloc[i]["exchange"]),

                predicted_direction[i],



                float(

                    negative_probability[i]

                ),



                float(

                    neutral_probability[i]

                ),



                float(

                    positive_probability[i]

                ),



                float(

                    prediction_score[i]

                ),



                metadata.iloc[i][

                    "event_trade_date"

                ],



                metadata.iloc[i][

                    "prediction_cutoff_ts"

                ],



                predicted_at,



                horizon,

            )

        )



    if not rows:

        print(

            "nNo predictions to persist."

        )

        return



    sql = f"""

        INSERT INTO {OUTPUT_TABLE} (

            news_id,

            security_id,

            exchange,

            predicted_direction,



            negative_probability,

            neutral_probability,

            positive_probability,



            prediction_score,



            event_trade_date,

            prediction_cutoff_ts,



            predicted_at,

            horizon

        )

        VALUES %s



        ON CONFLICT (

            news_id,

            security_id,

            exchange,

            horizon

        )

        DO UPDATE SET



            predicted_direction =

                EXCLUDED.predicted_direction,



            negative_probability =

                EXCLUDED.negative_probability,



            neutral_probability =

                EXCLUDED.neutral_probability,



            positive_probability =

                EXCLUDED.positive_probability,



            prediction_score =

                EXCLUDED.prediction_score,



            event_trade_date =

                EXCLUDED.event_trade_date,



            prediction_cutoff_ts =

                EXCLUDED.prediction_cutoff_ts,



            predicted_at =

                EXCLUDED.predicted_at;

    """



    print(

        f"nPersisting +{horizon}D predictions..."

    )



    with conn.cursor() as cur:



        execute_values(

            cur,

            sql,

            rows,

            page_size=5000,

        )



    conn.commit()



    print(

        f"Predictions persisted: "

        f"{len(rows):,}"

    )



# ---------------------------------------------------------------------

# Verification

# ---------------------------------------------------------------------



def verify_predictions(

    conn,

    horizon,

    model_version,

):



    print("n" + "-" * 70)

    print(

        f"PREDICTION VERIFICATION - +{horizon}D"

    )

    print("-" * 70)



    with conn.cursor() as cur:



        # ---------------------------------------------------------

        # Overall count

        # ---------------------------------------------------------



        cur.execute(

            f"""

            SELECT

                COUNT(*) AS total_predictions,

                COUNT(DISTINCT news_id) AS distinct_events,

                COUNT(DISTINCT security_id) AS distinct_securities,

                COUNT(DISTINCT (news_id, security_id, exchange)) AS distinct_exchange_rows,

                MIN(predicted_at) AS first_prediction,

                MAX(predicted_at) AS last_prediction

            FROM {OUTPUT_TABLE}

            WHERE horizon = %s;

            """,

            (

                horizon,

            ),

        )



        total = cur.fetchone()



        print(

            f"Total predictions: {total[0]:,}"

        )



        print(

            f"Distinct events:   {total[1]:,}"
        )
        print(
            f"Distinct securities: {total[2]:,}"
        )
        print(
            f"Distinct exchange rows: {total[3]:,}"

        )



        print(

            f"First prediction:  {total[2]}"

        )



        print(

            f"Last prediction:   {total[3]}"

        )



        # ---------------------------------------------------------

        # Direction distribution

        # ---------------------------------------------------------



        cur.execute(

            f"""

            SELECT

                predicted_direction,

                COUNT(*) AS count

            FROM {OUTPUT_TABLE}

            WHERE horizon = %s

            GROUP BY predicted_direction

            ORDER BY predicted_direction;

            """,

            (

                horizon,

            ),

        )



        print(

            "nDirection distribution:"

        )



        for direction, count in cur.fetchall():



            print(

                f"  {direction:<10} "

                f"{count:>10,}"

            )



        # ---------------------------------------------------------

        # Prediction score

        # ---------------------------------------------------------



        cur.execute(

            f"""

            SELECT

                MIN(prediction_score),

                MAX(prediction_score),

                AVG(prediction_score)

            FROM {OUTPUT_TABLE}

            WHERE horizon = %s;

            """,

            (

                horizon,

            ),

        )



        scores = cur.fetchone()



        print(

            "nPrediction score:"

        )



        if scores[0] is not None:



            print(

                f"  Minimum: "

                f"{scores[0]:.4f}"

            )



            print(

                f"  Maximum: "

                f"{scores[1]:.4f}"

            )



            print(

                f"  Average: "

                f"{scores[2]:.4f}"

            )



        # ---------------------------------------------------------

        # Duplicate check

        # ---------------------------------------------------------



        cur.execute(

            f"""

           SELECT

                news_id,

                horizon,

                COUNT(*) AS duplicate_count

            FROM {OUTPUT_TABLE}

            WHERE horizon = %s

            GROUP BY

                news_id,

                security_id,

                exchange,

                horizon

            HAVING COUNT(*) > 1

            LIMIT 10;

            """,

            (

                horizon,

            ),

        )



        duplicates = cur.fetchall()



        if duplicates:



            print(

                "nWARNING: duplicate predictions found:"

            )



            for row in duplicates:

                print(row)



            raise RuntimeError(

                "Prediction duplicate verification failed."

            )



        print(

            "nDuplicate check: PASS"

        )





# ---------------------------------------------------------------------

# Score one horizon

# ---------------------------------------------------------------------



def score_horizon(

    conn,

    horizon,

    rerun_all=False,

    news_ids=None,

):



    config = HORIZON_CONFIG[horizon]



    model_file = config["model_file"]

    model_version = config["model_version"]



    model_path = os.path.join(

        MODEL_DIR,

        model_file,

    )



    print("n")

    print("=" * 70)

    print(

        f"MARKETPULSE - LIGHTGBM +{horizon}D EVENT SCORING"

    )

    print("=" * 70)



    print(

        f"nHorizon: +{horizon} trading days"

    )



    print(

        f"Model: {model_file}"

    )



    print(

        f"Version: {model_version}"

    )



    print(

        f"Target: {config['target_column']}"

    )



    print(

        f"Label flag: {config['label_column']}"

    )



    # -------------------------------------------------------------

    # Model existence

    # -------------------------------------------------------------



    if not os.path.exists(model_path):



        raise FileNotFoundError(

            "LightGBM model not found:n"

            f"{model_path}"

        )



    # -------------------------------------------------------------

    # Load model

    # -------------------------------------------------------------



    print(

        "nLoading LightGBM model..."

    )



    model = lgb.Booster(

        model_file=model_path

    )



    print(

        "Model loaded successfully."

    )



    trained_features = list(

        model.feature_name()

    )



    print(

        f"Trained model feature count: "

        f"{len(trained_features)}"

    )



    model_categories = getattr(

        model,

        "pandas_categorical",

        [],

    )



    print(

        "Trained model categorical metadata count: "

        f"{len(model_categories)}"

    )



    # -------------------------------------------------------------

    # Load features

    # -------------------------------------------------------------



    df = load_features(

        conn=conn,

        horizon=horizon,

        model_version=model_version,

        rerun_all=rerun_all,

        news_ids=news_ids,

    )



    # -------------------------------------------------------------

    # Nothing to score

    # -------------------------------------------------------------



    if df.empty:



        if rerun_all:



            print(

                f"nNo prediction-eligible feature events "

                f"found for +{horizon}D."

            )



        else:



            print(

                f"nNo new +{horizon}D feature events "

                f"require scoring."

            )



            print(

                "Existing predictions are left unchanged."

            )



        print(

            "nNo new predictions for this horizon."

        )



        return



    # -------------------------------------------------------------

    # Prepare features

    # -------------------------------------------------------------



    metadata, X = prepare_features(

        df,

        model,

    )



    # -------------------------------------------------------------

    # Validate/reorder

    # -------------------------------------------------------------



    X = validate_features(

        X,

        model,

    )



    # -------------------------------------------------------------

    # Score

    # -------------------------------------------------------------



    (

        predicted_direction,

        negative_probability,

        neutral_probability,

        positive_probability,

        prediction_score,

    ) = score_model(

        model,

        X,

    )



    # -------------------------------------------------------------

    # Persist

    # -------------------------------------------------------------



    save_predictions(

        conn=conn,

        metadata=metadata,

        horizon=horizon,

        predicted_direction=predicted_direction,

        negative_probability=negative_probability,

        neutral_probability=neutral_probability,

        positive_probability=positive_probability,

        prediction_score=prediction_score,

    )



    # -------------------------------------------------------------

    # Verify

    # -------------------------------------------------------------



    verify_predictions(

        conn=conn,

        horizon=horizon,

        model_version=model_version,

    )



    print("n" + "=" * 70)

    print(

        f"+{horizon}D SCORING SUCCESS"

    )

    print("=" * 70)





# ---------------------------------------------------------------------

# Argument parsing

# ---------------------------------------------------------------------



def parse_arguments():



    parser = argparse.ArgumentParser(

        description=(

            "Score MarketPulse event features using "

            "the LightGBM +1D, +5D and +10D models."

        )

    )



    parser.add_argument(

        "--horizon",

        type=int,

        choices=[1, 5, 10],

        help=(

            "Prediction horizon in trading days. "

            "Use 1, 5 or 10."

        ),

    )



    parser.add_argument(

        "--all",

        action="store_true",

        help=(

            "Run incremental scoring for all three "

            "horizons: +1D, +5D and +10D."

        ),

    )



    parser.add_argument(

        "--rerun-all",

        action="store_true",

        help=(

            "Re-score every prediction-eligible feature "

            "row for the selected horizon(s)."

        ),

    )



    parser.add_argument(

        "--news-ids-file",

        type=str,

        help="Score exactly the news_id values listed in this file.",

    )



    args = parser.parse_args()



    if args.horizon is None and not args.all:



        parser.error(

            "Specify either --horizon 1|5|10 or --all."

        )



    if args.horizon is not None and args.all:



        parser.error(

            "Use either --horizon or --all, not both."

        )



    if args.news_ids_file and args.rerun_all:

        parser.error("--news-ids-file cannot be combined with --rerun-all.")



    return args





# ---------------------------------------------------------------------

# Main

# ---------------------------------------------------------------------



def main():



    args = parse_arguments()



    conn = None



    news_ids = None

    if args.news_ids_file:

        news_ids = [

            int(line.strip())

            for line in open(args.news_ids_file, "r", encoding="utf-8")

            if line.strip() and not line.lstrip().startswith("#")

        ]

        if len(news_ids) != len(set(news_ids)):

            raise ValueError("--news-ids-file contains duplicate news_id values.")



    try:



        # ---------------------------------------------------------

        # Connect

        # ---------------------------------------------------------



        conn = get_connection()



        print(

            "nDatabase connection: SUCCESS"

        )



        # ---------------------------------------------------------

        # Prepare prediction table

        # ---------------------------------------------------------



        prepare_prediction_table(

            conn

        )



        # ---------------------------------------------------------

        # Determine horizons

        # ---------------------------------------------------------



        if args.all:



            horizons = [1, 5, 10]



        else:



            horizons = [args.horizon]



        # ---------------------------------------------------------

        # Score horizons

        # ---------------------------------------------------------



        for horizon in horizons:



            score_horizon(

                conn=conn,

                horizon=horizon,

                rerun_all=args.rerun_all,

                news_ids=news_ids,

            )



        # ---------------------------------------------------------

        # Final summary

        # ---------------------------------------------------------



        print("n")

        print("=" * 70)

        print("MARKETPULSE MULTI-HORIZON SCORING COMPLETE")

        print("=" * 70)



        if args.rerun_all:



            print(

                "nMode: FULL RE-SCORE"

            )



        else:



            print(

                "nMode: INCREMENTAL"

            )



        print(

            "nHorizons processed:"

        )



        for horizon in horizons:



            version = HORIZON_CONFIG[

                horizon

            ]["model_version"]



            print(

                f"  +{horizon}D -> {version}"

            )



        print(

            "nPrediction table:"

            f" {OUTPUT_TABLE}"

        )



        print(

            "nSUCCESS"

        )



    except Exception:



        if conn is not None:



            conn.rollback()



        raise



    finally:



        if conn is not None:



            conn.close()





# ---------------------------------------------------------------------

# Entry point

# ---------------------------------------------------------------------



if __name__ == "__main__":

    main()