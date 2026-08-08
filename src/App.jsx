import "./App.css";
import { useState } from "react";

import Header from "./components/Header";
import SummaryCards from "./components/SummaryCards";
import SearchBar from "./components/SearchBar";
import AnnouncementTable from "./components/AnnouncementTable";
import Footer from "./components/Footer";

import { useAnnouncements } from "./hooks/useAnnouncements";


function App() {

    const {

        rows,

        summary,

        lastUpdated,

        equityCount,

        smeCount,

        loading,

        error,

        reload

    } = useAnnouncements();


    const [searchText, setSearchText] = useState("");


    return (

        <div className="app">

            <Header />

            <main className="dashboard">

                <SummaryCards

                    summary={summary}

                    equityCount={equityCount}

                    smeCount={smeCount}

                    lastUpdated={lastUpdated}

                />


                <SearchBar

                    searchText={searchText}

                    setSearchText={setSearchText}

                    reload={reload}

                />


                <AnnouncementTable

                    rows={rows}

                    loading={loading}

                    error={error}

                    searchText={searchText}

                />

            </main>

            <Footer />

        </div>

    );

}


export default App;