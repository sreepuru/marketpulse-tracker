import { useEffect, useState } from "react";
import { getMarketMovement } from "../services/marketService";

export function useMarketMovement() {
  const [marketData, setMarketData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function loadMarketData() {
      try {
        setLoading(true);

        const result = await getMarketMovement();

        setMarketData(result.data || []);
        setError(null);

      } catch (err) {
        console.error("Market data error:", err);
        setError(err.message);

      } finally {
        setLoading(false);
      }
    }

    loadMarketData();
  }, []);

  return {
    marketData,
    loading,
    error
  };
}