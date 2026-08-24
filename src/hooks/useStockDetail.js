import { useState } from "react";

import { API_BASE_URL } from "../config";

export function useStockDetail() {

    const [stock, setStock] = useState(null);

    const [loading, setLoading] = useState(false);

    const [error, setError] = useState(null);


    async function searchStock(symbol) {

        const cleanSymbol = symbol.trim().toUpperCase();

        if (!cleanSymbol) {
            return;
        }


        try {

            setLoading(true);

            setError(null);

            setStock(null);


            const response = await fetch(
                `${API_BASE_URL}/api/stock/${encodeURIComponent(cleanSymbol)}`
            );


            if (!response.ok) {

                if (response.status === 404) {

                    throw new Error(
                        `Stock not found: ${cleanSymbol}`
                    );

                }


                throw new Error(
                    `Stock API failed: ${response.status}`
                );

            }


            const data = await response.json();


            setStock(data);


        } catch (err) {

            console.error(
                "Stock search error:",
                err
            );

            setError(err.message);


        } finally {

            setLoading(false);

        }

    }


    function clearStock() {

        setStock(null);

        setError(null);

    }


    return {
        stock,
        loading,
        error,
        searchStock,
        clearStock
    };

}