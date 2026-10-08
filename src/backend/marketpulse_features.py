"""
Canonical MarketPulse technical features.

This module contains only deterministic feature calculations.
It is intended to be shared by the LightGBM baseline and LSTM.

Important:
The caller must provide only price rows that were available at the
prediction cutoff. With daily data, an intraday news item must not use
that day's closing price.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MARKET_CLOSE = time(15, 30)


def safe_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def point_in_time_cutoff(
    published_at: datetime,
    market_close: time = MARKET_CLOSE,
) -> datetime:
    """
    Daily-data-safe cutoff.

    Before/at market close:
        use the previous completed trading session.

    After market close:
        same day's completed session is allowed.
    """
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=IST)
    else:
        published_at = published_at.astimezone(IST)

    if published_at.time() > market_close:
        return published_at.replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

    return (published_at - timedelta(days=1)).replace(
        hour=23, minute=59, second=59, microsecond=999999
    )


def rolling_mean(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def rolling_std(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    data = values[-window:]
    mean = sum(data) / len(data)
    variance = sum((x - mean) ** 2 for x in data) / max(len(data) - 1, 1)
    return variance ** 0.5


def ema(values: list[float], span: int) -> list[float]:
    if not values:
        return []

    alpha = 2.0 / (span + 1.0)
    result = [values[0]]

    for value in values[1:]:
        result.append(alpha * value + (1.0 - alpha) * result[-1])

    return result


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None

    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(changes)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if len(values) < 35:
        return None, None, None

    ema12 = ema(values, 12)
    ema26 = ema(values, 26)
    macd_values = [
        ema12[i + 26 - 12] - ema26[i]
        for i in range(len(ema26))
    ]

    signal_values = ema(macd_values, 9)
    line = macd_values[-1]
    signal = signal_values[-1]
    return line, signal, line - signal


def bollinger(values: list[float], window: int = 20):
    if len(values) < window:
        return None, None, None, None

    middle = rolling_mean(values, window)
    std = rolling_std(values, window)

    if middle is None or std is None:
        return None, None, None, None

    upper = middle + 2.0 * std
    lower = middle - 2.0 * std
    current = values[-1]

    position = None
    if upper != lower:
        position = (current - lower) / (upper - lower)

    return middle, upper, lower, position


def atr(rows: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(rows) <= period:
        return None

    true_ranges: list[float] = []

    for i in range(1, len(rows)):
        high = safe_float(rows[i].get("high"))
        low = safe_float(rows[i].get("low"))
        previous_close = safe_float(rows[i - 1].get("close"))

        if None in (high, low, previous_close):
            continue

        true_ranges.append(
            max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        )

    if len(true_ranges) < period:
        return None

    return sum(true_ranges[-period:]) / period


def build_features(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)

    closes = [v for v in (safe_float(r.get("close")) for r in rows) if v is not None]
    volumes = [v for v in (safe_float(r.get("volume")) for r in rows) if v is not None]

    if not closes:
        return {}

    current = closes[-1]

    def momentum(window: int) -> float | None:
        if len(closes) < window + 1:
            return None
        base = closes[-window - 1]
        return None if base == 0 else current / base - 1.0

    sma5 = rolling_mean(closes, 5)
    sma10 = rolling_mean(closes, 10)
    sma20 = rolling_mean(closes, 20)

    ema5 = ema(closes, 5)
    ema10 = ema(closes, 10)
    ema20 = ema(closes, 20)

    macd_line, macd_signal, macd_hist = macd(closes)
    bb_middle, bb_upper, bb_lower, bb_position = bollinger(closes, 20)

    return {
        "close": current,
        "daily_return": (
            None if len(closes) < 2 or closes[-2] == 0
            else current / closes[-2] - 1.0
        ),
        "momentum_5d": momentum(5),
        "momentum_10d": momentum(10),
        "momentum_20d": momentum(20),
        "volatility_5d": rolling_std(
            [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))],
            5,
        ),
        "volatility_20d": rolling_std(
            [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))],
            20,
        ),
        "sma_5": sma5,
        "sma_10": sma10,
        "sma_20": sma20,
        "ema_5": ema5[-1],
        "ema_10": ema10[-1],
        "ema_20": ema20[-1],
        "rsi_14": rsi(closes, 14),
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "bb_middle_20": bb_middle,
        "bb_upper_20": bb_upper,
        "bb_lower_20": bb_lower,
        "bb_position_20": bb_position,
        "atr_14": atr(rows, 14),
        "relative_volume_5": (
            None
            if not volumes or rolling_mean(volumes, 5) in (None, 0)
            else volumes[-1] / rolling_mean(volumes, 5)
        ),
        "relative_volume_20": (
            None
            if not volumes or rolling_mean(volumes, 20) in (None, 0)
            else volumes[-1] / rolling_mean(volumes, 20)
        ),
        "close_vs_sma20": (
            None if sma20 in (None, 0)
            else current / sma20 - 1.0
        ),
    }