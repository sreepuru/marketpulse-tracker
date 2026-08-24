// ==========================================================
// MarketPulse - NSE Corporate Actions
// Announcement Service
// ==========================================================

import { API_BASE_URL } from "../config";


// ==========================================================
// Get Announcements
// ==========================================================

export async function getAnnouncements() {

    const response = await fetch(
        `${API_BASE_URL}/api/corporate-actions`,
        {
            cache: "no-store"
        }
    );

    if (!response.ok) {

        throw new Error(
            `Unable to load corporate actions: ${response.status}`
        );

    }

    const json = await response.json();

    console.log(
        "MarketPulse Corporate Actions API:",
        json
    );

    /*
     * API returns an array of corporate-action records.
     *
     * Keep the service response compatible with the
     * existing frontend structure.
     */

    const rows = Array.isArray(json)
        ? json
        : Array.isArray(json.data)
            ? json.data
            : [];

    return {

        rows,

        lastUpdated:
            rows.length > 0
                ? (
                    rows
                        .map(row =>
                            row.updated_at ||
                            row.record_received_date ||
                            row.created_at
                        )
                        .filter(Boolean)
                        .sort()
                        .at(-1) || ""
                )
                : "",

        recordCount: rows.length,

        source: "NSE"

    };

}


// ==========================================================
// Summary
// ==========================================================

export function getSummary(rows) {

    return {

        total: rows.length,

        dividend: rows.filter(row =>
            String(row.action_type || "")
                .toUpperCase() === "DIVIDEND"
        ).length,

        bonus: rows.filter(row =>
            String(row.action_type || "")
                .toUpperCase() === "BONUS"
        ).length,

        rights: rows.filter(row =>
            String(row.action_type || "")
                .toUpperCase() === "RIGHTS"
        ).length,

        buyback: rows.filter(row =>
            String(row.action_type || "")
                .toUpperCase() === "BUYBACK"
        ).length,

        boardMeeting: rows.filter(row =>
            String(row.action_type || "")
                .toUpperCase() === "BOARD_MEETING"
        ).length

    };

}