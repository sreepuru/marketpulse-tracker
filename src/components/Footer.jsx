function Footer() {

    const currentYear = new Date().getFullYear();

    return (

        <footer className="footer">

            <div>

                <strong>📈 MarketPulse - NSE Dividend Tracker</strong>

            </div>

            <div style={{ marginTop: "8px" }}>

                Developed by <strong>Sreedhar P</strong>

            </div>

            <div style={{ marginTop: "8px", fontSize: "13px" }}>

                Version 1.0.0 | © {currentYear} | React + Python + NSE APIs

            </div>

        </footer>

    );

}

export default Footer;