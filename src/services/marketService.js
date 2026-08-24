import { API_BASE_URL } from "../config";

export async function getMarketMovement() {
  const response = await fetch(
    `${API_BASE_URL}/api/market/movement`
  );

  if (!response.ok) {
    throw new Error(
      `Market API failed: ${response.status}`
    );
  }

  return response.json();
}