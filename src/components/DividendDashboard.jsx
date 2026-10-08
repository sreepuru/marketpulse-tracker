import { useEffect, useMemo, useState } from "react";
import "../DividendDashboard.css";
import { API_BASE_URL } from "../config";


const ROWS_PER_PAGE = 12;


// ==========================================================
// Helpers
// ==========================================================

function number(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return null;
    }

    const parsed = Number(value);

    return Number.isFinite(parsed)
        ? parsed
        : null;
}


function formatMoney(value) {
    const n = number(value);

    if (n === null) {
        return "—";
    }

    return `₹${n.toLocaleString("en-IN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    })}`;
}


function formatPercent(value) {
    const n = number(value);

    if (n === null) {
        return "—";
    }

    return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}


function formatDate(value) {
    if (!value) {
        return "—";
    }

    const parts = String(value).split("-");

    if (parts.length !== 3) {
        return String(value);
    }

    const year = parts[0];
    const month = Number(parts[1]);
    const day = Number(parts[2]);

    const monthName = new Date(
        year,
        month - 1,
        1
    ).toLocaleString("en-US", {
        month: "short"
    });

    return `${day} ${monthName} ${year}`;
}


function formatDateTime(value) {
    if (!value) {
        return "—";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return String(value);
    }

    return date.toLocaleString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit"
    });
}


// ==========================================================
// Sorting
// ==========================================================

const SORT_FIELDS = {

    symbol: {
        type: "string"
    },

    dividend: {
        type: "number"
    },

    ex_date: {
        type: "date"
    },

    record_date: {
        type: "date"
    },

    record_received_date: {
        type: "date"
    },

    dividend_yield_percent: {
        type: "number"
    },

    price_change_since_announcement: {
        type: "number"
    },

    current_price: {
    type: "number"
    }

};


function getSortValue(row, key) {

    const field = SORT_FIELDS[key];

    if (!field) {
        return null;
    }

    const value = row[key];

    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return null;
    }


    if (field.type === "number") {

        const parsed = Number(value);

        return Number.isFinite(parsed)
            ? parsed
            : null;

    }


    if (field.type === "date") {

        const timestamp =
            new Date(value).getTime();

        return Number.isNaN(timestamp)
            ? null
            : timestamp;

    }


    return String(value)
        .trim()
        .toUpperCase();
}


function compareValues(a, b, direction) {

    // Empty values always stay at bottom.
    if (a === null && b === null) {
        return 0;
    }

    if (a === null) {
        return 1;
    }

    if (b === null) {
        return -1;
    }


    let result;


    if (
        typeof a === "number" &&
        typeof b === "number"
    ) {

        result = a - b;

    } else {

        result = String(a).localeCompare(
            String(b),
            undefined,
            {
                numeric: true,
                sensitivity: "base"
            }
        );

    }


    return direction === "asc"
        ? result
        : -result;
}


// ==========================================================
// Sort Header
// ==========================================================

function SortHeader({
    label,
    sortKey,
    sortConfig,
    onSort
}) {

    const active =
        sortConfig.key === sortKey;

    const direction =
        active
            ? sortConfig.direction
            : null;


    return (
        <th>

            <button
                type="button"
                className={
                    active
                        ? "mp-dividend-sort active"
                        : "mp-dividend-sort"
                }
                onClick={() => onSort(sortKey)}
                aria-label={`Sort by ${label}`}
            >

                <span>
                    {label}
                </span>

                <span
                    className="mp-dividend-sort-indicator"
                    aria-hidden="true"
                >
                    {active
                        ? direction === "asc"
                            ? "↑"
                            : "↓"
                        : "↕"}
                </span>

            </button>

        </th>
    );
}


// ==========================================================
// Component
// ==========================================================

function DividendDashboard({
    marketDate
}) {

    const [
        dividends,
        setDividends
    ] = useState([]);


    const [
        loading,
        setLoading
    ] = useState(true);


    const [
        error,
        setError
    ] = useState(null);


    const [
        segment,
        setSegment
    ] = useState("EQ");


    const [
        currentPage,
        setCurrentPage
    ] = useState(1);


    const [
        lastUpdated,
        setLastUpdated
    ] = useState(null);


    const [
        sortConfig,
        setSortConfig
    ] = useState({
        key: "ex_date",
        direction: "desc"
    });

    const [
    showMethodology,
    setShowMethodology
    ] = useState(false);

    const [
    stockSearch,
    setStockSearch
    ] = useState("");


    // ======================================================
    // Load Dividend Data
    // ======================================================

    useEffect(() => {

        let cancelled = false;


        async function loadDividends() {

            try {

                setLoading(true);

                setError(null);


                const response =
                    await fetch(
                        `${API_BASE_URL}/api/dividends/dashboard`
                    );


                if (!response.ok) {

                    throw new Error(
                        `Dividend API failed: ${response.status}`
                    );

                }


                const result =
                    await response.json();


                if (cancelled) {
                    return;
                }


                const rows =
                    Array.isArray(result.data)
                        ? result.data
                        : [];


                setDividends(rows);


                setLastUpdated(
                    result.last_updated ||
                    result.updated_at ||
                    rows[0]?.updated_at ||
                    rows[0]?.created_at ||
                    null
                );


            } catch (err) {

                if (cancelled) {
                    return;
                }


                console.error(
                    "Dividend dashboard error:",
                    err
                );


                setError(
                    err.message ||
                    "Unable to load dividend data."
                );


            } finally {

                if (!cancelled) {
                    setLoading(false);
                }

            }

        }


        loadDividends();


        return () => {
            cancelled = true;
        };

    }, []);


    // ======================================================
    // Equity / SME Filter
    // ======================================================

    const filteredDividends = useMemo(() => {

    const search =
        stockSearch
            .trim()
            .toUpperCase();

        return dividends.filter((stock) => {

            const series =
                String(stock.series || "")
                    .toUpperCase()
                    .trim();


            // Equity / SME
            const segmentMatch =
                segment === "SM"
                    ? series === "SM"
                    : (
                        series === "EQ" ||
                        series === "BE" ||
                        series === "BZ"
                    );


            if (!segmentMatch) {
                return false;
            }


            // Stock search
            if (!search) {
                return true;
            }


            const symbol =
                String(
                    stock.symbol || ""
                ).toUpperCase();


            const companyName =
                String(
                    stock.company_name ||
                    stock.company ||
                    ""
                ).toUpperCase();


            return (
                symbol.includes(search) ||
                companyName.includes(search)
            );

        });

    }, [
        dividends,
        segment,
        stockSearch
    ]);


    // ======================================================
    // Sorting
    // ======================================================

    const sortedDividends =
        useMemo(() => {

            const rows =
                [...filteredDividends];


            rows.sort((a, b) => {

                const aValue =
                    getSortValue(
                        a,
                        sortConfig.key
                    );


                const bValue =
                    getSortValue(
                        b,
                        sortConfig.key
                    );


                return compareValues(
                    aValue,
                    bValue,
                    sortConfig.direction
                );

            });


            return rows;

        }, [
            filteredDividends,
            sortConfig
        ]);


    // ======================================================
    // Pagination
    // ======================================================

    const totalPages =
        Math.max(
            1,
            Math.ceil(
                sortedDividends.length /
                ROWS_PER_PAGE
            )
        );


    useEffect(() => {

        if (currentPage > totalPages) {

            setCurrentPage(
                totalPages
            );

        }

    }, [
        currentPage,
        totalPages
    ]);


    const visibleRows =
        useMemo(() => {

            const start =
                (currentPage - 1) *
                ROWS_PER_PAGE;


            return sortedDividends.slice(
                start,
                start + ROWS_PER_PAGE
            );

        }, [
            sortedDividends,
            currentPage
        ]);


    // ======================================================
    // Upcoming Ex-Dates
    // ======================================================

    const upcomingCount =
        filteredDividends.filter(
            (item) => {

                if (
                    !item.ex_date ||
                    !marketDate
                ) {
                    return false;
                }


                return (
                    item.ex_date >=
                    marketDate
                );

            }
        ).length;


    // ======================================================
    // Sort Handler
    // ======================================================

    const handleSort = (key) => {

        setCurrentPage(1);


        setSortConfig(
            (current) => {

                if (current.key === key) {

                    return {
                        key,
                        direction:
                            current.direction === "asc"
                                ? "desc"
                                : "asc"
                    };

                }


                return {
                    key,
                    direction: "asc"
                };

            }
        );

    };


    // ======================================================
    // Segment Handler
    // ======================================================

    const changeSegment = (value) => {

        setSegment(value);

        setCurrentPage(1);

    };


    // ======================================================
    // Page Handler
    // ======================================================

    const changePage = (page) => {

        setCurrentPage(
            Math.max(
                1,
                Math.min(
                    page,
                    totalPages
                )
            )
        );

    };


    // ======================================================
    // Loading
    // ======================================================

    if (loading) {

        return (

            <section className="mp-dividend-page">

                <div className="mp-dividend-loading">

                    <div className="mp-dividend-loading-mark">
                        ₹
                    </div>

                    <h2>
                        Loading dividends
                    </h2>

                    <p>
                        Fetching the latest dividend data...
                    </p>

                </div>

            </section>

        );

    }


    // ======================================================
    // Error
    // ======================================================

    if (error) {

        return (

            <section className="mp-dividend-page">

                <div className="mp-dividend-error">

                    <div className="mp-dividend-error-mark">
                        !
                    </div>

                    <h2>
                        Unable to load dividends
                    </h2>

                    <p>
                        {error}
                    </p>

                </div>

            </section>

        );

    }


    // ======================================================
    // Pagination Range
    // ======================================================

    const pageNumbers =
        Array.from(
            {
                length: totalPages
            },
            (_, index) => index + 1
        );


    // ======================================================
    // Render
    // ======================================================

    return (

        <section className="mp-dividend-page">

            {/* ==================================================
                PAGE HEADER
            ================================================== */}

            <header className="mp-dividend-header">

                <div>

                    <span className="mp-dividend-kicker">
                        INCOME INTELLIGENCE
                    </span>

                    <h1 className="mp-dividend-title">
                        Dividend Stocks
                    </h1>

                    <p className="mp-dividend-description">
                        Dividend announcements, key dates and
                        price movement.
                    </p>

                </div>


                <div className="mp-dividend-summary">

                    <div className="mp-dividend-summary-card">

                        <span>
                            Dividend Stocks
                        </span>

                        <strong>
                            {filteredDividends.length}
                        </strong>

                    </div>


                    <div className="mp-dividend-summary-card">

                        <span>
                            Upcoming Ex-Dates
                        </span>

                        <strong>
                            {upcomingCount}
                        </strong>

                    </div>

                </div>

            </header>


            {/* ==================================================
                SEGMENT TABS
            ================================================== */}

            <div className="mp-dividend-toolbar">

                <div className="mp-dividend-tabs">
                    ...
                </div>


                <div className="mp-dividend-search">

                    <span className="mp-dividend-search-icon">
                        ⌕
                    </span>

                    <input
                        type="search"
                        value={stockSearch}
                        onChange={(event) => {

                            setStockSearch(
                                event.target.value
                            );

                            setCurrentPage(1);

                        }}
                        placeholder="Search stock..."
                        aria-label="Search dividend stock"
                    />

                    {stockSearch && (

                        <button
                            type="button"
                            className="mp-dividend-search-clear"
                            onClick={() => {

                                setStockSearch("");

                                setCurrentPage(1);

                            }}
                            aria-label="Clear stock search"
                        >
                            ×
                        </button>

                    )}

                </div>


                <div className="mp-dividend-updated">
                    ...
                </div>

            </div>


            {/* ==================================================
                TABLE
            ================================================== */}

            <div className="mp-dividend-table-card">

                <div className="mp-dividend-table-wrap">

                    <table className="mp-dividend-table">

                        <thead>

                            <tr>

                                <SortHeader
                                    label="Symbol"
                                    sortKey="symbol"
                                    sortConfig={sortConfig}
                                    onSort={handleSort}
                                />


                                <SortHeader
                                    label="Dividend"
                                    sortKey="dividend"
                                    sortConfig={sortConfig}
                                    onSort={handleSort}
                                />


                                <SortHeader
                                    label="Ex-Date"
                                    sortKey="ex_date"
                                    sortConfig={sortConfig}
                                    onSort={handleSort}
                                />


                                <SortHeader
                                    label="Record Date"
                                    sortKey="record_date"
                                    sortConfig={sortConfig}
                                    onSort={handleSort}
                                />


                                <SortHeader
                                    label="Received"
                                    sortKey="record_received_date"
                                    sortConfig={sortConfig}
                                    onSort={handleSort}
                                />


                                <SortHeader
                                    label="Dividend Yield"
                                    sortKey="dividend_yield_percent"
                                    sortConfig={sortConfig}
                                    onSort={handleSort}
                                />

                                <SortHeader
                                    label="Current Price"
                                    sortKey="current_price"
                                    sortConfig={sortConfig}
                                    onSort={handleSort}
                                />

                                <SortHeader
                                    label="Price Change"
                                    sortKey="price_change_since_announcement"
                                    sortConfig={sortConfig}
                                    onSort={handleSort}
                                />

                            </tr>

                        </thead>


                        <tbody>

                            {visibleRows.length === 0 ? (

                                <tr>

                                    <td
                                        colSpan="7"
                                        className="mp-dividend-empty-row"
                                    >
                                        No dividend records available
                                        for this segment.
                                    </td>

                                </tr>

                            ) : (

                                visibleRows.map(
                                    (stock) => {

                                        const dividend =
                                            number(
                                                stock.dividend
                                            );


                                        const dividendYield =
                                            number(
                                                stock.dividend_yield_percent
                                            );


                                        const priceChange =
                                            number(
                                                stock.price_change_since_announcement
                                            );


                                        const priceChangePercent =
                                            number(
                                                stock.price_change_since_announcement_percent
                                            );


                                        const priceChangeClass =
                                            priceChange === null
                                                ? "mp-dividend-empty"
                                                : priceChange >= 0
                                                    ? "mp-dividend-positive"
                                                    : "mp-dividend-negative";


                                        return (

                                            <tr
                                                key={
                                                    stock.corporate_action_id ??
                                                    `${stock.symbol}-${stock.ex_date}-${stock.record_received_date}`
                                                }
                                            >

                                                {/* Symbol */}

                                                <td>

                                                    <span className="mp-dividend-symbol">
                                                        {stock.symbol || "—"}
                                                    </span>

                                                    {stock.series && (

                                                        <small className="mp-dividend-series">
                                                            {stock.series}
                                                        </small>

                                                    )}

                                                </td>


                                                {/* Dividend */}

                                                <td>

                                                    <span className="mp-dividend-money">
                                                        {formatMoney(dividend)}
                                                    </span>

                                                </td>


                                                {/* Ex Date */}

                                                <td>

                                                    <span className="mp-dividend-date">
                                                        {formatDate(
                                                            stock.ex_date
                                                        )}
                                                    </span>

                                                </td>


                                                {/* Record Date */}

                                                <td>

                                                    <span className="mp-dividend-date">
                                                        {formatDate(
                                                            stock.record_date
                                                        )}
                                                    </span>

                                                </td>


                                                {/* Received */}

                                                <td>

                                                    <span className="mp-dividend-date">
                                                        {formatDate(
                                                            stock.record_received_date
                                                        )}
                                                    </span>

                                                </td>


                                                {/* Yield */}

                                                <td>

                                                    <span className="mp-dividend-yield">

                                                        {dividendYield !== null
                                                            ? `${dividendYield.toFixed(2)}%`
                                                            : "—"}

                                                    </span>

                                                </td>

                                                {/* Current Price */}

                                                <td>

                                                    {number(stock.current_price) !== null ? (

                                                        <span className="mp-dividend-current-price">
                                                            {formatMoney(
                                                                stock.current_price
                                                            )}
                                                        </span>

                                                    ) : (

                                                        <span className="mp-dividend-empty">
                                                            —
                                                        </span>

                                                    )}

                                                </td>


                                                {/* Price Change */}

                                                <td>

                                                    {priceChange !== null ? (

                                                        <div
                                                            className={
                                                                `mp-dividend-change ${priceChangeClass}`
                                                            }
                                                        >

                                                            <strong>
                                                                {priceChange >= 0
                                                                    ? "+"
                                                                    : ""}

                                                                {formatMoney(
                                                                    priceChange
                                                                )}
                                                            </strong>


                                                            {priceChangePercent !== null && (

                                                                <small>
                                                                    {formatPercent(
                                                                        priceChangePercent
                                                                    )}
                                                                </small>

                                                            )}

                                                        </div>

                                                    ) : (

                                                        <span className="mp-dividend-empty">
                                                            —
                                                        </span>

                                                    )}

                                                </td>

                                            </tr>

                                        );

                                    }
                                )

                            )}

                        </tbody>

                    </table>

                </div>

                {/* ==================================================
    CALCULATION METHODOLOGY
================================================== */}

<div className="mp-methodology">

    <button
        type="button"
        className="mp-methodology-toggle"
        onClick={() =>
            setShowMethodology(
                (value) => !value
            )
        }
        aria-expanded={showMethodology}
    >

        <span className="mp-methodology-left">

            <span className="mp-methodology-icon">
                ⓘ
            </span>

            <span className="mp-methodology-text">

                <strong>
                    Calculation Methodology
                </strong>

                <small>
                    How Dividend Yield and Price Change
                    are calculated
                </small>

            </span>

        </span>


        <span className="mp-methodology-chevron">
            {showMethodology ? "⌃" : "⌄"}
        </span>

    </button>


    {showMethodology && (

        <div className="mp-methodology-content">

            <div className="mp-formula-card">

                <span className="mp-formula-title">
                    Dividend Yield
                </span>

                <div className="mp-formula">

                    <span>
                        Dividend
                    </span>

                    <span className="mp-formula-operator">
                        ÷
                    </span>

                    <span>
                        Yesterday Close Price
                    </span>

                    <span className="mp-formula-operator">
                        ×
                    </span>

                    <span>
                        100
                    </span>

                </div>

            </div>


            <div className="mp-formula-card">

                <span className="mp-formula-title">
                    Price Change Since Announcement
                </span>

                <div className="mp-formula">

                    <span>
                        Current Price
                    </span>

                    <span className="mp-formula-operator">
                        −
                    </span>

                    <span>
                        Price on Record Received Date
                    </span>

                </div>

            </div>


            <div className="mp-formula-note">

                <span>—</span>

                means the required price data
                is unavailable.

            </div>

        </div>

    )}

</div>

                {/* ==================================================
                    TABLE FOOTER
                ================================================== */}

                <footer className="mp-dividend-footer">

                    <span className="mp-dividend-count">

                        Showing{" "}

                        {filteredDividends.length === 0
                            ? 0
                            : (
                                (currentPage - 1) *
                                ROWS_PER_PAGE
                            ) + 1}

                        {" "}–{" "}

                        {Math.min(
                            currentPage *
                            ROWS_PER_PAGE,
                            filteredDividends.length
                        )}

                        {" "}of{" "}

                        {filteredDividends.length}

                        {" "}stocks

                    </span>


                    <div
                        className="mp-dividend-pagination"
                        aria-label="Dividend pagination"
                    >

                        <button
                            type="button"
                            disabled={
                                currentPage === 1
                            }
                            onClick={() =>
                                changePage(
                                    currentPage - 1
                                )
                            }
                            aria-label="Previous page"
                        >
                            ‹
                        </button>


                        {pageNumbers.map(
                            (page) => (

                                <button
                                    type="button"
                                    key={page}
                                    className={
                                        page === currentPage
                                            ? "active"
                                            : ""
                                    }
                                    onClick={() =>
                                        changePage(page)
                                    }
                                    aria-current={
                                        page === currentPage
                                            ? "page"
                                            : undefined
                                    }
                                >
                                    {page}
                                </button>

                            )
                        )}


                        <button
                            type="button"
                            disabled={
                                currentPage === totalPages
                            }
                            onClick={() =>
                                changePage(
                                    currentPage + 1
                                )
                            }
                            aria-label="Next page"
                        >
                            ›
                        </button>

                    </div>

                </footer>

            </div>


            <div className="mp-dividend-updated-bottom">

                Dividend data last updated:

                <strong>
                    {formatDateTime(lastUpdated)}
                </strong>

            </div>

        </section>

    );

}


export default DividendDashboard;