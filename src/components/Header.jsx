import { useEffect, useState } from "react";

function Header({ activeTab, setActiveTab }) {

    const [currentTime, setCurrentTime] = useState("");

    useEffect(() => {

        const updateCurrentTime = () => {

            const now = new Date();

            setCurrentTime(
                now.toLocaleTimeString("en-IN", {
                    hour: "2-digit",
                    minute: "2-digit",
                    hour12: true
                })
            );

        };

        updateCurrentTime();

        const timer = setInterval(
            updateCurrentTime,
            60000
        );

        return () => clearInterval(timer);

    }, []);

    const tabs = [
        "Dividend Tracker",
        "Corporate Actions",
        "Market",
        "Watchlist",
        "Alerts"
    ];

    return (

        <header className="header">

            {/* Top Header */}

            <div className="header-top">

                <div className="brand">

                    <div className="brand-title">
                        📈 MarketPulse
                    </div>

                    <div className="brand-subtitle">
                        Market Intelligence Platform
                    </div>

                </div>


                <div className="live-section">

                    <span className="live-dot">
                        ●
                    </span>

                    <span className="live-text">
                        LIVE
                    </span>

                    <span className="current-time">
                        {currentTime}
                    </span>

                </div>

            </div>


            {/* Navigation */}

            <div className="navigation-wrapper">

                <nav className="navigation-tabs">

                    {tabs.map((tab) => (

                        <button
                            key={tab}
                            className={
                                activeTab === tab
                                    ? "nav-tab active"
                                    : "nav-tab"
                            }
                            onClick={() =>
                                setActiveTab(tab)
                            }
                        >

                            {tab}

                        </button>

                    ))}

                </nav>

            </div>

        </header>

    );

}

export default Header;