import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import psycopg
import os
import subprocess
import sys
import tempfile

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

load_dotenv()




# ==========================================================
# MarketPulse API
# ==========================================================

from src.backend.ai_feedback_api_v9 import router as ai_feedback_router
from src.backend.ai_prediction_service import router as ai_prediction_router

app = FastAPI(
    title="MarketPulse API",
    version="1.0.0"
)

app.include_router(ai_feedback_router)
app.include_router(ai_prediction_router)

# ==========================================================
# Runtime configuration
# ==========================================================

ENVIRONMENT = os.getenv(
    "MARKETPULSE_ENV",
    "development"
).strip().lower()

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "MARKETPULSE_CORS_ORIGINS",
        ",".join(DEFAULT_CORS_ORIGINS),
    ).split(",")
    if origin.strip()
]

# Debugging: Print loaded origins to console on startup
print(f"--- MarketPulse API CORS Origins: {CORS_ORIGINS} ---")

if not CORS_ORIGINS:
    print("WARNING: No CORS origins configured. Defaulting to allow all for debugging.")
    CORS_ORIGINS = ["*"]

DB_CONFIG = {
    "host": os.getenv("MARKETPULSE_DB_HOST", "localhost"),
    "port": os.getenv("MARKETPULSE_DB_PORT", "5432"),
    "dbname": os.getenv("MARKETPULSE_DB_NAME", "marketpulse"),
    "user": os.getenv("MARKETPULSE_DB_USER", "postgres"),
    "password": os.getenv("MARKETPULSE_DB_PASSWORD", ""),
}

if ENVIRONMENT == "production" and not DB_CONFIG["password"]:
    raise RuntimeError(
        "MARKETPULSE_DB_PASSWORD must be set in production."
    )


# ==========================================================
# CORS
# ==========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================================
# Database Connection
# ==================================================================================

def get_connection():
    return psycopg.connect(**DB_CONFIG)


# ==========================================================
# Mapping API Models
# ==========================================================

class ManualMappingRequest(BaseModel):
    news_id: int
    security_id: int
    reviewer: str = "USER"
    alias: Optional[str] = None


class AgentFeedbackRequest(BaseModel):
    news_id: int
    verdict: str
    wrong_reason: Optional[str] = None
    comment: Optional[str] = None
    reviewer: str = "USER"
    corrected_security_id: Optional[int] = None


class ScoreEventRequest(BaseModel):
    news_id: int


class MapperEventRequest(BaseModel):
    news_id: int

    
# ==========================================================
# Root
# ==========================================================

@app.get("/")
def root():

    return {
        "application": "MarketPulse API",
        "status": "running"
    }


# ==========================================================
# Database Health
# ==========================================================

@app.get("/api/health")
def health():

    try:

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute("SELECT 1")

                result = cur.fetchone()

        return {
            "status": "healthy",
            "database": "connected",
            "result": result[0]
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Database connection failed: {str(e)}"
        )


# ==========================================================
# Market Movement
# ==========================================================

@app.get("/api/market/movement")
def market_movement():

    query = """
        SELECT
            symbol,
            isin,
            series,
            trade_date,
            current_price,
            previous_price,
            price_change,
            change_percent

        FROM latest_price_movement

        ORDER BY change_percent DESC;
    """

    try:

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute(query)

                rows = cur.fetchall()

                columns = [
                    "symbol",
                    "isin",
                    "series",
                    "trade_date",
                    "current_price",
                    "previous_price",
                    "price_change",
                    "change_percent"
                ]

                data = [
                    dict(zip(columns, row))
                    for row in rows
                ]

        return {
            "status": "success",
            "count": len(data),
            "data": data
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Unable to load market movement: {str(e)}"
        )


# ==========================================================
# Market Summary
# ==========================================================

@app.get("/api/market/summary")
def market_summary():

    query = """
        WITH latest_market AS (

            SELECT
                *
            FROM latest_price_movement
            WHERE trade_date = (
                SELECT MAX(trade_date)
                FROM latest_price_movement
            )

        )

        SELECT

            MAX(trade_date) AS market_date,

            COUNT(*) AS total_securities,

            COUNT(*) FILTER (
                WHERE change_percent > 0
            ) AS advances,

            COUNT(*) FILTER (
                WHERE change_percent < 0
            ) AS declines,

            COUNT(*) FILTER (
                WHERE change_percent = 0
            ) AS unchanged,

            COUNT(*) FILTER (
                WHERE change_percent IS NULL
            ) AS no_change_data

        FROM latest_market;
    """

    try:

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute(query)

                row = cur.fetchone()


        market_date = row[0]
        total_securities = row[1] or 0
        advances = row[2] or 0
        declines = row[3] or 0
        unchanged = row[4] or 0
        no_change_data = row[5] or 0


        advance_decline_ratio = None

        if declines > 0:

            advance_decline_ratio = round(
                advances / declines,
                2
            )


        return {

            "status": "success",

            "market_date": market_date,

            "total_securities":
                total_securities,

            "advances":
                advances,

            "declines":
                declines,

            "unchanged":
                unchanged,

            "no_change_data":
                no_change_data,

            "advance_decline_ratio":
                advance_decline_ratio

        }


    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Unable to load market summary: {str(e)}"
        )

# ==========================================================
# Top Gainers
# ==========================================================

@app.get("/api/market/gainers")
def market_gainers():

    query = """
            SELECT

                symbol,
                isin,
                series,
                trade_date,
                current_price,
                previous_price,
                price_change,
                change_percent

            FROM latest_price_movement

            WHERE trade_date = (
                SELECT MAX(trade_date)
                FROM latest_price_movement
            )

            AND change_percent IS NOT NULL

            ORDER BY
                change_percent DESC

            LIMIT 10;
        """

    try:

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute(query)

                rows = cur.fetchall()

                columns = [
                    "symbol",
                    "isin",
                    "series",
                    "trade_date",
                    "current_price",
                    "previous_price",
                    "price_change",
                    "change_percent"
                ]

                data = [
                    dict(zip(columns, row))
                    for row in rows
                ]

        return {
            "status": "success",
            "count": len(data),
            "data": data
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Unable to load top gainers: {str(e)}"
        )


# ==========================================================
# Top Losers
# ==========================================================

@app.get("/api/market/losers")
def market_losers():

    query = """
            SELECT

                symbol,
                isin,
                series,
                trade_date,
                current_price,
                previous_price,
                price_change,
                change_percent

            FROM latest_price_movement

            WHERE trade_date = (
                SELECT MAX(trade_date)
                FROM latest_price_movement
            )

            AND change_percent IS NOT NULL

            ORDER BY
                change_percent ASC

            LIMIT 10;
        """

    try:

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute(query)

                rows = cur.fetchall()

                columns = [
                    "symbol",
                    "isin",
                    "series",
                    "trade_date",
                    "current_price",
                    "previous_price",
                    "price_change",
                    "change_percent"
                ]

                data = [
                    dict(zip(columns, row))
                    for row in rows
                ]

        return {
            "status": "success",
            "count": len(data),
            "data": data
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Unable to load top losers: {str(e)}"
        )


# ==========================================================
# BSE Live Indices
# ==========================================================

BSE_LIVE_FILE = (
    Path(__file__).resolve().parents[2]
    / "public"
    / "bse-live-market.json"
)


@app.get("/api/live/bse/indices")
def bse_live_indices():

    try:

        if not BSE_LIVE_FILE.exists():

            raise HTTPException(
                status_code=404,
                detail="BSE live market file not found."
            )

        with open(
            BSE_LIVE_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        return {
            "status": "success",
            "source": "BSE",
            "last_updated": data.get(
                "last_updated"
            ),
            "count": len(
                data.get(
                    "major_indices",
                    []
                )
            ),
            "data": data.get(
                "major_indices",
                []
            )
        }

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to load BSE live indices: "
                f"{str(e)}"
            )
        )

    
# ==========================================================
# Corporate Action Summary
# ==========================================================

@app.get("/api/corporate-actions/summary")
def corporate_actions_summary():

    query = """
        SELECT
            COUNT(*) AS total,

            COUNT(*) FILTER (
                WHERE action_type = 'DIVIDEND'
            ) AS dividend,

            COUNT(*) FILTER (
                WHERE action_type = 'BONUS'
            ) AS bonus,

            COUNT(*) FILTER (
                WHERE action_type = 'RIGHTS'
            ) AS rights,

            COUNT(*) FILTER (
                WHERE action_type = 'BUYBACK'
            ) AS buyback,

            COUNT(*) FILTER (
                WHERE action_type = 'BOARD_MEETING'
            ) AS board_meeting,

            /*
             * Last Updated priority:
             * 1. updated_at
             * 2. created_at
             * 3. record_received_date as a date-only fallback
             *
             * This prevents the UI from showing "-" when updated_at
             * is not populated for older corporate-action records.
             */
           MAX(
            COALESCE(
            updated_at,
            created_at,
            record_received_date::timestamp
            )
            ) AS last_updated

        FROM corporate_actions;
    """

    try:

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute(query)

                row = cur.fetchone()

        return {
            "status": "success",
            "total": row[0],
            "dividend": row[1],
            "bonus": row[2],
            "rights": row[3],
            "buyback": row[4],
            "boardMeeting": row[5],
            "last_updated": row[6]
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Unable to load corporate action summary: {str(e)}"
        )


# ==========================================================
# Corporate Actions List
# ==========================================================

@app.get("/api/corporate-actions")
def corporate_actions():

    query = """
        SELECT
            corporate_action_id,
            security_id,
            symbol,
            isin,
            series,
            subject,
            ex_date,
            record_date,
            record_received_date,
            action_type,
            match_method,
            broadcast_date,
            created_at,
            updated_at

        FROM corporate_actions

        ORDER BY
            ex_date DESC NULLS LAST,
            symbol;
    """

    try:

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute(query)

                rows = cur.fetchall()

                columns = [
                    "corporate_action_id",
                    "security_id",
                    "symbol",
                    "isin",
                    "series",
                    "subject",
                    "ex_date",
                    "record_date",
                    "record_received_date",
                    "action_type",
                    "match_method",
                    "broadcast_date",
                    "created_at",
                    "updated_at"
                ]

                data = [
                    dict(zip(columns, row))
                    for row in rows
                ]

        return {
            "status": "success",
            "count": len(data),
            "data": data
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Unable to load corporate actions: {str(e)}"
        )


# ==========================================================
# Security Counts
# ==========================================================

@app.get("/api/market/security-counts")
def market_security_counts():

    query = """
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN sm.series IN ('EQ', 'BE', 'BZ')
                        THEN 1
                        ELSE 0
                    END
                ),
                0
            ) AS equity,

            COALESCE(
                SUM(
                    CASE
                        WHEN sm.series = 'SM'
                        THEN 1
                        ELSE 0
                    END
                ),
                0
            ) AS sme

        FROM daily_prices dp

        JOIN security_master sm
            ON sm.security_id = dp.security_id

        WHERE dp.trade_date = (
            SELECT MAX(trade_date)
            FROM daily_prices
        );
    """

    try:

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute(query)

                row = cur.fetchone()

        return {
            "status": "success",
            "equity": row[0],
            "sme": row[1]
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Unable to load security counts: {str(e)}"
        )

# ==========================================================
# Stock Search
# ==========================================================

@app.get("/api/stock/search")
def stock_search(q: str = ""):

    query_text = q.strip()

    if not query_text:
        return {
            "status": "success",
            "count": 0,
            "data": []
        }

    search_pattern = f"%{query_text}%"

    try:

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        security_id,
                        symbol,
                        isin,
                        series,
                        instrument_id,
                        instrument_type,
                        instrument_name,
                        exchange,
                        segment,
                        security_category,
                        is_active

                    FROM security_master

                    WHERE
                        UPPER(symbol) LIKE UPPER(%s)

                        OR UPPER(isin) LIKE UPPER(%s)

                        OR UPPER(instrument_name) LIKE UPPER(%s)

                        OR CAST(instrument_id AS TEXT) LIKE %s

                        OR UPPER(series) LIKE UPPER(%s)

                    ORDER BY
                        CASE
                            WHEN UPPER(symbol) = UPPER(%s)
                                THEN 1

                            WHEN UPPER(isin) = UPPER(%s)
                                THEN 2

                            WHEN UPPER(symbol) LIKE UPPER(%s)
                                THEN 3

                            WHEN UPPER(instrument_name) LIKE UPPER(%s)
                                THEN 4

                            ELSE 5
                        END,

                        is_active DESC,

                        symbol

                    LIMIT 20
                    """,

                    (
                        search_pattern,
                        search_pattern,
                        search_pattern,
                        search_pattern,
                        search_pattern,

                        query_text,
                        query_text,
                        f"{query_text}%",
                        f"{query_text}%"
                    )
                )

                rows = cur.fetchall()

        columns = [
            "security_id",
            "symbol",
            "isin",
            "series",
            "instrument_id",
            "instrument_type",
            "instrument_name",
            "exchange",
            "segment",
            "security_category",
            "is_active"
        ]

        data = [
            dict(zip(columns, row))
            for row in rows
        ]

        return {
            "status": "success",
            "count": len(data),
            "data": data
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Unable to search securities: {str(e)}"
        )



# ==========================================================
# Stock Detail API
# ==========================================================

@app.get("/api/stock/{symbol}")
def stock_detail(symbol: str):

    symbol = symbol.strip().upper()

    try:

        with get_connection() as conn:

            with conn.cursor() as cur:

                # ==========================================
                # Security Master
                # ==========================================

                cur.execute(
                    """
                    SELECT
                        security_id,
                        symbol,
                        isin,
                        series,
                        instrument_id,
                        instrument_type,
                        instrument_name,
                        exchange,
                        segment,
                        security_category,
                        is_active

                    FROM security_master

                    WHERE UPPER(symbol) = %s

                    ORDER BY
                        is_active DESC,
                        security_id

                    LIMIT 1
                    """,
                    (symbol,)
                )

                security = cur.fetchone()

                if not security:

                    raise HTTPException(
                        status_code=404,
                        detail=f"Security not found: {symbol}"
                    )

                security_columns = [
                    "security_id",
                    "symbol",
                    "isin",
                    "series",
                    "instrument_id",
                    "instrument_type",
                    "instrument_name",
                    "exchange",
                    "segment",
                    "security_category",
                    "is_active"
                ]

                security_data = dict(
                    zip(
                        security_columns,
                        security
                    )
                )

                security_id = security_data["security_id"]


                # ==========================================
                # Latest Price
                # ==========================================

                cur.execute(
                    """
                    SELECT
                        trade_date,
                        open,
                        high,
                        low,
                        close,
                        last_price,
                        previous_close,
                        volume,
                        turnover

                    FROM daily_prices

                    WHERE security_id = %s

                    ORDER BY trade_date DESC

                    LIMIT 1
                    """,
                    (security_id,)
                )

                latest = cur.fetchone()

                latest_data = None

                if latest:

                    latest_columns = [
                        "trade_date",
                        "open",
                        "high",
                        "low",
                        "close",
                        "last_price",
                        "previous_close",
                        "volume",
                        "turnover"
                    ]

                    latest_data = dict(
                        zip(
                            latest_columns,
                            latest
                        )
                    )


                # ==========================================
                # Historical Prices
                # ==========================================

                cur.execute(
                    """
                    SELECT
                        trade_date,
                        open,
                        high,
                        low,
                        close,
                        last_price,
                        previous_close,
                        volume,
                        turnover

                    FROM daily_prices

                    WHERE security_id = %s

                    ORDER BY trade_date DESC

                    LIMIT 100
                    """,
                    (security_id,)
                )

                price_rows = cur.fetchall()

                price_columns = [
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "last_price",
                    "previous_close",
                    "volume",
                    "turnover"
                ]

                historical_prices = [
                    dict(
                        zip(
                            price_columns,
                            row
                        )
                    )
                    for row in price_rows
                ]


                # ==========================================
                # Corporate Actions
                # ==========================================

                cur.execute(
                    """
                    SELECT
                        corporate_action_id,
                        subject,
                        action_type,
                        ex_date,
                        record_date,
                        record_received_date,
                        bc_start_date,
                        bc_end_date,
                        nd_start_date,
                        nd_end_date,
                        face_value,
                        broadcast_date,
                        match_method

                    FROM corporate_actions

                    WHERE security_id = %s

                    ORDER BY
                        ex_date DESC NULLS LAST,
                        broadcast_date DESC NULLS LAST

                    LIMIT 100
                    """,
                    (security_id,)
                )

                action_rows = cur.fetchall()

                action_columns = [
                    "corporate_action_id",
                    "subject",
                    "action_type",
                    "ex_date",
                    "record_date",
                    "record_received_date",
                    "bc_start_date",
                    "bc_end_date",
                    "nd_start_date",
                    "nd_end_date",
                    "face_value",
                    "broadcast_date",
                    "match_method"
                ]

                corporate_actions = [
                    dict(
                        zip(
                            action_columns,
                            row
                        )
                    )
                    for row in action_rows
                ]

        # ==========================================================
        # Events
        # ==========================================================

        EVENT_ACTION_TYPES = {
            "BOARD_MEETING",
            "AGM",
            "EGM",
            "ANNOUNCEMENT",
            "POSTAL_BALLOT"
        }

        events = [
            action
            for action in corporate_actions
            if str(action.get("action_type", "")).upper()
            in EVENT_ACTION_TYPES
        ]


        # ==========================================================
        # Corporate Actions
        # ==========================================================

        corporate_action_items = [
            action
            for action in corporate_actions
            if str(action.get("action_type", "")).upper()
            not in EVENT_ACTION_TYPES
        ]

        return {
            "status": "success",
            "security": security_data,
            "latest_price": latest_data,
            "historical_prices": historical_prices,
            "corporate_actions": corporate_action_items,
            "events": events,
            "results": []
        }

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Unable to load stock details: {str(e)}"
        )


# ==========================================================
# Dividend Dashboard API
# ==========================================================

@app.get("/api/dividends/dashboard")
def dividend_dashboard():

    query = """
        WITH dividend_actions AS (

            SELECT
                ca.security_id,
                ca.symbol,
                ca.series,
                ca.ex_date,
                ca.record_date,
                ca.record_received_date,

                CASE

                    WHEN regexp_match(
                        UPPER(ca.subject),
                        '(?:RS|RE)\\s*([0-9]+(?:\\.[0-9]+)?)'
                    ) IS NOT NULL

                    THEN (
                        regexp_match(
                            UPPER(ca.subject),
                            '(?:RS|RE)\\s*([0-9]+(?:\\.[0-9]+)?)'
                        )
                    )[1]::numeric

                    ELSE NULL

                END AS dividend_amount

            FROM corporate_actions ca

            WHERE ca.action_type = 'DIVIDEND'
        ),


        latest_prices AS (

            SELECT DISTINCT ON (dp.security_id)

                dp.security_id,
                dp.trade_date,
                dp.close,
                dp.previous_close

            FROM daily_prices dp

            ORDER BY
                dp.security_id,
                dp.trade_date DESC
        )


        SELECT

            d.symbol,

            d.series,

            d.dividend_amount AS dividend,

            d.ex_date,

            d.record_date,

            d.record_received_date,

            lp.close AS current_price,


            /* ------------------------------------------
               Dividend Yield

               Dividend / Previous Close × 100
               ------------------------------------------ */

            CASE

                WHEN
                    d.dividend_amount IS NOT NULL
                    AND lp.previous_close IS NOT NULL
                    AND lp.previous_close <> 0

                THEN ROUND(
                    (
                        d.dividend_amount /
                        lp.previous_close
                    ) * 100,
                    2
                )

                ELSE NULL

            END AS dividend_yield_percent,


            /* ------------------------------------------
               Price Change Since Announcement

               Current Price -
               Price on Record Received Date

               Only calculate when the latest market
               price is on or after the record received date.
               ------------------------------------------ */

            CASE

                WHEN
                    d.record_received_date IS NOT NULL
                    AND lp.trade_date >= d.record_received_date
                    AND lp.close IS NOT NULL
                    AND received_price.close IS NOT NULL

                THEN
                    lp.close -
                    received_price.close

                ELSE NULL

            END AS price_change_since_announcement,


            /* ------------------------------------------
               Price Change %

               Change / Record Received Date Price × 100
               ------------------------------------------ */

            CASE

                WHEN
                    d.record_received_date IS NOT NULL
                    AND lp.trade_date >= d.record_received_date
                    AND lp.close IS NOT NULL
                    AND received_price.close IS NOT NULL
                    AND received_price.close <> 0

                THEN ROUND(
                    (
                        (
                            lp.close -
                            received_price.close
                        )
                        /
                        received_price.close
                    ) * 100,
                    2
                )

                ELSE NULL

            END AS price_change_since_announcement_percent


        FROM dividend_actions d


        /* ----------------------------------------------
           Latest available market price
           ---------------------------------------------- */

        LEFT JOIN latest_prices lp

            ON lp.security_id =
               d.security_id


        /* ----------------------------------------------
           Price on / before Record Received Date
           ---------------------------------------------- */

        LEFT JOIN LATERAL (

            SELECT
                dp.trade_date,
                dp.close

            FROM daily_prices dp

            WHERE
                dp.security_id =
                    d.security_id

                AND d.record_received_date IS NOT NULL

                AND dp.trade_date <=
                    d.record_received_date

            ORDER BY
                dp.trade_date DESC

            LIMIT 1

        ) received_price

        ON TRUE


        ORDER BY
            d.ex_date DESC NULLS LAST,
            d.symbol;
    """


    last_updated_query = """
        SELECT
            COALESCE(
                MAX(updated_at),
                MAX(created_at),
                MAX(record_received_date)::timestamp
            ) AS last_updated

        FROM corporate_actions;
    """


    try:

        with get_connection() as conn:

            with conn.cursor() as cur:

                # ------------------------------------------
                # Dividend data
                # ------------------------------------------

                cur.execute(query)

                rows = cur.fetchall()


                # ------------------------------------------
                # Last updated
                # ------------------------------------------

                cur.execute(
                    last_updated_query
                )

                last_updated_row = cur.fetchone()


        # ==================================================
        # Clean API response
        # ==================================================

        columns = [
            "symbol",
            "series",
            "dividend",
            "ex_date",
            "record_date",
            "record_received_date",
            "current_price",
            "dividend_yield_percent",
            "price_change_since_announcement",
            "price_change_since_announcement_percent"
        ]


        data = [
            dict(
                zip(
                    columns,
                    row
                )
            )
            for row in rows
        ]


        last_updated = (
            last_updated_row[0]
            if last_updated_row
            else None
        )


        return {

            "status": "success",

            "count": len(data),

            "last_updated": last_updated,

            "data": data

        }


    except Exception as e:

        raise HTTPException(

            status_code=500,

            detail=(
                "Unable to load dividend dashboard: "
                f"{str(e)}"
            )

        )



# ==========================================================
# Market News & Feeds
# ==========================================================

@app.get("/api/news/overview")
def market_news_overview():
    query = """
        SELECT
            COUNT(*) AS total_events,
            COUNT(*) FILTER (WHERE UPPER(TRIM(COALESCE(mapping_status, ''))) = 'MAPPED') AS mapped_events,
            COUNT(*) FILTER (WHERE UPPER(TRIM(COALESCE(mapping_status, ''))) <> 'MAPPED') AS not_mapped_events,
            COUNT(*) FILTER (
                WHERE UPPER(TRIM(COALESCE(mapping_status, ''))) = 'MAPPED'
                  AND UPPER(TRIM(COALESCE(asset_category, ''))) NOT IN ('MUTUAL_FUND', 'ETF', 'BOND', 'OTHER')
            ) AS equity_events,
            COUNT(*) FILTER (
                WHERE UPPER(TRIM(COALESCE(mapping_status, ''))) = 'MAPPED'
                  AND UPPER(TRIM(COALESCE(asset_category, ''))) = 'MUTUAL_FUND'
            ) AS mutual_fund_events,
            COUNT(*) FILTER (
                WHERE UPPER(TRIM(COALESCE(mapping_status, ''))) = 'MAPPED'
                  AND UPPER(TRIM(COALESCE(asset_category, ''))) = 'ETF'
            ) AS etf_events,
            COUNT(*) FILTER (
                WHERE UPPER(TRIM(COALESCE(mapping_status, ''))) = 'MAPPED'
                  AND UPPER(TRIM(COALESCE(asset_category, ''))) = 'BOND'
            ) AS bond_events,
            COUNT(*) FILTER (
                WHERE UPPER(TRIM(COALESCE(mapping_status, ''))) = 'MAPPED'
                  AND UPPER(TRIM(COALESCE(asset_category, ''))) = 'OTHER'
            ) AS other_events,
            MAX(created_at) AS latest_data_pulled_at,
            MAX(published_at) AS latest_published_at
        FROM market_news;
    """

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()

        columns = [
            "total_events", "mapped_events", "not_mapped_events",
            "equity_events", "mutual_fund_events", "etf_events",
            "bond_events", "other_events",
            "latest_data_pulled_at", "latest_published_at",
        ]
        data = dict(zip(columns, row))
        return {"status": "success", **data}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to load market news overview: {str(e)}",
        )


@app.get("/api/news/pipeline-overview")
def market_news_pipeline_overview():
    """Return a control-tower view of MarketPulse data universe and pipeline coverage."""
    queries = {
        "masters": """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE is_active = TRUE) AS active,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(asset_category,'')) = 'EQUITY') AS equity,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(asset_category,'')) = 'MUTUAL_FUND') AS mutual_fund,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(asset_category,'')) = 'ETF') AS etf,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(asset_category,'')) = 'BOND') AS bond,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(asset_category,'')) = 'OTHER') AS other,
                COUNT(*) FILTER (WHERE asset_category IS NULL OR TRIM(asset_category) = '') AS unclassified
            FROM security_master;
        """,
        "events": """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(mapping_status,'')) = 'MAPPED') AS mapped,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(mapping_status,'')) = 'PENDING') AS pending,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(mapping_status,'')) = 'AMBIGUOUS') AS ambiguous,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(mapping_status,'')) = 'NOT_APPLICABLE') AS not_applicable,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(asset_category,'')) = 'EQUITY' AND UPPER(COALESCE(mapping_status,'')) = 'MAPPED') AS equity,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(asset_category,'')) = 'MUTUAL_FUND' AND UPPER(COALESCE(mapping_status,'')) = 'MAPPED') AS mutual_fund,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(asset_category,'')) = 'ETF' AND UPPER(COALESCE(mapping_status,'')) = 'MAPPED') AS etf,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(asset_category,'')) = 'BOND' AND UPPER(COALESCE(mapping_status,'')) = 'MAPPED') AS bond,
                COUNT(*) FILTER (WHERE UPPER(COALESCE(asset_category,'')) = 'OTHER' AND UPPER(COALESCE(mapping_status,'')) = 'MAPPED') AS other
            FROM market_news;
        """,
        "audit": """
            SELECT
                COUNT(*) AS total_audited,
                COUNT(*) FILTER (WHERE pit_reason = 'HISTORY_AVAILABLE' AND feature_reason = 'READY_FOR_SCORING') AS feature_ready,
                COUNT(*) FILTER (WHERE pit_reason = 'HISTORY_AVAILABLE' AND feature_reason = 'READY_FOR_SCORING'
                    AND prediction_1d_status = 'AVAILABLE'
                    AND prediction_5d_status = 'AVAILABLE'
                    AND prediction_10d_status = 'AVAILABLE') AS fully_scored,
                COUNT(*) FILTER (WHERE pit_reason = 'INSUFFICIENT_HISTORY') AS insufficient_history,
                COUNT(*) FILTER (WHERE pit_reason = 'NO_HISTORY') AS no_history,
                COUNT(*) FILTER (WHERE pit_reason = 'NOT_MAPPED') AS not_mapped,
                COUNT(*) FILTER (WHERE pit_reason = 'NO_PUBLISHED_AT') AS no_published_at,
                COUNT(*) FILTER (WHERE pit_reason = 'NOT_APPLICABLE') AS not_applicable,
                COUNT(*) FILTER (WHERE feature_reason = 'FEATURES_NOT_BUILT') AS features_missing
            FROM market_news_ml_pipeline_audit;
        """,
        "predictions": """
            SELECT
                COUNT(*) FILTER (WHERE horizon = 1) AS rows_1d,
                COUNT(*) FILTER (WHERE horizon = 5) AS rows_5d,
                COUNT(*) FILTER (WHERE horizon = 10) AS rows_10d,
                COUNT(DISTINCT news_id) FILTER (WHERE horizon = 1) AS events_1d,
                COUNT(DISTINCT news_id) FILTER (WHERE horizon = 5) AS events_5d,
                COUNT(DISTINCT news_id) FILTER (WHERE horizon = 10) AS events_10d
            FROM market_news_ml_predictions;
        """,
        "prices": """
            SELECT
                COUNT(*) AS price_rows,
                COUNT(DISTINCT security_id) AS securities_with_prices,
                MAX(trade_date) AS latest_price_date
            FROM daily_prices;
        """,
        "features": """
            SELECT COUNT(*) AS feature_rows, COUNT(DISTINCT news_id) AS feature_events
            FROM market_news_ml_features;
        """,
        "freshness": """
            SELECT MAX(created_at) AS latest_data_pulled_at,
                   MAX(published_at) AS latest_published_at
            FROM market_news;
        """,
    }

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                result = {}
                for key, query in queries.items():
                    cur.execute(query)
                    row = cur.fetchone()
                    result[key] = row

        def as_dict(row, columns):
            return dict(zip(columns, row))

        masters = as_dict(result["masters"], ["total","active","equity","mutual_fund","etf","bond","other","unclassified"])
        events = as_dict(result["events"], ["total","mapped","pending","ambiguous","not_applicable","equity","mutual_fund","etf","bond","other"])
        audit = as_dict(result["audit"], ["total_audited","feature_ready","fully_scored","insufficient_history","no_history","not_mapped","no_published_at","not_applicable","features_missing"])
        predictions = as_dict(result["predictions"], ["rows_1d","rows_5d","rows_10d","events_1d","events_5d","events_10d"])
        prices = as_dict(result["prices"], ["price_rows","securities_with_prices","latest_price_date"])
        features = as_dict(result["features"], ["feature_rows","feature_events"])
        freshness = as_dict(result["freshness"], ["latest_data_pulled_at","latest_published_at"])

        return {
            "status": "success",
            "masters": masters,
            "events": events,
            "audit": audit,
            "predictions": predictions,
            "prices": prices,
            "features": features,
            "freshness": freshness,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unable to load pipeline overview: {str(e)}")

@app.get("/api/news")
def market_news(
    limit: int = 500,
    offset: int = 0,
    exchange: str = "ALL",
    category: str = "ALL",
    search: str = "",
    feed: str = "EQUITY",
    asset_category: str = "ALL",
):

    limit = max(1, min(limit, 1000))
    offset = max(0, offset)

    exchange_filter = exchange.strip().upper()
    category_filter = category.strip().upper()
    search_text = search.strip()
    feed_filter = feed.strip().upper()
    asset_category_filter = asset_category.strip()

    valid_feeds = {"EQUITY", "NON_EQUITY", "EXCEPTIONS", "ALL"}
    valid_asset_categories = {
        "ALL", "EQUITY", "MUTUAL_FUND", "ETF", "BOND", "OTHER", "UNCLASSIFIED",
    }

    if feed_filter not in valid_feeds:
        feed_filter = "EQUITY"

    if asset_category_filter not in valid_asset_categories:
        asset_category_filter = "ALL"

    valid_exchanges = {"ALL", "NSE", "BSE"}

    valid_categories = {
        "ALL",
        "ANNOUNCEMENTS",
        "BOARD_MEETINGS",
        "CORPORATE_ACTIONS",
        "FINANCIAL_RESULTS",
        "NOTICES",
    }

    if exchange_filter not in valid_exchanges:
        exchange_filter = "ALL"

    if category_filter not in valid_categories:
        category_filter = "ALL"

    where_clauses = []
    params = []

    if exchange_filter != "ALL":
        where_clauses.append("mn.exchange = %s")
        params.append(exchange_filter)

    if category_filter != "ALL":
        where_clauses.append("mn.category = %s")
        params.append(category_filter)

    if search_text:
        search_pattern = f"%{search_text}%"

        where_clauses.append(
            """
            (
                COALESCE(mn.symbol, '') ILIKE %s
                OR COALESCE(mn.company_name, '') ILIKE %s
                OR COALESCE(mn.title, '') ILIKE %s
                OR COALESCE(mn.description, '') ILIKE %s
                OR COALESCE(mn.category, '') ILIKE %s
                OR COALESCE(mn.external_id, '') ILIKE %s
                OR COALESCE(mn.asset_category, '') ILIKE %s
                OR COALESCE(mn.mapping_status, '') ILIKE %s
                OR CAST(COALESCE(mn.news_id, 0) AS TEXT) ILIKE %s
                OR CAST(COALESCE(mn.security_id, 0) AS TEXT) ILIKE %s
                OR COALESCE(sm.isin, '') ILIKE %s
                OR COALESCE(sm.bse_scrip_code, '') ILIKE %s
                OR COALESCE(sm.nse_symbol, '') ILIKE %s
                OR COALESCE(sm.bse_symbol, '') ILIKE %s
                OR COALESCE(sm.nse_name, '') ILIKE %s
                OR COALESCE(sm.bse_name, '') ILIKE %s
            )
            """
        )

        params.extend([search_pattern] * 16)

    # Feed routing is based first on mapping status, then on asset category:
    #   1) anything not MAPPED -> Exceptions / Not classified or not mapped
    #   2) MAPPED + non-equity asset -> Mutual funds / ETF / Bonds / Others
    #   3) MAPPED + everything else -> Equity market events
    # Normalize mapping_status so values such as "Mapped", "MAPPED " or
    # " pending " do not break routing.
    normalized_mapping_status = "UPPER(TRIM(COALESCE(mn.mapping_status, '')))"

    if feed_filter == "EQUITY":
        where_clauses.append(
            f"""
            (
                {normalized_mapping_status} = 'MAPPED'
                AND COALESCE(UPPER(TRIM(mn.asset_category)), '') NOT IN
                    ('MUTUAL_FUND', 'ETF', 'BOND', 'OTHER')
            )
            """
        )
    elif feed_filter == "NON_EQUITY":
        where_clauses.append(
            f"""
            (
                {normalized_mapping_status} = 'MAPPED'
                AND UPPER(TRIM(COALESCE(mn.asset_category, ''))) IN
                    ('MUTUAL_FUND', 'ETF', 'BOND', 'OTHER')
            )
            """
        )
    elif feed_filter == "EXCEPTIONS":
        where_clauses.append(
            f"{normalized_mapping_status} <> 'MAPPED'"
        )

    if asset_category_filter != "ALL":
        if asset_category_filter == "UNCLASSIFIED":
            where_clauses.append("mn.asset_category IS NULL")
        else:
            where_clauses.append("mn.asset_category = %s")
            params.append(asset_category_filter)

    where_sql = ""

    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    count_query = f"""
        SELECT COUNT(*)
        FROM market_news mn
        LEFT JOIN security_master sm
            ON sm.security_id = mn.security_id
        {where_sql};
    """

    query = f"""
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
            mn.source_url,
            mn.external_id,
            mn.created_at,
            mn.impact_level,
            mn.direction,
            mn.asset_category,
            mn.mapping_status,
            mn.mapping_method,
            mn.mapping_confidence,
            amd.decision_id AS agent_decision_id,
            amd.decision AS agent_decision,
            amd.security_id AS agent_predicted_security_id,
            amd.confidence AS agent_prediction_confidence,
            amd.reason AS agent_reason,
            amd.status AS agent_decision_status,
            amd.reviewed_at AS agent_reviewed_at,
            amd.reviewed_by AS agent_reviewed_by,
            sm.isin,
            sm.bse_scrip_code,
            sm.nse_symbol,
            sm.bse_symbol,
            COUNT(mna.attachment_id) AS attachment_count,

            mlp1.predicted_direction AS ml_1d_predicted_direction,
            mlp1.negative_probability AS ml_1d_negative_probability,
            mlp1.neutral_probability AS ml_1d_neutral_probability,
            mlp1.positive_probability AS ml_1d_positive_probability,
            mlp1.prediction_score AS ml_1d_prediction_score,
            mlp1.predicted_at AS ml_1d_predicted_at,
            mlp5.predicted_direction AS ml_5d_predicted_direction,
            mlp5.negative_probability AS ml_5d_negative_probability,
            mlp5.neutral_probability AS ml_5d_neutral_probability,
            mlp5.positive_probability AS ml_5d_positive_probability,
            mlp5.prediction_score AS ml_5d_prediction_score,
            mlp5.predicted_at AS ml_5d_predicted_at,
            mlp10.predicted_direction AS ml_10d_predicted_direction,
            mlp10.negative_probability AS ml_10d_negative_probability,
            mlp10.neutral_probability AS ml_10d_neutral_probability,
            mlp10.positive_probability AS ml_10d_positive_probability,
            mlp10.prediction_score AS ml_10d_prediction_score,
            mlp10.predicted_at AS ml_10d_predicted_at,
            f.forward_return_1d AS actual_return_plus_1d,
            f.forward_return_5d AS actual_return_plus_5d,
            f.forward_return_10d AS actual_return_plus_10d,
            f.direction_1d AS actual_direction_plus_1d,
            f.direction_5d AS actual_direction_plus_5d,
            f.direction_10d AS actual_direction_plus_10d,
            (f.direction_1d IS NOT NULL) AS actual_outcome_available_1d,
            (f.direction_5d IS NOT NULL) AS actual_outcome_available_5d,
            (f.direction_10d IS NOT NULL) AS actual_outcome_available_10d,
            CASE WHEN mn.mapping_status <> 'MAPPED' THEN 'NOT_MAPPED' WHEN mlp1.news_id IS NOT NULL THEN 'AVAILABLE' WHEN f.news_id IS NOT NULL THEN 'NO_PREDICTION' WHEN mn.published_at IS NULL THEN 'NO_PUBLISHED_AT' WHEN hist.history_rows = 0 THEN 'NO_HISTORY' WHEN hist.history_rows < 20 THEN 'INSUFFICIENT_HISTORY' ELSE 'NO_FEATURES' END AS ml_1d_prediction_status,
            CASE WHEN mn.mapping_status <> 'MAPPED' THEN 'NOT_MAPPED' WHEN mlp5.news_id IS NOT NULL THEN 'AVAILABLE' WHEN f.news_id IS NOT NULL THEN 'NO_PREDICTION' WHEN mn.published_at IS NULL THEN 'NO_PUBLISHED_AT' WHEN hist.history_rows = 0 THEN 'NO_HISTORY' WHEN hist.history_rows < 20 THEN 'INSUFFICIENT_HISTORY' ELSE 'NO_FEATURES' END AS ml_5d_prediction_status,
            CASE WHEN mn.mapping_status <> 'MAPPED' THEN 'NOT_MAPPED' WHEN mlp10.news_id IS NOT NULL THEN 'AVAILABLE' WHEN f.news_id IS NOT NULL THEN 'NO_PREDICTION' WHEN mn.published_at IS NULL THEN 'NO_PUBLISHED_AT' WHEN hist.history_rows = 0 THEN 'NO_HISTORY' WHEN hist.history_rows < 20 THEN 'INSUFFICIENT_HISTORY' ELSE 'NO_FEATURES' END AS ml_10d_prediction_status,
            hist.history_rows AS ml_history_rows,
            'LightGBM' AS ml_model_name,
            'LightGBM-1D/5D/10D' AS ml_model_version,

            pa.pit_status AS pipeline_pit_status,
            pa.pit_reason AS pipeline_pit_reason,
            pa.pit_reason_detail AS pipeline_pit_reason_detail,
            pa.feature_status AS pipeline_feature_status,
            pa.feature_reason AS pipeline_feature_reason,
            pa.feature_reason_detail AS pipeline_feature_reason_detail,
            pa.last_stage AS pipeline_last_stage,
            pa.checked_at AS pipeline_checked_at

        FROM market_news mn

        LEFT JOIN security_master sm
            ON sm.security_id = mn.security_id

        LEFT JOIN market_news_attachments mna
            ON mna.news_id = mn.news_id

        LEFT JOIN market_news_ml_features f
            ON f.news_id = mn.news_id

        LEFT JOIN market_news_ml_predictions mlp1
            ON mlp1.news_id = mn.news_id AND mlp1.horizon = 1
        LEFT JOIN market_news_ml_predictions mlp5
            ON mlp5.news_id = mn.news_id AND mlp5.horizon = 5
        LEFT JOIN market_news_ml_predictions mlp10
            ON mlp10.news_id = mn.news_id AND mlp10.horizon = 10

        LEFT JOIN market_news_ml_pipeline_audit pa
            ON pa.news_id = mn.news_id

        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS history_rows
            FROM daily_prices dp
            WHERE dp.security_id = mn.security_id
              AND dp.trade_date BETWEEN
                  (CASE
                    WHEN (mn.published_at AT TIME ZONE 'Asia/Kolkata')::time > TIME '15:30'
                      THEN (mn.published_at AT TIME ZONE 'Asia/Kolkata')::date
                    ELSE ((mn.published_at AT TIME ZONE 'Asia/Kolkata')::date - INTERVAL '1 day')::date
                  END - INTERVAL '140 days')::date
                  AND CASE
                    WHEN (mn.published_at AT TIME ZONE 'Asia/Kolkata')::time > TIME '15:30'
                      THEN (mn.published_at AT TIME ZONE 'Asia/Kolkata')::date
                    ELSE ((mn.published_at AT TIME ZONE 'Asia/Kolkata')::date - INTERVAL '1 day')::date
                  END
        ) hist ON TRUE

            LEFT JOIN LATERAL (
                SELECT
                    d.decision_id,
                    d.decision,
                    d.security_id,
                    d.confidence,
                    d.reason,
                    d.status,
                    d.reviewed_at,
                    d.reviewed_by
                FROM security_mapping_decisions d
                WHERE d.news_id = mn.news_id
                ORDER BY d.created_at DESC, d.decision_id DESC
                LIMIT 1
            ) amd ON TRUE


        {where_sql}

        GROUP BY
            mn.news_id,
            mn.exchange,
            mn.symbol,
            mn.security_id,
            mn.company_name,
            mn.category,
            mn.title,
            mn.description,
            mn.published_at,
            mn.source_url,
            mn.external_id,
            mn.created_at,
            mn.impact_level,
            mn.direction,
            mn.asset_category,
            mn.mapping_status,
            mn.mapping_method,
            mn.mapping_confidence,
            amd.decision_id,
            amd.decision,
            amd.security_id,
            amd.confidence,
            amd.reason,
            amd.status,
            amd.reviewed_at,
            amd.reviewed_by,
            sm.isin,
            sm.bse_scrip_code,
            sm.nse_symbol,
            sm.bse_symbol,
            mlp1.news_id, mlp1.predicted_direction, mlp1.negative_probability, mlp1.neutral_probability, mlp1.positive_probability, mlp1.prediction_score, mlp1.predicted_at,
            mlp5.news_id, mlp5.predicted_direction, mlp5.negative_probability, mlp5.neutral_probability, mlp5.positive_probability, mlp5.prediction_score, mlp5.predicted_at,
            mlp10.news_id, mlp10.predicted_direction, mlp10.negative_probability, mlp10.neutral_probability, mlp10.positive_probability, mlp10.prediction_score, mlp10.predicted_at,
            f.news_id, f.forward_return_1d, f.forward_return_5d, f.forward_return_10d, f.direction_1d, f.direction_5d, f.direction_10d, hist.history_rows,
            pa.pit_status, pa.pit_reason, pa.pit_reason_detail,
            pa.feature_status, pa.feature_reason, pa.feature_reason_detail,
            pa.last_stage, pa.checked_at

        ORDER BY
            mn.published_at DESC NULLS LAST,
            mn.created_at DESC NULLS LAST,
            mn.news_id DESC

        LIMIT %s
        OFFSET %s;
    """

    try:

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    count_query,
                    tuple(params)
                )

                total = cur.fetchone()[0] or 0

                cur.execute(
                    query,
                    tuple(params) + (limit, offset)
                )

                rows = cur.fetchall()

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
            "external_id",
            "created_at",
            "impact_level",
            "direction",
            "asset_category",
            "mapping_status",
            "mapping_method",
            "mapping_confidence",
            "agent_decision_id",
            "agent_decision",
            "agent_predicted_security_id",
            "agent_prediction_confidence",
            "agent_reason",
            "agent_decision_status",
            "agent_reviewed_at",
            "agent_reviewed_by",
            "isin",
            "bse_scrip_code",
            "nse_symbol",
            "bse_symbol",
            "attachment_count",
            "ml_1d_predicted_direction", "ml_1d_negative_probability", "ml_1d_neutral_probability", "ml_1d_positive_probability", "ml_1d_prediction_score", "ml_1d_predicted_at",
            "ml_5d_predicted_direction", "ml_5d_negative_probability", "ml_5d_neutral_probability", "ml_5d_positive_probability", "ml_5d_prediction_score", "ml_5d_predicted_at",
            "ml_10d_predicted_direction", "ml_10d_negative_probability", "ml_10d_neutral_probability", "ml_10d_positive_probability", "ml_10d_prediction_score", "ml_10d_predicted_at",
            "actual_return_plus_1d", "actual_return_plus_5d", "actual_return_plus_10d", "actual_direction_plus_1d", "actual_direction_plus_5d", "actual_direction_plus_10d",
            "actual_outcome_available_1d", "actual_outcome_available_5d", "actual_outcome_available_10d",
            "ml_1d_prediction_status", "ml_5d_prediction_status", "ml_10d_prediction_status", "ml_history_rows",
            "ml_model_name", "ml_model_version",
            "pipeline_pit_status", "pipeline_pit_reason", "pipeline_pit_reason_detail",
            "pipeline_feature_status", "pipeline_feature_reason", "pipeline_feature_reason_detail",
            "pipeline_last_stage", "pipeline_checked_at",
        ]

        data = [
            dict(zip(columns, row))
            for row in rows
        ]

        return {
            "status": "success",
            "count": len(data),
            "total": total,
            "limit": limit,
            "offset": offset,
            "exchange": exchange_filter,
            "category": category_filter,
            "data": data,
            "news": data,
        }

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Unable to load market news: {str(e)}"
        )

# ==========================================================
# Targeted Security Mapping
# ==========================================================

@app.post("/api/mapping/run-event")
def run_event_mapping(request: MapperEventRequest):
    """
    Run the canonical MarketPulse security mapper for exactly one
    unmapped news event.

    This does NOT run the mapper against the full news universe.
    It restricts the mapper to the supplied news_id.
    """

    news_id = int(request.news_id)

    if news_id <= 0:
        raise HTTPException(
            status_code=400,
            detail="news_id must be positive."
        )

    mapper_script = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "backend"
        / "marketpulse_map_news_security.py"
    )

    if not mapper_script.exists():
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Canonical mapping script not found.",
                "mapper_script": str(mapper_script),
            },
        )

    try:

        # ------------------------------------------------------
        # 1. Validate the news event
        # ------------------------------------------------------

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        mn.news_id,
                        mn.news_scope,
                        mn.exchange,
                        mn.symbol,
                        mn.company_name,
                        mn.security_id,
                        mn.mapping_status,
                        mn.mapping_method,
                        mn.mapping_confidence,
                        mn.asset_category
                    FROM market_news mn
                    WHERE mn.news_id = %s
                    """,
                    (news_id,),
                )

                row = cur.fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"News event {news_id} not found."
            )

        (
            _news_id,
            news_scope,
            exchange,
            symbol,
            company_name,
            previous_security_id,
            previous_mapping_status,
            previous_mapping_method,
            previous_mapping_confidence,
            previous_asset_category,
        ) = row

        # ------------------------------------------------------
        # 2. Only STOCK events belong to security mapping
        # ------------------------------------------------------

        if str(news_scope or "").upper() != "STOCK":
            raise HTTPException(
                status_code=409,
                detail=(
                    "This event is not a STOCK event and cannot be "
                    "mapped to a security."
                ),
            )

        # ------------------------------------------------------
        # 3. If already mapped, don't remap it
        # ------------------------------------------------------

        if (
            previous_security_id is not None
            and str(previous_mapping_status or "").upper() == "MAPPED"
        ):
            with get_connection() as conn:
                with conn.cursor() as cur:

                    cur.execute(
                        """
                        SELECT
                            security_id,
                            symbol,
                            instrument_name,
                            exchange,
                            isin,
                            asset_category
                        FROM security_master
                        WHERE security_id = %s
                        """,
                        (previous_security_id,),
                    )

                    security = cur.fetchone()

            return {
                "success": True,
                "already_mapped": True,
                "news_id": news_id,
                "mapping_status": "MAPPED",
                "mapping_method": previous_mapping_method,
                "mapping_confidence": previous_mapping_confidence,
                "security": (
                    {
                        "security_id": security[0],
                        "symbol": security[1],
                        "instrument_name": security[2],
                        "exchange": security[3],
                        "isin": security[4],
                        "asset_category": security[5],
                    }
                    if security
                    else None
                ),
            }

        # ------------------------------------------------------
        # 4. Run canonical mapper for ONLY this news_id
        # ------------------------------------------------------

        command = [
            sys.executable,
            str(mapper_script),
            "--apply",
            "--only-unmapped",
            "--start-id",
            str(news_id),
            "--end-id",
            str(news_id),
        ]

        completed = subprocess.run(
            command,
            cwd=str(Path(__file__).resolve().parents[2]),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        if completed.returncode != 0:
            raise RuntimeError(
                "Security mapper failed.\n"
                f"Exit code: {completed.returncode}\n"
                f"STDOUT:\n{completed.stdout[-6000:]}\n"
                f"STDERR:\n{completed.stderr[-6000:]}"
            )

        # ------------------------------------------------------
        # 5. Read the mapping result from PostgreSQL
        # ------------------------------------------------------

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT
                        mn.news_id,
                        mn.security_id,
                        mn.mapping_status,
                        mn.mapping_method,
                        mn.mapping_confidence,
                        mn.asset_category,
                        sm.symbol,
                        sm.instrument_name,
                        sm.exchange,
                        sm.isin
                    FROM market_news mn
                    LEFT JOIN security_master sm
                        ON sm.security_id = mn.security_id
                    WHERE mn.news_id = %s
                    """,
                    (news_id,),
                )

                result = cur.fetchone()

        if not result:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"News event {news_id} disappeared while "
                    "mapping was running."
                ),
            )

        (
            result_news_id,
            security_id,
            mapping_status,
            mapping_method,
            mapping_confidence,
            asset_category,
            mapped_symbol,
            instrument_name,
            mapped_exchange,
            isin,
        ) = result

        # ------------------------------------------------------
        # 6. Return a clean UI response
        # ------------------------------------------------------

        return {
            "success": True,
            "already_mapped": False,
            "news_id": result_news_id,
            "previous_mapping": {
                "security_id": previous_security_id,
                "mapping_status": previous_mapping_status,
                "mapping_method": previous_mapping_method,
                "mapping_confidence": previous_mapping_confidence,
            },
            "mapping_status": mapping_status,
            "mapping_method": mapping_method,
            "mapping_confidence": mapping_confidence,
            "asset_category": asset_category,
            "security": (
                {
                    "security_id": security_id,
                    "symbol": mapped_symbol,
                    "instrument_name": instrument_name,
                    "exchange": mapped_exchange,
                    "isin": isin,
                }
                if security_id is not None
                else None
            ),
            "mapper_output": completed.stdout[-4000:],
        }

    except HTTPException:
        raise

    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail=(
                f"Security mapping timed out for news_id {news_id}."
            ),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Unable to map event {news_id}: {str(e)}"
            ),
        )


# ==========================================================
# Targeted LightGBM Scoring
# ==========================================================

@app.post("/api/ml/score-event")
def score_event(request: ScoreEventRequest):
    """Build PIT/features and score one mapped market event using existing models."""

    news_id = int(request.news_id)

    if news_id <= 0:
        raise HTTPException(status_code=400, detail="news_id must be positive.")

    ai_scoring_dir = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "backend"
        / "AI Scoring"
        / "individual_stocks"
    )

    pit_script = ai_scoring_dir / "marketpulse_build_ml_dataset_pit_v2.py"
    feature_script = ai_scoring_dir / "marketpulse_build_event_features.py"
    score_script = ai_scoring_dir / "marketpulse_score_lightgbm_1d.py"

    required_scripts = [pit_script, feature_script, score_script]
    missing_scripts = [str(path) for path in required_scripts if not path.exists()]
    if missing_scripts:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "One or more LightGBM pipeline scripts are missing.",
                "missing_scripts": missing_scripts,
            },
        )

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        mn.news_id,
                        mn.security_id,
                        mn.mapping_status,
                        mn.asset_category,
                        sm.instrument_name,
                        sm.asset_category AS security_asset_category
                    FROM market_news mn
                    LEFT JOIN security_master sm
                        ON sm.security_id = mn.security_id
                    WHERE mn.news_id = %s
                    """,
                    (news_id,),
                )
                row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="News event not found.")

        (
            _news_id,
            security_id,
            mapping_status,
            asset_category,
            instrument_name,
            security_asset_category,
        ) = row

        if not security_id or str(mapping_status or "").upper() != "MAPPED":
            raise HTTPException(
                status_code=409,
                detail="Map the event to a canonical security before running LightGBM scoring.",
            )

        if str(security_asset_category or asset_category or "").upper() != "EQUITY":
            raise HTTPException(
                status_code=409,
                detail=(
                    "LightGBM price-reaction scoring is currently available only "
                    f"for EQUITY events. Current asset category: "
                    f"{security_asset_category or asset_category or 'UNCLASSIFIED'}."
                ),
            )

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            prefix="marketpulse_score_",
            delete=False,
            encoding="utf-8",
        ) as handle:
            handle.write(f"{news_id}\n")
            news_ids_file = Path(handle.name)

        def run_stage(stage_name: str, script: Path, args: list[str], timeout: int = 300):
            command = [sys.executable, str(script), *args]
            completed = subprocess.run(
                command,
                cwd=str(Path(__file__).resolve().parents[2]),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"{stage_name} failed with exit code {completed.returncode}.\n"
                    f"STDOUT:\n{completed.stdout[-6000:]}\n"
                    f"STDERR:\n{completed.stderr[-6000:]}"
                )
            return completed

        # 1. PIT sample for exactly this event.
        run_stage(
            "PIT build",
            pit_script,
            ["--start-id", str(news_id), "--end-id", str(news_id)],
            timeout=300,
        )

        # 2. Event features for exactly this event.
        run_stage(
            "Feature build",
            feature_script,
            ["--news-ids-file", str(news_ids_file)],
            timeout=300,
        )

        # 3. Score exactly this event using existing trained models.
        run_stage(
            "LightGBM scoring",
            score_script,
            ["--all", "--news-ids-file", str(news_ids_file)],
            timeout=300,
        )

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        horizon,
                        predicted_direction,
                        negative_probability,
                        neutral_probability,
                        positive_probability,
                        prediction_score,
                        event_trade_date,
                        prediction_cutoff_ts,
                        prediction_note,
                        predicted_at
                    FROM market_news_ml_predictions
                    WHERE news_id = %s
                    ORDER BY horizon
                    """,
                    (news_id,),
                )
                rows = cur.fetchall()

        horizons = {}
        for row in rows:
            (
                horizon,
                predicted_direction,
                negative_probability,
                neutral_probability,
                positive_probability,
                prediction_score,
                event_trade_date,
                prediction_cutoff_ts,
                prediction_note,
                predicted_at,
            ) = row
            horizons[f"{int(horizon)}D"] = {
                "predicted_direction": predicted_direction,
                "negative_probability": negative_probability,
                "neutral_probability": neutral_probability,
                "positive_probability": positive_probability,
                "prediction_score": prediction_score,
                "event_trade_date": event_trade_date,
                "prediction_cutoff_ts": prediction_cutoff_ts,
                "prediction_note": prediction_note,
                "predicted_at": predicted_at,
            }

        if not horizons:
            raise HTTPException(
                status_code=422,
                detail=(
                    "The LightGBM stages completed, but no prediction rows were produced "
                    f"for news_id {news_id}. This event may not have sufficient PIT history/features."
                ),
            )

        return {
            "success": True,
            "news_id": news_id,
            "security_id": security_id,
            "instrument_name": instrument_name,
            "asset_category": security_asset_category or asset_category,
            "horizons": horizons,
        }

    except HTTPException:
        raise
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="LightGBM scoring timed out while processing this event.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to score event {news_id}: {str(e)}",
        )
    finally:
        try:
            if 'news_ids_file' in locals() and news_ids_file.exists():
                news_ids_file.unlink()
        except Exception:
            pass


# ==========================================================
# Manual Security Mapping
# ==========================================================

@app.post("/api/mapping/manual")
def manual_security_mapping(request: ManualMappingRequest):

    try:

        with get_connection() as conn:

            with conn.cursor() as cur:

                # --------------------------------------------------
                # 1. Validate security exists
                # --------------------------------------------------

                cur.execute(
                    """
                    SELECT
                        security_id,
                        instrument_name,
                        exchange,
                        asset_category,
                        is_active
                    FROM security_master
                    WHERE security_id = %s
                    """,
                    (request.security_id,)
                )

                security = cur.fetchone()

                if not security:
                    raise HTTPException(
                        status_code=404,
                        detail="Security not found in security_master."
                    )

                security_asset_category = security[3]

                # --------------------------------------------------
                # 2. Read current news mapping
                # --------------------------------------------------

                cur.execute(
                    """
                    SELECT
                        news_id,
                        exchange,
                        company_name,
                        mapping_status,
                        security_id
                    FROM market_news
                    WHERE news_id = %s
                    FOR UPDATE
                    """,
                    (request.news_id,)
                )

                news = cur.fetchone()

                if not news:
                    raise HTTPException(
                        status_code=404,
                        detail="News event not found."
                    )

                (
                    news_id,
                    news_exchange,
                    company_name,
                    previous_status,
                    previous_security_id,
                ) = news

                # --------------------------------------------------
                # 3. Update market_news
                # --------------------------------------------------

                cur.execute(
                    """
                    UPDATE market_news
                    SET
                        security_id = %s,
                        mapping_status = 'MAPPED',
                        mapping_method = 'USER_CONFIRMED',
                        mapping_confidence = 1.000,
                        asset_category = %s
                    WHERE news_id = %s
                    """,
                    (
                        request.security_id,
                        security_asset_category,
                        request.news_id,
                    )
                )

                # --------------------------------------------------
                # 4. Persist user-confirmed identity
                # --------------------------------------------------

                identity_value = (
                    request.alias
                    or company_name
                    or ""
                ).strip()

                if identity_value:

                    normalized_value = " ".join(
                        identity_value.upper().split()
                    )

                    cur.execute(
                        """
                        INSERT INTO security_identity (
                            security_id,
                            identity_type,
                            identity_value,
                            normalized_value,
                            exchange,
                            source,
                            confidence,
                            is_active,
                            evidence
                        )
                        VALUES (
                            %s,
                            'ALIAS',
                            %s,
                            %s,
                            %s,
                            'USER_CONFIRMED',
                            1.00000,
                            TRUE,
                            %s::jsonb
                        )
                        ON CONFLICT (
                            security_id,
                            identity_type,
                            normalized_value,
                            exchange
                        )
                        DO UPDATE SET
                            source = 'USER_CONFIRMED',
                            confidence = 1.00000,
                            is_active = TRUE,
                            evidence = EXCLUDED.evidence,
                            updated_at = CURRENT_TIMESTAMP
                        """,
                        (
                            request.security_id,
                            identity_value,
                            normalized_value,
                            news_exchange,
                            json.dumps({
                                "news_id": request.news_id,
                                "previous_status": previous_status,
                                "previous_security_id": previous_security_id,
                                "reviewer": request.reviewer,
                                "confirmed_at": datetime.utcnow().isoformat(),
                            }),
                        )
                    )

                # --------------------------------------------------
                # 5. Preserve Agent prediction and record review
                # --------------------------------------------------

                cur.execute(
                    """
                    UPDATE security_mapping_decisions
                    SET
                        status = 'USER_CONFIRMED',
                        reviewed_at = CURRENT_TIMESTAMP,
                        reviewed_by = %s,
                        requires_review = FALSE,
                        evidence = COALESCE(evidence, '{}'::jsonb)
                            || %s::jsonb
                    WHERE news_id = %s
                      AND decision = 'MATCH'
                    """,
                    (
                        request.reviewer,
                        json.dumps({
                            "user_confirmed_security_id":
                                request.security_id,
                            "previous_security_id":
                                previous_security_id,
                            "manual_mapping": True,
                        }),
                        request.news_id,
                    )
                )

            conn.commit()

        return {
            "status": "success",
            "news_id": request.news_id,
            "security_id": request.security_id,
            "mapping_status": "MAPPED",
            "mapping_method": "USER_CONFIRMED",
        }

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Unable to update security mapping: {str(e)}"
        )

# ==========================================================
# Agent Mapping Feedback
# ==========================================================

@app.post("/api/mapping/agent-feedback")
def agent_mapping_feedback(request: AgentFeedbackRequest):

    verdict = request.verdict.strip().upper()

    if verdict not in {"CORRECT", "WRONG"}:
        raise HTTPException(
            status_code=400,
            detail="verdict must be CORRECT or WRONG."
        )

    try:

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute(
                    """
                    SELECT decision_id
                    FROM security_mapping_decisions
                    WHERE news_id = %s
                    ORDER BY created_at DESC, decision_id DESC
                    LIMIT 1
                    """,
                    (request.news_id,)
                )

                row = cur.fetchone()

                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail="No Agent decision found for this news event."
                    )

                decision_id = row[0]

                cur.execute(
                    """
                    UPDATE security_mapping_decisions
                    SET
                        status = 'USER_REVIEWED',
                        reviewed_at = CURRENT_TIMESTAMP,
                        reviewed_by = %s,
                        requires_review = FALSE,
                        evidence = COALESCE(evidence, '{}'::jsonb)
                            || %s::jsonb
                    WHERE decision_id = %s
                    """,
                    (
                        request.reviewer,
                        json.dumps({
                            "review_outcome": verdict,
                            "wrong_reason": request.wrong_reason,
                            "comment": request.comment,
                        }),
                        decision_id,
                    )
                )

            conn.commit()

        return {
            "status": "success",
            "news_id": request.news_id,
            "decision_id": decision_id,
            "review_outcome": verdict,
        }

    except HTTPException:
        raise

    except Exception as e:

        raise HTTPException(
            status_code=500,
            detail=f"Unable to save Agent feedback: {str(e)}"
        )

    

# ==========================================================
# BSE Market Trend
# ==========================================================

@app.get("/api/live/bse/trend")
def bse_market_trend(period: str = "1M"):

    from datetime import date, timedelta
    import requests

    period = period.upper()

    period_days = {
        "1W": 7,
        "1M": 31,
        "1Y": 365,
    }

    if period not in period_days:
        period = "1M"

    to_date = date.today()

    from_date = (
        to_date -
        timedelta(
            days=period_days[period]
        )
    )

    url = (
        "https://api.bseindia.com"
        "/BseIndiaAPI/api/ProduceCSVForDate/w"
    )

    params = {
        "strIndex": "SENSEX",

        "dtFromDate":
            from_date.strftime("%d/%m/%Y"),

        "dtToDate":
            to_date.strftime("%d/%m/%Y"),

        "period": "D",
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/139.0.0.0 Safari/537.36"
        ),

        "Accept":
            "text/csv,application/json,text/plain,*/*",

        "Referer":
            "https://www.bseindia.com/",
    }

    try:

        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=30
        )

        response.raise_for_status()

        print()
        print("=" * 70)
        print("BSE MARKET TREND")
        print("=" * 70)

        print(
            "URL:",
            response.url
        )

        print(
            "HTTP Status:",
            response.status_code
        )

        print(
            "Content-Type:",
            response.headers.get(
                "Content-Type"
            )
        )

        # --------------------------------------------------
        # BSE returns CSV for this endpoint
        # --------------------------------------------------

        text = response.text.strip()

        if not text:

            return {
                "status": "success",
                "source": "BSE",
                "index": "SENSEX",
                "period": period,
                "count": 0,
                "data": []
            }

        # --------------------------------------------------
        # Read CSV
        # --------------------------------------------------

        from io import StringIO

        import pandas as pd

        df = pd.read_csv(
            StringIO(text)
        )

        print(
            "CSV Columns:",
            list(df.columns)
        )

        print(
            "Rows:",
            len(df)
        )

        # --------------------------------------------------
        # Normalize column names
        # --------------------------------------------------

        df.columns = [
            str(column).strip()
            for column in df.columns
        ]

        # --------------------------------------------------
        # Find columns
        # --------------------------------------------------

        date_column = None
        close_column = None

        for column in df.columns:

            normalized = (
                str(column)
                .strip()
                .lower()
            )

            if normalized == "date":

                date_column = column

            elif normalized == "close":

                close_column = column

        if (
            date_column is None
            or close_column is None
        ):

            raise ValueError(
                "BSE historical response "
                "does not contain Date/Close columns. "
                f"Columns received: {list(df.columns)}"
            )

        # --------------------------------------------------
        # Build chart data
        # --------------------------------------------------

        trend = []

        for _, row in df.iterrows():

            raw_date = row.get(
                date_column
            )

            raw_close = row.get(
                close_column
            )

            if (
                pd.isna(raw_date)
                or pd.isna(raw_close)
            ):
                continue

            try:

                close_value = float(
                    raw_close
                )

            except (
                TypeError,
                ValueError
            ):

                continue

            trend.append({

                "date":
                    str(raw_date),

                "value":
                    close_value,

            })

        # --------------------------------------------------
        # Sort by date
        # --------------------------------------------------

        trend.sort(
            key=lambda item:
                item["date"]
        )

        print(
            "Trend records:",
            len(trend)
        )

        if trend:

            print(
                "First:",
                trend[0]
            )

            print(
                "Last:",
                trend[-1]
            )

        return {

            "status":
                "success",

            "source":
                "BSE",

            "index":
                "SENSEX",

            "period":
                period,

            "from_date":
                from_date.isoformat(),

            "to_date":
                to_date.isoformat(),

            "count":
                len(trend),

            "data":
                trend,

        }

    except requests.RequestException as error:

        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to fetch BSE "
                f"market trend: {error}"
            )
        )

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to process BSE "
                f"market trend: {error}"
            )
        )