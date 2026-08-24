import { useEffect, useState } from "react";

import "./App.css";

import DividendDashboard from "./components/DividendDashboard";
import StockSearch from "./components/StockSearch";

import { API_BASE_URL } from "./config";

function formatDate(date) {
    if (!date) return "-";

    const parts = String(date).split("-");

    if (parts.length !== 3) return date;

    const year = parts[0];
    const month = Number(parts[1]);
    const day = Number(parts[2]);

    const monthNames = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    ];

    return `${String(day).padStart(2, "0")}-${monthNames[month - 1]}-${year}`;
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

function App() {
    const [activeTab, setActiveTab] = useState("dividend");

    const [marketSummary, setMarketSummary] = useState(null);
    const [marketGainers, setMarketGainers] = useState([]);
    const [marketLosers, setMarketLosers] = useState([]);

    const [corporateSummary, setCorporateSummary] = useState({
        total: 0,
        dividend: 0,
        bonus: 0,
        rights: 0,
        buyback: 0,
        boardMeeting: 0,
        lastUpdated: null
    });

    const [equityCount, setEquityCount] = useState(0);
    const [smeCount, setSmeCount] = useState(0);

    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        async function loadDashboard() {
            try {
                setLoading(true);
                setError(null);

                const [
                    summaryResponse,
                    gainersResponse,
                    losersResponse,
                    corporateResponse,
                    securityResponse
                ] = await Promise.all([
                    fetch(`${API_BASE_URL}/api/market/summary`),
                    fetch(`${API_BASE_URL}/api/market/gainers`),
                    fetch(`${API_BASE_URL}/api/market/losers`),
                    fetch(`${API_BASE_URL}/api/corporate-actions/summary`),
                    fetch(`${API_BASE_URL}/api/market/security-counts`)
                ]);

                if (!summaryResponse.ok) {
                    throw new Error(`Market summary API failed: ${summaryResponse.status}`);
                }

                if (!gainersResponse.ok) {
                    throw new Error(`Gainers API failed: ${gainersResponse.status}`);
                }

                if (!losersResponse.ok) {
                    throw new Error(`Losers API failed: ${losersResponse.status}`);
                }

                if (!corporateResponse.ok) {
                    throw new Error(`Corporate actions API failed: ${corporateResponse.status}`);
                }

                if (!securityResponse.ok) {
                    throw new Error(`Security count API failed: ${securityResponse.status}`);
                }

                const [
                    summaryData,
                    gainersData,
                    losersData,
                    corporateData,
                    securityData
                ] = await Promise.all([
                    summaryResponse.json(),
                    gainersResponse.json(),
                    losersResponse.json(),
                    corporateResponse.json(),
                    securityResponse.json()
                ]);

                setMarketSummary(summaryData);
                setMarketGainers(gainersData.data || []);
                setMarketLosers(losersData.data || []);

                setCorporateSummary({
                    total: corporateData.total ?? 0,
                    dividend: corporateData.dividend ?? 0,
                    bonus: corporateData.bonus ?? 0,
                    rights: corporateData.rights ?? 0,
                    buyback: corporateData.buyback ??
                        corporateData.buybacks ?? 0,
                    boardMeeting: corporateData.boardMeeting ??
                        corporateData.board_meetings ?? 0,
                    lastUpdated: corporateData.last_updated ??
                        corporateData.lastUpdated ?? null
                });

                setEquityCount(securityData.equity ?? 0);
                setSmeCount(securityData.sme ?? 0);
            } catch (err) {
                console.error("Dashboard loading error:", err);
                setError(err.message);
            } finally {
                setLoading(false);
            }
        }

        loadDashboard();
    }, []);

    if (loading) {
        return (
            <div className="loading-screen">
                <div className="loading-content">
                    <div className="loading-logo">MP</div>
                    <h2>MarketPulse</h2>
                    <p>Loading market data...</p>
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="loading-screen">
                <div className="error-content">
                    <div className="error-icon">!</div>
                    <h2>MarketPulse</h2>
                    <p>{error}</p>
                </div>
            </div>
        );
    }

    const marketDate = marketSummary?.market_date || null;
    const marketDateDisplay = formatDate(marketDate);

    const securities =
        marketSummary?.securities ??
        marketSummary?.total_securities ??
        marketSummary?.security_count ??
        0;

    const topGainer = marketGainers.length ? marketGainers[0] : null;
    const topLoser = marketLosers.length ? marketLosers[0] : null;

    return (
        <div className="app">
            <header className="header">
                <div className="brand">
                    <div className="brand-logo">MP</div>

                    <div>
                        <h1>MarketPulse</h1>
                        <p>Dividend intelligence &amp; market movement</p>
                    </div>
                </div>

                <div className="header-market-date">
                    <span>MARKET DATA</span>
                    <strong>{marketDateDisplay}</strong>
                </div>
            </header>

            <nav className="navigation" aria-label="Dashboard navigation">
                <button
                    className={activeTab === "dividend" ? "nav-tab active" : "nav-tab"}
                    onClick={() => setActiveTab("dividend")}
                >
                    <span>💰</span>
                    Dividend Dashboard
                </button>

                <button
                    className={activeTab === "stock" ? "nav-tab active" : "nav-tab"}
                    onClick={() => setActiveTab("stock")}
                >
                    <span>📰</span>
                    Stock News &amp; Feed
                </button>
            </nav>

            {activeTab === "dividend" && (
                <main>
                    <section className="dashboard-section market-snapshot-section">
                        <div className="section-heading">
                            <div>
                                <span className="section-eyebrow">MARKET OVERVIEW</span>
                                <h2>Market Snapshot</h2>
                            </div>
                            <span>Latest available trading date</span>
                        </div>

                        <div className="snapshot-grid">
                            <div className="snapshot-card market-date-card">
                                <div className="snapshot-title">
                                    <span className="icon-badge cyan">📅</span>
                                    Market Date
                                </div>
                                <div className="snapshot-value">{marketDateDisplay}</div>
                                <div className="snapshot-note">Latest trading data</div>
                            </div>

                            <div className="snapshot-card securities-card">
                                <div className="snapshot-title">
                                    <span className="icon-badge violet">◈</span>
                                    Securities
                                </div>
                                <div className="snapshot-value">
                                    {Number(securities).toLocaleString()}
                                </div>
                                <div className="snapshot-note">From PostgreSQL</div>
                            </div>

                            <div className="snapshot-card gainer-card">
                                <div className="snapshot-title">
                                    <span className="icon-badge green">↗</span>
                                    Top Gainer
                                </div>
                                <div className="snapshot-date">{marketDateDisplay}</div>
                                <div className="mover-symbol">
                                    {topGainer?.symbol || "—"}
                                </div>
                                <div className="mover-change positive">
                                    {topGainer
                                        ? `+${topGainer.change_percent}%`
                                        : "—"}
                                </div>
                                <div className="mover-price">
                                    {topGainer?.current_price != null
                                        ? `₹${topGainer.current_price}`
                                        : "Price unavailable"}
                                </div>
                            </div>

                            <div className="snapshot-card loser-card">
                                <div className="snapshot-title">
                                    <span className="icon-badge coral">↘</span>
                                    Top Loser
                                </div>
                                <div className="snapshot-date">{marketDateDisplay}</div>
                                <div className="mover-symbol">
                                    {topLoser?.symbol || "—"}
                                </div>
                                <div className="mover-change negative">
                                    {topLoser
                                        ? `${topLoser.change_percent}%`
                                        : "—"}
                                </div>
                                <div className="mover-price">
                                    {topLoser?.current_price != null
                                        ? `₹${topLoser.current_price}`
                                        : "Price unavailable"}
                                </div>
                            </div>
                        </div>
                    </section>

                    <section className="dashboard-section corporate-section">
                        <div className="section-heading">
                            <div className="heading-with-subtitle">
                                <div>
                                    <span className="section-eyebrow">ANNOUNCEMENTS</span>
                                    <h2>Corporate Actions</h2>
                                </div>
                                <span>Available announcements</span>
                            </div>

                            <div className="total-pill">
                                {corporateSummary.total} total
                            </div>
                        </div>

                        <div className="corporate-grid">
                            <div className="corporate-card dividend-card">
                                <div className="corporate-icon">💰</div>
                                <div className="corporate-content">
                                    <strong>{corporateSummary.dividend}</strong>
                                    <span>Dividend</span>
                                    <small>Last Updated</small>
                                    <b>{formatDateTime(corporateSummary.lastUpdated)}</b>
                                </div>
                            </div>

                            <div className="corporate-card bonus-card">
                                <div className="corporate-icon">🎁</div>
                                <div className="corporate-content">
                                    <strong>{corporateSummary.bonus}</strong>
                                    <span>Bonus</span>
                                </div>
                            </div>

                            <div className="corporate-card rights-card">
                                <div className="corporate-icon">📋</div>
                                <div className="corporate-content">
                                    <strong>{corporateSummary.rights}</strong>
                                    <span>Rights</span>
                                </div>
                            </div>

                            <div className="corporate-card buyback-card">
                                <div className="corporate-icon">↩</div>
                                <div className="corporate-content">
                                    <strong>{corporateSummary.buyback}</strong>
                                    <span>Buyback</span>
                                </div>
                            </div>

                            <div className="corporate-card board-card">
                                <div className="corporate-icon">▦</div>
                                <div className="corporate-content">
                                    <strong>{corporateSummary.boardMeeting}</strong>
                                    <span>Board Meeting</span>
                                </div>
                            </div>

                            <div className="corporate-card equity-card">
                                <div className="corporate-icon">📊</div>
                                <div className="corporate-content">
                                    <strong>{equityCount.toLocaleString()}</strong>
                                    <span>Equity</span>
                                </div>
                            </div>

                            <div className="corporate-card sme-card">
                                <div className="corporate-icon">🏭</div>
                                <div className="corporate-content">
                                    <strong>{smeCount.toLocaleString()}</strong>
                                    <span>SME</span>
                                </div>
                            </div>
                        </div>
                    </section>

                    <DividendDashboard marketDate={marketDate} />

                    <section className="dashboard-section movers-section">
                        <div className="movers-grid">
                            <div className="movers-card">
                                <div className="movers-header">
                                    <div>
                                        <span className="section-eyebrow">MARKET MOVEMENT</span>
                                        <h2>📈 Top Gainers</h2>
                                        <span>{marketDateDisplay}</span>
                                    </div>
                                    <span className="gainer-label">GAINERS</span>
                                </div>

                                <div className="movers-table-header">
                                    <span>#</span>
                                    <span>Symbol</span>
                                    <span>Price</span>
                                    <span>Change</span>
                                </div>

                                {marketGainers.slice(0, 5).map((stock, index) => (
                                    <div
                                        className="movers-row"
                                        key={`${stock.symbol}-${stock.isin}`}
                                    >
                                        <span>{index + 1}</span>
                                        <strong>{stock.symbol}</strong>
                                        <span>
                                            {stock.current_price != null
                                                ? `₹${stock.current_price}`
                                                : "—"}
                                        </span>
                                        <span className="positive">
                                            {stock.change_percent != null
                                                ? `+${stock.change_percent}%`
                                                : "—"}
                                        </span>
                                    </div>
                                ))}

                                {!marketGainers.length && (
                                    <div className="movers-empty">
                                        No gainer data available.
                                    </div>
                                )}
                            </div>

                            <div className="movers-card">
                                <div className="movers-header">
                                    <div>
                                        <span className="section-eyebrow">MARKET MOVEMENT</span>
                                        <h2>📉 Top Losers</h2>
                                        <span>{marketDateDisplay}</span>
                                    </div>
                                    <span className="loser-label">LOSERS</span>
                                </div>

                                <div className="movers-table-header">
                                    <span>#</span>
                                    <span>Symbol</span>
                                    <span>Price</span>
                                    <span>Change</span>
                                </div>

                                {marketLosers.slice(0, 5).map((stock, index) => (
                                    <div
                                        className="movers-row"
                                        key={`${stock.symbol}-${stock.isin}`}
                                    >
                                        <span>{index + 1}</span>
                                        <strong>{stock.symbol}</strong>
                                        <span>
                                            {stock.current_price != null
                                                ? `₹${stock.current_price}`
                                                : "—"}
                                        </span>
                                        <span className="negative">
                                            {stock.change_percent != null
                                                ? `${stock.change_percent}%`
                                                : "—"}
                                        </span>
                                    </div>
                                ))}

                                {!marketLosers.length && (
                                    <div className="movers-empty">
                                        No loser data available.
                                    </div>
                                )}
                            </div>
                        </div>
                    </section>
                </main>
            )}

            {activeTab === "stock" && (
                <main>
                    <section className="stock-feed-page">
                        <div className="page-title">
                            <span>STOCK INTELLIGENCE</span>
                            <h2>Stock News &amp; Feed</h2>
                            <p>
                                Search a stock for its price, dividend and corporate-action feed.
                            </p>
                        </div>
                        <StockSearch />
                    </section>
                </main>
            )}
        </div>
    );
}

export default App;