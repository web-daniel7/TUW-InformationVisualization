/**
 * A class to render a temporal line chart visualizing the trend of a selected climate variable.
 * It aggregates spatial grid data into monthly averages and handles user interactions.
 */
class HistoryChart {
    /**
     * Initializes the History Chart instance.
     * Sets up the SVG structure, margins, axes groups, and initial scales.
     * @param {String} containerId - The CSS selector (e.g., "#line-container") of the HTML element to render the chart in.
     */
    constructor(containerId) {
        this.container = d3.select(containerId);
        this.margin = { top: 20, right: 30, bottom: 40, left: 60 };
        this.svg = this.container.append("svg")
            .attr("width", "100%")
            .attr("height", 250) // Fixed height
            .style("overflow", "visible");
        this.g = this.svg.append("g")
            .attr("transform", `translate(${this.margin.left},${this.margin.top})`);
        this.xAxisGroup = this.g.append("g");
        this.yAxisGroup = this.g.append("g");
        this.path = this.g.append("path")
            .attr("fill", "none")
            .attr("stroke", "steelblue")
            .attr("stroke-width", 2);
        this.x = d3.scaleTime();
        this.y = d3.scaleLinear();
    }

    /**
     * Updates the chart with new data and a selected variable.
     * Aggregates spatial data (lat/lon grid points) into a single monthly average,
     * updates scales/axes, and manages interactive elements (hover/click).
     * @param {Array} data - The raw data array from the country-specific CSV (era5_monthly_XXX.csv).
     * @param {String} [variable="2t"] - The specific climate variable key to visualize (e.g., '2t', 'tp').
     */
    update(data, variable = "2t") {
        if (!data || data.length === 0) return;

        // 1. Calculate Width Dynamically
        const containerRect = this.container.node().getBoundingClientRect();
        const width = containerRect.width - this.margin.left - this.margin.right;
        const height = 250 - this.margin.top - this.margin.bottom;
        const safeWidth = width > 0 ? width : 600;

        // 2. Pre-process Data (Average Lat/Lon per Month)
        const nestedData = d3.groups(data, d => `${d.year}-${d.month}`);
        const processedData = nestedData.map(([key, values]) => {
            const [year, month] = key.split("-");
            return {
                date: new Date(year, month - 1),
                value: d3.mean(values, v => +v[variable])
            };
        }).sort((a, b) => a.date - b.date);

        // 3. Update Scales
        this.x.domain(d3.extent(processedData, d => d.date)).range([0, safeWidth]);
        const [min, max] = d3.extent(processedData, d => d.value);
        this.y.domain([min * 0.99, max * 1.01]).range([height, 0]);

        // 4. Draw Axes
        this.xAxisGroup.attr("transform", `translate(0,${height})`)
            .call(d3.axisBottom(this.x).ticks(5));
        this.yAxisGroup.transition().duration(500)
            .call(d3.axisLeft(this.y));

        // 5. Draw Line
        const lineGenerator = d3.line()
            .x(d => this.x(d.date))
            .y(d => this.y(d.value));
        this.path.datum(processedData)
            .transition().duration(500)
            .attr("d", lineGenerator);

        // 6. Interaction Points (Dots)
        const dots = this.g.selectAll(".dot")
            .data(processedData);
        dots.exit().remove();
        dots.enter().append("circle")
            .attr("class", "dot")
            .merge(dots)
            .attr("cx", d => this.x(d.date))
            .attr("cy", d => this.y(d.value))
            .attr("r", 5)
            .attr("fill", "steelblue")
            .attr("opacity", 0) // Invisible until hover
            .on("mouseover", function(event, d) {
                d3.select(this).attr("opacity", 1).attr("fill", "orange");
            })
            .on("mouseout", function() {
                d3.select(this).attr("opacity", 0);
            })
            .on("click", (event, d) => {
                const dateEvent = new CustomEvent("dateChanged", {
                    detail: { year: d.date.getFullYear(), month: d.date.getMonth() + 1 }
                });
                window.dispatchEvent(dateEvent);
                this.g.selectAll(".dot").attr("opacity", 0);
                d3.select(event.currentTarget).attr("opacity", 1).attr("fill", "red");
            });
    }
}