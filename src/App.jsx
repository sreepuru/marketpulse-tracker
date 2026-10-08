import { useEffect, useState } from "react";

import "./App.css";

import HomeDashboard from "./components/HomeDashboard";
import DividendDashboard from "./components/DividendDashboard";
import StockSearch from "./components/StockSearch";
import News from "./components/News";

import { API_BASE_URL } from "./config";


// ==========================================================
// Date Helpers
// ==========================================================

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


// ==========================================================
// Application
// ==========================================================

function App() {

    // ------------------------------------------------------
    // Navigation
    // ------------------------------------------------------

    const [activeTab, setActiveTab] = useState("home");


    // ------------------------------------------------------
    // Existing Market Data
    // ------------------------------------------------------

    const [marketSummary, setMarketSummary] = useState(null);

    const [marketGainers, setMarketGainers] = useState([]);

    const [marketLosers, setMarketLosers] = useState([]);


    // ------------------------------------------------------
    // Corporate Actions
    // ------------------------------------------------------

    const [corporateSummary, setCorporateSummary] = useState({
        total: 0,
        dividend: 0,
        bonus: 0,
        rights: 0,
        buyback: 0,
        boardMeeting: 0,
        lastUpdated: null
    });


    // ------------------------------------------------------
    // Security Counts
    // ------------------------------------------------------

    const [equityCount, setEquityCount] = useState(0);

    const [smeCount, setSmeCount] = useState(0);


    // ------------------------------------------------------
    // Loading / Error
    // ------------------------------------------------------

    const [loading, setLoading] = useState(true);

    const [error, setError] = useState(null);


    // ======================================================
    // Load Dashboard Data
    // ======================================================

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
                        `${API_BASE_URL}/api/corporate-actions/summary`
                    ),

                    fetch(
                        `${API_BASE_URL}/api/market/security-counts`
                    )

                ]);


                // --------------------------------------------------
                // API Validation
                // --------------------------------------------------

                if (!summaryResponse.ok) {

                    throw new Error(
                        `Market summary API failed: ${summaryResponse.status}`
                    );

                }


                if (!gainersResponse.ok) {

                    throw new Error(
                        `Gainers API failed: ${gainersResponse.status}`
                    );

                }


                if (!losersResponse.ok) {

                    throw new Error(
                        `Losers API failed: ${losersResponse.status}`
                    );

                }


                if (!corporateResponse.ok) {

                    throw new Error(
                        `Corporate actions API failed: ${corporateResponse.status}`
                    );

                }


                if (!securityResponse.ok) {

                    throw new Error(
                        `Security count API failed: ${securityResponse.status}`
                    );

                }


                // --------------------------------------------------
                // Parse Responses
                // --------------------------------------------------

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


                // --------------------------------------------------
                // Market Data
                // --------------------------------------------------

                setMarketSummary(summaryData);


                setMarketGainers(
                    gainersData.data || []
                );


                setMarketLosers(
                    losersData.data || []
                );


                // --------------------------------------------------
                // Corporate Actions
                // --------------------------------------------------

                setCorporateSummary({

                    total:
                        corporateData.total ??
                        0,

                    dividend:
                        corporateData.dividend ??
                        0,

                    bonus:
                        corporateData.bonus ??
                        0,

                    rights:
                        corporateData.rights ??
                        0,

                    buyback:
                        corporateData.buyback ??
                        corporateData.buybacks ??
                        0,

                    boardMeeting:
                        corporateData.boardMeeting ??
                        corporateData.board_meetings ??
                        0,

                    lastUpdated:
                        corporateData.last_updated ??
                        corporateData.lastUpdated ??
                        null

                });


                // --------------------------------------------------
                // Security Counts
                // --------------------------------------------------

                setEquityCount(
                    securityData.equity ?? 0
                );


                setSmeCount(
                    securityData.sme ?? 0
                );


            } catch (err) {

                console.error(
                    "Dashboard loading error:",
                    err
                );

                setError(
                    err.message
                );


            } finally {

                setLoading(false);

            }

        }


        loadDashboard();

    }, []);


    // ======================================================
    // Loading Screen
    // ======================================================

    if (loading) {

        return (

            <div className="loading-screen">

                <div className="loading-content">

                    <div className="loading-logo">
                        MP
                    </div>

                    <h2>
                        MarketPulse
                    </h2>

                    <p>
                        Loading market data...
                    </p>

                </div>

            </div>

        );

    }


    // ======================================================
    // Error Screen
    // ======================================================

    if (error) {

        return (

            <div className="loading-screen">

                <div className="error-content">

                    <div className="error-icon">
                        !
                    </div>

                    <h2>
                        MarketPulse
                    </h2>

                    <p>
                        {error}
                    </p>

                </div>

            </div>

        );

    }


    // ======================================================
    // Existing Market Information
    // ======================================================

    const marketDate =
        marketSummary?.market_date ||
        null;


    const marketDateDisplay =
        formatDate(marketDate);


    const securities =
        marketSummary?.securities ??
        marketSummary?.total_securities ??
        marketSummary?.security_count ??
        0;


    const topGainer =
        marketGainers.length
            ? marketGainers[0]
            : null;


    const topLoser =
        marketLosers.length
            ? marketLosers[0]
            : null;


    // ======================================================
    // Render
    // ======================================================

    return (

        <div className="app">


            {/* ==================================================
                Header
               ================================================== */}

            <header className="mp-header">

                <div className="mp-brand">

                    <div className="mp-brand-mark">
                        <span>⌁</span>
                    </div>

                    <div className="mp-brand-text">

                        <h1>
                            MarketPulse
                        </h1>

                        <p>
                            Pulse of the Indian Markets
                        </p>

                    </div>

                </div>


                <div className="mp-header-right">

                    <div className="mp-market-status">

                        <span className="mp-status-dot" />

                        <div>

                            <strong>
                                Market Data
                            </strong>

                            <small>
                                NSE
                            </small>

                        </div>

                    </div>


                    <div className="mp-market-date">

                        <span>
                            MARKET DATE
                        </span>

                        <strong>
                            {marketDateDisplay}
                        </strong>

                    </div>

                </div>

            </header>


            {/* ==================================================
                Navigation
               ================================================== */}

            <nav
                className="navigation"
                aria-label="Dashboard navigation"
            >

                <button
                    className={
                        activeTab === "home"
                            ? "nav-tab active"
                            : "nav-tab"
                    }
                    onClick={() => setActiveTab("home")}
                >
                    <span>⌂</span>
                    Market Overview
                </button>


                <button
                    className={
                        activeTab === "dividend"
                            ? "nav-tab active"
                            : "nav-tab"
                    }
                    onClick={() => setActiveTab("dividend")}
                >
                    <span>💰</span>
                    Dividends
                </button>


                <button
                    className={
                        activeTab === "stock"
                            ? "nav-tab active"
                            : "nav-tab"
                    }
                    onClick={() => setActiveTab("stock")}
                >
                    <span>📰</span>
                    Stock Feed
                </button>


                <button
                    className={
                        activeTab === "news"
                            ? "nav-tab active"
                            : "nav-tab"
                    }
                    onClick={() => setActiveTab("news")}
                >
                    <span>📰</span>
                    News &amp; Feeds
                </button>

            </nav>


            {/* ==================================================
                HOME / MARKET OVERVIEW
               ================================================== */}

            {activeTab === "home" && (

                <main>

                    <HomeDashboard />

                </main>

            )}


            {/* ==================================================
                DIVIDEND DASHBOARD
               ================================================== */}

            {activeTab === "dividend" && (

                <main className="dividend-page">

                    <DividendDashboard
                        marketDate={marketDate}
                    />

                </main>

            )}


            {/* ==================================================
                STOCK NEWS & FEED
               ================================================== */}

            {activeTab === "stock" && (

                <main>

                    <section className="stock-feed-page">

                        <div className="page-title">

                            <span>
                                STOCK INTELLIGENCE
                            </span>

                            <h2>
                                Stock News &amp; Feed
                            </h2>

                            <p>
                                Search a stock for its price,
                                dividend and corporate-action feed.
                            </p>

                        </div>


                        <StockSearch />

                    </section>

                </main>

            )}


            {/* ==================================================
                NEWS & GLOBAL FEEDS
               ================================================== */}

            {activeTab === "news" && (

                <main className="news-page-container">

                    <News />

                </main>

            )}

        </div>

    );

}


export default App;