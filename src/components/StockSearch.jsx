import { useEffect, useMemo, useState } from "react";
import "../StockSearch.css";
import { API_BASE_URL } from "../config";

function StockSearch() {
    const [symbol, setSymbol] = useState("ADSL");
    const [searchValue, setSearchValue] = useState("ADSL");

    const [stock, setStock] = useState(null);

    const [searchResults, setSearchResults] = useState([]);

    const [loading, setLoading] = useState(false);
    const [searching, setSearching] = useState(false);

    const [error, setError] = useState("");

    // ==========================================================
    // LOAD STOCK DETAILS
    // ==========================================================

    const fetchStock = async (stockSymbol) => {
        const cleanSymbol = String(stockSymbol || "")
            .trim()
            .toUpperCase();

        if (!cleanSymbol) {
            return;
        }

        setLoading(true);
        setError("");

        try {
            const response = await fetch(
                `${API_BASE_URL}/api/stock/${encodeURIComponent(
                    cleanSymbol
                )}`
            );

            if (!response.ok) {
                throw new Error(
                    `Unable to load stock (${response.status})`
                );
            }

            const result = await response.json();

            if (!result) {
                throw new Error(
                    "No stock data returned."
                );
            }

            setStock(result);
            setSymbol(cleanSymbol);

            setSearchResults([]);

        } catch (err) {
            console.error(
                "Stock detail error:",
                err
            );

            setStock(null);

            setError(
                err?.message ||
                "Unable to load stock information."
            );

        } finally {
            setLoading(false);
        }
    };


    // ==========================================================
    // SEARCH SECURITIES
    // ==========================================================

    const searchStocks = async () => {
        const query = searchValue.trim();

        if (!query) {
            setSearchResults([]);
            return;
        }

        setSearching(true);
        setError("");

        try {
            const response = await fetch(
                `${API_BASE_URL}/api/stock/search?q=${encodeURIComponent(
                    query
                )}`
            );

            if (!response.ok) {
                throw new Error(
                    `Search failed (${response.status})`
                );
            }

            const result = await response.json();

            console.log(
                "Stock search result:",
                result
            );

            const results =
                Array.isArray(result?.data)
                    ? result.data
                    : [];

            setSearchResults(results);

            if (results.length === 0) {
                setError(
                    `No securities found for "${query}".`
                );
            }

        } catch (err) {
            console.error(
                "Stock search error:",
                err
            );

            setSearchResults([]);

            setError(
                err?.message ||
                "Unable to search stocks."
            );

        } finally {
            setSearching(false);
        }
    };


    // ==========================================================
    // SEARCH BUTTON
    // ==========================================================

    const handleSearch = () => {
        searchStocks();
    };


    // ==========================================================
    // ENTER KEY
    // ==========================================================

    const handleKeyDown = (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            searchStocks();
        }
    };


    // ==========================================================
    // SELECT SEARCH RESULT
    // ==========================================================

    const handleSelectStock = (result) => {
        if (!result) {
            return;
        }

        const selectedSymbol =
            result.symbol ||
            result.trading_symbol;

        if (!selectedSymbol) {
            setError(
                "Selected security does not have a symbol."
            );

            return;
        }

        setSearchValue(selectedSymbol);

        setSearchResults([]);

        fetchStock(selectedSymbol);
    };


    // ==========================================================
    // INITIAL STOCK
    // ==========================================================

    useEffect(() => {
        fetchStock("ADSL");
    }, []);


    // ==========================================================
    // NORMALISE API DATA
    // ==========================================================

    const security =
        stock?.security || {};

    const latest =
        stock?.latest_price || {};

    const historicalPrices =
        Array.isArray(
            stock?.historical_prices
        )
            ? stock.historical_prices
            : [];

    const corporateActionItems =
        Array.isArray(
            stock?.corporate_actions
        )
            ? stock.corporate_actions
            : [];

    const eventItems =
        Array.isArray(
            stock?.events
        )
            ? stock.events
            : [];

    const resultItems =
        Array.isArray(
            stock?.results
        )
            ? stock.results
            : [];


    // ==========================================================
    // LAST 5 TRADING DAYS
    // ==========================================================

    const recentPrices = useMemo(() => {

        return [...historicalPrices]
            .sort((a, b) => {
                return (
                    new Date(b.trade_date) -
                    new Date(a.trade_date)
                );
            })
            .slice(0, 5);

    }, [historicalPrices]);


    // ==========================================================
    // RESULTS
    // ==========================================================

    /*
     * Results data is not yet returned by the backend.
     *
     * We intentionally do NOT manufacture Positive / Negative
     * values. The UI is ready for actual result data.
     */

    const resultQuarters = [
        {
            quarter: "Q1",
            actual: null,
            expected: null,
            actualDate: null,
            expectedDate: null
        },
        {
            quarter: "Q2",
            actual: null,
            expected: null,
            actualDate: null,
            expectedDate: null
        },
        {
            quarter: "Q3",
            actual: null,
            expected: null,
            actualDate: null,
            expectedDate: null
        },
        {
            quarter: "Q4",
            actual: null,
            expected: null,
            actualDate: null,
            expectedDate: null
        }
    ];


    // ==========================================================
    // PRICE CHANGE
    // ==========================================================

    const currentPrice = Number(
        latest.close ??
        latest.last_price ??
        0
    );

    const previousClose = Number(
        latest.previous_close ??
        0
    );

    const priceChange =
        previousClose
            ? currentPrice - previousClose
            : 0;

    const changePercent =
        previousClose
            ? (priceChange / previousClose) * 100
            : 0;

    const isPositive =
        priceChange > 0;

    const isNegative =
        priceChange < 0;


    // ==========================================================
    // FORMAT NUMBER
    // ==========================================================

    const formatNumber = (value) => {

        if (
            value === null ||
            value === undefined ||
            value === ""
        ) {
            return "—";
        }

        const number = Number(value);

        if (Number.isNaN(number)) {
            return value;
        }

        return number.toLocaleString(
            "en-IN",
            {
                maximumFractionDigits: 2
            }
        );
    };


    // ==========================================================
    // FORMAT PRICE
    // ==========================================================

    const formatPrice = (value) => {

        if (
            value === null ||
            value === undefined ||
            value === ""
        ) {
            return "—";
        }

        const number = Number(value);

        if (Number.isNaN(number)) {
            return value;
        }

        return `₹${number.toLocaleString(
            "en-IN",
            {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            }
        )}`;
    };


    // ==========================================================
    // FORMAT DATE
    // ==========================================================

    const formatDate = (value) => {

        if (!value) {
            return "—";
        }

        const date = new Date(value);

        if (Number.isNaN(date.getTime())) {
            return value;
        }

        return date.toLocaleDateString(
            "en-IN",
            {
                day: "2-digit",
                month: "short",
                year: "numeric"
            }
        );
    };


    // ==========================================================
    // RENDER
    // ==========================================================

    return (

        <div className="mp-stock-page">


            {/* ==================================================
                PAGE HEADER
            ================================================== */}

            <section className="mp-stock-page-header">

                <div className="mp-stock-title-row">

                    <div>

                        <div className="mp-eyebrow">
                            MARKETPULSE
                        </div>

                        <h1>
                            Stock News &amp; Feed
                        </h1>

                        <p>
                            Stock information, recent price
                            action, corporate actions and market news.
                        </p>

                    </div>

                </div>


                {/* ==================================================
                    SEARCH
                ================================================== */}

                <div className="mp-stock-search">

                    <input
                        type="text"
                        value={searchValue}
                        onChange={(event) => {

                            setSearchValue(
                                event.target.value
                            );

                            setSearchResults([]);

                            if (error) {
                                setError("");
                            }

                        }}
                        onKeyDown={handleKeyDown}
                        placeholder="Search symbol, company name or ISIN..."
                        aria-label="Search stock"
                    />

                    <button
                        type="button"
                        onClick={handleSearch}
                        disabled={
                            searching ||
                            loading
                        }
                    >

                        {searching
                            ? "Searching..."
                            : "Search"}

                    </button>

                </div>


                {/* ==================================================
                    SEARCH RESULTS
                ================================================== */}

                {searchResults.length > 0 && (

                    <div className="mp-stock-search-results">

                        <div className="mp-search-results-title">
                            Matching Securities
                        </div>


                        {searchResults.map(
                            (result, index) => (

                                <button
                                    type="button"
                                    className="mp-search-result"
                                    key={
                                        result.security_id ||
                                        result.symbol ||
                                        index
                                    }
                                    onClick={() =>
                                        handleSelectStock(
                                            result
                                        )
                                    }
                                >

                                    <div className="mp-search-result-main">

                                        <strong>
                                            {result.symbol ||
                                                "—"}
                                        </strong>

                                        <span>
                                            {result.instrument_name ||
                                                result.name ||
                                                "Company name unavailable"}
                                        </span>

                                    </div>


                                    <div className="mp-search-result-meta">

                                        {result.exchange && (
                                            <span>
                                                {result.exchange}
                                            </span>
                                        )}

                                        {result.series && (
                                            <span>
                                                {result.series}
                                            </span>
                                        )}

                                        {result.isin && (
                                            <span>
                                                ISIN:{" "}
                                                {result.isin}
                                            </span>
                                        )}

                                    </div>

                                </button>

                            )
                        )}

                    </div>

                )}

            </section>


            {/* ==================================================
                ERROR
            ================================================== */}

            {error && (

                <div className="mp-stock-error">
                    {error}
                </div>

            )}


            {/* ==================================================
                STOCK OVERVIEW
            ================================================== */}

            {stock && (

                <section className="mp-stock-overview">


                    {/* STOCK IDENTITY */}

                    <div className="mp-stock-identity">

                        <div className="mp-stock-symbol">
                            {security.symbol ||
                                symbol}
                        </div>

                        <div className="mp-stock-company">
                            {security.instrument_name ||
                                security.name ||
                                "Company name unavailable"}
                        </div>

                        <div className="mp-stock-meta">

                            {security.exchange ||
                                "BSE"}

                            <span>
                                •
                            </span>

                            {security.series ||
                                "EQ"}

                            {security.isin && (
                                <>

                                    <span>
                                        •
                                    </span>

                                    {security.isin}

                                </>
                            )}

                        </div>

                    </div>


                    {/* PRICE */}

                    <div className="mp-stock-price">

                        <div className="mp-stock-price-label">
                            LAST PRICE
                        </div>

                        <div className="mp-stock-price-value">

                            {formatPrice(
                                currentPrice
                            )}

                        </div>

                        <div
                            className={
                                `mp-stock-price-change ${
                                    isPositive
                                        ? "positive"
                                        : isNegative
                                        ? "negative"
                                        : "neutral"
                                }`
                            }
                        >

                            {isPositive
                                ? "+"
                                : ""}

                            {formatPrice(
                                priceChange
                            )}

                            <span>

                                (
                                {isPositive
                                    ? "+"
                                    : ""}
                                {changePercent.toFixed(
                                    2
                                )}
                                %)

                            </span>

                        </div>

                    </div>


                    {/* METRICS */}

                    <div className="mp-stock-metrics">


                        <div className="mp-stock-metric">

                            <span>
                                Trade Date
                            </span>

                            <strong>
                                {formatDate(
                                    latest.trade_date
                                )}
                            </strong>

                        </div>


                        <div className="mp-stock-metric">

                            <span>
                                Open
                            </span>

                            <strong>
                                {formatPrice(
                                    latest.open
                                )}
                            </strong>

                        </div>


                        <div className="mp-stock-metric">

                            <span>
                                High
                            </span>

                            <strong>
                                {formatPrice(
                                    latest.high
                                )}
                            </strong>

                        </div>


                        <div className="mp-stock-metric">

                            <span>
                                Low
                            </span>

                            <strong>
                                {formatPrice(
                                    latest.low
                                )}
                            </strong>

                        </div>


                        <div className="mp-stock-metric">

                            <span>
                                Prev. Close
                            </span>

                            <strong>
                                {formatPrice(
                                    latest.previous_close
                                )}
                            </strong>

                        </div>


                        <div className="mp-stock-metric">

                            <span>
                                Volume
                            </span>

                            <strong>
                                {formatNumber(
                                    latest.volume
                                )}
                            </strong>

                        </div>


                        <div className="mp-stock-metric">

                            <span>
                                Turnover
                            </span>

                            <strong>
                                {latest.turnover
                                    ? formatNumber(
                                        latest.turnover
                                    )
                                    : "—"}
                            </strong>

                        </div>

                    </div>

                </section>

            )}


            {/* ==================================================
                RECENT PRICE ACTION
            ================================================== */}

            {stock && (

                <section className="mp-stock-card">

                    <div className="mp-stock-card-header">

                        <div>

                            <h2>
                                Recent Price Action
                            </h2>

                            <p>
                                Last 5 trading days
                            </p>

                        </div>

                        <span className="mp-stock-card-badge">
                            5 DAYS
                        </span>

                    </div>


                    <div className="mp-price-table-wrapper">

                        <table className="mp-price-table">

                            <thead>

                                <tr>

                                    <th>
                                        Date
                                    </th>

                                    <th>
                                        Open
                                    </th>

                                    <th>
                                        High
                                    </th>

                                    <th>
                                        Low
                                    </th>

                                    <th>
                                        Close
                                    </th>

                                    <th>
                                        Volume
                                    </th>

                                </tr>

                            </thead>


                            <tbody>

                                {recentPrices.length === 0 ? (

                                    <tr>

                                        <td
                                            colSpan="6"
                                            className="mp-empty-cell"
                                        >
                                            No historical price
                                            data available.
                                        </td>

                                    </tr>

                                ) : (

                                    recentPrices.map(
                                        (price, index) => (

                                            <tr
                                                key={
                                                    price.trade_date ||
                                                    index
                                                }
                                            >

                                                <td>
                                                    {formatDate(
                                                        price.trade_date
                                                    )}
                                                </td>

                                                <td>
                                                    {formatPrice(
                                                        price.open
                                                    )}
                                                </td>

                                                <td>
                                                    {formatPrice(
                                                        price.high
                                                    )}
                                                </td>

                                                <td>
                                                    {formatPrice(
                                                        price.low
                                                    )}
                                                </td>

                                                <td className="price-close">
                                                    {formatPrice(
                                                        price.close
                                                    )}
                                                </td>

                                                <td>
                                                    {formatNumber(
                                                        price.volume
                                                    )}
                                                </td>

                                            </tr>

                                        )
                                    )

                                )}

                            </tbody>

                        </table>

                    </div>

                </section>

            )}


            {/* ==================================================
                CORPORATE ACTIONS + EVENTS
            ================================================== */}

            {stock && (

                <section className="mp-actions-events-grid">


                    {/* ==================================================
                        CORPORATE ACTIONS
                    ================================================== */}

                    <div className="mp-stock-card">

                        <div className="mp-stock-card-header">

                            <div>

                                <h2>
                                    Corporate Actions
                                </h2>

                                <p>
                                    Dividends, bonus, rights and other actions
                                </p>

                            </div>

                            <span className="mp-stock-card-badge">
                                {corporateActionItems.length}
                            </span>

                        </div>


                        <div className="mp-corporate-actions">

                            {corporateActionItems.length === 0 ? (

                                <div className="mp-empty-cell">
                                    No corporate actions available.
                                </div>

                            ) : (

                                corporateActionItems
                                    .slice(0, 5)
                                    .map(
                                        (action, index) => (

                                            <div
                                                className="mp-corporate-action"
                                                key={
                                                    action.corporate_action_id ||
                                                    index
                                                }
                                            >

                                                <div className="mp-action-type">

                                                    {action.action_type ||
                                                        "ACTION"}

                                                </div>


                                                <div className="mp-action-details">

                                                    <strong>

                                                        {action.subject ||
                                                            "Corporate action"}

                                                    </strong>


                                                    <div className="mp-action-dates">

                                                        {action.ex_date && (

                                                            <span>

                                                                Ex:{" "}
                                                                {formatDate(
                                                                    action.ex_date
                                                                )}

                                                            </span>

                                                        )}


                                                        {action.record_date && (

                                                            <span>

                                                                Record:{" "}
                                                                {formatDate(
                                                                    action.record_date
                                                                )}

                                                            </span>

                                                        )}

                                                    </div>

                                                </div>


                                                <div className="mp-action-date">

                                                    {formatDate(
                                                        action.ex_date ||
                                                        action.broadcast_date
                                                    )}

                                                </div>

                                            </div>

                                        )
                                    )

                            )}

                        </div>

                    </div>


                    {/* ==================================================
                        EVENTS
                    ================================================== */}

                    <div className="mp-stock-card">

                        <div className="mp-stock-card-header">

                            <div>

                                <h2>
                                    Events
                                </h2>

                                <p>
                                    Board meetings and company announcements
                                </p>

                            </div>

                            <span className="mp-stock-card-badge">
                                {eventItems.length}
                            </span>

                        </div>


                        <div className="mp-events-list">

                            {eventItems.length === 0 ? (

                                <div className="mp-empty-cell">
                                    No upcoming events available.
                                </div>

                            ) : (

                                eventItems
                                    .slice(0, 5)
                                    .map(
                                        (event, index) => (

                                            <div
                                                className="mp-event-item"
                                                key={
                                                    event.corporate_action_id ||
                                                    index
                                                }
                                            >

                                                <div className="mp-event-date">

                                                    <strong>

                                                        {formatDate(
                                                            event.ex_date ||
                                                            event.broadcast_date
                                                        )}

                                                    </strong>

                                                </div>


                                                <div className="mp-event-content">

                                                    <div className="mp-event-type">

                                                        {event.action_type ===
                                                        "BOARD_MEETING"
                                                            ? "Board Meeting"
                                                            : "Announcement"}

                                                    </div>


                                                    <div className="mp-event-subject">

                                                        {event.subject ||
                                                            "Company event"}

                                                    </div>


                                                    {event.broadcast_date && (

                                                        <div className="mp-event-broadcast">

                                                            Announced{" "}

                                                            {formatDate(
                                                                event.broadcast_date
                                                            )}

                                                        </div>

                                                    )}

                                                </div>

                                            </div>

                                        )
                                    )

                            )}

                        </div>

                    </div>

                </section>

            )}


            {/* ==================================================
                RESULTS
            ================================================== */}

            {stock && (

                <section className="mp-stock-card mp-results-card">

                    <div className="mp-stock-card-header">

                        <div>

                            <h2>
                                Results
                            </h2>

                            <p>
                                Quarterly and annual result outlook
                            </p>

                        </div>

                        <span className="mp-stock-card-badge">
                            Q1 — Q4
                        </span>

                    </div>


                    <div className="mp-results-table-wrapper">

                        <table className="mp-results-table">

                            <thead>

                                <tr>

                                    <th>
                                        Status
                                    </th>

                                    {resultQuarters.map(
                                        (item) => (

                                            <th
                                                key={
                                                    item.quarter
                                                }
                                            >
                                                {item.quarter}
                                            </th>

                                        )
                                    )}

                                </tr>

                            </thead>


                            <tbody>


                                {/* ACTUAL */}

                                <tr>

                                    <td className="mp-results-row-label">
                                        Actual
                                    </td>


                                    {resultQuarters.map(
                                        (item) => (

                                            <td
                                                key={
                                                    `${item.quarter}-actual`
                                                }
                                            >

                                                {item.actual ? (

                                                    <div
                                                        className={
                                                            `mp-result-status ${
                                                                item.actual ===
                                                                "Positive"
                                                                    ? "positive"
                                                                    : item.actual ===
                                                                      "Negative"
                                                                    ? "negative"
                                                                    : "neutral"
                                                            }`
                                                        }
                                                    >

                                                        <strong>
                                                            {item.actual}
                                                        </strong>

                                                        {item.actualDate && (

                                                            <small>
                                                                {formatDate(
                                                                    item.actualDate
                                                                )}
                                                            </small>

                                                        )}

                                                    </div>

                                                ) : (

                                                    <div className="mp-result-status unavailable">

                                                        <strong>
                                                            —
                                                        </strong>

                                                        <small>
                                                            No data
                                                        </small>

                                                    </div>

                                                )}

                                            </td>

                                        )
                                    )}

                                </tr>


                                {/* CURRENT EXPECTATION */}

                                <tr>

                                    <td className="mp-results-row-label">
                                        Current Expectation
                                    </td>


                                    {resultQuarters.map(
                                        (item) => (

                                            <td
                                                key={
                                                    `${item.quarter}-expected`
                                                }
                                            >

                                                {item.expected ? (

                                                    <div
                                                        className={
                                                            `mp-result-status ${
                                                                item.expected ===
                                                                "Positive"
                                                                    ? "positive"
                                                                    : item.expected ===
                                                                      "Negative"
                                                                    ? "negative"
                                                                    : "neutral"
                                                            }`
                                                        }
                                                    >

                                                        <strong>
                                                            {item.expected}
                                                        </strong>

                                                        {item.expectedDate && (

                                                            <small>
                                                                {formatDate(
                                                                    item.expectedDate
                                                                )}
                                                            </small>

                                                        )}

                                                    </div>

                                                ) : (

                                                    <div className="mp-result-status unavailable">

                                                        <strong>
                                                            —
                                                        </strong>

                                                        <small>
                                                            Not available
                                                        </small>

                                                    </div>

                                                )}

                                            </td>

                                        )
                                    )}

                                </tr>

                            </tbody>

                        </table>

                    </div>


                    <div className="mp-results-note">

                        <span>
                            ℹ
                        </span>

                        Reliable quarterly result and analyst
                        consensus data will be connected here.

                    </div>

                </section>

            )}


            {/* ==================================================
                EXISTING NEWS / FEEDS
            ================================================== */}

            <section className="mp-news-feed-section">

                <div className="mp-section-heading">

                    <div>

                        <div className="mp-eyebrow">
                            MARKET INTELLIGENCE
                        </div>

                        <h2>
                            Latest News &amp; Feeds
                        </h2>

                    </div>

                </div>


                <div className="mp-news-feed-grid">


                    {/* LATEST NEWS */}

                    <div className="mp-news-column">

                        <h3>
                            Latest News
                        </h3>

                        <div className="mp-news-placeholder">
                            Your existing news feed stays here.
                        </div>

                    </div>


                    {/* ANALYST */}

                    <div className="mp-news-column">

                        <h3>
                            Analyst Ratings &amp; Predictions
                        </h3>

                        <div className="mp-news-placeholder">
                            Analyst data will be connected here.
                        </div>

                    </div>


                    {/* GLOBAL DOMAIN */}

                    <div className="mp-news-column">

                        <h3>
                            Global Domain Information
                        </h3>

                        <div className="mp-news-placeholder">
                            Global domain information and news
                            will be connected here.
                        </div>

                    </div>

                </div>

            </section>

        </div>

    );
}

export default StockSearch;