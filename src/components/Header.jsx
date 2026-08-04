import { useEffect, useState } from "react";

function Header() {

    const [lastUpdated, setLastUpdated] = useState("");

    useEffect(() => {

        updateTime();

        const timer = setInterval(updateTime, 1000);

        return () => clearInterval(timer);

    }, []);

    function updateTime() {

        const now = new Date();

        const formatted = now.toLocaleString("en-IN", {
            day: "2-digit",
            month: "short",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
            hour12: true
        });

        setLastUpdated(formatted);

    }

    return (

        <header className="header">

            <div className="header-left">

                <h1>
                    📈 MarketPulse
                </h1>

                <h3>
                    NSE Dividend Tracker
                </h3>

            </div>

            <div className="header-right">

                <div className="status">

                    🟢 LIVE

                </div>

                <div className="updated">

                    Last Updated

                </div>

                <div className="time">

                    {lastUpdated}

                </div>

            </div>

        </header>

    );

}

export default Header;