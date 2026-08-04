// ==========================================================
// MarketPulse - NSE Dividend Tracker
// Service Layer
// ==========================================================

const JSON_FILE = "/corporate-actions.json";

/**
 * Load Corporate Actions JSON
 */
export async function getAnnouncements() {

    try {

        const response = await fetch(JSON_FILE, {
            cache: "no-store"
        });

        if (!response.ok) {

            throw new Error(
                `Unable to load ${JSON_FILE} (${response.status})`
            );

        }

        const data = await response.json();

        return data;

    }
    catch (error) {

        console.error("Error loading Corporate Actions");

        console.error(error);

        throw error;

    }

}

/**
 * Dashboard Statistics
 */
export function getSummary(rows) {

    if (!rows || rows.length === 0) {

        return {

            total: 0,
            dividend: 0,
            bonus: 0,
            split: 0,
            boardMeeting: 0

        };

    }

    const dividend = rows.filter(r =>
        r.subject?.toLowerCase().includes("dividend")
    ).length;

    const bonus = rows.filter(r =>
        r.subject?.toLowerCase().includes("bonus")
    ).length;

    const split = rows.filter(r =>
        r.subject?.toLowerCase().includes("split")
    ).length;

    const boardMeeting = rows.filter(r =>
        r.subject?.toLowerCase().includes("board")
    ).length;

    return {

        total: rows.length,

        dividend,

        bonus,

        split,

        boardMeeting

    };

}