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

    const [lastUpdated, setLastUpdated] = useState("");

    const [recordCount, setRecordCount] = useState(0);

    const [equityCount, setEquityCount] = useState(0);

    const [smeCount, setSmeCount] = useState(0);

    const [source, setSource] = useState("");

    const [loading, setLoading] = useState(true);

    const [error, setError] = useState("");


    async function loadData() {

        try {

            setLoading(true);

            const result = await getAnnouncements();

            console.log("MarketPulse Result:", result);

            setRows(result.rows);

            setSummary(
                getSummary(result.rows)
            );

            setLastUpdated(
                result.lastUpdated
            );

            setRecordCount(
                result.recordCount
            );

            setEquityCount(
                result.equityCount
            );

            setSmeCount(
                result.smeCount
            );

            setSource(
                result.source
            );

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

    }, []);


    return {

        rows,

        summary,

        lastUpdated,

        recordCount,

        equityCount,

        smeCount,

        source,

        loading,

        error,

        reload

    };

}