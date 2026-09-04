/* ==========================================================
   BLOCKHash — Dashboard WireGuard
   Récupère /api/overview (backend Flask) ; si indisponible,
   bascule automatiquement sur data/sample-data.json (mode démo).
   ========================================================== */

const REFRESH_INTERVAL_MS = 30000;
const API_URL = "/api/overview";
const DEMO_URL = "data/sample-data.json";

const state = {
  data: null,
  isDemo: false,
  sort: { key: "timestamp", dir: "desc" },
  statusFilter: "all",
  search: "",
};

const els = {
  clock: document.getElementById("clock"),
  connPill: document.getElementById("conn-pill"),
  connLabel: document.getElementById("conn-label"),
  demoBanner: document.getElementById("demo-banner"),
  refreshBtn: document.getElementById("refresh-btn"),
  viewTitle: document.getElementById("view-title"),
  viewSubtitle: document.getElementById("view-subtitle"),
  heroThroughput: document.getElementById("hero-throughput"),
  kpiActive: document.getElementById("kpi-active"),
  kpiActiveDetail: document.getElementById("kpi-active-detail"),
  kpiRx: document.getElementById("kpi-rx"),
  kpiTx: document.getElementById("kpi-tx"),
  kpiAlerts: document.getElementById("kpi-alerts"),
  recentEvents: document.getElementById("recent-events"),
  distributionLegend: document.getElementById("distribution-legend"),
  logTableBody: document.getElementById("log-table-body"),
  logEmpty: document.getElementById("log-empty"),
  logSearch: document.getElementById("log-search"),
  statusFilters: document.getElementById("status-filters"),
  clientGrid: document.getElementById("client-grid"),
};

const VIEW_META = {
  overview: { title: "Vue d'ensemble", subtitle: "État en temps réel des tunnels VPN BLOCKHash" },
  journal: { title: "Journal des connexions", subtitle: "Historique des handshakes et volumes échangés par tunnel" },
  clients: { title: "Clients WireGuard", subtitle: "Statut détaillé de chaque pair configuré" },
};

let throughputChart = null;
let distributionChart = null;

// ---------------------------------------------------------------
// Utilitaires de formatage
// ---------------------------------------------------------------
function formatBytes(bytes) {
  if (!bytes) return "0 o";
  const units = ["o", "Ko", "Mo", "Go", "To"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatRelativeTime(isoString) {
  if (!isoString) return "jamais";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(isoString).getTime()) / 1000));
  if (seconds < 60) return `il y a ${seconds}s`;
  if (seconds < 3600) return `il y a ${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `il y a ${Math.floor(seconds / 3600)} h`;
  return `il y a ${Math.floor(seconds / 86400)} j`;
}

function statusLabel(status) {
  return { online: "En ligne", idle: "Inactif", never: "Jamais connecté" }[status] || status;
}

// ---------------------------------------------------------------
// Chargement des données (API réelle -> repli sur démo)
// ---------------------------------------------------------------
async function loadData() {
  try {
    const res = await fetch(API_URL, { headers: buildHeaders(), cache: "no-store" });
    if (!res.ok) throw new Error("api unreachable");
    state.data = await res.json();
    state.isDemo = false;
  } catch (err) {
    const res = await fetch(DEMO_URL, { cache: "no-store" });
    state.data = await res.json();
    state.isDemo = true;
  }
  render();
}

function buildHeaders() {
  const token = window.localStorage.getItem("blockhash_dashboard_token");
  return token ? { "X-API-Token": token } : {};
}

// ---------------------------------------------------------------
// Rendu global
// ---------------------------------------------------------------
function render() {
  renderConnectionStatus();
  renderKpis();
  renderThroughputChart();
  renderRecentEvents();
  renderDistributionChart();
  renderLogTable();
  renderClientGrid();
}

function renderConnectionStatus() {
  els.demoBanner.hidden = !state.isDemo;
  els.connPill.classList.toggle("is-online", !state.isDemo);
  els.connPill.classList.toggle("is-demo", state.isDemo);
  els.connLabel.textContent = state.isDemo ? "Mode démonstration" : "API connectée";
}

function renderKpis() {
  const { stats } = state.data;
  els.kpiActive.textContent = stats.active_tunnels;
  els.kpiActiveDetail.textContent = `sur ${stats.total_peers} pairs configurés`;
  els.kpiRx.textContent = formatBytes(stats.total_rx_bytes);
  els.kpiTx.textContent = formatBytes(stats.total_tx_bytes);
  els.kpiAlerts.textContent = stats.alerts;

  const lastPoint = state.data.throughput_series?.at(-1);
  if (lastPoint) {
    const mbps = ((lastPoint.rx + lastPoint.tx) * 8) / (300 * 1_000_000); // approx sur 5 min
    els.heroThroughput.textContent = mbps.toFixed(1);
  }
}

function renderThroughputChart() {
  const series = state.data.throughput_series || [];
  const ctx = document.getElementById("throughput-chart");
  const cfg = {
    type: "line",
    data: {
      labels: series.map((p) => p.t),
      datasets: [
        {
          label: "Réception",
          data: series.map((p) => p.rx),
          borderColor: "#4C7FFF",
          backgroundColor: "rgba(76,127,255,0.12)",
          fill: true,
          tension: 0.35,
          pointRadius: 0,
          borderWidth: 2,
        },
        {
          label: "Émission",
          data: series.map((p) => p.tx),
          borderColor: "#34D399",
          backgroundColor: "rgba(52,211,153,0.10)",
          fill: true,
          tension: 0.35,
          pointRadius: 0,
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 600 },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.dataset.label} : ${formatBytes(c.raw)}` } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#5B6785", font: { family: "JetBrains Mono", size: 10 } } },
        y: { grid: { color: "#1C2740" }, ticks: { color: "#5B6785", font: { family: "JetBrains Mono", size: 10 }, callback: (v) => formatBytes(v) } },
      },
    },
  };

  if (throughputChart) {
    throughputChart.data = cfg.data;
    throughputChart.update();
  } else {
    throughputChart = new Chart(ctx, cfg);
  }
}

function renderRecentEvents() {
  const logs = (state.data.logs || []).slice(0, 6);
  els.recentEvents.innerHTML = logs
    .map(
      (log) => `
      <li>
        <span class="event-dot"></span>
        <div class="event-main">
          <strong>${log.peer}</strong>
          <span>${log.endpoint || "endpoint inconnu"} · ${formatBytes(log.rx_bytes)} reçus</span>
        </div>
        <span class="event-time">${log.timestamp}</span>
      </li>`
    )
    .join("") || `<li><div class="event-main"><span>Aucun événement récent.</span></div></li>`;
}

function renderDistributionChart() {
  const peers = [...(state.data.peers || [])]
    .map((p) => ({ name: p.name, total: p.rx_bytes + p.tx_bytes }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 5);

  const palette = ["#4C7FFF", "#34D399", "#F5A623", "#8A96AD", "#EF4444"];
  const ctx = document.getElementById("distribution-chart");
  const cfg = {
    type: "doughnut",
    data: {
      labels: peers.map((p) => p.name),
      datasets: [{ data: peers.map((p) => p.total), backgroundColor: palette, borderWidth: 0 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: "68%",
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.label} : ${formatBytes(c.raw)}` } } },
    },
  };

  if (distributionChart) {
    distributionChart.data = cfg.data;
    distributionChart.update();
  } else {
    distributionChart = new Chart(ctx, cfg);
  }

  els.distributionLegend.innerHTML = peers
    .map(
      (p, i) => `
      <li>
        <span class="dotname"><i style="background:${palette[i]}"></i>${p.name}</span>
        <code>${formatBytes(p.total)}</code>
      </li>`
    )
    .join("");
}

// ---------------------------------------------------------------
// Journal : tri + filtres + recherche (100% côté client)
// ---------------------------------------------------------------
function getPeerStatus(peerName) {
  const peer = (state.data.peers || []).find((p) => p.name === peerName);
  return peer ? peer.status : "idle";
}

function getFilteredSortedLogs() {
  let rows = [...(state.data.logs || [])];

  if (state.statusFilter !== "all") {
    rows = rows.filter((r) => getPeerStatus(r.peer) === state.statusFilter);
  }

  if (state.search) {
    const q = state.search.toLowerCase();
    rows = rows.filter((r) =>
      [r.peer, r.endpoint, r.allowed_ips, r.public_key].some((v) => (v || "").toLowerCase().includes(q))
    );
  }

  const { key, dir } = state.sort;
  rows.sort((a, b) => {
    let av = a[key], bv = b[key];
    if (typeof av === "string") av = av.toLowerCase();
    if (typeof bv === "string") bv = bv.toLowerCase();
    if (av < bv) return dir === "asc" ? -1 : 1;
    if (av > bv) return dir === "asc" ? 1 : -1;
    return 0;
  });

  return rows;
}

function renderLogTable() {
  const rows = getFilteredSortedLogs();
  els.logEmpty.hidden = rows.length > 0;

  els.logTableBody.innerHTML = rows
    .map(
      (r) => `
      <tr>
        <td>${r.timestamp}</td>
        <td>${r.peer}</td>
        <td>${r.endpoint || "—"}</td>
        <td>${r.allowed_ips || "—"}</td>
        <td>${formatBytes(r.rx_bytes)}</td>
        <td>${formatBytes(r.tx_bytes)}</td>
      </tr>`
    )
    .join("");

  document.querySelectorAll("#log-table thead th").forEach((th) => {
    th.classList.toggle("is-sorted", th.dataset.sort === state.sort.key);
    th.classList.toggle("asc", th.dataset.sort === state.sort.key && state.sort.dir === "asc");
  });
}

// ---------------------------------------------------------------
// Clients : grille de cartes
// ---------------------------------------------------------------
function renderClientGrid() {
  const peers = state.data.peers || [];
  els.clientGrid.innerHTML = peers
    .map(
      (p) => `
      <div class="client-card">
        <div class="client-card-head">
          <span class="client-name">${p.name}</span>
          <span class="status-badge status-badge--${p.status}"><span class="dot"></span>${statusLabel(p.status)}</span>
        </div>
        <div class="client-meta">
          <span>Tunnel : <strong>${p.allowed_ips}</strong></span>
          <span>Endpoint : <strong>${p.endpoint || "—"}</strong></span>
          <span>Dernier handshake : <strong>${formatRelativeTime(p.last_handshake)}</strong></span>
        </div>
        <div class="client-transfer">
          <div><span>Reçu</span><strong>${formatBytes(p.rx_bytes)}</strong></div>
          <div><span>Émis</span><strong>${formatBytes(p.tx_bytes)}</strong></div>
        </div>
      </div>`
    )
    .join("");
}

// ---------------------------------------------------------------
// Navigation entre vues
// ---------------------------------------------------------------
function switchView(view) {
  document.querySelectorAll(".nav-item").forEach((btn) => btn.classList.toggle("is-active", btn.dataset.view === view));
  document.querySelectorAll(".view").forEach((sec) => sec.classList.toggle("is-active", sec.dataset.view === view));
  els.viewTitle.textContent = VIEW_META[view].title;
  els.viewSubtitle.textContent = VIEW_META[view].subtitle;
}

document.querySelectorAll(".nav-item").forEach((btn) => btn.addEventListener("click", () => switchView(btn.dataset.view)));
document.querySelectorAll("[data-goto]").forEach((btn) => btn.addEventListener("click", () => switchView(btn.dataset.goto)));

// ---------------------------------------------------------------
// Interactions : recherche, filtres, tri, rafraîchissement
// ---------------------------------------------------------------
els.logSearch.addEventListener("input", (e) => {
  state.search = e.target.value.trim();
  renderLogTable();
});

els.statusFilters.addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  document.querySelectorAll("#status-filters .chip").forEach((c) => c.classList.remove("is-active"));
  chip.classList.add("is-active");
  state.statusFilter = chip.dataset.status;
  renderLogTable();
});

document.querySelectorAll("#log-table thead th").forEach((th) => {
  th.addEventListener("click", () => {
    const key = th.dataset.sort;
    if (state.sort.key === key) {
      state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
    } else {
      state.sort = { key, dir: "desc" };
    }
    renderLogTable();
  });
});

els.refreshBtn.addEventListener("click", () => {
  els.refreshBtn.classList.add("is-spinning");
  loadData().finally(() => setTimeout(() => els.refreshBtn.classList.remove("is-spinning"), 400));
});

// ---------------------------------------------------------------
// Horloge + rafraîchissement automatique
// ---------------------------------------------------------------
function tickClock() {
  els.clock.textContent = new Date().toLocaleTimeString("fr-FR");
}
setInterval(tickClock, 1000);
tickClock();

loadData();
setInterval(loadData, REFRESH_INTERVAL_MS);
