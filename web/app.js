"use strict";

const DISPATCH_ENDPOINT = "/api/v1/dispatch";
const REQUEST_TIMEOUT_MS = 180_000;
const SVG_NS = "http://www.w3.org/2000/svg";
const MAX_SCENARIO_BYTES = 1_000_000;
const MAX_TIME_SERIES_BYTES = 25_000_000;
const MAX_TABLE_ROWS = 1_000;

const CHART = Object.freeze({
  width: 960,
  height: 380,
  top: 18,
  right: 76,
  bottom: 54,
  left: 76,
});

const DASH_PATTERNS = Object.freeze({
  solid: "",
  dash: "10 6",
  dot: "2 5",
  dashdot: "12 5 2 5",
});

const state = { busy: false };

const elements = {
  form: document.querySelector("#dispatch-form"),
  scenarioInput: document.querySelector("#scenario-input"),
  timeSeriesInput: document.querySelector("#time-series-input"),
  runButton: document.querySelector("#run-button"),
  statusPanel: document.querySelector("#status-panel"),
  statusSymbol: document.querySelector("#status-symbol"),
  statusTitle: document.querySelector("#status-title"),
  statusDetail: document.querySelector("#status-detail"),
  emptyState: document.querySelector("#empty-state"),
  results: document.querySelector("#results"),
  resultsTitle: document.querySelector("#results-title"),
  resultSummary: document.querySelector("#result-summary"),
  metricNpv: document.querySelector("#metric-npv"),
  metricIrr: document.querySelector("#metric-irr"),
  metricSimplePayback: document.querySelector("#metric-simple-payback"),
  metricDiscountedPayback: document.querySelector("#metric-discounted-payback"),
  metricLcos: document.querySelector("#metric-lcos"),
  metricCurtailment: document.querySelector("#metric-curtailment"),
  metricCycles: document.querySelector("#metric-cycles"),
  metricEolCard: document.querySelector("#metric-eol-card"),
  metricEolCapacity: document.querySelector("#metric-eol-capacity"),
  limitationsList: document.querySelector("#limitations-list"),
};

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function asFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatDecimal(value, maximumFractionDigits = 2) {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits,
    minimumFractionDigits: 0,
  }).format(value);
}

function formatEur(value) {
  return value === null ? "—" : `${formatDecimal(value, 0)} EUR`;
}

function formatPercentFromFraction(value) {
  return value === null ? "—" : `${formatDecimal(value * 100, 2)}%`;
}

function formatYears(value) {
  return value === null ? "—" : `${formatDecimal(value, 1)} years`;
}

function setStatus(kind, title, detail) {
  const kinds = {
    loading: { className: "status-loading", symbol: "…" },
    success: { className: "status-success", symbol: "✓" },
    warning: { className: "status-warning", symbol: "!" },
    error: { className: "status-error", symbol: "×" },
    idle: { className: "", symbol: "—" },
  };
  const selected = kinds[kind] || kinds.idle;
  elements.statusPanel.className = `status-panel ${selected.className}`.trim();
  elements.statusSymbol.textContent = selected.symbol;
  elements.statusTitle.textContent = title;
  elements.statusDetail.textContent = detail;
}

function setBusy(busy) {
  state.busy = busy;
  updateRunButton();
  elements.runButton.setAttribute("aria-busy", String(busy));
}

function selectedFiles() {
  return {
    scenario: elements.scenarioInput.files[0] || null,
    timeSeries: elements.timeSeriesInput.files[0] || null,
  };
}

function updateRunButton() {
  const files = selectedFiles();
  elements.runButton.disabled = state.busy || !files.scenario || !files.timeSeries;
}

function describeSelection() {
  const files = selectedFiles();
  if (!files.scenario || !files.timeSeries) {
    setStatus(
      "idle",
      "Waiting for input files",
      "Choose a scenario JSON and its time-series CSV to enable the run.",
    );
    return;
  }
  if (files.scenario.size > MAX_SCENARIO_BYTES) {
    setStatus(
      "warning",
      "Scenario file looks too large",
      `${files.scenario.name} is ${formatDecimal(files.scenario.size, 0)} bytes; the API rejects scenarios above ${formatDecimal(MAX_SCENARIO_BYTES, 0)} bytes.`,
    );
    return;
  }
  if (files.timeSeries.size > MAX_TIME_SERIES_BYTES) {
    setStatus(
      "warning",
      "Time-series file looks too large",
      `${files.timeSeries.name} is ${formatDecimal(files.timeSeries.size, 0)} bytes; the API rejects time series above ${formatDecimal(MAX_TIME_SERIES_BYTES, 0)} bytes.`,
    );
    return;
  }
  setStatus(
    "idle",
    "Ready to run",
    `${files.scenario.name} and ${files.timeSeries.name} will be posted to the dispatch API.`,
  );
}

function summarizeDetail(detail) {
  if (typeof detail === "string") {
    return detail.slice(0, 400);
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (!isRecord(item)) {
          return typeof item === "string" ? item : "";
        }
        const location = Array.isArray(item.loc) ? item.loc.join(".") : "";
        const message = typeof item.msg === "string" ? item.msg : "";
        return location ? `${location}: ${message}` : message;
      })
      .filter(Boolean);
    return messages.join("; ").slice(0, 400);
  }
  return "The API returned an error response.";
}

function failureTitle(status) {
  if (status === 400) {
    return "The uploaded files were rejected as defective";
  }
  if (status === 413) {
    return "An upload exceeds the size limit";
  }
  if (status === 422) {
    return "The files are readable but a value is invalid";
  }
  if (status >= 500) {
    return "The dispatch API failed";
  }
  return `The dispatch API answered with status ${status}`;
}

async function postDispatch(files) {
  const body = new FormData();
  body.append("scenario", files.scenario, files.scenario.name);
  body.append("time_series", files.timeSeries, files.timeSeries.name);

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(DISPATCH_ENDPOINT, {
      method: "POST",
      body,
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();
    if (!response.ok) {
      const detail = isRecord(payload) ? payload.detail : payload;
      throw new Error(`${failureTitle(response.status)}. ${summarizeDetail(detail)}`);
    }
    if (!isRecord(payload)) {
      throw new Error("The dispatch response was not a JSON object.");
    }
    return payload;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("The dispatch request timed out after 180 seconds.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function normalizeIntervals(payload) {
  const raw = payload.dispatch_intervals;
  if (!Array.isArray(raw) || raw.length === 0) {
    throw new Error(
      "The dispatch response did not include the dispatch_intervals series this page charts.",
    );
  }
  const numericKeys = [
    "interval_hours",
    "pv_power_kw",
    "market_price_eur_per_mwh",
    "pv_charge_kw",
    "grid_charge_kw",
    "battery_export_kw",
    "grid_export_kw",
    "curtailed_pv_kw",
    "soc_start_kwh",
    "soc_end_kwh",
  ];
  return raw.map((item, index) => {
    if (!isRecord(item)) {
      throw new Error(`Interval ${index + 1} in the dispatch response is not an object.`);
    }
    const interval = { timestamp: typeof item.timestamp === "string" ? item.timestamp : "" };
    for (const key of numericKeys) {
      const value = asFiniteNumber(item[key]);
      if (value === null) {
        throw new Error(`Interval ${index + 1} is missing a numeric ${key}.`);
      }
      interval[key] = value;
    }
    return interval;
  });
}

function renderMetrics(payload) {
  const financial = isRecord(payload.financial_summary) ? payload.financial_summary : {};
  const dispatch = isRecord(payload.dispatch_summary) ? payload.dispatch_summary : {};

  elements.metricNpv.textContent = formatEur(asFiniteNumber(financial.npv_eur));

  const irr = asFiniteNumber(financial.irr_fraction);
  elements.metricIrr.textContent = irr === null ? "Not defined" : formatPercentFromFraction(irr);

  const simplePayback = asFiniteNumber(financial.simple_payback_years);
  elements.metricSimplePayback.textContent =
    simplePayback === null ? "Not reached" : formatYears(simplePayback);

  const discountedPayback = asFiniteNumber(financial.discounted_payback_years);
  elements.metricDiscountedPayback.textContent =
    discountedPayback === null ? "Not reached" : formatYears(discountedPayback);

  const lcos = asFiniteNumber(financial.lcos_eur_per_mwh);
  elements.metricLcos.textContent =
    lcos === null ? "Not defined" : `${formatDecimal(lcos, 2)} EUR/MWh`;

  const curtailmentReduction = asFiniteNumber(dispatch.curtailment_reduction_fraction);
  elements.metricCurtailment.textContent =
    curtailmentReduction === null
      ? "No baseline curtailment"
      : formatPercentFromFraction(curtailmentReduction);

  const cycles = asFiniteNumber(dispatch.equivalent_full_cycles);
  elements.metricCycles.textContent =
    cycles === null ? "—" : `${formatDecimal(cycles, 2)} cycles`;

  // The capacity_fade block exists only when the scenario models multi-year fade.
  const fade = isRecord(financial.capacity_fade) ? financial.capacity_fade : null;
  const fractions =
    fade && Array.isArray(fade.capacity_fraction_by_year) ? fade.capacity_fraction_by_year : [];
  const endOfLife = fractions.length > 0 ? asFiniteNumber(fractions[fractions.length - 1]) : null;
  elements.metricEolCard.hidden = endOfLife === null;
  elements.metricEolCapacity.textContent =
    endOfLife === null ? "—" : formatPercentFromFraction(endOfLife);
}

function renderLimitations(payload) {
  const fallback = [
    "Results are scenario calculations, not a forecast or engineering certification.",
  ];
  const limitations = Array.isArray(payload.limitations)
    ? payload.limitations.filter((item) => typeof item === "string" && item.trim() !== "")
    : [];
  elements.limitationsList.replaceChildren();
  for (const text of limitations.length > 0 ? limitations : fallback) {
    const item = document.createElement("li");
    item.textContent = text;
    elements.limitationsList.append(item);
  }
}

function renderResultSummary(payload, intervals) {
  const name = typeof payload.scenario_name === "string" ? payload.scenario_name : "Scenario";
  const solver = isRecord(payload.solver) ? payload.solver : {};
  const phases = isRecord(solver.phases) ? solver.phases : {};
  const economic = isRecord(phases.economic) ? phases.economic : {};
  const status = typeof economic.status === "string" ? economic.status : "unknown";
  const intervalHours = intervals[0].interval_hours;
  elements.resultSummary.textContent =
    `${name} · ${intervals.length} intervals of ${formatDecimal(intervalHours, 2)} h · ` +
    `solver status: ${status}`;
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    element.setAttribute(key, String(value));
  }
  return element;
}

function svgText(x, y, text, className, anchor) {
  const element = svgElement("text", { x, y, class: className, "text-anchor": anchor });
  element.textContent = text;
  return element;
}

function niceStep(roughStep) {
  const power = Math.pow(10, Math.floor(Math.log10(roughStep)));
  const fraction = roughStep / power;
  let nice;
  if (fraction <= 1) {
    nice = 1;
  } else if (fraction <= 2) {
    nice = 2;
  } else if (fraction <= 2.5) {
    nice = 2.5;
  } else if (fraction <= 5) {
    nice = 5;
  } else {
    nice = 10;
  }
  return nice * power;
}

function verticalScale(dataMin, dataMax, tickTarget = 5) {
  let low = Math.min(0, dataMin);
  let high = Math.max(0, dataMax);
  if (low === high) {
    high = low + 1;
  }
  const step = niceStep((high - low) / tickTarget);
  low = Math.floor(low / step) * step;
  high = Math.ceil(high / step) * step;
  const ticks = [];
  for (let value = low; value <= high + step / 2; value += step) {
    ticks.push(Math.abs(value) < step / 1_000_000 ? 0 : value);
  }
  return { min: low, max: high, step, ticks };
}

function horizontalTicks(totalHours, tickTarget = 8) {
  const step = niceStep(totalHours / tickTarget);
  const ticks = [];
  for (let value = 0; value <= totalHours + step / 1_000_000; value += step) {
    ticks.push(value);
  }
  const last = ticks[ticks.length - 1];
  if (totalHours - last > step / 2) {
    ticks.push(totalHours);
  }
  return ticks;
}

function tickLabel(value, step) {
  return formatDecimal(value, step < 1 ? 2 : 0);
}

function round2(value) {
  return Math.round(value * 100) / 100;
}

function stepPath(values, intervalHours, xScale, yScale) {
  const parts = [];
  for (let index = 0; index < values.length; index += 1) {
    const x0 = round2(xScale(index * intervalHours));
    const x1 = round2(xScale((index + 1) * intervalHours));
    const y = round2(yScale(values[index]));
    parts.push(index === 0 ? `M${x0} ${y}` : `L${x0} ${y}`, `L${x1} ${y}`);
  }
  return parts.join(" ");
}

function linePath(points, xScale, yScale) {
  return points
    .map((point, index) => {
      const command = index === 0 ? "M" : "L";
      return `${command}${round2(xScale(point.hour))} ${round2(yScale(point.value))}`;
    })
    .join(" ");
}

function seriesExtent(series) {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  const values = series.kind === "line" ? series.points.map((point) => point.value) : series.values;
  for (const value of values) {
    min = Math.min(min, value);
    max = Math.max(max, value);
  }
  return { min, max };
}

function axisExtent(seriesList) {
  let min = 0;
  let max = 0;
  for (const series of seriesList) {
    const extent = seriesExtent(series);
    min = Math.min(min, extent.min);
    max = Math.max(max, extent.max);
  }
  return { min, max };
}

function seriesSummarySentence(series, intervalHours) {
  const values = series.tableValues;
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  let maxIndex = 0;
  values.forEach((value, index) => {
    min = Math.min(min, value);
    if (value > max) {
      max = value;
      maxIndex = index;
    }
  });
  let sentence =
    `${series.label} ranges ${formatDecimal(min, 2)} to ${formatDecimal(max, 2)} ${series.unit}`;
  if (max > min) {
    sentence += `, highest around hour ${formatDecimal(maxIndex * intervalHours, 1)}`;
  }
  return `${sentence}.`;
}

function renderLegend(container, seriesList) {
  container.replaceChildren();
  for (const series of seriesList) {
    const item = document.createElement("span");
    item.className = "legend-item";
    const sample = svgElement("svg", {
      width: 30,
      height: 12,
      viewBox: "0 0 30 12",
      "aria-hidden": "true",
    });
    const line = svgElement("line", {
      x1: 1,
      y1: 6,
      x2: 29,
      y2: 6,
      class: `chart-series ${series.cssClass}`,
    });
    if (DASH_PATTERNS[series.dash]) {
      line.setAttribute("stroke-dasharray", DASH_PATTERNS[series.dash]);
    }
    sample.append(line);
    item.append(sample, document.createTextNode(` ${series.label} (${series.unit})`));
    container.append(item);
  }
}

function renderDataTable(table, intervals, seriesList) {
  table.replaceChildren();
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const heading of ["Hour (h)", "Timestamp", ...seriesList.map(
    (series) => `${series.label} (${series.unit})`,
  )]) {
    const cell = document.createElement("th");
    cell.setAttribute("scope", "col");
    cell.textContent = heading;
    headRow.append(cell);
  }
  head.append(headRow);

  const body = document.createElement("tbody");
  const rowCount = Math.min(intervals.length, MAX_TABLE_ROWS);
  const intervalHours = intervals[0].interval_hours;
  for (let index = 0; index < rowCount; index += 1) {
    const row = document.createElement("tr");
    const hourCell = document.createElement("td");
    hourCell.textContent = formatDecimal(index * intervalHours, 2);
    const timeCell = document.createElement("td");
    timeCell.textContent = intervals[index].timestamp;
    row.append(hourCell, timeCell);
    for (const series of seriesList) {
      const cell = document.createElement("td");
      cell.textContent = formatDecimal(series.tableValues[index], 2);
      row.append(cell);
    }
    body.append(row);
  }
  if (intervals.length > rowCount) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.setAttribute("colspan", String(seriesList.length + 2));
    cell.textContent =
      `Showing the first ${formatDecimal(rowCount, 0)} of ` +
      `${formatDecimal(intervals.length, 0)} intervals.`;
    row.append(cell);
    body.append(row);
  }
  table.append(head, body);
}

function drawAxis(svg, config) {
  const { xTicks, xStep, left, right, plotTop, plotBottom, xScale } = config;

  for (const axis of config.axes) {
    if (!axis) {
      continue;
    }
    for (const tick of axis.scale.ticks) {
      const y = round2(axis.yScale(tick));
      if (axis.side === "left") {
        svg.append(
          svgElement("line", {
            x1: left,
            y1: y,
            x2: right,
            y2: y,
            class: tick === 0 && axis.scale.min < 0 ? "chart-zero-line" : "chart-grid-line",
          }),
        );
        svg.append(
          svgText(left - 9, y + 4, tickLabel(tick, axis.scale.step), "chart-tick-label", "end"),
        );
      } else {
        svg.append(
          svgText(right + 9, y + 4, tickLabel(tick, axis.scale.step), "chart-tick-label", "start"),
        );
      }
    }
    const titleX = axis.side === "left" ? 16 : CHART.width - 12;
    const rotation = axis.side === "left" ? -90 : 90;
    const title = svgText(0, 0, axis.title, "chart-axis-title", "middle");
    title.setAttribute(
      "transform",
      `translate(${titleX} ${(plotTop + plotBottom) / 2}) rotate(${rotation})`,
    );
    svg.append(title);
    svg.append(
      svgElement("line", {
        x1: axis.side === "left" ? left : right,
        y1: plotTop,
        x2: axis.side === "left" ? left : right,
        y2: plotBottom,
        class: "chart-axis-line",
      }),
    );
  }

  svg.append(
    svgElement("line", {
      x1: left,
      y1: plotBottom,
      x2: right,
      y2: plotBottom,
      class: "chart-axis-line",
    }),
  );
  for (const tick of xTicks) {
    const x = round2(xScale(tick));
    svg.append(
      svgElement("line", {
        x1: x,
        y1: plotBottom,
        x2: x,
        y2: plotBottom + 5,
        class: "chart-axis-line",
      }),
    );
    svg.append(svgText(x, plotBottom + 20, tickLabel(tick, xStep), "chart-tick-label", "middle"));
  }
  svg.append(
    svgText(
      (left + right) / 2,
      CHART.height - 12,
      "Hours from series start (h)",
      "chart-axis-title",
      "middle",
    ),
  );
}

function renderChart(config) {
  const { svg, legend, table, intervals, seriesList, leftAxisTitle, rightAxisTitle } = config;
  const intervalHours = intervals[0].interval_hours;
  const totalHours = intervals.length * intervalHours;
  const left = CHART.left;
  const right = CHART.width - CHART.right;
  const plotTop = CHART.top;
  const plotBottom = CHART.height - CHART.bottom;

  const xScale = (hour) => left + (hour / totalHours) * (right - left);
  const xTicks = horizontalTicks(totalHours);
  const xStep = xTicks.length > 1 ? xTicks[1] - xTicks[0] : 1;

  const leftSeries = seriesList.filter((series) => series.axis === "left");
  const rightSeries = seriesList.filter((series) => series.axis === "right");
  const buildAxis = (list, title, side) => {
    if (list.length === 0) {
      return null;
    }
    const extent = axisExtent(list);
    const scale = verticalScale(extent.min, extent.max);
    const yScale = (value) =>
      plotBottom - ((value - scale.min) / (scale.max - scale.min)) * (plotBottom - plotTop);
    return { scale, yScale, title, side };
  };
  const leftAxis = buildAxis(leftSeries, leftAxisTitle, "left");
  const rightAxis = buildAxis(rightSeries, rightAxisTitle, "right");

  svg.replaceChildren();
  drawAxis(svg, {
    axes: [leftAxis, rightAxis],
    xTicks,
    xStep,
    left,
    right,
    plotTop,
    plotBottom,
    xScale,
  });

  for (const series of seriesList) {
    const axis = series.axis === "left" ? leftAxis : rightAxis;
    const d =
      series.kind === "line"
        ? linePath(series.points, xScale, axis.yScale)
        : stepPath(series.values, intervalHours, xScale, axis.yScale);
    const path = svgElement("path", { d, class: `chart-series ${series.cssClass}` });
    if (DASH_PATTERNS[series.dash]) {
      path.setAttribute("stroke-dasharray", DASH_PATTERNS[series.dash]);
    }
    svg.append(path);
  }

  const summary = seriesList
    .map((series) => seriesSummarySentence(series, intervalHours))
    .join(" ");
  svg.setAttribute(
    "aria-label",
    `${config.description} over ${formatDecimal(totalHours, 1)} hours. ${summary}`,
  );

  renderLegend(legend, seriesList);
  renderDataTable(table, intervals, seriesList);
}

function renderCharts(intervals) {
  const chargeValues = intervals.map((item) => item.pv_charge_kw + item.grid_charge_kw);
  const socPoints = [{ hour: 0, value: intervals[0].soc_start_kwh }];
  intervals.forEach((item, index) => {
    socPoints.push({ hour: (index + 1) * item.interval_hours, value: item.soc_end_kwh });
  });

  renderChart({
    svg: document.querySelector("#chart-pv"),
    legend: document.querySelector("#chart-pv-legend"),
    table: document.querySelector("#chart-pv-table"),
    intervals,
    description: "PV production and market price",
    leftAxisTitle: "Power (kW AC)",
    rightAxisTitle: "Price (EUR/MWh)",
    seriesList: [
      {
        label: "PV production",
        unit: "kW AC",
        axis: "left",
        cssClass: "series-pv",
        dash: "solid",
        kind: "step",
        values: intervals.map((item) => item.pv_power_kw),
        tableValues: intervals.map((item) => item.pv_power_kw),
      },
      {
        label: "Market price",
        unit: "EUR/MWh",
        axis: "right",
        cssClass: "series-price",
        dash: "dash",
        kind: "step",
        values: intervals.map((item) => item.market_price_eur_per_mwh),
        tableValues: intervals.map((item) => item.market_price_eur_per_mwh),
      },
    ],
  });

  renderChart({
    svg: document.querySelector("#chart-battery"),
    legend: document.querySelector("#chart-battery-legend"),
    table: document.querySelector("#chart-battery-table"),
    intervals,
    description: "Battery charging, discharging, and state of charge",
    leftAxisTitle: "Power (kW AC)",
    rightAxisTitle: "Stored energy (kWh DC)",
    seriesList: [
      {
        label: "Battery charge (PV plus grid)",
        unit: "kW AC",
        axis: "left",
        cssClass: "series-charge",
        dash: "dash",
        kind: "step",
        values: chargeValues,
        tableValues: chargeValues,
      },
      {
        label: "Battery discharge",
        unit: "kW AC",
        axis: "left",
        cssClass: "series-discharge",
        dash: "solid",
        kind: "step",
        values: intervals.map((item) => item.battery_export_kw),
        tableValues: intervals.map((item) => item.battery_export_kw),
      },
      {
        label: "State of charge at interval end",
        unit: "kWh DC",
        axis: "right",
        cssClass: "series-soc",
        dash: "dashdot",
        kind: "line",
        points: socPoints,
        tableValues: intervals.map((item) => item.soc_end_kwh),
      },
    ],
  });

  renderChart({
    svg: document.querySelector("#chart-grid"),
    legend: document.querySelector("#chart-grid-legend"),
    table: document.querySelector("#chart-grid-table"),
    intervals,
    description: "Grid export, grid import, and curtailed PV",
    leftAxisTitle: "Power (kW AC)",
    rightAxisTitle: "",
    seriesList: [
      {
        label: "Grid export",
        unit: "kW AC",
        axis: "left",
        cssClass: "series-export",
        dash: "solid",
        kind: "step",
        values: intervals.map((item) => item.grid_export_kw),
        tableValues: intervals.map((item) => item.grid_export_kw),
      },
      {
        label: "Grid import (battery charging)",
        unit: "kW AC",
        axis: "left",
        cssClass: "series-import",
        dash: "dash",
        kind: "step",
        values: intervals.map((item) => item.grid_charge_kw),
        tableValues: intervals.map((item) => item.grid_charge_kw),
      },
      {
        label: "Curtailed PV",
        unit: "kW AC",
        axis: "left",
        cssClass: "series-curtailed",
        dash: "dot",
        kind: "step",
        values: intervals.map((item) => item.curtailed_pv_kw),
        tableValues: intervals.map((item) => item.curtailed_pv_kw),
      },
    ],
  });
}

function renderResult(payload) {
  const intervals = normalizeIntervals(payload);
  renderResultSummary(payload, intervals);
  renderMetrics(payload);
  renderCharts(intervals);
  renderLimitations(payload);
  elements.emptyState.hidden = true;
  elements.results.hidden = false;
  elements.resultsTitle.focus();
}

async function runDispatch(event) {
  event.preventDefault();
  const files = selectedFiles();
  if (state.busy || !files.scenario || !files.timeSeries) {
    return;
  }
  setBusy(true);
  setStatus(
    "loading",
    "Running the dispatch optimization",
    "The kernel is solving the scenario; large series can take a while.",
  );
  try {
    const payload = await postDispatch(files);
    renderResult(payload);
    setStatus(
      "success",
      "Dispatch complete",
      `${typeof payload.scenario_name === "string" ? payload.scenario_name : "The scenario"} was solved; the charts below show this scenario only.`,
    );
  } catch (error) {
    setStatus(
      "error",
      "Dispatch failed",
      error instanceof Error ? error.message : "The dispatch request failed.",
    );
  } finally {
    setBusy(false);
  }
}

elements.form.addEventListener("submit", runDispatch);
elements.scenarioInput.addEventListener("change", () => {
  updateRunButton();
  describeSelection();
});
elements.timeSeriesInput.addEventListener("change", () => {
  updateRunButton();
  describeSelection();
});

updateRunButton();
