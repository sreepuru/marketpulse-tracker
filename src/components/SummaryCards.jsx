function SummaryCards({ summary }) {

    return (

        <div className="summary-container">

            <div className="summary-card">

                <div className="summary-title">

                    📄 Total Records

                </div>

                <div className="summary-value">

                    {summary.total}

                </div>

            </div>

            <div className="summary-card">

                <div className="summary-title">

                    💰 Dividend

                </div>

                <div className="summary-value">

                    {summary.dividend}

                </div>

            </div>

            <div className="summary-card">

                <div className="summary-title">

                    🎁 Bonus

                </div>

                <div className="summary-value">

                    {summary.bonus}

                </div>

            </div>

            <div className="summary-card">

                <div className="summary-title">

                    🏢 Board Meeting

                </div>

                <div className="summary-value">

                    {summary.boardMeeting}

                </div>

            </div>

        </div>

    );

}

export default SummaryCards;