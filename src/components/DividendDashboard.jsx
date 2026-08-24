import { useEffect, useMemo, useState } from "react";

const DIVIDEND_TABLE_CONFIG = {
    visibleHeight: 420,
    rowsPerPage: 12
};

import { API_BASE_URL } from "../config";

function number(value) {
    if (value === null || value === undefined || value === "") {
        return null;
    }

    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
}

function formatMoney(value) {
    const n = number(value);

    if (n === null) return "-";

    return `₹${n.toLocaleString("en-IN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    })}`;
}

function formatPercent(value) {
    const n = number(value);

    if (n === null) return "-";

    return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function formatDate(date) {
    if (!date) return "-";

    const parts = String(date).split("-");

    if (parts.length !== 3) return String(date);

    const year = parts[0];
    const month = Number(parts[1]);
    const day = Number(parts[2]);

    const monthName = new Date(year, month - 1, 1).toLocaleString("en-US", {
        month: "short"
    });

    return `${day} ${monthName} ${year}`;
}

function formatDateTime(value) {
    if (!value) return "-";

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

function DividendDashboard({ marketDate }) {
    const [dividends, setDividends] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [currentPage, setCurrentPage] = useState(1);
    const [lastUpdated, setLastUpdated] = useState(null);
    const [segment, setSegment] = useState("EQ");
    const [showMethodology, setShowMethodology] = useState(false);

    useEffect(() => {
        async function loadDividends() {
            try {
                setLoading(true);
                setError(null);

                const response = await fetch(
                    `${API_BASE_URL}/api/dividends/dashboard`
                );

                if (!response.ok) {
                    throw new Error(
                        `Dividend API failed: ${response.status}`
                    );
                }

                const result = await response.json();
                const rows = result.data || [];

                setDividends(rows);

                setLastUpdated(
                    result.last_updated ||
                    result.updated_at ||
                    rows[0]?.updated_at ||
                    rows[0]?.created_at ||
                    null
                );
            } catch (err) {
                console.error("Dividend dashboard error:", err);
                setError(err.message);
            } finally {
                setLoading(false);
            }
        }

        loadDividends();
    }, []);

    const filteredDividends = useMemo(() => {
        return dividends.filter((stock) => {
            const series = String(stock.series || "")
                .toUpperCase()
                .trim();

            if (segment === "SM") {
                return series === "SM";
            }

            return series === "EQ" || series === "BE" || series === "BZ";
        });
    }, [dividends, segment]);

    const totalPages = Math.max(
        1,
        Math.ceil(
            filteredDividends.length /
            DIVIDEND_TABLE_CONFIG.rowsPerPage
        )
    );

    useEffect(() => {
        if (currentPage > totalPages) {
            setCurrentPage(totalPages);
        }
    }, [currentPage, totalPages]);

    const visibleRows = useMemo(() => {
        const start =
            (currentPage - 1) *
            DIVIDEND_TABLE_CONFIG.rowsPerPage;

        return filteredDividends.slice(
            start,
            start + DIVIDEND_TABLE_CONFIG.rowsPerPage
        );
    }, [filteredDividends, currentPage]);

    const upcomingCount = filteredDividends.filter((item) => {
        if (!item.ex_date || !marketDate) return false;
        return item.ex_date >= marketDate;
    }).length;

    const changePage = (page) => {
        setCurrentPage(Math.max(1, Math.min(page, totalPages)));
    };

    if (loading) {
        return (
            <section className="dashboard-section dividend-dashboard">
                <div className="dividend-loading">
                    <span className="loading-dot" />
                    Loading dividend data...
                </div>
            </section>
        );
    }

    if (error) {
        return (
            <section className="dashboard-section dividend-dashboard">
                <div className="dividend-error">
                    <strong>Dividend data error</strong>
                    <span>{error}</span>
                </div>
            </section>
        );
    }

    return (
        <section className="dashboard-section dividend-dashboard">
            <div className="dividend-header">
                <div className="dividend-heading">
                    <div className="dividend-title-area">
                        <span className="dividend-title-icon">₹</span>
                        <div>
                            <span className="section-eyebrow">INCOME INTELLIGENCE</span>
                            <h2>Dividend Stocks</h2>
                        </div>
                    </div>

                    <p>
                        Dividend announcements, key dates and price movement
                    </p>
                </div>

                <div className="dividend-summary">
                    <div className="dividend-stat">
                        <span>Dividend Stocks</span>
                        <strong>{filteredDividends.length}</strong>
                    </div>

                    <div className="dividend-stat upcoming-stat">
                        <span>Upcoming Ex-Dates</span>
                        <strong>{upcomingCount}</strong>
                    </div>
                </div>
            </div>

            <div className="dividend-controls">
                <div className="segment-tabs" role="tablist">
                    <button
                        className={
                            segment === "EQ"
                                ? "segment-tab active"
                                : "segment-tab"
                        }
                        onClick={() => {
                            setSegment("EQ");
                            setCurrentPage(1);
                        }}
                    >
                        <span>📊</span>
                        Equity
                    </button>

                    <button
                        className={
                            segment === "SM"
                                ? "segment-tab active"
                                : "segment-tab"
                        }
                        onClick={() => {
                            setSegment("SM");
                            setCurrentPage(1);
                        }}
                    >
                        <span>🏭</span>
                        SME
                    </button>
                </div>

                <div className="dividend-update-note">
                    <span className="status-dot" />
                    Last updated:
                    <strong>{formatDateTime(lastUpdated)}</strong>
                </div>
            </div>

            <div className="methodology-bar">
                <button
                    className="methodology-toggle"
                    onClick={() => setShowMethodology((value) => !value)}
                    aria-expanded={showMethodology}
                >
                    <span className="methodology-icon">ⓘ</span>
                    <span>
                        <strong>Calculation Methodology</strong>
                        <small>
                            How Dividend Yield and Price Change are calculated
                        </small>
                    </span>
                    <span className="methodology-chevron">
                        {showMethodology ? "⌃" : "⌄"}
                    </span>
                </button>

                {showMethodology && (
                    <div className="methodology-panel">
                        <div className="formula-card">
                            <span className="formula-title">Dividend Yield</span>
                            <div className="formula-expression">
                                <span>Dividend</span>
                                <span className="formula-operator">÷</span>
                                <span>Yesterday Close Price</span>
                                <span className="formula-operator">×</span>
                                <span>100</span>
                            </div>
                        </div>

                        <div className="formula-card">
                            <span className="formula-title">
                                Price Change Since Announcement
                            </span>
                            <div className="formula-expression">
                                <span>Current Price</span>
                                <span className="formula-operator">−</span>
                                <span>Price on Record Received Date</span>
                            </div>
                        </div>

                        <div className="formula-note">
                            <span>—</span>
                            means the required price data is unavailable.
                        </div>
                    </div>
                )}
            </div>

            <div
                className="dividend-table-wrapper"
                style={{
                    "--dividend-table-height":
                        `${DIVIDEND_TABLE_CONFIG.visibleHeight}px`
                }}
            >
                <table className="dividend-table">
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th>Dividend</th>
                            <th>Ex-Date</th>
                            <th>Record Date</th>
                            <th>Received</th>
                            <th>
                                Dividend Yield
                                <small>Dividend / Yesterday Close</small>
                            </th>
                            <th>
                                Price Change
                                <small>Current Price − Price on Received Date</small>
                            </th>
                        </tr>
                    </thead>

                    <tbody>
                        {visibleRows.length === 0 ? (
                            <tr>
                                <td colSpan="7" className="not-available empty-row">
                                    No dividend records available for this segment.
                                </td>
                            </tr>
                        ) : (
                            visibleRows.map((stock) => {
                                const dividend = number(stock.dividend);
                                const dividendYield = number(
                                    stock.dividend_yield_percent
                                );
                                const priceChange = number(
                                    stock.price_change_since_announcement
                                );
                                const priceChangePercent = number(
                                    stock.price_change_since_announcement_percent
                                );

                                return (
                                    <tr
                                        key={
                                            stock.corporate_action_id ??
                                            `${stock.symbol}-${stock.ex_date}-${stock.record_received_date}`
                                        }
                                    >
                                        <td className="symbol-cell">
                                            {stock.symbol || "-"}
                                        </td>

                                        <td className="dividend-amount">
                                            {formatMoney(dividend)}
                                        </td>

                                        <td>
                                            <span className="date-value">
                                                {formatDate(stock.ex_date)}
                                            </span>
                                        </td>

                                        <td>
                                            <span className="date-value">
                                                {formatDate(stock.record_date)}
                                            </span>
                                        </td>

                                        <td>
                                            <span className="received-value">
                                                {formatDate(stock.record_received_date)}
                                            </span>
                                        </td>

                                        <td>
                                            <span className="yield-value">
                                                {dividendYield !== null
                                                    ? `${dividendYield.toFixed(2)}%`
                                                    : "—"}
                                            </span>
                                        </td>

                                        <td className="price-change-cell">
                                            {priceChange !== null ? (
                                                <div
                                                    className={
                                                        priceChange >= 0
                                                            ? "since-positive"
                                                            : "since-negative"
                                                    }
                                                >
                                                    <strong>
                                                        {priceChange >= 0 ? "+" : ""}
                                                        {formatMoney(priceChange)}
                                                    </strong>

                                                    {priceChangePercent !== null && (
                                                        <small>
                                                            {formatPercent(priceChangePercent)}
                                                        </small>
                                                    )}
                                                </div>
                                            ) : (
                                                <span
                                                    className="not-available"
                                                    title="Required price data is unavailable"
                                                >
                                                    —
                                                </span>
                                            )}
                                        </td>
                                    </tr>
                                );
                            })
                        )}
                    </tbody>
                </table>
            </div>

            <div className="table-footer">
                <span>
                    Showing{" "}
                    {filteredDividends.length === 0
                        ? 0
                        : (currentPage - 1) *
                            DIVIDEND_TABLE_CONFIG.rowsPerPage +
                          1}
                    {" "}to{" "}
                    {Math.min(
                        currentPage * DIVIDEND_TABLE_CONFIG.rowsPerPage,
                        filteredDividends.length
                    )}
                    {" "}of {filteredDividends.length} dividend stocks
                </span>

                <div className="pagination">
                    <button
                        disabled={currentPage === 1}
                        onClick={() => changePage(currentPage - 1)}
                        aria-label="Previous page"
                    >
                        ‹
                    </button>

                    {Array.from(
                        { length: totalPages },
                        (_, index) => index + 1
                    ).map((page) => (
                        <button
                            key={page}
                            className={page === currentPage ? "active" : ""}
                            onClick={() => changePage(page)}
                        >
                            {page}
                        </button>
                    ))}

                    <button
                        disabled={currentPage === totalPages}
                        onClick={() => changePage(currentPage + 1)}
                        aria-label="Next page"
                    >
                        ›
                    </button>
                </div>
            </div>
        </section>
    );
}

export default DividendDashboard;