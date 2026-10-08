"""
MarketPulse AI Prediction Service

Use from existing api.py:

    from src.backend.ai_prediction_service import (
        router as ai_prediction_router
    )

    app.include_router(ai_prediction_router)

Environment variables:
    MARKETPULSE_DB_HOST
    MARKETPULSE_DB_PORT
    MARKETPULSE_DB_NAME
    MARKETPULSE_DB_USER
    MARKETPULSE_DB_PASSWORD

Optional:
    MARKETPULSE_OLLAMA_URL
    MARKETPULSE_OLLAMA_MODEL

Default Ollama model:
    gemma3:4b

This service:
    1. Loads one market_news record.
    2. Resolves its security using security_id or exact company-name match.
    3. Sends the filing/news text to Ollama/Gemma.
    4. Stores the AI prediction in market_news_ai_predictions.
    5. When a stock is mapped and the news timestamp is known,
       calculates 1D/3D/5D price outcomes from daily_prices.
    6. Calculates a conservative automatic assessment.
    7. Stores the outcome in market_news_ai_outcomes.

It intentionally does not overwrite market_news or human feedback.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg
from fastapi import APIRouter, HTTPException


router = APIRouter(
    prefix="/api",
    tags=["MarketPulse AI"],
)


# ==========================================================
# Configuration
# ==========================================================

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


# ==========================================================
# Controlled AI taxonomy
# ==========================================================

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
            "items": {
                "type": "string",
            },
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


# ==========================================================
# Database
# ==========================================================

def get_connection():
    return psycopg.connect(**DB_CONFIG)


# ==========================================================
# Helpers
# ==========================================================

def clean_text(value: Optional[str]) -> str:
    if not value:
        return ""

    value = value.replace("\x00", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def sha256_text(value: str) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def json_safe(value: Any) -> Any:
    """
    Convert PostgreSQL/Python values into JSON-friendly values.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            str(k): json_safe(v)
            for k, v in value.items()
        }

    if isinstance(value, list):
        return [
            json_safe(v)
            for v in value
        ]

    return value


# ==========================================================
# Ollama
# ==========================================================

def call_ollama(prompt: str) -> dict[str, Any]:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are the MarketPulse financial-event classifier. "
                    "Classify the supplied NSE/BSE corporate disclosure. "
                    "Do not invent facts. "
                    "Use NOT_SURE when evidence is insufficient. "
                    "The exchange feed category and company identity are "
                    "trusted metadata. "
                    "Do not infer manipulation from price movement. "
                    "Return only the requested JSON object."
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

    request = Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(
            request,
            timeout=180,
        ) as response:
            raw = response.read().decode(
                "utf-8",
                errors="replace",
            )

    except HTTPError as exc:
        detail = exc.read().decode(
            "utf-8",
            errors="replace",
        )

        raise RuntimeError(
            f"Ollama HTTP {exc.code}: {detail[:500]}"
        ) from exc

    except URLError as exc:
        raise RuntimeError(
            f"Unable to reach Ollama at "
            f"{OLLAMA_URL}: {exc}"
        ) from exc

    outer = json.loads(raw)

    content = (
        outer
        .get("message", {})
        .get("content", "")
    )

    if isinstance(content, str):
        result = json.loads(content)
    elif isinstance(content, dict):
        result = content
    else:
        raise RuntimeError(
            "Ollama returned an unsupported response format."
        )

    validate_prediction(result)

    return result


def validate_prediction(
    prediction: dict[str, Any],
) -> None:

    if prediction.get("event_type") not in EVENT_TYPES:
        prediction["event_type"] = "OTHER"

    if prediction.get("event_status") not in EVENT_STATUS:
        prediction["event_status"] = "NOT_SURE"

    if prediction.get("direction") not in DIRECTIONS:
        prediction["direction"] = "NOT_SURE"

    if prediction.get("impact_level") not in IMPACTS:
        prediction["impact_level"] = "NOT_SURE"

    try:
        confidence = float(
            prediction.get("confidence", 0)
        )

        prediction["confidence"] = max(
            0,
            min(100, confidence),
        )

    except (
        TypeError,
        ValueError,
    ):
        prediction["confidence"] = 0

    prediction["reason"] = clean_text(
        prediction.get("reason")
    )

    facts = prediction.get("key_facts")

    if not isinstance(facts, list):
        prediction["key_facts"] = []

    else:
        prediction["key_facts"] = [
            clean_text(str(item))
            for item in facts
            if clean_text(str(item))
        ][:10]


# ==========================================================
# News loading
# ==========================================================

def load_news(news_id: int) -> dict[str, Any]:

    query = """
        SELECT
            news_id,
            exchange,
            symbol,
            security_id,
            company_name,
            category,
            title,
            description,
            published_at,
            source_url
        FROM market_news
        WHERE news_id = %s;
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

            cur.execute(
                query,
                (news_id,),
            )

            row = cur.fetchone()

    if not row:

        raise HTTPException(
            status_code=404,
            detail=f"News not found: {news_id}",
        )

    return dict(
        zip(
            columns,
            row,
        )
    )


# ==========================================================
# Security resolution
# ==========================================================

def resolve_security(
    news: dict[str, Any],
) -> Optional[dict[str, Any]]:

    columns = [
        "security_id",
        "symbol",
        "isin",
        "instrument_name",
        "exchange",
    ]

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
          AND UPPER(TRIM(instrument_name))
              = UPPER(TRIM(%s))
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
                            columns,
                            row,
                        )
                    )

            company_name = clean_text(
                news.get("company_name")
            )

            if company_name:

                cur.execute(
                    query_by_name,
                    (
                        news.get("exchange"),
                        company_name,
                    ),
                )

                rows = cur.fetchall()

                if len(rows) == 1:

                    return dict(
                        zip(
                            columns,
                            rows[0],
                        )
                    )

    return None


# ==========================================================
# Prompt construction
# ==========================================================

def build_prompt(
    news: dict[str, Any],
    security: Optional[dict[str, Any]],
) -> str:

    company = clean_text(
        news.get("company_name")
    )

    title = clean_text(
        news.get("title")
    )

    description = clean_text(
        news.get("description")
    )

    published_at = news.get(
        "published_at"
    )

    security_text = "NOT_MAPPED"

    if security:

        security_text = (
            f"Symbol: {security.get('symbol')}\n"
            f"ISIN: {security.get('isin')}\n"
            f"Company: {security.get('instrument_name')}\n"
            f"Exchange: {security.get('exchange')}"
        )

    return f"""
Trusted feed metadata:
Exchange: {news.get('exchange')}
Feed category: {news.get('category')}
Company: {company}
Published at: {published_at}

Trusted security mapping:
{security_text}

Headline:
{title}

Description:
{description[:8000]}

Classification instructions:
1. Determine the primary event represented by this disclosure.
2. Select the event based on the actual current disclosure, not background references.
3. Use only evidence in the supplied text.
4. FINANCIAL_RESULT requires explicit financial-results/reporting language.
5. A dividend should be classified as DIVIDEND when the disclosure is actually
   about a dividend declaration/payment/record or ex date.
6. NCD/debenture interest is INTEREST_PAYMENT.
7. NCD/debenture redemption is DEBENTURE_REDEMPTION.
8. A company acquisition/share purchase is ACQUISITION.
9. A Regulation 29 or similar ownership disclosure should be
   SHAREHOLDING_CHANGE unless the text clearly establishes another event.
10. A board meeting scheduled for a future date is BOARD_MEETING + UPCOMING.
11. Appointment/resignation should be selected only when the disclosure
    actually announces that personnel event.
12. Direction describes likely informational/business direction of this filing,
    not a guaranteed stock-price movement.
13. Impact describes materiality of the disclosure, not trading confidence.
14. Never claim market manipulation based only on price movement.
15. If evidence is insufficient, use NOT_SURE.
"""


# ==========================================================
# Prediction persistence
# ==========================================================

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
                    json.dumps(
                        prediction["key_facts"],
                        ensure_ascii=False,
                    ),
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


# ==========================================================
# Price data
# ==========================================================

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

    if not row:
        return None

    return dict(
        zip(
            columns,
            row,
        )
    )


def prices_after_event(
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


def average_prior_volume(
    security_id: int,
    event_date: date,
    lookback: int = 20,
) -> Optional[float]:

    query = """
        SELECT AVG(volume)
        FROM (
            SELECT volume
            FROM daily_prices
            WHERE security_id = %s
              AND trade_date < %s
              AND volume IS NOT NULL
            ORDER BY trade_date DESC
            LIMIT %s
        ) x;
    """

    with get_connection() as conn:

        with conn.cursor() as cur:

            cur.execute(
                query,
                (
                    security_id,
                    event_date,
                    lookback,
                ),
            )

            row = cur.fetchone()

    if not row or row[0] is None:
        return None

    return float(row[0])


# ==========================================================
# Outcome calculation
# ==========================================================

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
            "event_trade_date": event_date,
            "calculation_status": "NO_BASE_PRICE",
        }

    future = prices_after_event(
        security["security_id"],
        event_date,
        5,
    )

    returns = {
        "1d": None,
        "3d": None,
        "5d": None,
    }

    indexes = {
        "1d": 0,
        "3d": 2,
        "5d": 4,
    }

    base_close = base.get("close")

    if base_close is not None:
        base_close = float(base_close)

    for name, index in indexes.items():

        if (
            base_close
            and len(future) > index
            and future[index].get("close") is not None
        ):

            current_close = float(
                future[index]["close"]
            )

            returns[name] = (
                (current_close / base_close) - 1
            ) * 100

    volume_ratio = None

    if future:

        first_volume = future[0].get(
            "volume"
        )

        prior_average = average_prior_volume(
            security["security_id"],
            event_date,
        )

        if (
            first_volume is not None
            and prior_average
            and prior_average != 0
        ):

            volume_ratio = (
                float(first_volume)
                / prior_average
            )

    return {
        "prediction_id": prediction_id,
        "news_id": news_id,
        "event_trade_date": event_date,
        "stock_return_1d": returns["1d"],
        "stock_return_3d": returns["3d"],
        "stock_return_5d": returns["5d"],
        "volume_ratio_1d": volume_ratio,
        "calculation_status": (
            "CALCULATED"
            if returns["1d"] is not None
            else "INSUFFICIENT_FUTURE_DATA"
        ),
    }


# ==========================================================
# Outcome persistence
# ==========================================================

def store_outcome(
    result: dict[str, Any],
) -> dict[str, Any]:

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


# ==========================================================
# Conservative automatic outcome assessment
# ==========================================================

def assess_outcome(
    prediction: dict[str, Any],
    outcome: dict[str, Any],
) -> dict[str, Any]:

    direction = str(
        prediction.get("direction") or "NOT_SURE"
    ).upper()

    one_day = outcome.get(
        "stock_return_1d"
    )

    if one_day is None:

        return {
            "auto_assessment": "NOT_ENOUGH_DATA",
            "possible_explanation": "UNKNOWN",
            "market_reaction": "NO_DATA",
        }

    one_day = float(one_day)

    if direction == "POSITIVE":

        if one_day > 0.75:
            return {
                "auto_assessment": "CONFIRMED",
                "possible_explanation": (
                    "DIRECTION_CONFIRMED"
                ),
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

    elif direction == "NEGATIVE":

        if one_day < -0.75:
            return {
                "auto_assessment": "CONFIRMED",
                "possible_explanation": (
                    "DIRECTION_CONFIRMED"
                ),
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
            "UP"
            if one_day > 0
            else "DOWN"
            if one_day < 0
            else "FLAT"
        ),
    }


# ==========================================================
# Main API
# ==========================================================

@router.post("/news/{news_id}/ai/predict")
def predict_news(news_id: int):

    news = load_news(news_id)

    security = resolve_security(
        news
    )

    news_scope = str(
        news.get("news_scope") or "STOCK"
    ).upper()

    stock_outcome_enabled = (
        security is not None
        and news_scope == "STOCK"
    )

    prompt = build_prompt(
        news,
        security,
    )

    try:

        prediction = call_ollama(
            prompt
        )

    except Exception as exc:

        raise HTTPException(
            status_code=502,
            detail=(
                "AI prediction failed: "
                f"{exc}"
            ),
        )

    stored = store_prediction(
        news,
        prediction,
        prompt,
    )

    outcome = None
    assessment = None

    published_at = news.get(
        "published_at"
    )

    if (
        stock_outcome_enabled
        and isinstance(
            published_at,
            datetime,
        )
    ):

        outcome = calculate_outcome(
            stored["prediction_id"],
            news_id,
            security,
            published_at,
        )

        outcome = store_outcome(
            outcome
        )

        assessment = assess_outcome(
            prediction,
            outcome,
        )

        update_auto_assessment(
            outcome["outcome_id"],
            assessment,
        )

    return json_safe({
        "status": "success",
        "news": news,
        "security": security,
        "news_scope": news_scope,
        "stock_outcome_enabled": (
            stock_outcome_enabled
        ),
        "prediction": {
            "prediction_id":
                stored["prediction_id"],
            **prediction,
        },
        "outcome": outcome,
        "assessment": assessment,
    })