from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import psycopg
import os

load_dotenv()


# ==========================================================
# MarketPulse API
# ==========================================================

app = FastAPI(
    title="MarketPulse API",
    version="1.0.0"
)


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
        SELECT
            MAX(trade_date) AS market_date,
            COUNT(*) AS total_securities
        FROM latest_price_movement;
    """

    try:

        with get_connection() as conn:

            with conn.cursor() as cur:

                cur.execute(query)

                row = cur.fetchone()

        return {
            "status": "success",
            "market_date": row[0],
            "total_securities": row[1]
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

        WHERE change_percent IS NOT NULL

        ORDER BY change_percent DESC

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

        WHERE change_percent IS NOT NULL

        ORDER BY change_percent ASC

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


        return {
            "status": "success",
            "security": security_data,
            "latest_price": latest_data,
            "historical_prices": historical_prices,
            "corporate_actions": corporate_actions
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