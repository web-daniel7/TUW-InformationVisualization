/**
 * Global State Management
 * Tracks the current selection and loaded data to coordinate views.
 */
let appState = {
    selectedCountry: null, // ISO code of the selected country
    activeVariable: "2t",
    fullCountryData: []
};

/**
 * Mapping of variable keys to their specific Global CSV file paths.
 */
const variableFiles = {
    "2t": "data/global/country_avg_2t.csv",
    "tp": "data/global/country_avg_tp.csv",
    "10si": "data/global/country_avg_10si.csv",
    "2d": "data/global/country_avg_2d.csv",
    "swvl1": "data/global/country_avg_swvl1.csv",
    "sde": "data/global/country_avg_sde.csv",
    "sf": "data/global/country_avg_sf.csv",
    "skt": "data/global/country_avg_skt.csv",
    "ssr": "data/global/country_avg_ssr.csv",
    "slhf": "data/global/country_avg_slhf.csv",
    "sshf": "data/global/country_avg_sshf.csv"
};

/**
 * Human-readable labels for the climate variables.
 */
const climateVars = {
    "2t": "Temperature (2m)",
    "tp": "Total Precipitation",
    "10si": "Wind Speed",
    "2d": "Dewpoint Temp",
    "swvl1": "Soil Water",
    "sde": "Snow Depth",
    "sf": "Snowfall",
    "skt": "Skin Temp",
    "ssr": "Solar Radiation",
    "slhf": "Latent Heat Flux",
    "sshf": "Sensible Heat Flux"
};

// Global chart instances
let map, pcPlot, historyChart;

/**
 * Generates the radio button filter panel for variable selection.
 * Clears existing filters and creates new ones based on `climateVars`.
 */
function createFilterPanel() {
    const container = d3.select("#variable-checkboxes");
    container.html("");
    Object.entries(climateVars).forEach(([key, label]) => {
        const div = container.append("div").attr("class", "filter-item");
        div.append("input")
            .attr("type", "radio")
            .attr("name", "climate-variable")
            .attr("id", "chk-" + key)
            .attr("value", key)
            .property("checked", key === "2t") // Default to Temperature
            .on("change", function() {
                updateMapVariable(key);
            });
        div.append("label").attr("for", "chk-" + key).text(" " + label);
    });
}

/**
 * Switches the active climate variable.
 * 1. Updates the UI label.
 * 2. Loads the new Global CSV for the world map.
 * 3. If a country is selected, updates the detailed views (Gradient Map & History Chart).
 * @param {String} variableKey - The key of the variable to switch to (e.g., '2t').
 */
function updateMapVariable(variableKey) {
    const filePath = variableFiles[variableKey];
    console.log(`Switching Variable to: ${variableKey} (${filePath})`);
    d3.select("#current-var-display").text(climateVars[variableKey]);
    d3.csv(filePath).then(data => {
        appState.activeVariable = variableKey;

        // 1. Update Global World Map Colors
        if (map) {
            map.avgData = data;
            map.renderWorld();
        }

        // 2. If zoomed in, update the detailed views with the new variable
        if (appState.selectedCountry && appState.fullCountryData.length > 0) {
            if (map) map.renderDetailedGrid(appState.fullCountryData, appState.activeVariable);
            if (historyChart) historyChart.update(appState.fullCountryData, appState.activeVariable);
        }

    }).catch(err => console.error("Could not load file:", filePath));
}

// --- Initialization Block ---

Promise.all([
    // Load GeoJSON for map shapes and the default CSV data
    d3.json("https://raw.githubusercontent.com/holtzy/D3-graph-gallery/master/DATA/world.geojson"),
    d3.csv(variableFiles["2t"])
]).then(([geoData, avgData]) => {

    // 1. Initialize Components
    map = new WorldMap("#map-container", geoData, avgData);
    createFilterPanel();
    if (typeof ParallelCoordinates !== 'undefined') {
        pcPlot = new ParallelCoordinates("#pc-container");
    } else {
        console.warn("ParallelCoordinates class not found.");
    }
    if (typeof HistoryChart !== 'undefined') {
        historyChart = new HistoryChart("#line-container");
    } else {
        console.warn("HistoryChart class not found.");
    }

    // 2. Setup Event Listener: Country Selected (Zoom In)
    window.addEventListener('countrySelected', (e) => {
        appState.selectedCountry = e.detail;
        console.log("Country selected:", appState.selectedCountry);
        d3.select("#pc-container").style("display", "block");
        d3.select("#line-container").style("display", "block");
        const csvPath = `data/countries/era5_monthly_${appState.selectedCountry}.csv`;
        d3.csv(csvPath).then(data => {
            appState.fullCountryData = data;
            // Update Map (Switch to detailed gradient view)
            if (map) map.renderDetailedGrid(data, appState.activeVariable);
            // Update Parallel Coordinates (Show multivariate data)
            if (pcPlot) pcPlot.update(data);
            // Update History Chart (Show trend for active variable)
            if (historyChart) historyChart.update(data, appState.activeVariable);
        }).catch(err => {
            console.error(`Could not load data for ${appState.selectedCountry}`, err);
        });
    });

    // 3. Setup Event Listener: Date Changed (Linking History -> Map/PC)
    window.addEventListener('dateChanged', (e) => {
        const { year, month } = e.detail;
        console.log(`Filtering views for Year: ${year}, Month: ${month}`);

        if (appState.fullCountryData.length > 0) {
            // Filter data for that specific time
            const filteredData = appState.fullCountryData.filter(d =>
                +d.year === year && +d.month === month
            );
            // Update Map to show gradient ONLY for that month
            if (map) map.renderDetailedGrid(filteredData, appState.activeVariable);
            if (pcPlot) pcPlot.update(filteredData);
        }
    });

}).catch(err => console.error("Initialization error:", err));
