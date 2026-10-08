import { useEffect, useMemo, useState } from "react";
import "../HomeDashboard.css";
import { API_BASE_URL } from "../config";


function formatNumber(value, decimals = 2) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "-";
    }

    const number = Number(value);

    if (Number.isNaN(number)) {
        return String(value);
    }

    return number.toLocaleString("en-IN", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}


function formatPercent(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "-";
    }

    const number = Number(value);

    if (Number.isNaN(number)) {
        return String(value);
    }

    return `${number >= 0 ? "+" : ""}${number.toFixed(2)}%`;
}


function getChangeClass(value) {
    const number = Number(value);

    if (
        Number.isNaN(number) ||
        number === 0
    ) {
        return "neutral";
    }

    return number > 0
        ? "positive"
        : "negative";
}


function getInitials(symbol) {
    if (!symbol) {
        return "MP";
    }

    return String(symbol)
        .replace(/[^A-Za-z]/g, "")
        .slice(0, 2)
        .toUpperCase();
}


/* ==========================================================
   MARKET BREADTH
   ========================================================== */

function MarketBreadth({ summary }) {

    const advances =
        Number(summary?.advances || 0);

    const declines =
        Number(summary?.declines || 0);

    const unchanged =
        Number(summary?.unchanged || 0);

    const total =
        advances +
        declines +
        unchanged;

    const advancePercent =
        total
            ? (advances / total) * 100
            : 0;

    const declinePercent =
        total
            ? (declines / total) * 100
            : 0;

    const unchangedPercent =
        total
            ? (unchanged / total) * 100
            : 0;

    const ratio =
        declines > 0
            ? (advances / declines).toFixed(2)
            : advances > 0
                ? "∞"
                : "-";


    return (
        <section className="market-card breadth-card">

            <div className="section-heading">

                <div>
                    <h2>Market Breadth</h2>

                    <p>
                        Overall participation across NSE securities
                    </p>
                </div>

                <span className="info-badge">
                    i
                </span>

            </div>


            <div className="breadth-metrics">

                <div className="breadth-metric">

                    <span className="metric-label positive-text">
                        Advances
                    </span>

                    <strong>
                        {formatNumber(
                            advances,
                            0
                        )}
                    </strong>

                    <span>
                        {advancePercent.toFixed(1)}%
                    </span>

                </div>


                <div className="breadth-divider" />


                <div className="breadth-metric">

                    <span className="metric-label negative-text">
                        Declines
                    </span>

                    <strong>
                        {formatNumber(
                            declines,
                            0
                        )}
                    </strong>

                    <span>
                        {declinePercent.toFixed(1)}%
                    </span>

                </div>


                <div className="breadth-divider" />


                <div className="breadth-metric">

                    <span className="metric-label neutral-text">
                        Unchanged
                    </span>

                    <strong>
                        {formatNumber(
                            unchanged,
                            0
                        )}
                    </strong>

                    <span>
                        {unchangedPercent.toFixed(1)}%
                    </span>

                </div>


                <div className="breadth-divider" />


                <div className="breadth-metric">

                    <span className="metric-label">
                        Total Stocks
                    </span>

                    <strong>
                        {formatNumber(
                            total,
                            0
                        )}
                    </strong>

                    <span>
                        NSE
                    </span>

                </div>

            </div>


            <div className="breadth-bar">

                <span
                    className="breadth-advance"
                    style={{
                        width:
                            `${advancePercent}%`
                    }}
                />

                <span
                    className="breadth-decline"
                    style={{
                        width:
                            `${declinePercent}%`
                    }}
                />

                <span
                    className="breadth-unchanged"
                    style={{
                        width:
                            `${unchangedPercent}%`
                    }}
                />

            </div>


            <div className="breadth-ratio">

                Advance / Decline Ratio

                <strong>
                    {ratio}
                </strong>

            </div>

        </section>
    );
}


/* ==========================================================
   INDEX CARD
   ========================================================== */

function IndexCard({ index }) {

    const changeClass =
        getChangeClass(
            index?.percentChange
        );


    return (
        <div className="index-card">

            <div className="index-card-header">

                <span className="index-name">
                    {index?.name || "-"}
                </span>

                <span
                    className={
                        `index-icon ${changeClass}`
                    }
                >
                    {changeClass === "positive"
                        ? "↗"
                        : changeClass === "negative"
                            ? "↘"
                            : "•"}
                </span>

            </div>


            <strong className="index-value">

                {formatNumber(
                    index?.value
                )}

            </strong>


            <div
                className={
                    `index-change ${changeClass}`
                }
            >

                {index?.change !== null &&
                    index?.change !== undefined
                    ? `${
                        Number(index.change) >= 0
                            ? "+"
                            : ""
                    }${formatNumber(
                        index.change
                    )}`
                    : "-"
                }


                {" "}


                {index?.percentChange !== null &&
                    index?.percentChange !== undefined
                    ? `(${formatPercent(
                        index.percentChange
                    )})`
                    : ""
                }


                {changeClass === "positive"
                    ? " ↑"
                    : changeClass === "negative"
                        ? " ↓"
                        : ""
                }

            </div>


            <div className="mini-chart">

                <span
                    className={
                        `mini-line ${changeClass}`
                    }
                />

            </div>

        </div>
    );
}


/* ==========================================================
   MAJOR INDICES
   ========================================================== */

function MajorIndices({ indices }) {

    const preferredOrder = [

        "SENSEX",

        "BSE-100",

        "SNSX50",

        "SNXT50",

        "BHRT22"

    ];


    const indexMap =
        new Map(
            (
                Array.isArray(indices)
                    ? indices
                    : []
            ).map((item) => [

                String(
                    item.symbol ||
                    item.name ||
                    ""
                ).toUpperCase(),

                item

            ])
        );


    const cards =
        preferredOrder.map(
            (symbol) => {

                const actual =
                    indexMap.get(
                        symbol
                    );


                return {

                    name:
                        actual?.name ||
                        symbol,

                    value:
                        actual?.value ??
                        null,

                    change:
                        actual?.change ??
                        null,

                    percentChange:
                        actual?.change_percent ??
                        actual?.percentChange ??
                        actual?.percent_change ??
                        null

                };

            }
        );


    return (
        <section className="market-section">

            <div className="section-heading">

                <div>

                    <h2>
                        Major Indices
                    </h2>

                    <p>
                        BSE market snapshot
                    </p>

                </div>


                <span className="market-source-badge">
                    BSE
                </span>

            </div>


            <div className="indices-grid">

                {cards.map(
                    (index) => (

                        <IndexCard
                            key={
                                index.name
                            }
                            index={index}
                        />

                    )
                )}

            </div>

        </section>
    );
}


/* ==========================================================
   MOVEMENT TABLE
   ========================================================== */

function MovementTable({
    title,
    rows,
    type
}) {

    return (
        <section className="market-card movement-card">

            <div className="section-heading">

                <div>
                    <h2>{title}</h2>

                    <p>
                        {type === "gainers"
                            ? "Strongest performers today"
                            : "Weakest performers today"}
                    </p>
                </div>

                <button className="view-button">
                    View All
                </button>

            </div>


            <div className="movement-table">

                <div className="movement-header">

                    <span>Stock</span>
                    <span>Price</span>
                    <span>Change</span>
                    <span>% Change</span>

                </div>


                {rows.length === 0 ? (

                    <div className="empty-state">
                        No market data available
                    </div>

                ) : (

                    rows.slice(0, 6).map(
                        (row, index) => {

                            const change =
                                Number(
                                    row.price_change ?? 0
                                );

                            const changePercent =
                                Number(
                                    row.change_percent ?? 0
                                );

                            const price =
                                Number(
                                    row.current_price ?? 0
                                );


                            return (

                                <div
                                    className="movement-row"
                                    key={
                                        row.symbol ||
                                        index
                                    }
                                >

                                    <div className="stock-cell">

                                        <span className="stock-avatar">
                                            {getInitials(
                                                row.symbol
                                            )}
                                        </span>

                                        <div>

                                            <strong>
                                                {row.symbol || "-"}
                                            </strong>

                                            <small>
                                                {row.series || ""}
                                            </small>

                                        </div>

                                    </div>


                                    <span>
                                        ₹{formatNumber(price)}
                                    </span>


                                    <span
                                        className={
                                            change >= 0
                                                ? "positive-text"
                                                : "negative-text"
                                        }
                                    >
                                        {change >= 0
                                            ? "+"
                                            : ""}
                                        {formatNumber(change)}
                                    </span>


                                    <span
                                        className={
                                            changePercent >= 0
                                                ? "positive-text"
                                                : "negative-text"
                                        }
                                    >
                                        {changePercent >= 0
                                            ? "+"
                                            : ""}
                                        {changePercent.toFixed(2)}%
                                    </span>

                                </div>

                            );

                        }
                    )

                )}

            </div>

        </section>
    );
}


/* ==========================================================
   MARKET STATISTICS
   ========================================================== */

function MarketStatistics({
    summary,
    securityCounts
}) {

    const total =
        summary?.total ??
        summary?.totalStocks ??
        securityCounts?.total ??
        0;


    return (

        <section className="market-card statistics-card">

            <div className="section-heading">

                <div>

                    <h2>
                        Market Statistics
                    </h2>

                    <p>
                        Today's market snapshot
                    </p>

                </div>

            </div>


            <div className="statistics-list">

                <div>
                    <span>
                        Stocks Traded
                    </span>

                    <strong>
                        {formatNumber(
                            total,
                            0
                        )}
                    </strong>
                </div>


                <div>

                    <span>
                        Advances
                    </span>

                    <strong className="positive-text">

                        {formatNumber(
                            summary?.advances,
                            0
                        )}

                    </strong>

                </div>


                <div>

                    <span>
                        Declines
                    </span>

                    <strong className="negative-text">

                        {formatNumber(
                            summary?.declines,
                            0
                        )}

                    </strong>

                </div>


                <div>

                    <span>
                        Unchanged
                    </span>

                    <strong>

                        {formatNumber(
                            summary?.unchanged,
                            0
                        )}

                    </strong>

                </div>


                <div>

                    <span>
                        Equity Securities
                    </span>

                    <strong>

                        {formatNumber(
                            securityCounts?.equity,
                            0
                        )}

                    </strong>

                </div>


                <div>

                    <span>
                        SME Securities
                    </span>

                    <strong>

                        {formatNumber(
                            securityCounts?.sme,
                            0
                        )}

                    </strong>

                </div>

            </div>

        </section>
    );
}


/* ==========================================================
   SECTOR PERFORMANCE
   ========================================================== */

function SectorPerformance() {

    const sectors = [

        "NIFTY BANK",
        "NIFTY IT",
        "NIFTY AUTO",
        "NIFTY PHARMA",
        "NIFTY METAL",
        "NIFTY FMCG",
        "NIFTY REALTY",
        "NIFTY ENERGY"

    ];


    return (

        <section className="market-card sector-card">

            <div className="section-heading">

                <div>

                    <h2>
                        Sector Performance
                    </h2>

                    <p>
                        Sector data will be connected next
                    </p>

                </div>


                <button className="view-button">
                    View All Sectors
                </button>

            </div>


            <div className="sector-grid">

                {sectors.map(
                    (sector) => (

                        <div
                            className="sector-item pending"
                            key={sector}
                        >

                            <span className="sector-icon">
                                •
                            </span>


                            <div>

                                <strong>
                                    {sector}
                                </strong>

                                <small>
                                    --
                                </small>

                            </div>

                        </div>

                    )
                )}

            </div>

        </section>
    );
}


/* ==========================================================
   HOME DASHBOARD
   ========================================================== */

function MarketTrendChart({
    data,
    loading,
    error
}) {

    if (loading) {

        return (
            <div className="trend-chart-state">
                Loading SENSEX trend...
            </div>
        );

    }

    if (error) {

        return (
            <div className="trend-chart-state error">
                Unable to load market trend
            </div>
        );

    }

    if (!data || data.length === 0) {

        return (
            <div className="trend-chart-state">
                No SENSEX trend data available
            </div>
        );

    }


    const width = 760;
    const height = 250;

    const paddingLeft = 58;
    const paddingRight = 18;
    const paddingTop = 18;
    const paddingBottom = 35;


    const values = data
        .map(item => Number(item.value))
        .filter(Number.isFinite);


    if (values.length === 0) {

        return (
            <div className="trend-chart-state">
                No valid SENSEX values available
            </div>
        );

    }


    const minValue = Math.min(...values);
    const maxValue = Math.max(...values);

    const range =
        maxValue - minValue || 1;


    const chartWidth =
        width -
        paddingLeft -
        paddingRight;

    const chartHeight =
        height -
        paddingTop -
        paddingBottom;


    const points = values.map(
        (value, index) => {

            const x =
                paddingLeft +
                (
                    index /
                    Math.max(values.length - 1, 1)
                ) *
                chartWidth;

            const y =
                paddingTop +
                (
                    (maxValue - value) /
                    range
                ) *
                chartHeight;

            return {
                x,
                y,
                value,
                date:
                    data[index]?.date
            };

        }
    );


    const linePoints =
        points
            .map(
                point =>
                    `${point.x},${point.y}`
            )
            .join(" ");


    const firstValue =
        values[0];

    const lastValue =
        values[values.length - 1];

    const change =
        lastValue - firstValue;

    const changePercent =
        firstValue !== 0
            ? (change / firstValue) * 100
            : 0;


    const latest =
        values[values.length - 1];


    return (
        <div className="trend-chart-container">

            <div className="trend-chart-summary">

                <div>
                    <span>
                        BSE SENSEX
                    </span>

                    <strong>
                        {latest.toLocaleString(
                            "en-IN",
                            {
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2
                            }
                        )}
                    </strong>
                </div>

                <div
                    className={
                        changePercent >= 0
                            ? "trend-change positive-text"
                            : "trend-change negative-text"
                    }
                >

                    {changePercent >= 0
                        ? "+"
                        : ""}

                    {changePercent.toFixed(2)}%

                </div>

            </div>


            <div className="trend-chart">

                <svg
                    viewBox={`0 0 ${width} ${height}`}
                    preserveAspectRatio="none"
                    role="img"
                    aria-label="BSE SENSEX market trend"
                >

                    {/* Grid lines */}

                    <line
                        x1={paddingLeft}
                        y1={paddingTop}
                        x2={width - paddingRight}
                        y2={paddingTop}
                        className="trend-grid-line"
                    />

                    <line
                        x1={paddingLeft}
                        y1={height / 2}
                        x2={width - paddingRight}
                        y2={height / 2}
                        className="trend-grid-line"
                    />

                    <line
                        x1={paddingLeft}
                        y1={height - paddingBottom}
                        x2={width - paddingRight}
                        y2={height - paddingBottom}
                        className="trend-grid-line"
                    />


                    {/* Price labels */}

                    <text
                        x="4"
                        y={paddingTop + 4}
                        className="trend-axis-label"
                    >
                        {maxValue.toLocaleString(
                            "en-IN",
                            {
                                maximumFractionDigits: 0
                            }
                        )}
                    </text>

                    <text
                        x="4"
                        y={height / 2 + 4}
                        className="trend-axis-label"
                    >
                        {(
                        (minValue + maxValue) / 2
                        ).toLocaleString(
                            "en-IN",
                            {
                                maximumFractionDigits: 0
                            }
                        )}
                    </text>

                    <text
                        x="4"
                        y={height - paddingBottom + 4}
                        className="trend-axis-label"
                    >
                        {minValue.toLocaleString(
                            "en-IN",
                            {
                                maximumFractionDigits: 0
                            }
                        )}
                    </text>


                    {/* Trend line */}

                    <polyline
                        points={linePoints}
                        fill="none"
                        className={
                            changePercent >= 0
                                ? "trend-line positive"
                                : "trend-line negative"
                        }
                    />


                    {/* Latest point */}

                    {points.length > 0 && (

                        <circle
                            cx={points[points.length - 1].x}
                            cy={points[points.length - 1].y}
                            r="4"
                            className="trend-point"
                        />

                    )}

                </svg>

            </div>


            <div className="trend-chart-footer">

                <span>
                    {data[0]?.date || "-"}
                </span>

                <span>
                    {data[data.length - 1]?.date || "-"}
                </span>

            </div>

        </div>
    );
}   


export default function HomeDashboard() {

    const [summary, setSummary] =
        useState(null);


    const [gainers, setGainers] =
        useState([]);


    const [losers, setLosers] =
        useState([]);


    const [securityCounts, setSecurityCounts] =
        useState(null);


    const [trendPeriod, setTrendPeriod] = 
        useState("1M");


    const [trendData, setTrendData] = 
        useState([]);


    const [trendLoading, setTrendLoading] = 
        useState(false);


    const [trendError, setTrendError] = 
        useState(null);


    const [bseIndices, setBseIndices] =
        useState([]);


    const [bseUpdated, setBseUpdated] =
        useState(null);


    const [loading, setLoading] =
        useState(true);


    const [error, setError] =
        useState(null);


    const [lastUpdated, setLastUpdated] =
        useState(null);


    useEffect(() => {

        let cancelled = false;


        async function loadMarketData() {

            try {

                setLoading(true);

                setError(null);


                const [
                    summaryResponse,
                    gainersResponse,
                    losersResponse,
                    securityResponse,
                    bseIndicesResponse
                ] = await Promise.all([

                    fetch(
                        `${API_BASE_URL}/api/market/summary`
                    ),

                    fetch(
                        `${API_BASE_URL}/api/market/gainers`
                    ),

                    fetch(
                        `${API_BASE_URL}/api/market/losers`
                    ),

                    fetch(
                        `${API_BASE_URL}/api/market/security-counts`
                    ),

                    fetch(
                        `${API_BASE_URL}/api/live/bse/indices`
                    )

                ]);


                if (!summaryResponse.ok) {

                    throw new Error(
                        `Market summary failed: ${summaryResponse.status}`
                    );

                }


                if (!gainersResponse.ok) {

                    throw new Error(
                        `Gainers failed: ${gainersResponse.status}`
                    );

                }


                if (!losersResponse.ok) {

                    throw new Error(
                        `Losers failed: ${losersResponse.status}`
                    );

                }


                if (!securityResponse.ok) {

                    throw new Error(
                        `Security counts failed: ${securityResponse.status}`
                    );

                }


                if (!bseIndicesResponse.ok) {

                    throw new Error(
                        `BSE indices failed: ${bseIndicesResponse.status}`
                    );

                }


                const [
                    summaryData,
                    gainersData,
                    losersData,
                    securityData,
                    bseData
                ] = await Promise.all([

                    summaryResponse.json(),

                    gainersResponse.json(),

                    losersResponse.json(),

                    securityResponse.json(),

                    bseIndicesResponse.json()

                ]);


                if (cancelled) {
                    return;
                }


                setSummary(
                    summaryData
                );


                setGainers(

                    Array.isArray(
                        gainersData
                    )

                        ? gainersData

                        : gainersData?.data || []

                );


                setLosers(

                    Array.isArray(
                        losersData
                    )

                        ? losersData

                        : losersData?.data || []

                );


                setSecurityCounts(

                    securityData?.data ||
                    securityData ||
                    null

                );


                setBseIndices(

                    Array.isArray(
                        bseData?.data
                    )

                        ? bseData.data

                        : []

                );


                setBseUpdated(

                    bseData?.last_updated ||
                    null

                );


                setLastUpdated(

                    bseData?.last_updated ||
                    summaryData?.lastUpdated ||
                    new Date().toISOString()

                );

            }

            catch (err) {

                if (!cancelled) {

                    setError(
                        err.message
                    );

                }

            }

            finally {

                if (!cancelled) {

                    setLoading(false);

                }

            }

        }


        loadMarketData();



                return () => {

                    cancelled = true;

                };

            }, []);



    useEffect(() => {

        let cancelled = false;

        async function loadTrend() {

            try {

                setTrendLoading(true);
                setTrendError(null);

                const response = await fetch(
                    `${API_BASE_URL}/api/live/bse/trend?period=${trendPeriod}`
                );

                if (!response.ok) {

                    throw new Error(
                        `Market trend failed: ${response.status}`
                    );

                }

                const result =
                    await response.json();

                if (cancelled) {
                    return;
                }

                setTrendData(
                    Array.isArray(result?.data)
                        ? result.data
                        : []
                );

            } catch (err) {

                if (!cancelled) {

                    console.error(
                        "Market trend error:",
                        err
                    );

                    setTrendError(
                        err.message
                    );

                    setTrendData([]);

                }

            } finally {

                if (!cancelled) {
                    setTrendLoading(false);
                }

            }

        }

        loadTrend();

        return () => {
            cancelled = true;
        };

    }, [trendPeriod]);


    const formattedUpdated =
        useMemo(() => {

            if (!lastUpdated) {
                return "-";
            }


            const date =
                new Date(
                    lastUpdated
                );


            if (
                Number.isNaN(
                    date.getTime()
                )
            ) {

                return String(
                    lastUpdated
                );

            }


            return date.toLocaleString(
                "en-IN",
                {
                    day: "2-digit",
                    month: "short",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit"
                }
            );

        }, [
            lastUpdated
        ]);


    const formattedBseUpdated =
        useMemo(() => {

            if (!bseUpdated) {
                return "-";
            }


            const date =
                new Date(
                    bseUpdated
                );


            if (
                Number.isNaN(
                    date.getTime()
                )
            ) {

                return String(
                    bseUpdated
                );

            }


            return date.toLocaleString(
                "en-IN",
                {
                    day: "2-digit",
                    month: "short",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit"
                }
            );

        }, [
            bseUpdated
        ]);


    if (loading) {

        return (

            <main className="market-page">

                <div className="page-loading">

                    <div className="loading-leaf">
                        MP
                    </div>

                    <h2>
                        Loading MarketPulse...
                    </h2>

                    <p>
                        Fetching today's market data
                    </p>

                </div>

            </main>

        );

    }


    if (error) {

        return (

            <main className="market-page">

                <div className="page-error">

                    <h2>
                        Unable to load market data
                    </h2>

                    <p>
                        {error}
                    </p>

                    <button
                        onClick={() =>
                            window.location.reload()
                        }
                        className="retry-button"
                    >
                        Try Again
                    </button>

                </div>

            </main>

        );

    }


    return (

        <main className="market-page">

            <div className="market-title">

                <div>

                    <span className="eyebrow">
                        INDIAN MARKETS
                    </span>

                    <h1>
                        Market Overview
                    </h1>

                    <p>
                        A consolidated view of Indian markets, indices and stock movers.
                    </p>

                </div>

            </div>


            <div className="market-layout">

                <MarketBreadth
                    summary={summary}
                />


                <section className="market-card trend-card">

                    <div className="section-heading">

                        <div>

                            <h2>
                                Market Trend
                            </h2>

                            <p>
                                BSE SENSEX historical trend
                            </p>

                        </div>


                        <div className="trend-periods">

                            <button
                                className={
                                    trendPeriod === "1D"
                                        ? "active"
                                        : ""
                                }
                                disabled
                                title="Intraday data will be connected separately"
                            >
                                1D
                            </button>


                            <button
                                className={
                                    trendPeriod === "1W"
                                        ? "active"
                                        : ""
                                }
                                onClick={() =>
                                    setTrendPeriod("1W")
                                }
                            >
                                1W
                            </button>


                            <button
                                className={
                                    trendPeriod === "1M"
                                        ? "active"
                                        : ""
                                }
                                onClick={() =>
                                    setTrendPeriod("1M")
                                }
                            >
                                1M
                            </button>


                            <button
                                className={
                                    trendPeriod === "1Y"
                                        ? "active"
                                        : ""
                                }
                                onClick={() =>
                                    setTrendPeriod("1Y")
                                }
                            >
                                1Y
                            </button>

                        </div>

                    </div>


                    <MarketTrendChart
                        data={trendData}
                        loading={trendLoading}
                        error={trendError}
                    />

                </section>

            </div>


            <MajorIndices
                indices={bseIndices}
            />


            <div className="movement-layout">

                <MovementTable
                    title="Top Gainers"
                    rows={gainers}
                    type="gainers"
                />


                <MovementTable
                    title="Top Losers"
                    rows={losers}
                    type="losers"
                />


                <MarketStatistics
                    summary={summary}
                    securityCounts={securityCounts}
                />

            </div>


        </main>

    );
}