// ==========================================================
// MarketPulse - NSE Dividend Tracker
// Announcement Service
// ==========================================================

const JSON_FILE = "/corporate-actions.json";


// ==========================================================
// Get Announcements
// ==========================================================

export async function getAnnouncements() {

    // Add timestamp to ensure the latest JSON is requested
    const url = `${JSON_FILE}?t=${Date.now()}`;

    const response = await fetch(url, {
        cache: "no-store"
    });

    if (!response.ok) {

        throw new Error(
            "Unable to load corporate-actions.json"
        );

    }

    const json = await response.json();

    console.log("MarketPulse JSON:", json);

    return {

        rows: Array.isArray(json.data)
            ? json.data
            : [],

        lastUpdated: json.lastUpdated || "",

        recordCount: json.recordCount || 0,

        equityCount: json.equityCount || 0,

        smeCount: json.smeCount || 0,

        source: json.source || "NSE"

    };

}


// ==========================================================
// Summary
// ==========================================================

export function getSummary(rows) {

    return {

        total: rows.length,

        dividend: rows.filter(row =>
            (row.subject || "")
                .toLowerCase()
                .includes("dividend")
        ).length,

        bonus: rows.filter(row =>
            (row.subject || "")
                .toLowerCase()
                .includes("bonus")
        ).length,

        split: rows.filter(row =>
            (row.subject || "")
                .toLowerCase()
                .includes("split")
        ).length,

        boardMeeting: rows.filter(row =>
            (row.subject || "")
                .toLowerCase()
                .includes("board")
        ).length

    };

}