import { useMemo, useState } from "react";

function AnnouncementTable({

    rows,
    loading,
    error,
    searchText

}) {

    const [sortField, setSortField] = useState("exDate");

    const [sortDirection, setSortDirection] = useState("asc");

    function handleSort(field) {

        if (sortField === field) {

            setSortDirection(prev =>
                prev === "asc" ? "desc" : "asc"
            );

        } else {

            setSortField(field);

            setSortDirection("asc");

        }

    }

    const filteredRows = useMemo(() => {

        let data = [...rows];

        // Search
        if (searchText) {

            const keyword = searchText.toLowerCase();

            data = data.filter(item =>

                (item.symbol || "")
                    .toLowerCase()
                    .includes(keyword)

                ||

                (item.comp || "")
                    .toLowerCase()
                    .includes(keyword)

                ||

                (item.subject || "")
                    .toLowerCase()
                    .includes(keyword)

            );

        }

        // Sorting
        data.sort((a, b) => {

            const valueA = (a[sortField] || "").toString();

            const valueB = (b[sortField] || "").toString();

            if (sortDirection === "asc") {

                return valueA.localeCompare(valueB);

            }

            return valueB.localeCompare(valueA);

        });

        return data;

    }, [rows, searchText, sortField, sortDirection]);

    if (loading) {

        return (

            <div className="table-container">

                <h2 style={{ padding: "30px" }}>

                    Loading Corporate Actions...

                </h2>

            </div>

        );

    }

    if (error) {

        return (

            <div className="table-container">

                <h2 style={{ padding: "30px", color: "red" }}>

                    {error}

                </h2>

            </div>

        );

    }

    return (

        <>

            <div className="table-info">

                Showing

                <strong>

                    {" "}

                    {filteredRows.length}

                    {" "}

                </strong>

                Records

            </div>

            <div className="table-container">

                <table>

                    <thead>

                        <tr>

                            <th onClick={() => handleSort("symbol")}>

                                Symbol ▲▼

                            </th>

                            <th onClick={() => handleSort("comp")}>

                                Company ▲▼

                            </th>

                            <th>

                                Subject

                            </th>

                            <th onClick={() => handleSort("exDate")}>

                                Ex Date ▲▼

                            </th>

                            <th onClick={() => handleSort("recDate")}>

                                Record Date ▲▼

                            </th>

                            <th>

                                Face Value

                            </th>

                            <th>

                                Series

                            </th>

                        </tr>

                    </thead>

                    <tbody>

                        {

                            filteredRows.length === 0 ?

                                (

                                    <tr>

                                        <td

                                            colSpan="7"

                                            className="no-data"

                                        >

                                            No Records Found

                                        </td>

                                    </tr>

                                )

                                :

                                (

                                    filteredRows.map((item, index) => (

                                        <tr key={index}>

                                            <td>

                                                <strong>

                                                    {item.symbol}

                                                </strong>

                                            </td>

                                            <td>

                                                {item.comp}

                                            </td>

                                            <td>

                                                <span
                                                    className={

                                                        item.subject?.toLowerCase().includes("dividend")

                                                            ? "badge dividend"

                                                            : item.subject?.toLowerCase().includes("bonus")

                                                                ? "badge bonus"

                                                                : "badge default"

                                                    }
                                                >

                                                    {item.subject}

                                                </span>

                                            </td>

                                            <td>

                                                {item.exDate || "-"}

                                            </td>

                                            <td>

                                                {item.recDate || "-"}

                                            </td>

                                            <td>

                                                {item.faceVal || "-"}

                                            </td>

                                            <td>

                                                {item.series || "-"}

                                            </td>

                                        </tr>

                                    ))

                                )

                        }

                    </tbody>

                </table>

            </div>

        </>

    );

}

export default AnnouncementTable;