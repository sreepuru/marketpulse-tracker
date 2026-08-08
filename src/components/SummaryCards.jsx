function SummaryCards({
    summary,
    equityCount,
    smeCount,
    lastUpdated
}) {

    return (

        <div className="summary-container">

            {/* Total Records */}

            <div className="kpi-card total-card">

                <div className="kpi-title">
                    📄 Total Records
                </div>

                <div className="kpi-value">
                    {summary.total}
                </div>

                <div className="kpi-subtitle">
                    Last updated
                </div>

                <div className="kpi-subtitle-value">
                    {lastUpdated || "Loading..."}
                </div>

            </div>


            {/* Equity */}

            <div className="kpi-card equity-card">

                <div className="kpi-title">
                    📈 Equity
                </div>

                <div className="kpi-value">
                    {equityCount}
                </div>

            </div>


            {/* SME */}

            <div className="kpi-card sme-card">

                <div className="kpi-title">
                    🏢 SME
                </div>

                <div className="kpi-value">
                    {smeCount}
                </div>

            </div>


            {/* Dividend */}

            <div className="kpi-card dividend-card">

                <div className="kpi-title">
                    💰 Dividend
                </div>

                <div className="kpi-value">
                    {summary.dividend}
                </div>

            </div>


            {/* Bonus */}

            <div className="kpi-card bonus-card">

                <div className="kpi-title">
                    🎁 Bonus
                </div>

                <div className="kpi-value">
                    {summary.bonus}
                </div>

            </div>


            {/* Board Meeting */}

            <div className="kpi-card board-card">

                <div className="kpi-title">
                    🏢 Board Meeting
                </div>

                <div className="kpi-value">
                    {summary.boardMeeting}
                </div>

            </div>

        </div>

    );

}

export default SummaryCards;