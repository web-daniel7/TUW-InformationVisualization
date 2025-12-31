/**
 * A class to render an interactive Choropleth World Map using D3.js.
 * It supports global data visualization, semantic zooming into specific countries,
 * and rendering detailed grid-based climate gradients upon interaction.
 */
class WorldMap {

    /**
     * Initializes the World Map instance.
     * Sets up dimensions, stores initial data, and prepares the D3 container.
     * @param {String} containerId - The CSS selector (e.g., "#map-container") for the SVG parent.
     * @param {Object} geoData - The GeoJSON or TopoJSON object containing world country features.
     * @param {Array} initialAvgData - The array of global average data (country_avg_XXX.csv) for the initial coloring.
     */
    constructor(containerId, geoData, initialAvgData) {
        this.container = d3.select(containerId);
        this.geoData = geoData;
        this.avgData = initialAvgData;
        this.width = this.container.node().getBoundingClientRect().width;
        this.height = 600;
        this.selectedCountry = null;
        this.init();
    }

    /**
     * Sets up the SVG, Map Projection, Color Scales, and Zoom behaviors.
     * Called automatically by the constructor.
     */
    init() {
        this.svg = this.container.append("svg")
            .attr("width", "100%")
            .attr("height", this.height)
            .attr("viewBox", `0 0 ${this.width} ${this.height}`);
        this.g = this.svg.append("g");

        // 1. Define Projection
        this.projection = d3.geoNaturalEarth1()
            .scale(this.width / 1.5 / Math.PI)
            .translate([this.width / 2, this.height / 2]);
        this.path = d3.geoPath().projection(this.projection);

        // 2. Setup Color Scale
        this.colorScale = d3.scaleSequential(d3.interpolateRdYlBu)
            .domain([310, 240]); //Kelvin/Temp

        // 3. Setup Tooltip
        this.tooltip = d3.select("body").append("div")
            .attr("class", "tooltip")
            .style("opacity", 0);

        // 4. Zoom
        this.zoom = d3.zoom()
            .scaleExtent([1, 8])
            .on("zoom", (event) => this.g.attr("transform", event.transform));
        this.renderWorld();
    }

    /**
     * Displays a tooltip with the country name and its value.
     * @param {Object} event - The DOM MouseEvent.
     * @param {Object} d - The data bound to the hovered element (GeoJSON feature).
     */
    showTooltip(event, d) {
        const record = this.avgData.find(r => r.country_code === d.id);
        const val = record ? +record.value : null;
        const displayVal = val !== null ? val.toFixed(2) : 'N/A';
        this.tooltip.transition().duration(200).style("opacity", .9);
        this.tooltip.html(`<strong>${d.properties.name}</strong><br/>Avg: ${displayVal}`)
            .style("left", (event.pageX + 10) + "px")
            .style("top", (event.pageY - 28) + "px");
    }

    /**
     * Hides the tooltip when the mouse leaves a country.
     */
    hideTooltip() {
        this.tooltip.transition().duration(500).style("opacity", 0);
    }

    /**
     * Renders or updates the Choropleth map.
     * Recalculates the color domain based on the current `avgData` and uses the
     * D3 join pattern to update fill colors dynamically.
     */
    renderWorld() {
        // 1. Update scale domain
        const values = this.avgData.map(d => +d.value);
        const minVal = d3.min(values);
        const maxVal = d3.max(values);
        // Update the colors stretch
        this.colorScale.domain([minVal, maxVal]);
        console.log(`Map Color Domain Updated: ${minVal} to ${maxVal}`);

        // 2. Bind data
        const countries = this.g.selectAll(".country")
            .data(this.geoData.features);

        // 3. Draw/ update parth
        countries.join(
            // ENTER: Create new paths for countries (runs only once usually)
            enter => enter.append("path")
                .attr("class", "country")
                .attr("d", this.path)
                .attr("stroke", "#fff")
                .attr("stroke-width", 0.5)
                .on("mouseover", (event, d) => this.showTooltip(event, d))
                .on("mouseout", () => this.hideTooltip())
                .on("click", (event, d) => this.clicked(event, d)),
            update => update
        )
        .transition().duration(750) //Animation
        .attr("fill", d => {
            const record = this.avgData.find(r => r.country_code === d.id);
            return record ? this.colorScale(+record.value) : "#ccc";
        });
    }

    /**
     * Handles the click event on a country.
     * Zooms into the selected country and dispatches a 'countrySelected' event.
     * If the same country is clicked again, it resets the view.
     * @param {Object} event - The DOM MouseEvent.
     * @param {Object} d - The GeoJSON feature of the clicked country.
     */
    clicked(event, d) {
        if (this.selectedCountry === d) return this.reset();
        this.selectedCountry = d;
        const [[x0, y0], [x1, y1]] = this.path.bounds(d);
        event.stopPropagation();
        this.svg.transition().duration(750).call(
            this.zoom.transform,
            d3.zoomIdentity
                .translate(this.width / 2, this.height / 2)
                .scale(Math.min(8, 0.9 / Math.max((x1 - x0) / this.width, (y1 - y0) / this.height)))
                .translate(-(x0 + x1) / 2, -(y0 + y1) / 2)
        );
        // Notify main controller to load detailed CSV (era5_monthly_XXX.csv)
        const countryEvent = new CustomEvent("countrySelected", { detail: d.id });
        window.dispatchEvent(countryEvent);
    }

    /**
     * Resets the map zoom to the global view and clears the selection.
     */
    reset() {
        this.selectedCountry = null;
        this.svg.transition().duration(750).call(
            this.zoom.transform,
            d3.zoomIdentity
        );
    }

/**
     * Renders the local climate gradient (grid points) for the selected country.
     * @param {Array} detailData - The rows from the specific country CSV (era5_monthly_XXX.csv).
     * @param {String} [variable='2t'] - The variable key to visualize (e.g., '2t', 'tp').
     */
    renderDetailedGrid(detailData, variable = '2t') {
        // 1. Clear previous detail layers
        this.g.selectAll(".grid-cell").remove();
        if (!detailData || detailData.length === 0) return;

        // 2. Setup a local color scale for this specific country's range
        const extent = d3.extent(detailData, d => +d[variable]);
        const localColorScale = d3.scaleSequential(d3.interpolateViridis)
            .domain(extent);

        // 3. Draw the "Gradient" using small rectangles (Grid cells)
        const cellSize = 4;
        this.g.selectAll(".grid-cell")
            .data(detailData)
            .enter()
            .append("rect")
            .attr("class", "grid-cell")
            // Use projection to convert lat/lon to X/Y
            .attr("x", d => this.projection([+d.lon, +d.lat])[0] - cellSize/2)
            .attr("y", d => this.projection([+d.lon, +d.lat])[1] - cellSize/2)
            .attr("width", cellSize)
            .attr("height", cellSize)
            .attr("fill", d => localColorScale(+d[variable]))
            .attr("opacity", 0) // Start invisible for transition
            .transition()
            .duration(1000)
            .attr("opacity", 0.8);

        // 4. Add a specific tooltip for the grid points
        this.g.selectAll(".grid-cell")
            .on("mouseover", (event, d) => {
                this.tooltip.transition().duration(100).style("opacity", .9);
                this.tooltip.html(`
                    <strong>Location:</strong> ${d.lat}, ${d.lon}<br/>
                    <strong>${variable}:</strong> ${(+d[variable]).toFixed(2)}<br/>
                    <strong>Date:</strong> ${d.year}-${d.month}
                `)
                .style("left", (event.pageX + 10) + "px")
                .style("top", (event.pageY - 28) + "px");
            })
            .on("mouseout", () => {
                this.tooltip.transition().duration(500).style("opacity", 0);
            });
    }
}