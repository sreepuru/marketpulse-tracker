function SearchBar({ searchText, setSearchText, reload }) {

    return (

        <div className="search-container">

            <input
                className="search-input"
                type="text"
                placeholder="Search by Symbol, Company or Subject..."
                value={searchText}
                onChange={(e) => setSearchText(e.target.value)}
            />

            <button
                className="refresh-button"
                onClick={reload}
            >
                🔄 Refresh
            </button>

        </div>

    );

}

export default SearchBar;