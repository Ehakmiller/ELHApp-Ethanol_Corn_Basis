const DATA_BASE_URL =
  "https://pub-e1ba77626f844f97953cd74102f37629.r2.dev/corn_basis";

const CONFIG = {
  DEFAULT_CENTER: [41.9, -93.5],
  DEFAULT_ZOOM: 5,
  BASIS_MIN: -0.5,
  BASIS_MAX: 0.5,
};

const state = {
  index: null,
  snapshotDate: null,
  snapshotRows: [],
  filteredRows: [],
  historyRows: null,
  chartRequestId: 0,
  map: null,
  markerLayer: null,
  chart: null,
};

const els = {
  status: document.getElementById("statusMessage"),
  currentButton: document.getElementById("currentButton"),
  monthButton: document.getElementById("monthButton"),
  yearButton: document.getElementById("yearButton"),
  dateSelect: document.getElementById("dateSelect"),
  plantSelect: document.getElementById("plantSelect"),
  stateSelect: document.getElementById("stateSelect"),
  ownershipSelect: document.getElementById("ownershipSelect"),
  technologySelect: document.getElementById("technologySelect"),
  railSelect: document.getElementById("railSelect"),
  avgBasis: document.getElementById("avgBasis"),
  lowBasis: document.getElementById("lowBasis"),
  highBasis: document.getElementById("highBasis"),
  plantCount: document.getElementById("plantCount"),
  chartCaption: document.getElementById("chartCaption"),
  rowCount: document.getElementById("rowCount"),
  tableBody: document.getElementById("plantTableBody"),
};

function dataUrl(path) {
  return `${DATA_BASE_URL.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;
}

async function fetchJson(path) {
  const response = await fetch(dataUrl(path), { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`);
  }
  return response.json();
}

function setStatus(message, isError = false) {
  els.status.textContent = message;
  els.status.style.color = isError ? "#b42318" : "";
}

function numeric(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function formatBasis(value) {
  const num = numeric(value);
  return num === null ? "--" : num.toFixed(2);
}

function formatPrice(value) {
  const num = numeric(value);
  return num === null ? "--" : num.toFixed(3);
}

function label(value) {
  if (Array.isArray(value)) {
    return value.length ? value.join(", ") : "--";
  }
  return value === null || value === undefined || String(value).trim() === "" ? "--" : String(value);
}

function uniqueSorted(rows, getter) {
  const values = new Set();
  rows.forEach((row) => {
    const value = getter(row);
    if (Array.isArray(value)) {
      value.forEach((item) => item && values.add(String(item)));
    } else if (value !== null && value !== undefined && String(value).trim() !== "") {
      values.add(String(value));
    }
  });
  return [...values].sort((a, b) => a.localeCompare(b));
}

function populateSelect(select, options, placeholder) {
  const current = select.value;
  select.innerHTML = "";
  const all = document.createElement("option");
  all.value = "";
  all.textContent = placeholder;
  select.appendChild(all);
  options.forEach((option) => {
    const node = document.createElement("option");
    node.value = option;
    node.textContent = option;
    select.appendChild(node);
  });
  select.value = options.includes(current) ? current : "";
}

function populateDateSelect() {
  els.dateSelect.innerHTML = "";
  state.index.snapshots.forEach((date) => {
    const option = document.createElement("option");
    option.value = date;
    option.textContent = date;
    els.dateSelect.appendChild(option);
  });
  els.dateSelect.value = state.snapshotDate || state.index.latest;
}

function initMap() {
  state.map = L.map("basisMap", {
    preferCanvas: true,
    scrollWheelZoom: true,
  }).setView(CONFIG.DEFAULT_CENTER, CONFIG.DEFAULT_ZOOM);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(state.map);

  state.markerLayer = L.layerGroup().addTo(state.map);
}

function basisColor(value) {
  const num = numeric(value);
  if (num === null) return "#8793a1";
  const clamped = Math.max(CONFIG.BASIS_MIN, Math.min(CONFIG.BASIS_MAX, num));
  const ratio = (clamped - CONFIG.BASIS_MIN) / (CONFIG.BASIS_MAX - CONFIG.BASIS_MIN);
  if (ratio < 0.5) {
    const t = ratio / 0.5;
    return blend([190, 44, 31], [246, 205, 86], t);
  }
  const t = (ratio - 0.5) / 0.5;
  return blend([246, 205, 86], [25, 132, 87], t);
}

function blend(a, b, t) {
  const rgb = a.map((start, index) => Math.round(start + (b[index] - start) * t));
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
}

function popupHtml(row) {
  return `
    <div class="basis-popup">
      <strong>${label(row.plant_name)}</strong><br>
      ${label(row.city)}${row.city && row.state ? ", " : ""}${label(row.state)}<br>
      Ownership: ${label(row.ownership)}<br>
      Basis: ${formatBasis(row.basis)}<br>
      Flat price: ${formatPrice(row.flat_price)}<br>
      Contract: ${label(row.contract)}<br>
      Delivery: ${label(row.delivery_month)}<br>
      Technology: ${label(row.technology)}<br>
      Rail: ${label(row.rail_lines)}<br>
      Capacity: ${label(row.capacity_mgy)} MGY
    </div>
  `;
}

function renderMap() {
  state.markerLayer.clearLayers();
  const bounds = [];
  state.filteredRows.forEach((row) => {
    const lat = numeric(row.latitude);
    const lon = numeric(row.longitude);
    if (lat === null || lon === null) return;
    const marker = L.circleMarker([lat, lon], {
      radius: 7,
      color: "#1c2733",
      weight: 1,
      fillColor: basisColor(row.basis),
      fillOpacity: 0.9,
    }).bindPopup(popupHtml(row));
    marker.addTo(state.markerLayer);
    bounds.push([lat, lon]);
  });

  if (bounds.length) {
    state.map.fitBounds(bounds, { padding: [28, 28], maxZoom: 8 });
  } else {
    state.map.setView(CONFIG.DEFAULT_CENTER, CONFIG.DEFAULT_ZOOM);
  }
}

function currentFilters() {
  return {
    plant: els.plantSelect.value,
    state: els.stateSelect.value,
    ownership: els.ownershipSelect.value,
    technology: els.technologySelect.value,
    rail: els.railSelect.value,
  };
}

function rowMatchesFilters(row, filters) {
  if (filters.plant && row.plant_id !== filters.plant) return false;
  if (filters.state && row.state !== filters.state) return false;
  if (filters.ownership && row.ownership !== filters.ownership) return false;
  if (filters.technology && row.technology !== filters.technology) return false;
  if (filters.rail && !(Array.isArray(row.rail_lines) && row.rail_lines.includes(filters.rail))) return false;
  return true;
}

function applyFilters() {
  const filters = currentFilters();
  state.filteredRows = state.snapshotRows.filter((row) => rowMatchesFilters(row, filters));
  renderSummary();
  renderMap();
  renderTable();
  renderChart().catch(handleError);
}

function renderSummary() {
  const basisValues = state.filteredRows.map((row) => numeric(row.basis)).filter((value) => value !== null);
  const plantIds = new Set(state.filteredRows.map((row) => row.plant_id).filter(Boolean));
  if (!basisValues.length) {
    els.avgBasis.textContent = "--";
    els.lowBasis.textContent = "--";
    els.highBasis.textContent = "--";
  } else {
    const sum = basisValues.reduce((acc, value) => acc + value, 0);
    els.avgBasis.textContent = (sum / basisValues.length).toFixed(2);
    els.lowBasis.textContent = Math.min(...basisValues).toFixed(2);
    els.highBasis.textContent = Math.max(...basisValues).toFixed(2);
  }
  els.plantCount.textContent = plantIds.size.toLocaleString();
}

function renderTable() {
  els.tableBody.innerHTML = "";
  els.rowCount.textContent = `${state.filteredRows.length.toLocaleString()} rows`;
  const rows = [...state.filteredRows].sort((a, b) => label(a.plant_name).localeCompare(label(b.plant_name)));
  if (!rows.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="empty-row" colspan="8">No plants match the current filters.</td>`;
    els.tableBody.appendChild(tr);
    return;
  }
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${label(row.plant_name)}</td>
      <td>${label(row.state)}</td>
      <td>${label(row.ownership)}</td>
      <td>${formatBasis(row.basis)}</td>
      <td>${formatPrice(row.flat_price)}</td>
      <td>${label(row.contract)}</td>
      <td>${label(row.technology)}</td>
      <td>${label(row.rail_lines)}</td>
    `;
    els.tableBody.appendChild(tr);
  });
}

async function ensureHistories() {
  if (!state.historyRows) {
    const rows = await fetchJson("history/all_basis_history.json");
    state.historyRows = rows.map(normalizeRow);
  }
}

function chartContext() {
  const filters = currentFilters();
  if (filters.plant) return { type: "plant", value: filters.plant, label: selectedText(els.plantSelect) };
  if (filters.state) return { type: "state", value: filters.state, label: filters.state };
  if (filters.technology) return { type: "technology", value: filters.technology, label: filters.technology };
  if (filters.rail) return { type: "rail", value: filters.rail, label: filters.rail };
  return { type: "industry", value: "", label: "Industry average" };
}

function selectedText(select) {
  return select.options[select.selectedIndex]?.textContent || select.value;
}

async function renderChart() {
  const requestId = ++state.chartRequestId;
  const ctxInfo = chartContext();
  try {
    await ensureHistories();
  } catch (error) {
    drawChart([], "History files are not available.");
    return;
  }
  if (requestId !== state.chartRequestId) return;

  let rows = state.historyRows || [];
  if (ctxInfo.type === "plant") {
    rows = rows.filter((row) => row.plant_id === ctxInfo.value);
  } else if (ctxInfo.type === "state") {
    rows = rows.filter((row) => row.state === ctxInfo.value);
  } else if (ctxInfo.type === "technology") {
    rows = rows.filter((row) => row.technology === ctxInfo.value);
  } else if (ctxInfo.type === "rail") {
    rows = rows.filter((row) => Array.isArray(row.rail_lines) && row.rail_lines.includes(ctxInfo.value));
  }

  const points = averageBasisByDate(rows);
  drawChart(points, `${ctxInfo.label} basis history (${points.length} dates)`);
}

function averageBasisByDate(rows) {
  const byDate = new Map();
  rows.forEach((row) => {
    const value = numeric(row.basis);
    if (!row.date || value === null) return;
    const bucket = byDate.get(row.date) || { sum: 0, count: 0 };
    bucket.sum += value;
    bucket.count += 1;
    byDate.set(row.date, bucket);
  });
  return [...byDate.entries()]
    .map(([date, bucket]) => ({ date, value: bucket.sum / bucket.count }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function drawChart(points, caption) {
  els.chartCaption.textContent = caption;
  const chartData = {
    labels: points.map((point) => point.date),
    datasets: [
      {
        label: "Basis",
        data: points.map((point) => point.value),
        borderColor: "#176c6a",
        backgroundColor: "rgba(23, 108, 106, 0.15)",
        pointRadius: points.length > 80 ? 0 : 2,
        pointHoverRadius: 4,
        spanGaps: true,
        tension: 0.2,
      },
    ],
  };

  if (state.chart) {
    state.chart.data = chartData;
    state.chart.update();
    return;
  }

  state.chart = new Chart(document.getElementById("historyChart"), {
    type: "line",
    data: chartData,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
      },
      scales: {
        x: {
          ticks: { maxTicksLimit: 8 },
          grid: { display: false },
        },
        y: {
          title: { display: true, text: "Basis" },
        },
      },
    },
  });
}

function populateFilters() {
  populatePlantSelect();
  populateSelect(els.stateSelect, uniqueSorted(state.snapshotRows, (row) => row.state), "All states");
  populateSelect(els.ownershipSelect, uniqueSorted(state.snapshotRows, (row) => row.ownership), "All ownership");
  populateSelect(els.technologySelect, uniqueSorted(state.snapshotRows, (row) => row.technology), "All technology");
  populateSelect(els.railSelect, uniqueSorted(state.snapshotRows, (row) => row.rail_lines), "All rail lines");
}

function populatePlantSelect() {
  const current = els.plantSelect.value;
  els.plantSelect.innerHTML = "";
  const all = document.createElement("option");
  all.value = "";
  all.textContent = "All plants";
  els.plantSelect.appendChild(all);

  const byPlant = new Map();
  state.snapshotRows.forEach((row) => {
    if (!row.plant_id || byPlant.has(row.plant_id)) return;
    const place = [row.city, row.state].filter(Boolean).join(", ");
    const text = `${label(row.plant_name)}${place ? ` - ${place}` : ""} (${row.plant_id})`;
    byPlant.set(row.plant_id, text);
  });

  [...byPlant.entries()]
    .sort((a, b) => a[1].localeCompare(b[1]))
    .forEach(([plantId, text]) => {
      const option = document.createElement("option");
      option.value = plantId;
      option.textContent = text;
      els.plantSelect.appendChild(option);
    });

  els.plantSelect.value = byPlant.has(current) ? current : "";
}

function closestSnapshot(daysBack) {
  const latest = new Date(`${state.index.latest}T00:00:00`);
  const target = new Date(latest);
  target.setDate(target.getDate() - daysBack);
  let best = state.index.latest;
  let bestDiff = Infinity;
  state.index.snapshots.forEach((date) => {
    const snapshot = new Date(`${date}T00:00:00`);
    if (snapshot > latest) return;
    const diff = Math.abs(snapshot - target);
    if (diff < bestDiff) {
      best = date;
      bestDiff = diff;
    }
  });
  return best;
}

async function loadSnapshot(date, useLatestPath = false) {
  setStatus(`Loading ${date || "latest"}...`);
  const rows = useLatestPath ? await fetchJson("latest.json") : await fetchJson(`snapshots/${date}.json`);
  state.snapshotRows = rows.map(normalizeRow);
  state.snapshotDate = date || state.index.latest;
  els.dateSelect.value = state.snapshotDate;
  populateFilters();
  applyFilters();
  setStatus(`Showing ${state.snapshotDate}`);
}

function normalizeRow(row) {
  return {
    ...row,
    plant_id: row.plant_id === null || row.plant_id === undefined ? "" : String(row.plant_id),
    rail_lines: Array.isArray(row.rail_lines) ? row.rail_lines : [],
  };
}

function wireEvents() {
  els.currentButton.addEventListener("click", () => loadSnapshot(state.index.latest, true).catch(handleError));
  els.monthButton.addEventListener("click", () => loadSnapshot(closestSnapshot(30)).catch(handleError));
  els.yearButton.addEventListener("click", () => loadSnapshot(closestSnapshot(365)).catch(handleError));
  els.dateSelect.addEventListener("change", () => loadSnapshot(els.dateSelect.value).catch(handleError));
  [els.plantSelect, els.stateSelect, els.ownershipSelect, els.technologySelect, els.railSelect].forEach((select) => {
    select.addEventListener("change", applyFilters);
  });
}

function handleError(error) {
  console.error(error);
  setStatus(`Data load failed: ${error.message}`, true);
}

async function init() {
  initMap();
  wireEvents();
  state.index = await fetchJson("index.json");
  populateDateSelect();
  await ensureHistories();
  await loadSnapshot(state.index.latest, true);
}

init().catch(handleError);
