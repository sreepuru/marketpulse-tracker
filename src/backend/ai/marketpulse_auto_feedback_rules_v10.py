"""
MarketPulse V10 - Outcome assessment rules

This module contains ONLY the deterministic assessment logic.
It does not fetch market data and does not update PostgreSQL.

Important:
- A price move opposite to AI direction does NOT automatically mean
  the AI prediction was wrong.
- "MANIPULATION" is never inferred automatically.
- The output can be CONFIRMED, CONTRADICTED, UNRESOLVED, or NOT_ENOUGH_DATA.
"""

from __future__ import annotations


def classify_market_reaction(
    stock_return_1d: float | None,
    threshold: float = 0.75,
) -> str:
    if stock_return_1d is None:
        return "NO_DATA"

    if stock_return_1d > threshold:
        return "UP"
    if stock_return_1d < -threshold:
        return "DOWN"
    return "FLAT"


def assess_prediction(
    predicted_direction: str | None,
    stock_return_1d: float | None,
    nifty_return_1d: float | None,
    sector_return_1d: float | None,
    volume_ratio_1d: float | None,
) -> dict:
    direction = (predicted_direction or "NOT_SURE").upper()

    if stock_return_1d is None:
        return {
            "auto_assessment": "NOT_ENOUGH_DATA",
            "possible_explanation": "UNKNOWN",
            "market_reaction": "NO_DATA",
        }

    reaction = classify_market_reaction(stock_return_1d)

    if direction not in {"POSITIVE", "NEGATIVE"}:
        return {
            "auto_assessment": "UNRESOLVED",
            "possible_explanation": "UNKNOWN",
            "market_reaction": reaction,
        }

    # Prefer relative performance when benchmark data is available.
    benchmark = sector_return_1d
    if benchmark is None:
        benchmark = nifty_return_1d

    excess = None
    if benchmark is not None:
        excess = stock_return_1d - benchmark

    if direction == "POSITIVE":
        aligned = stock_return_1d > 0
        materially_contradicted = stock_return_1d < 0

    else:
        aligned = stock_return_1d < 0
        materially_contradicted = stock_return_1d > 0

    if aligned:
        return {
            "auto_assessment": "CONFIRMED",
            "possible_explanation": "DIRECTION_CONFIRMED",
            "market_reaction": reaction,
            "excess_return_1d": excess,
        }

    # Opposite raw direction, but market/sector also moved strongly.
    if materially_contradicted and excess is not None:
        if direction == "POSITIVE" and excess >= 0:
            return {
                "auto_assessment": "UNRESOLVED",
                "possible_explanation": "MARKET_OR_SECTOR_MOVE",
                "market_reaction": reaction,
                "excess_return_1d": excess,
            }

        if direction == "NEGATIVE" and excess <= 0:
            return {
                "auto_assessment": "UNRESOLVED",
                "possible_explanation": "MARKET_OR_SECTOR_MOVE",
                "market_reaction": reaction,
                "excess_return_1d": excess,
            }

    # Large contradictory stock move with relative under/over-performance.
    if materially_contradicted:
        if volume_ratio_1d is not None and volume_ratio_1d >= 2:
            explanation = "UNUSUAL_PRICE_ACTIVITY"
        else:
            explanation = "CONTRADICTORY_MARKET_REACTION"

        return {
            "auto_assessment": "UNRESOLVED",
            "possible_explanation": explanation,
            "market_reaction": reaction,
            "excess_return_1d": excess,
        }

    return {
        "auto_assessment": "UNRESOLVED",
        "possible_explanation": "UNKNOWN",
        "market_reaction": reaction,
        "excess_return_1d": excess,
    }
