/**
 * A class to render a Parallel Coordinates plot for multivariate data visualization.
 * It visualizes relationships between multiple climate variables and supports interactive axis brushing for filtering.
 */
class ParallelCoordinates {
    /**
     * Initializes the Parallel Coordinates chart.
     * Sets up the SVG container, groups for lines and axes, and basic scaling logic.
     * @param {String} containerId - The CSS selector (e.g., "#pc-container") of the HTML element to render the chart in.
     */
    constructor(containerId) {
        this.container = d3.select(containerId);
        this.margin = { top: 30, right: 10, bottom: 10, left: 0 };
        this.svg = this.container.append("svg")
            .attr("width", "100%")
            .attr("height", 400)
            .style("overflow", "visible"); // Allow labels to show outside
        this.g = this.svg.append("g")
            .attr("transform", `translate(${this.margin.left},${this.margin.top})`);

        this.pathGroup = this.g.append("g").attr("class", "paths");
        this.axisGroup = this.g.append("g").attr("class", "axes");

        this.yScales = {};
        this.xScale = d3.scalePoint().padding(0.5);

        this.metaKeys = ["year", "month", "lat", "lon", "country_code"];
    }

    /**
     * Updates the chart with new data.
     * Dynamically calculates width, determines dimensions, draws polylines, and enables brushing.
     * @param {Array<Object>} data - Array of data objects (e.g., rows from the CSV) containing climate variables.
     */
    update(data) {
        if (!data || data.length === 0) return;

        // 1. Calculate Dimensions Dynamically
        const containerRect = this.container.node().getBoundingClientRect();
        this.width = containerRect.width - this.margin.left - this.margin.right;

        // Determine which variables to show (filter out year, lat, lon)
        const keys = Object.keys(data[0]);
        this.dimensions = keys.filter(d => !this.metaKeys.includes(d));

        // 2. Update Scales
        this.xScale.domain(this.dimensions).range([0, this.width]);
        this.dimensions.forEach(dim => {
            this.yScales[dim] = d3.scaleLinear()
                .domain(d3.extent(data, d => +d[dim]))
                .range([360, 0]); // Height - margins
        });

        // 3. Draw Lines
        const lineGenerator = d3.line();
        const path = d => lineGenerator(this.dimensions.map(p =>
            [this.xScale(p), this.yScales[p](d[p])]
        ));

        // JOIN pattern for lines
        this.pathGroup.selectAll("path")
            .data(data)
            .join("path")
            .attr("d", path)
            .style("fill", "none")
            .style("stroke", "#4682B4") // Steelblue
            .style("stroke-width", 1)
            .style("opacity", 0.15); // Low opacity to see density

        // 4. Draw Axes
        this.axisGroup.selectAll(".dimension").remove(); // Clear old axes
        const axes = this.axisGroup.selectAll(".dimension")
            .data(this.dimensions)
            .enter().append("g")
            .attr("class", "dimension")
            .attr("transform", d => `translate(${this.xScale(d)})`);
        axes.each(function(d) {
             d3.select(this).call(d3.axisLeft(d3.scaleLinear()
                .domain(d3.extent(data, row => +row[d]))
                .range([360, 0])
             ));
        });
        axes.append("text")
            .style("text-anchor", "middle")
            .attr("y", -10)
            .text(d => d)
            .style("fill", "black")
            .style("font-size", "10px")
            .style("font-weight", "bold");

        // 5. Add Brushing
        const yScales = this.yScales; // Capture for closure
        const pathGroup = this.pathGroup; // Capture for closure
        axes.append("g")
            .attr("class", "brush")
            .each(function(d) {
                d3.select(this).call(
                    d3.brushY()
                        .extent([[-10, 0], [10, 360]])
                        .on("brush end", function(event) {
                            // Brushing Logic
                            const selection = event.selection;
                            if (!selection) {
                                // Reset if cleared
                                pathGroup.selectAll("path").style("display", null);
                                return;
                            }
                            const [y1, y0] = selection.map(yScales[d].invert);
                            // Filter Lines
                            pathGroup.selectAll("path")
                                .style("display", row => {
                                    const val = +row[d];
                                    return (val <= y1 && val >= y0) ? null : "none";
                                });
                        })
                );
            });
    }
}