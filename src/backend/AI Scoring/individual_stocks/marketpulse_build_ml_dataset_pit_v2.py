"""

MarketPulse ML Dataset Builder - Point-in-Time Safe V2 (NSE Tier A+B)



Builds up to 60 completed trading-session inputs for each eligible NSE STOCK news event.



Batch-oriented implementation: context and prices are loaded per batch, and

samples/labels are written in bulk to reduce database round-trips.



Point-in-time rule:

    - During market hours (<= 15:30 IST), use only sessions before the

      publication date.

    - After market close (> 15:30 IST), the publication day's close is usable.



Forward labels start AFTER the base/cutoff session:

    1D = first subsequent trading session

    3D = third subsequent trading session

    5D = fifth subsequent trading session

    10D = tenth subsequent trading session



This prevents the event day's closing price from leaking into an intraday

prediction.



The target thresholds are provisional and should be recalibrated on the

larger historical news population before production training.

"""



from __future__ import annotations



import argparse

import os

from datetime import date, datetime, time, timedelta

from pathlib import Path

from typing import Any

from zoneinfo import ZoneInfo



import psycopg

from dotenv import load_dotenv



LOOKBACK_DAYS = 60

POSITIVE_THRESHOLD = 0.0075

NEGATIVE_THRESHOLD = -0.0075



MARKET_CLOSE = time(15, 30)

IST = ZoneInfo("Asia/Kolkata")





def load_environment() -> None:

    candidates = [

        Path.cwd() / ".env",

        Path(__file__).resolve().parents[2] / ".env",

    ]



    for candidate in candidates:

        if candidate.exists():

            load_dotenv(candidate)

            return



    load_dotenv()





def db_config() -> dict[str, Any]:

    config = {

        "host": os.getenv("MARKETPULSE_DB_HOST", "localhost"),

        "port": int(os.getenv("MARKETPULSE_DB_PORT", "5432")),

        "dbname": os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),

        "user": os.getenv("MARKETPULSE_DB_USER", "postgres"),

        "password": os.getenv("MARKETPULSE_DB_PASSWORD", ""),

    }



    if not config["password"]:

        raise RuntimeError(

            "MARKETPULSE_DB_PASSWORD is not configured. Check .env."

        )



    return config





def get_connection() -> psycopg.Connection:

    return psycopg.connect(**db_config())





def normalize_datetime(value: datetime) -> datetime:

    if value.tzinfo is None:

        return value.replace(tzinfo=IST)



    return value.astimezone(IST)





def prediction_cutoff(published_at: datetime) -> datetime:

    """

    Return the timestamp representing the last completed daily session that

    is safe to use for an event published at published_at.

    """

    published_at = normalize_datetime(published_at)



    if published_at.time() > MARKET_CLOSE:

        return published_at.replace(

            hour=23,

            minute=59,

            second=59,

            microsecond=999999,

        )



    previous_day = published_at.date() - timedelta(days=1)



    return datetime.combine(

        previous_day,

        time(23, 59, 59, 999999),

        tzinfo=IST,

    )





def get_news_ids(

    limit: int | None,

    start_id: int | None,

    end_id: int | None,

    news_ids: list[int] | None = None,

) -> list[int]:

    if news_ids is not None:

        if not news_ids:

            return []

        sql = """

            SELECT mn.news_id

            FROM market_news mn

            WHERE mn.news_id = ANY(%s)

              AND mn.news_scope = 'STOCK'

              AND mn.security_id IS NOT NULL

              AND mn.published_at IS NOT NULL

            ORDER BY mn.news_id ASC

        """

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute(sql, (news_ids,))

                found = [int(row[0]) for row in cur.fetchall()]

        missing = sorted(set(news_ids) - set(found))

        if missing:

            raise RuntimeError(

                f"Exact-ID mode: requested news_ids are not eligible/mapped: {missing}"

            )

        return found



    conditions = [

        "mn.news_scope = 'STOCK'",

        "mn.security_id IS NOT NULL",

        "mn.published_at IS NOT NULL",

    ]



    params: list[Any] = []



    if start_id is not None:

        conditions.append("mn.news_id >= %s")

        params.append(start_id)



    if end_id is not None:

        conditions.append("mn.news_id <= %s")

        params.append(end_id)



    sql = f"""

        SELECT mn.news_id

        FROM market_news mn

        WHERE {" AND ".join(conditions)}

        ORDER BY mn.news_id ASC

    """



    if limit is not None:

        sql += " LIMIT %s"

        params.append(limit)



    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(sql, tuple(params))

            return [int(row[0]) for row in cur.fetchall()]





def load_contexts(

    conn: psycopg.Connection,

    news_ids: list[int],

) -> dict[int, dict[str, Any]]:

    """Load event context for a batch in one database round-trip."""

    if not news_ids:

        return {}



    sql = """

        SELECT
            mn.news_id,
            mn.security_id,
            sm.exchange_tag,
            mn.category,
            mn.published_at,
            p.predicted_event_type,
            p.predicted_event_status
        FROM market_news mn
        JOIN security_master sm
            ON sm.security_id = mn.security_id
        LEFT JOIN LATERAL (
            SELECT
                predicted_event_type,
                predicted_event_status
            FROM market_news_ai_predictions p
            WHERE p.news_id = mn.news_id
            ORDER BY p.predicted_at DESC, p.prediction_id DESC
            LIMIT 1
        ) p ON TRUE
        WHERE mn.news_id = ANY(%s)
        AND mn.news_scope = 'STOCK'
        AND mn.security_id IS NOT NULL
        AND mn.published_at IS NOT NULL;
    """



    columns = [
        "news_id",
        "security_id",
        "exchange_tag",
        "category",
        "published_at",
        "predicted_event_type",
        "predicted_event_status",
    ]



    with conn.cursor() as cur:

        cur.execute(sql, (news_ids,))

        rows = cur.fetchall()



    return {

        int(row[0]): dict(zip(columns, row))

        for row in rows

    }





def load_history(
    conn: psycopg.Connection,
    security_id: int,
    exchange: str,
    cutoff_date,
) -> list[dict[str, Any]]:
    sql = """
        SELECT trade_date, open, high, low, close, volume, turnover
        FROM daily_prices
        WHERE security_id = %s
          AND exchange = %s
          AND trade_date <= %s
        ORDER BY trade_date DESC
        LIMIT %s;
    """

    columns = ["trade_date", "open", "high", "low", "close", "volume", "turnover"]
    with conn.cursor() as cur:
        cur.execute(sql, (security_id, exchange, cutoff_date, LOOKBACK_DAYS))
        rows = cur.fetchall()
    result = [dict(zip(columns, row)) for row in rows]
    result.reverse()
    return result


def load_future(
    conn: psycopg.Connection,
    security_id: int,
    exchange: str,
    base_trade_date,
) -> list[dict[str, Any]]:
    sql = """
        SELECT trade_date, close
        FROM daily_prices
        WHERE security_id = %s
          AND exchange = %s
          AND trade_date > %s
        ORDER BY trade_date ASC
        LIMIT 10;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (security_id, exchange, base_trade_date))
        return [{"trade_date": row[0], "close": row[1]} for row in cur.fetchall()]


def exchange_options(exchange_tag: str | None) -> list[str]:
    tag = (exchange_tag or "NSE").strip().upper()
    if tag == "BOTH":
        return ["NSE", "BSE"]
    if tag == "BSE":
        return ["BSE"]
    return ["NSE"]


def load_price_cache(
    conn: psycopg.Connection,
    contexts: dict[int, dict[str, Any]],
) -> dict[tuple[int, str], list[dict[str, Any]]]:
    if not contexts:
        return {}

    securities = sorted({int(ctx["security_id"]) for ctx in contexts.values()})
    cutoff_dates = [prediction_cutoff(ctx["published_at"]).date() for ctx in contexts.values()]
    min_cutoff = min(cutoff_dates)
    max_cutoff = max(cutoff_dates)
    min_date = min_cutoff - timedelta(days=140)
    max_date = max_cutoff + timedelta(days=20)

    sql = """
        SELECT security_id, exchange, trade_date, open, high, low, close, volume, turnover
        FROM daily_prices
        WHERE security_id = ANY(%s)
          AND trade_date BETWEEN %s AND %s
          AND exchange IN ('NSE', 'BSE')
        ORDER BY security_id, exchange, trade_date ASC;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (securities, min_date, max_date))
        fetched = cur.fetchall()

    columns = ["security_id", "exchange", "trade_date", "open", "high", "low", "close", "volume", "turnover"]
    cache: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for row in fetched:
        item = dict(zip(columns, row))
        key = (int(item["security_id"]), str(item["exchange"]).upper())
        cache.setdefault(key, []).append(item)
    return cache


def get_history_from_cache(
    price_cache: dict[tuple[int, str], list[dict[str, Any]]],
    security_id: int,
    exchange: str,
    cutoff_date: date,
) -> list[dict[str, Any]]:
    rows = [row for row in price_cache.get((security_id, exchange), []) if row["trade_date"] <= cutoff_date]
    return rows[-LOOKBACK_DAYS:]


def get_future_from_cache(
    price_cache: dict[tuple[int, str], list[dict[str, Any]]],
    security_id: int,
    exchange: str,
    base_trade_date: date,
) -> list[dict[str, Any]]:
    rows = [row for row in price_cache.get((security_id, exchange), []) if row["trade_date"] > base_trade_date]
    return [{"trade_date": row["trade_date"], "close": row["close"]} for row in rows[:10]]


def safe_float(value: Any) -> float | None:

    try:

        return None if value is None else float(value)

    except (TypeError, ValueError):

        return None





def rolling_mean(

    values: list[float],

    window: int,

) -> float | None:

    if len(values) < window:

        return None

    return sum(values[-window:]) / window





def rolling_std(

    values: list[float],

    window: int,

) -> float | None:

    if len(values) < window:

        return None



    segment = values[-window:]

    mean = sum(segment) / len(segment)



    variance = sum(

        (x - mean) ** 2 for x in segment

    ) / max(len(segment) - 1, 1)



    return variance ** 0.5





def ema(

    values: list[float],

    span: int,

) -> list[float]:

    if not values:

        return []



    alpha = 2.0 / (span + 1.0)

    result = [values[0]]



    for value in values[1:]:

        result.append(

            alpha * value

            + (1.0 - alpha) * result[-1]

        )



    return result





def rsi(

    values: list[float],

    period: int = 14,

) -> float | None:

    if len(values) <= period:

        return None



    changes = [

        values[i] - values[i - 1]

        for i in range(1, len(values))

    ]



    gains = [max(x, 0.0) for x in changes]

    losses = [max(-x, 0.0) for x in changes]



    avg_gain = sum(gains[:period]) / period

    avg_loss = sum(losses[:period]) / period



    for i in range(period, len(changes)):

        avg_gain = (

            (avg_gain * (period - 1))

            + gains[i]

        ) / period



        avg_loss = (

            (avg_loss * (period - 1))

            + losses[i]

        ) / period



    if avg_loss == 0:

        return 100.0



    rs = avg_gain / avg_loss

    return 100.0 - (100.0 / (1.0 + rs))





def macd(

    values: list[float],

) -> tuple[float | None, float | None, float | None]:

    if len(values) < 35:

        return None, None, None



    ema12 = ema(values, 12)

    ema26 = ema(values, 26)



    offset = len(ema12) - len(ema26)



    macd_values = [

        ema12[offset + i] - ema26[i]

        for i in range(len(ema26))

    ]



    if len(macd_values) < 9:

        return macd_values[-1], None, None



    signal_values = ema(macd_values, 9)

    line = macd_values[-1]

    signal = signal_values[-1]



    return line, signal, line - signal





def bollinger(

    values: list[float],

    window: int = 20,

) -> tuple[float | None, float | None, float | None, float | None]:

    if len(values) < window:

        return None, None, None, None



    middle = rolling_mean(values, window)

    std = rolling_std(values, window)



    if middle is None or std is None:

        return None, None, None, None



    upper = middle + (2.0 * std)

    lower = middle - (2.0 * std)

    current = values[-1]



    position = None



    if upper != lower:

        position = (current - lower) / (upper - lower)



    return middle, upper, lower, position





def atr(

    rows: list[dict[str, Any]],

    period: int = 14,

) -> float | None:

    if len(rows) <= period:

        return None



    ranges: list[float] = []



    for i in range(1, len(rows)):

        high = safe_float(rows[i]["high"])

        low = safe_float(rows[i]["low"])

        prev_close = safe_float(rows[i - 1]["close"])



        if None in (high, low, prev_close):

            continue



        ranges.append(

            max(

                high - low,

                abs(high - prev_close),

                abs(low - prev_close),

            )

        )



    if len(ranges) < period:

        return None



    return sum(ranges[-period:]) / period





def build_row_features(

    rows: list[dict[str, Any]],

) -> list[dict[str, Any]]:

    """

    Build sequence-level features per trading row.

    All calculations use only observations at or before that row.

    """

    closes: list[float] = []

    volumes: list[float] = []

    returns: list[float] = []



    output: list[dict[str, Any]] = []



    for row in rows:



        close = safe_float(row["close"])

        volume = safe_float(row["volume"])

        high = safe_float(row["high"])

        low = safe_float(row["low"])



        daily_return = None



        if (

            close is not None

            and closes

            and closes[-1] != 0

        ):

            daily_return = close / closes[-1] - 1.0

            returns.append(daily_return)



        range_pct = None



        if (

            close not in (None, 0)

            and high is not None

            and low is not None

        ):

            range_pct = (high - low) / close



        output.append(

            {

                **row,

                "daily_return": daily_return,

                "volume_ratio_5d": (

                    None

                    if (

                        volume is None

                        or rolling_mean(volumes, 5) in (None, 0)

                    )

                    else volume / rolling_mean(volumes, 5)

                ),

                "range_pct": range_pct,

                "volatility_5d": (

                    rolling_std(returns, 5)

                    if len(returns) >= 5

                    else None

                ),

                "momentum_5d": (

                    None

                    if close is None

                    or len(closes) < 5

                    or closes[-5] == 0

                    else close / closes[-5] - 1.0

                ),

                "momentum_10d": (

                    None

                    if close is None

                    or len(closes) < 10

                    or closes[-10] == 0

                    else close / closes[-10] - 1.0

                ),

                "momentum_20d": (

                    None

                    if close is None

                    or len(closes) < 20

                    or closes[-20] == 0

                    else close / closes[-20] - 1.0

                ),

            }

        )



        if close is not None:

            closes.append(close)



        if volume is not None:

            volumes.append(volume)



    return output





def direction_from_return(

    value: float | None,

) -> str | None:

    if value is None:

        return None



    if value >= POSITIVE_THRESHOLD:

        return "POSITIVE"



    if value <= NEGATIVE_THRESHOLD:

        return "NEGATIVE"



    return "NEUTRAL"





def calculate_labels(

    base_close: Any,

    future_rows: list[dict[str, Any]],

) -> dict[str, Any]:

    base = safe_float(base_close)



    output: list[float | None] = []



    for index in (0, 2, 4, 9):



        if len(future_rows) <= index:

            output.append(None)

            continue



        future_close = safe_float(

            future_rows[index]["close"]

        )



        if base in (None, 0) or future_close is None:

            output.append(None)

        else:

            output.append(

                future_close / base - 1.0

            )



    return {

        "forward_return_1d": output[0],

        "forward_return_3d": output[1],

        "forward_return_5d": output[2],

        "forward_return_10d": output[3],

        "direction_1d": direction_from_return(output[0]),

        "direction_3d": direction_from_return(output[1]),

        "direction_5d": direction_from_return(output[2]),

        "direction_10d": direction_from_return(output[3]),

    }





def build_sample_payload(
    context: dict[str, Any],
    exchange: str,
    rows: list[dict[str, Any]],
    labels: dict[str, Any],
    cutoff_ts: datetime,
    cutoff_trade_date: date,
) -> tuple[list[tuple[Any, ...]], tuple[Any, ...]]:
    news_id = int(context["news_id"])
    security_id = int(context["security_id"])
    event_date = context["published_at"].date()

    closes = [x for x in (safe_float(row["close"]) for row in rows) if x is not None]
    indicators = {
        "rsi_14": rsi(closes, 14), "macd": None, "macd_signal": None, "macd_hist": None,
        "bb_position_20": None, "sma_5": rolling_mean(closes, 5), "sma_10": rolling_mean(closes, 10),
        "sma_20": rolling_mean(closes, 20), "ema_5": ema(closes, 5)[-1] if closes else None,
        "ema_10": ema(closes, 10)[-1] if closes else None, "ema_20": ema(closes, 20)[-1] if closes else None,
        "atr_14": atr(rows, 14), "volatility_20d": None, "relative_volume_20": None, "close_vs_sma20": None,
    }
    ml, ms, mh = macd(closes)
    indicators.update(macd=ml, macd_signal=ms, macd_hist=mh)
    _, _, _, bb_position = bollinger(closes, 20)
    indicators["bb_position_20"] = bb_position
    if len(closes) >= 21:
        returns = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
        indicators["volatility_20d"] = rolling_std(returns, 20)
    volumes = [x for x in (safe_float(row["volume"]) for row in rows) if x is not None]
    avg_volume_20 = rolling_mean(volumes, 20)
    if avg_volume_20 not in (None, 0) and volumes:
        indicators["relative_volume_20"] = volumes[-1] / avg_volume_20
    if indicators["sma_20"] not in (None, 0) and closes:
        indicators["close_vs_sma20"] = closes[-1] / indicators["sma_20"] - 1.0

    sample_rows = []
    for position, row in enumerate(rows, start=1):
        sample_rows.append((
            news_id, security_id, exchange, cutoff_trade_date, event_date, position, row["trade_date"],
            row["close"], row["open"], row["high"], row["low"], row["volume"], row["turnover"],
            row["daily_return"], row["volume_ratio_5d"], row["range_pct"], row["volatility_5d"],
            row["momentum_5d"], row["momentum_10d"], row["momentum_20d"], context["category"],
            context["predicted_event_type"], context["predicted_event_status"], None, cutoff_ts, cutoff_trade_date,
            indicators["rsi_14"], indicators["macd"], indicators["macd_signal"], indicators["macd_hist"],
            indicators["bb_position_20"], indicators["sma_5"], indicators["sma_10"], indicators["sma_20"],
            indicators["ema_5"], indicators["ema_10"], indicators["ema_20"], indicators["atr_14"],
            indicators["volatility_20d"], indicators["relative_volume_20"], indicators["close_vs_sma20"],
        ))

    label_row = (
        news_id, security_id, exchange, event_date, labels["forward_return_1d"], labels["forward_return_3d"],
        labels["forward_return_5d"], labels["forward_return_10d"], labels["direction_1d"],
        labels["direction_3d"], labels["direction_5d"], labels["direction_10d"],
    )
    return sample_rows, label_row


def save_batch(
    conn: psycopg.Connection,
    sample_rows: list[tuple[Any, ...]],
    label_rows: list[tuple[Any, ...]],
    targets: list[tuple[int, str]],
) -> None:
    if not targets:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "DELETE FROM market_news_ml_samples WHERE news_id = %s AND exchange = %s;",
            targets,
        )
        cur.executemany(
            """
            INSERT INTO market_news_ml_samples (
                news_id, security_id, exchange, sequence_end_date, event_trade_date, sequence_index, trade_date,
                close, open, high, low, volume, turnover, daily_return, volume_ratio_5d, range_pct,
                volatility_5d, momentum_5d, momentum_10d, momentum_20d, feed_category, ai_event_type,
                ai_event_status, ai_sentiment, prediction_cutoff_ts, cutoff_trade_date, rsi_14, macd,
                macd_signal, macd_hist, bb_position_20, sma_5, sma_10, sma_20, ema_5, ema_10, ema_20,
                atr_14, volatility_20d, relative_volume_20, close_vs_sma20
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            );
            """, sample_rows)
        cur.executemany(
            """
            INSERT INTO market_news_ml_labels (
                news_id, security_id, exchange, event_trade_date, forward_return_1d, forward_return_3d,
                forward_return_5d, forward_return_10d, direction_1d, direction_3d, direction_5d, direction_10d, label_status
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'AUTO')
            ON CONFLICT (news_id, security_id, exchange) DO UPDATE SET
                event_trade_date=EXCLUDED.event_trade_date, forward_return_1d=EXCLUDED.forward_return_1d,
                forward_return_3d=EXCLUDED.forward_return_3d, forward_return_5d=EXCLUDED.forward_return_5d,
                forward_return_10d=EXCLUDED.forward_return_10d, direction_1d=EXCLUDED.direction_1d,
                direction_3d=EXCLUDED.direction_3d, direction_5d=EXCLUDED.direction_5d,
                direction_10d=EXCLUDED.direction_10d, updated_at=CURRENT_TIMESTAMP;
            """, label_rows)
    conn.commit()


def build_batch(
    conn: psycopg.Connection, news_ids: list[int],
) -> tuple[int, int, int, int, dict[str, int]]:
    contexts = load_contexts(conn, news_ids)
    price_cache = load_price_cache(conn, contexts)
    sample_rows=[]; label_rows=[]; targets=[]
    built=skipped=failed=0; reasons={}
    def add_reason(reason): reasons[reason]=reasons.get(reason,0)+1

    for news_id in news_ids:
        context=contexts.get(news_id)
        if not context:
            skipped += 1; add_reason("NO_CONTEXT"); continue
        try:
            cutoff_ts=prediction_cutoff(context["published_at"]); security_id=int(context["security_id"])
            for exchange in exchange_options(context.get("exchange_tag")):
                history=get_history_from_cache(price_cache, security_id, exchange, cutoff_ts.date())
                if len(history) < LOOKBACK_DAYS:
                    skipped += 1; add_reason(f"NO_HISTORY_{exchange}")
                    print(f"  SKIP news_id={news_id} exchange={exchange} | reason=NO_HISTORY | security_id={security_id} | cutoff={cutoff_ts.date()} | sessions={len(history)}")
                    continue
                base_trade_date=history[-1]["trade_date"]
                future=get_future_from_cache(price_cache, security_id, exchange, base_trade_date)
                labels=calculate_labels(history[-1]["close"], future)
                rows=build_row_features(history)
                samples,label=build_sample_payload(context, exchange, rows, labels, cutoff_ts, base_trade_date)
                sample_rows.extend(samples); label_rows.append(label); targets.append((news_id,exchange)); built += 1
        except Exception as error:
            failed += 1; add_reason("FEATURE_BUILD_ERROR"); print(f"  ERROR news_id={news_id} | reason=FEATURE_BUILD_ERROR | {error}")
    if targets: save_batch(conn,sample_rows,label_rows,targets)
    return built,skipped,failed,len(sample_rows),reasons


def main() -> int:

    load_environment()



    parser = argparse.ArgumentParser()

    parser.add_argument("--all", action="store_true")

    parser.add_argument("--limit", type=int)

    parser.add_argument("--start-id", type=int)

    parser.add_argument("--end-id", type=int)

    parser.add_argument(

        "--news-ids-file",

        type=str,

        help="Process exactly the news_id values listed in this file; cannot be combined with range/limit modes.",

    )

    parser.add_argument("--batch-size", type=int, default=1000)

    args = parser.parse_args()



    if args.news_ids_file and (args.all or args.limit is not None or args.start_id is not None or args.end_id is not None):

        parser.error("--news-ids-file cannot be combined with --all, --limit, or --start-id/--end-id.")



    if not (

        args.all

        or args.limit is not None

        or args.start_id is not None

        or args.end_id is not None

        or args.news_ids_file

    ):

        parser.error("Use --all, --limit, --start-id/--end-id, or --news-ids-file.")



    if args.batch_size <= 0:

        parser.error("--batch-size must be greater than 0.")



    if args.news_ids_file:

        requested_ids = [

            int(line.strip())

            for line in Path(args.news_ids_file).read_text(encoding="utf-8").splitlines()

            if line.strip() and not line.lstrip().startswith("#")

        ]

        if len(requested_ids) != len(set(requested_ids)):

            parser.error("--news-ids-file contains duplicate news_id values.")

        news_ids = get_news_ids(None, None, None, requested_ids)

    else:

        news_ids = get_news_ids(args.limit, args.start_id, args.end_id)



    print("=" * 80)

    print("MarketPulse ML Dataset Builder - Point-in-Time Safe V2")

    print("=" * 80)

    print(f"Lookback : up to {LOOKBACK_DAYS} completed sessions")

    print(f"Batch    : {args.batch_size}")

    print(f"Records  : {len(news_ids)}")

    print("=" * 80)



    built = skipped = failed = sample_rows = 0

    reason_counts: dict[str, int] = {}



    with get_connection() as conn:

        for offset in range(0, len(news_ids), args.batch_size):

            batch = news_ids[offset:offset + args.batch_size]

            batch_no = offset // args.batch_size + 1

            total_batches = (len(news_ids) + args.batch_size - 1) // args.batch_size



            try:

                b, s, f, sr, batch_reasons = build_batch(conn, batch)

                built += b

                skipped += s

                failed += f

                sample_rows += sr

                for reason, count in batch_reasons.items():

                    reason_counts[reason] = reason_counts.get(reason, 0) + count



                print(

                    f"[{batch_no:03d}/{total_batches:03d}] "

                    f"events={len(batch)} built={b} skipped={s} failed={f} "

                    f"sample_rows={sr}"

                )

                if batch_reasons:

                    print(

                        "  Reasons: "

                        + ", ".join(

                            f"{reason}={count}"

                            for reason, count in sorted(batch_reasons.items())

                        )

                    )

            except Exception as error:

                conn.rollback()

                failed += len(batch)

                print(f"BATCH ERROR [{batch_no:03d}/{total_batches:03d}] | {error}")



    print()

    print("=" * 80)

    print("DATASET BUILD COMPLETE")

    print("=" * 80)

    print(

        f"Built={built} Skipped={skipped} Failed={failed} "

        f"Total={len(news_ids)} SampleRows={sample_rows}"

    )

    print()

    print("Skip / failure reasons:")

    if reason_counts:

        for reason, count in sorted(reason_counts.items()):

            print(f"  {reason:24s} {count:,}")

    else:

        print("  NONE")

    print("=" * 80)



    return 0





if __name__ == "__main__":

    raise SystemExit(main())