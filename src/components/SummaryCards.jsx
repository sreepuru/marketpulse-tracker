function formatLastUpdated(value) {

    if (!value) {
        return "Not available";
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


function SummaryCards({
    summary = {},
    equityCount,
    smeCount,
    lastUpdated,
    marketSummary,
    marketGainers = [],
    marketLosers = []
}) {

    const topGainer =
        marketGainers.length > 0
            ? marketGainers[0]
            : null;


    const topLoser =
        marketLosers.length > 0
            ? marketLosers[0]
            : null;


    /*
     * Resolve Last Updated from both possible sources.
     *
     * Priority:
     * 1. Explicit lastUpdated prop
     * 2. summary.last_updated from API
     */

    const resolvedLastUpdated =
        lastUpdated ||
        summary?.last_updated ||
        null;


    const formattedLastUpdated =
        formatLastUpdated(
            resolvedLastUpdated
        );


    return (

        <>

            {/* =====================================================
                MARKET OVERVIEW
            ===================================================== */}

            <div className="summary-container">


                {/* Market Date */}

                <div className="kpi-card market-date-card">

                    <div className="kpi-title">
                        📅 Market Date
                    </div>

                    <div className="kpi-value">
                        {marketSummary?.market_date || "Loading..."}
                    </div>

                    <div className="kpi-subtitle">
                        Latest available trading date
                    </div>

                </div>


                {/* Total Securities */}

                <div className="kpi-card market-security-card">

                    <div className="kpi-title">
                        📊 Securities
                    </div>

                    <div className="kpi-value">
                        {marketSummary?.total_securities ?? "Loading..."}
                    </div>

                    <div className="kpi-subtitle">
                        From PostgreSQL
                    </div>

                </div>


                {/* Top Gainer */}

                <div className="kpi-card market-gainer-card">

                    <div className="kpi-title">
                        🚀 Top Gainer
                    </div>


                    {topGainer ? (

                        <>

                            <div className="kpi-value">
                                {topGainer.symbol}
                            </div>

                            <div className="kpi-subtitle-value">
                                {topGainer.change_percent}%
                            </div>

                            <div className="kpi-subtitle">
                                ₹{topGainer.current_price}
                            </div>

                        </>

                    ) : (

                        <div className="kpi-value">
                            Loading...
                        </div>

                    )}

                </div>


                {/* Top Loser */}

                <div className="kpi-card market-loser-card">

                    <div className="kpi-title">
                        📉 Top Loser
                    </div>


                    {topLoser ? (

                        <>

                            <div className="kpi-value">
                                {topLoser.symbol}
                            </div>

                            <div className="kpi-subtitle-value">
                                {topLoser.change_percent}%
                            </div>

                            <div className="kpi-subtitle">
                                ₹{topLoser.current_price}
                            </div>

                        </>

                    ) : (

                        <div className="kpi-value">
                            Loading...
                        </div>

                    )}

                </div>

            </div>


            {/* =====================================================
                CORPORATE ACTION SUMMARY
            ===================================================== */}

            <div className="summary-container">


                {/* Total Records */}

                <div className="kpi-card total-card">

                    <div className="kpi-title">
                        📄 Total Records
                    </div>

                    <div className="kpi-value">
                        {summary.total ?? 0}
                    </div>

                    <div className="kpi-subtitle">
                        Last updated
                    </div>

                    <div className="kpi-subtitle-value">
                        {formattedLastUpdated}
                    </div>

                </div>


                {/* Equity */}

                <div className="kpi-card equity-card">

                    <div className="kpi-title">
                        📈 Equity
                    </div>

                    <div className="kpi-value">
                        {equityCount ?? 0}
                    </div>

                </div>


                {/* SME */}

                <div className="kpi-card sme-card">

                    <div className="kpi-title">
                        🏢 SME
                    </div>

                    <div className="kpi-value">
                        {smeCount ?? 0}
                    </div>

                </div>


                {/* Dividend */}

                <div className="kpi-card dividend-card">

                    <div className="kpi-title">
                        💰 Dividend
                    </div>

                    <div className="kpi-value">
                        {summary.dividend ?? 0}
                    </div>

                    <div className="kpi-subtitle">
                        Last updated
                    </div>

                    <div className="kpi-subtitle-value">
                        {formattedLastUpdated}
                    </div>

                </div>


                {/* Bonus */}

                <div className="kpi-card bonus-card">

                    <div className="kpi-title">
                        🎁 Bonus
                    </div>

                    <div className="kpi-value">
                        {summary.bonus ?? 0}
                    </div>

                </div>


                {/* Board Meeting */}

                <div className="kpi-card board-card">

                    <div className="kpi-title">
                        🏢 Board Meeting
                    </div>

                    <div className="kpi-value">
                        {summary.boardMeeting ?? 0}
                    </div>

                </div>

            </div>

        </>

    );

}


export default SummaryCards;