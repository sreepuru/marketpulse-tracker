import { useEffect, useState } from "react";

import {
    getAnnouncements,
    getSummary
} from "../services/announcementService";

export function useAnnouncements() {

    const [rows, setRows] = useState([]);

    const [summary, setSummary] = useState({

        total: 0,
        dividend: 0,
        bonus: 0,
        split: 0,
        boardMeeting: 0

    });

    const [loading, setLoading] = useState(true);

    const [error, setError] = useState("");

    async function loadData() {

        try {

            setLoading(true);

            const data = await getAnnouncements();

            setRows(data);

            setSummary(getSummary(data));

            setError("");

        }
        catch (err) {

            console.error(err);

            setError(err.message);

        }
        finally {

            setLoading(false);

        }

    }

    function reload() {

        loadData();

    }

    useEffect(() => {

        loadData();

        // Auto Refresh every 60 Seconds
        const interval = setInterval(() => {

            loadData();

        }, 60000);

        return () => clearInterval(interval);

    }, []);

    return {

        rows,

        summary,

        loading,

        error,

        reload

    };

}