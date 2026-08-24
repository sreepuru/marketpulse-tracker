import { useState } from "react";

import { useStockDetail } from "../hooks/useStockDetail";


function StockSearch() {

    const [symbol, setSymbol] = useState("");

    const {
        stock,
        loading,
        error,
        searchStock,
        clearStock
    } = useStockDetail();


    function handleSubmit(event) {

        event.preventDefault();

        searchStock(symbol);

    }


    return (

        <div className="stock-search-section">

            <h2>
                📰 Stock News & Feed
            </h2>


            <form
                onSubmit={handleSubmit}
                className="stock-search-form"
            >

                <input
                    type="text"
                    value={symbol}
                    onChange={(event) =>
                        setSymbol(event.target.value)
                    }
                    placeholder="Search stock e.g. MAHICKRA"
                />

                <button type="submit">
                    Search
                </button>

            </form>


            {loading && (
                <p>
                    Loading stock...
                </p>
            )}


            {error && (

                <div className="stock-error">

                    <p>
                        {error}
                    </p>

                </div>

            )}


            {stock && (

                <div className="stock-detail">

                    {/* ======================================
                        Security Information
                    ====================================== */}

                    <div className="stock-header">

                        <h3>
                            {stock.security.symbol}
                        </h3>

                        <p>
                            {stock.security.instrument_name}
                        </p>

                        <p>
                            ISIN: {stock.security.isin}
                        </p>

                        <p>
                            Series: {stock.security.series}
                        </p>

                    </div>


                    {/* ======================================
                        Latest Price
                    ====================================== */}

                    {stock.latest_price && (

                        <div className="stock-price-grid">

                            <div>
                                <strong>
                                    Trade Date
                                </strong>

                                <span>
                                    {stock.latest_price.trade_date}
                                </span>
                            </div>


                            <div>
                                <strong>
                                    Open
                                </strong>

                                <span>
                                    ₹{stock.latest_price.open}
                                </span>
                            </div>


                            <div>
                                <strong>
                                    High
                                </strong>

                                <span>
                                    ₹{stock.latest_price.high}
                                </span>
                            </div>


                            <div>
                                <strong>
                                    Low
                                </strong>

                                <span>
                                    ₹{stock.latest_price.low}
                                </span>
                            </div>


                            <div>
                                <strong>
                                    Close
                                </strong>

                                <span>
                                    ₹{stock.latest_price.close}
                                </span>
                            </div>


                            <div>
                                <strong>
                                    Volume
                                </strong>

                                <span>
                                    {stock.latest_price.volume}
                                </span>
                            </div>

                        </div>

                    )}


                    {/* ======================================
                        Historical Prices
                    ====================================== */}

                    <h3>
                        Historical Prices
                    </h3>

                    <table>

                        <thead>

                            <tr>
                                <th>Date</th>
                                <th>Open</th>
                                <th>High</th>
                                <th>Low</th>
                                <th>Close</th>
                                <th>Volume</th>
                            </tr>

                        </thead>

                        <tbody>

                            {stock.historical_prices.map(
                                (price) => (

                                    <tr
                                        key={
                                            `${stock.security.symbol}-${price.trade_date}`
                                        }
                                    >

                                        <td>
                                            {price.trade_date}
                                        </td>

                                        <td>
                                            ₹{price.open}
                                        </td>

                                        <td>
                                            ₹{price.high}
                                        </td>

                                        <td>
                                            ₹{price.low}
                                        </td>

                                        <td>
                                            ₹{price.close}
                                        </td>

                                        <td>
                                            {price.volume}
                                        </td>

                                    </tr>

                                )
                            )}

                        </tbody>

                    </table>


                    {/* ======================================
                        Corporate Actions
                    ====================================== */}

                    <h3>
                        Corporate Actions
                    </h3>

                    {stock.corporate_actions.length === 0 ? (

                        <p>
                            No corporate actions found.
                        </p>

                    ) : (

                        <table>

                            <thead>

                                <tr>
                                    <th>Type</th>
                                    <th>Subject</th>
                                    <th>Ex-Date</th>
                                    <th>Record Date</th>
                                </tr>

                            </thead>

                            <tbody>

                                {stock.corporate_actions.map(
                                    (action) => (

                                        <tr
                                            key={
                                                action.corporate_action_id
                                            }
                                        >

                                            <td>
                                                {action.action_type}
                                            </td>

                                            <td>
                                                {action.subject}
                                            </td>

                                            <td>
                                                {action.ex_date || "-"}
                                            </td>

                                            <td>
                                                {action.record_date || "-"}
                                            </td>

                                        </tr>

                                    )
                                )}

                            </tbody>

                        </table>

                    )}


                    <button
                        onClick={clearStock}
                        className="clear-stock-button"
                    >
                        Clear
                    </button>

                </div>

            )}

        </div>

    );

}

export default StockSearch;