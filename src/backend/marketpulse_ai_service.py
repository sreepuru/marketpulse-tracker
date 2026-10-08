"""
MarketPulse AI service - first end-to-end implementation.

Flow:
    market_news
       -> trusted stock mapping
       -> Gemma 3 4B prediction
       -> market_news_ai_predictions
       -> daily price outcome
       -> market_news_ai_outcomes

This module deliberately does not modify existing market_news classification fields.

Required:
    pip install psycopg2-binary

Ollama:
    http://127.0.0.1:11434
    model: gemma3:4b
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime
from typing import Any, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

import psycopg2
from psycopg2.extras import Json
from fastapi import APIRouter, HTTPException


router = APIRouter(prefix="/api", tags=["MarketPulse AI"])


DB_CONFIG = {
    "host": os.getenv("MARKETPULSE_DB_HOST", "localhost"),
    "port": int(os.getenv("MARKETPULSE_DB_PORT", "5432")),
    "dbname": os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
    "user": os.getenv("MARKETPULSE_DB_USER", "postgres"),
    "password": os.getenv("MARKETPULSE_DB_PASSWORD", ""),
}

OLLAMA_URL = os.getenv(
    "MARKETPULSE_OLLAMA_URL",
    "http://127.0.0.1:11434/api/chat",
)

OLLAMA_MODEL = os.getenv(
    "MARKETPULSE_OLLAMA_MODEL",
    "gemma3:4b",
)


EVENT_TYPES = [
    "OTHER",
    "DIVIDEND",
    "BOARD_MEETING",
    "FINANCIAL_RESULT",
    "ORDER_WIN",
    "ACQUISITION",
    "SHAREHOLDING_CHANGE",
    "BUYBACK",
    "PREFERENTIAL_ISSUE",
    "RIGHTS_ISSUE",
    "BONUS_ISSUE",
    "STOCK_SPLIT",
    "INTEREST_PAYMENT",
    "DEBENTURE_REDEMPTION",
    "DEBT_ISSUANCE",
    "DEBT_REPAYMENT",
    "APPOINTMENT",
    "RESIGNATION",
    "MANAGEMENT_CHANGE",
    "REGULATORY_PENALTY",
    "SHOW_CAUSE_NOTICE",
    "REGULATORY_ORDER",
    "LITIGATION",
    "SETTLEMENT",
    "CREDIT_RATING",
    "INSOLVENCY",
    "ANALYST_MEETING",
    "INVESTOR_MEETING",
    "NAV_UPDATE",
]

EVENT_STATUS = [
    "UPCOMING",
    "CONFIRMED",
    "COMPLETED",
    "NOT_SURE",
]

DIRECTIONS = [
    "POSITIVE",
    "NEGATIVE",
    "NEUTRAL",
    "NOT_SURE",
]

IMPACTS = [
    "HIGH",
    "MEDIUM",
    "LOW",
    "NOT_SURE",
]


MODEL_SCHEMA = {
    "type": "object",
    "properties": {
        "event_type": {
            "type": "string",
            "enum": EVENT_TYPES,
        },
        "event_status": {
            "type": "string",
            "enum": EVENT_STATUS,
        },
        "direction": {
            "type": "string",
            "enum": DIRECTIONS,
        },
        "impact_level": {
            "type": "string",
            "enum": IMPACTS,
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 100,
        },
        "reason": {
            "type": "string",
        },
        "key_facts": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "event_type",
        "event_status",
        "direction",
        "impact_level",
        "confidence",
        "reason",
        "key_facts",
    ],
}


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    value = value.replace("\x00", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def call_ollama(prompt: str) -> dict[str, Any]:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are the MarketPulse financial-event classifier. "
                    "Classify the supplied NSE/BSE corporate disclosure. "
                    "Do not invent facts. Use NOT_SURE when evidence is insufficient. "
                    "The exchange feed category and company identity are already trusted. "
                    "Return only the requested JSON structure."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "stream": False,
        "format": MODEL_SCHEMA,
        "options": {
            "temperature": 0,
        },
    }

    body = json.dumps(payload).encode("utf-8")

    request = Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(
            f"Ollama HTTP {exc.code}: {detail[:500]}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"Unable to reach Ollama at {OLLAMA_URL}: {exc}"
        ) from exc

    outer = json.loads(raw)
    content = outer.get("message", {}).get("content", "")

    if isinstance(content, dict):
        result = content
    else:
        result = json.loads(content)

    validate_prediction(result)

    return result


def validate_prediction(result: dict[str, Any]) -> None:
    if result.get("event_type") not in EVENT_TYPES:
        result["event_type"] = "OTHER"

    if result.get("event_status") not in EVENT_STATUS:
        result["event_status"] = "NOT_SURE"

    if result.get("direction") not in DIRECTIONS:
        result["direction"] = "NOT_SURE"

    if result.get("impact_level") not in IMPACTS:
        result["impact_level"] = "NOT_SURE"

    try:
        result["confidence"] = max(
            0,
            min(100, float(result.get("confidence", 0))),
        )
    except (TypeError, ValueError):
        result["confidence"] = 0

    result["reason"] = clean_text(
        result.get("reason")
    )

    key_facts = result.get("key_facts")
    if not isinstance(key_facts, list):
        result["key_facts"] = []
    else:
        result["key_facts"] = [
            clean_text(str(item))
            for item in key_facts
            if clean_text(str(item))
        ][:10]


def load_news(news_id: int) -> dict[str, Any]:
    query = """
        SELECT
            mn.news_id,
            mn.exchange,
            mn.symbol,
            mn.security_id,
            mn.company_name,
            mn.category,
            mn.title,
            mn.description,
            mn.published_at,
            mn.source_url
        FROM market_news mn
        WHERE mn.news_id = %s;
    """

    columns = [
        "news_id",
        "exchange",
        "symbol",
        "security_id",
        "company_name",
        "category",
        "title",
        "description",
        "published_at",
        "source_url",
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (news_id,))
            row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"News not found: {news_id}",
        )

    return dict(zip(columns, row))


def resolve_security(news: dict[str, Any]) -> Optional[dict[str, Any]]:
    query_by_id = """
        SELECT
            security_id,
            symbol,
            isin,
            instrument_name,
            exchange
        FROM security_master
        WHERE security_id = %s
        LIMIT 1;
    """

    query_by_name = """
        SELECT
            security_id,
            symbol,
            isin,
            instrument_name,
            exchange
        FROM security_master
        WHERE exchange = %s
          AND is_active = TRUE
          AND UPPER(TRIM(instrument_name)) = UPPER(TRIM(%s))
        LIMIT 2;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:

            if news.get("security_id") is not None:
                cur.execute(
                    query_by_id,
                    (news["security_id"],),
                )
                row = cur.fetchone()
                if row:
                    return dict(
                        zip(
                            [
                                "security_id",
                                "symbol",
                                "isin",
                                "instrument_name",
                                "exchange",
                            ],
                            row,
                        )
                    )

            if news.get("company_name"):
                cur.execute(
                    query_by_name,
                    (
                        news["exchange"],
                        news["company_name"],
                    ),
                )
                rows = cur.fetchall()

                if len(rows) == 1:
                    return dict(
                        zip(
                            [
                                "security_id",
                                "symbol",
                                "isin",
                                "instrument_name",
                                "exchange",
                            ],
                            rows[0],
                        )
                    )

    return None


def build_prompt(news: dict[str, Any], security: Optional[dict[str, Any]]) -> str:
    title = clean_text(news.get("title"))
    description = clean_text(news.get("description"))

    security_text = "NOT_MAPPED"

    if security:
        security_text = (
            f"Symbol: {security['symbol']}\n"
            f"ISIN: {security['isin']}\n"
            f"Company: {security['instrument_name']}\n"
            f"Exchange: {security['exchange']}"
        )

    return f"""
Trusted feed metadata:
Exchange: {news.get('exchange')}
Feed category: {news.get('category')}
Company: {news.get('company_name')}
Published at: {news.get('published_at')}

Trusted security mapping:
{security_text}

Headline:
{title}

Description:
{description[:7000]}

Rules:
1. Determine the primary event represented by this disclosure.
2. Use only evidence present in the text.
3. Do not treat a referenced historical/background event as the current primary event.
4. For financial results, require explicit result/reporting language.
5. Do not call an event positive merely because it sounds commercially good; use the actual disclosure context.
6. For direction and impact, choose NOT_SURE when evidence is insufficient.
7. Confidence is confidence in this classification, not trading confidence.
8. Do not mention manipulation unless the disclosure itself explicitly establishes it.
"""


def store_prediction(
    news: dict[str, Any],
    prediction: dict[str, Any],
    input_text: str,
) -> dict[str, Any]:

    query = """
        INSERT INTO market_news_ai_predictions (
            news_id,
            model_name,
            model_version,
            predicted_event_type,
            predicted_event_status,
            predicted_direction,
            predicted_impact_level,
            model_confidence,
            prediction_reason,
            key_facts,
            input_text_hash,
            input_text_chars,
            prediction_status
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, 'PREDICTED'
        )
        RETURNING
            prediction_id,
            predicted_at;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    news["news_id"],
                    OLLAMA_MODEL,
                    "MarketPulse-V1",
                    prediction["event_type"],
                    prediction["event_status"],
                    prediction["direction"],
                    prediction["impact_level"],
                    prediction["confidence"],
                    prediction["reason"],
                    Json(prediction["key_facts"]),
                    sha256_text(input_text),
                    len(input_text),
                ),
            )
            row = cur.fetchone()
            conn.commit()

    return {
        "prediction_id": row[0],
        "predicted_at": row[1],
    }


def trading_dates_after(
    security_id: int,
    event_date: date,
    limit: int = 5,
) -> list[dict[str, Any]]:

    query = """
        SELECT
            trade_date,
            close,
            last_price,
            volume
        FROM daily_prices
        WHERE security_id = %s
          AND trade_date > %s
        ORDER BY trade_date ASC
        LIMIT %s;
    """

    columns = [
        "trade_date",
        "close",
        "last_price",
        "volume",
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    security_id,
                    event_date,
                    limit,
                ),
            )
            rows = cur.fetchall()

    return [
        dict(zip(columns, row))
        for row in rows
    ]


def base_price_on_or_before(
    security_id: int,
    event_date: date,
) -> Optional[dict[str, Any]]:

    query = """
        SELECT
            trade_date,
            close,
            last_price,
            volume
        FROM daily_prices
        WHERE security_id = %s
          AND trade_date <= %s
        ORDER BY trade_date DESC
        LIMIT 1;
    """

    columns = [
        "trade_date",
        "close",
        "last_price",
        "volume",
    ]

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    security_id,
                    event_date,
                ),
            )
            row = cur.fetchone()

    return dict(zip(columns, row)) if row else None


def calculate_outcome(
    prediction_id: int,
    news_id: int,
    security: dict[str, Any],
    published_at: datetime,
) -> dict[str, Any]:

    event_date = published_at.date()

    base = base_price_on_or_before(
        security["security_id"],
        event_date,
    )

    if not base:
        return {
            "prediction_id": prediction_id,
            "news_id": news_id,
            "calculation_status": "NO_BASE_PRICE",
            "event_trade_date": event_date,
        }

    future = trading_dates_after(
        security["security_id"],
        event_date,
        5,
    )

    values = {
        "1d": None,
        "3d": None,
        "5d": None,
    }

    for key, index in (
        ("1d", 0),
        ("3d", 2),
        ("5d", 4),
    ):
        if len(future) > index and base["close"]:
            values[key] = (
                (float(future[index]["close"]) /
                 float(base["close"])) - 1
            ) * 100

    volume_ratio = None

    if future and future[0]["volume"] is not None:
        baseline_query = """
            SELECT AVG(volume)
            FROM (
                SELECT volume
                FROM daily_prices
                WHERE security_id = %s
                  AND trade_date < %s
                  AND volume IS NOT NULL
                ORDER BY trade_date DESC
                LIMIT 20
            ) x;
        """

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    baseline_query,
                    (
                        security["security_id"],
                        event_date,
                    ),
                )
                avg_volume = cur.fetchone()[0]

        if avg_volume and avg_volume != 0:
            volume_ratio = (
                float(future[0]["volume"]) /
                float(avg_volume)
            )

    result = {
        "prediction_id": prediction_id,
        "news_id": news_id,
        "event_trade_date": event_date,
        "stock_return_1d": values["1d"],
        "stock_return_3d": values["3d"],
        "stock_return_5d": values["5d"],
        "volume_ratio_1d": volume_ratio,
        "calculation_status": (
            "CALCULATED"
            if values["1d"] is not None
            else "INSUFFICIENT_FUTURE_DATA"
        ),
    }

    return result


def store_outcome(result: dict[str, Any]) -> dict[str, Any]:

    query = """
        INSERT INTO market_news_ai_outcomes (
            prediction_id,
            news_id,
            event_trade_date,
            stock_return_1d,
            stock_return_3d,
            stock_return_5d,
            volume_ratio_1d,
            calculation_status,
            calculated_at,
            updated_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT (prediction_id)
        DO UPDATE SET
            event_trade_date = EXCLUDED.event_trade_date,
            stock_return_1d = EXCLUDED.stock_return_1d,
            stock_return_3d = EXCLUDED.stock_return_3d,
            stock_return_5d = EXCLUDED.stock_return_5d,
            volume_ratio_1d = EXCLUDED.volume_ratio_1d,
            calculation_status = EXCLUDED.calculation_status,
            calculated_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        RETURNING outcome_id;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    result["prediction_id"],
                    result["news_id"],
                    result.get("event_trade_date"),
                    result.get("stock_return_1d"),
                    result.get("stock_return_3d"),
                    result.get("stock_return_5d"),
                    result.get("volume_ratio_1d"),
                    result["calculation_status"],
                ),
            )
            row = cur.fetchone()
            conn.commit()

    result["outcome_id"] = row[0]
    return result


def automatically_assess(
    prediction: dict[str, Any],
    outcome: dict[str, Any],
) -> dict[str, Any]:

    direction = prediction.get("direction", "NOT_SURE")
    one_day = outcome.get("stock_return_1d")

    if one_day is None:
        return {
            "auto_assessment": "NOT_ENOUGH_DATA",
            "possible_explanation": "UNKNOWN",
            "market_reaction": "NO_DATA",
        }

    if direction == "POSITIVE":
        if one_day > 0.75:
            return {
                "auto_assessment": "CONFIRMED",
                "possible_explanation": "DIRECTION_CONFIRMED",
                "market_reaction": "UP",
            }

        if one_day < -0.75:
            return {
                "auto_assessment": "UNRESOLVED",
                "possible_explanation": (
                    "CONTRADICTORY_MARKET_REACTION"
                ),
                "market_reaction": "DOWN",
            }

    if direction == "NEGATIVE":
        if one_day < -0.75:
            return {
                "auto_assessment": "CONFIRMED",
                "possible_explanation": "DIRECTION_CONFIRMED",
                "market_reaction": "DOWN",
            }

        if one_day > 0.75:
            return {
                "auto_assessment": "UNRESOLVED",
                "possible_explanation": (
                    "CONTRADICTORY_MARKET_REACTION"
                ),
                "market_reaction": "UP",
            }

    return {
        "auto_assessment": "UNRESOLVED",
        "possible_explanation": "UNKNOWN",
        "market_reaction": (
            "UP" if one_day > 0
            else "DOWN" if one_day < 0
            else "FLAT"
        ),
    }


def update_auto_assessment(
    outcome_id: int,
    assessment: dict[str, Any],
) -> None:

    query = """
        UPDATE market_news_ai_outcomes
        SET
            auto_assessment = %s,
            possible_explanation = %s,
            market_reaction = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE outcome_id = %s;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    assessment["auto_assessment"],
                    assessment["possible_explanation"],
                    assessment["market_reaction"],
                    outcome_id,
                ),
            )
            conn.commit()


@router.post("/news/{news_id}/ai/predict")
def predict_news(news_id: int):
    news = load_news(news_id)

    security = resolve_security(news)

    source_category = str(
        news.get("category") or ""
    )

    # A market-level notice can still be AI classified,
    # but it must not get a stock price outcome.
    can_calculate_stock_outcome = (
        security is not None
        and str(news.get("news_scope") or "STOCK").upper()
        == "STOCK"
    )

    prompt = build_prompt(news, security)

    prediction = call_ollama(prompt)

    stored = store_prediction(
        news,
        prediction,
        prompt,
    )

    outcome = None
    assessment = None

    if can_calculate_stock_outcome:
        published_at = news.get("published_at")

        if isinstance(published_at, datetime):
            outcome = calculate_outcome(
                stored["prediction_id"],
                news_id,
                security,
                published_at,
            )
            outcome = store_outcome(outcome)

            assessment = automatically_assess(
                prediction,
                outcome,
            )

            update_auto_assessment(
                outcome["outcome_id"],
                assessment,
            )

    return {
        "status": "success",
        "news": news,
        "security": security,
        "source_category": source_category,
        "stock_outcome_enabled": can_calculate_stock_outcome,
        "prediction": {
            "prediction_id": stored["prediction_id"],
            **prediction,
        },
        "outcome": outcome,
        "assessment": assessment,
    }