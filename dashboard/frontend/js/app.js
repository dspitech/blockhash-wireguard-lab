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
  clientSearch: "",
  clientManagementEnabled: true,
  throughputRange: "24h",
  journal: { page: 0, pageSize: 50, total: 0 },
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
  clientSearch: document.getElementById("client-search"),
  addClientBtn: document.getElementById("add-client-btn"),
  mgmtDisabledNote: document.getElementById("mgmt-disabled-note"),
  modalOverlay: document.getElementById("modal-overlay"),
  modalTitle: document.getElementById("modal-title"),
  modalBody: document.getElementById("modal-body"),
  modalClose: document.getElementById("modal-close"),
  drawerOverlay: document.getElementById("drawer-overlay"),
  drawerTitle: document.getElementById("drawer-title"),
  drawerBody: document.getElementById("drawer-body"),
  drawerClose: document.getElementById("drawer-close"),
  toastStack: document.getElementById("toast-stack"),
  rangeSelector: document.getElementById("range-selector"),
  rangeChartCanvas: document.getElementById("range-chart"),
  systemStats: document.getElementById("system-stats"),
  anomaliesList: document.getElementById("anomalies-list"),
  formSettings: document.getElementById("form-settings"),
  alertsEnabledToggle: document.getElementById("alerts-enabled-toggle"),
  formAlertRules: document.getElementById("form-alert-rules"),
  formAlertChannels: document.getElementById("form-alert-channels"),
  alertsHistoryList: document.getElementById("alerts-history-list"),
  dedupList: document.getElementById("dedup-list"),
  dedupClearAllBtn: document.getElementById("dedup-clear-all-btn"),
  exportLogCsvBtn: document.getElementById("export-log-csv"),
  exportLogPdfBtn: document.getElementById("export-log-pdf"),
  formWeeklyReport: document.getElementById("form-weekly-report"),
  sendWeeklyNowBtn: document.getElementById("send-weekly-now-btn"),
  complianceTableBody: document.getElementById("compliance-table-body"),
  complianceEmpty: document.getElementById("compliance-empty"),
  exportComplianceCsvBtn: document.getElementById("export-compliance-csv"),
  exportCompliancePdfBtn: document.getElementById("export-compliance-pdf"),
  backupsList: document.getElementById("backups-list"),
  createBackupBtn: document.getElementById("create-backup-btn"),
  rotateKeysBtn: document.getElementById("rotate-keys-btn"),
  restartTunnelBtn: document.getElementById("restart-tunnel-btn"),
  exportAuditBtn: document.getElementById("export-audit-btn"),
  serversList: document.getElementById("servers-list"),
  addServerBtn: document.getElementById("add-server-btn"),
  globalSearch: document.getElementById("global-search"),
  globalSearchResults: document.getElementById("global-search-results"),
  themeToggleBtn: document.getElementById("theme-toggle-btn"),
  themeIconDark: document.getElementById("theme-icon-dark"),
  themeIconLight: document.getElementById("theme-icon-light"),
  nocModeBtn: document.getElementById("noc-mode-btn"),
  journalPaginationInfo: document.getElementById("journal-pagination-info"),
  journalPageSize: document.getElementById("journal-page-size"),
  journalPrevPage: document.getElementById("journal-prev-page"),
  journalNextPage: document.getElementById("journal-next-page"),
  hamburgerBtn: document.getElementById("hamburger-btn"),
  sidebarBackdrop: document.getElementById("sidebar-backdrop"),
  sidebar: document.querySelector(".sidebar"),
};

const VIEW_META = {
  overview: { title: "Vue d'ensemble", subtitle: "État en temps réel des tunnels VPN BLOCKHash" },
  journal: { title: "Journal des connexions", subtitle: "Historique des handshakes et volumes échangés par tunnel" },
  clients: { title: "Clients WireGuard", subtitle: "Statut détaillé de chaque pair configuré" },
  monitoring: { title: "Monitoring avancé", subtitle: "Débit long terme, ressources serveur et anomalies détectées" },
  alerts: { title: "Alertes", subtitle: "Seuils, canaux de notification et historique des alertes envoyées" },
  compliance: { title: "Conformité", subtitle: "Clients inactifs, candidats à la révocation" },
  system: { title: "Système", subtitle: "Sauvegardes, rotation de clés, maintenance et multi-serveurs" },
};

let throughputChart = null;
let distributionChart = null;

// ---------------------------------------------------------------
// Utilitaires de formatage
// ---------------------------------------------------------------
function formatBytes(bytes) {
  if (!bytes || bytes < 1) return "0 o";
  const units = ["o", "Ko", "Mo", "Go", "To"];
  const i = Math.max(0, Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1));
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
  return { online: "En ligne", idle: "Inactif", never: "Jamais connecté", disabled: "Désactivé" }[status] || status;
}

function formatDate(isoDate) {
  if (!isoDate) return null;
  const d = new Date(isoDate);
  return Number.isNaN(d.getTime()) ? isoDate : d.toLocaleDateString("fr-FR");
}

function expiryState(expires) {
  if (!expires) return null;
  const days = Math.ceil((new Date(expires).getTime() - Date.now()) / 86400000);
  if (days < 0) return "expired";
  if (days <= 7) return "soon";
  return "ok";
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
    // /api/overview ne renvoie pas ce flag (il vient de /api/clients en pratique,
    // mais on suppose la gestion active tant que le serveur ne dit pas le contraire).
    state.clientManagementEnabled = state.data.client_management_enabled !== false;
  } catch (err) {
    const res = await fetch(DEMO_URL, { cache: "no-store" });
    state.data = await res.json();
    state.isDemo = true;
    state.clientManagementEnabled = false; // pas de backend en mode demo -> lecture seule
  }
  render();
}

function buildHeaders(json = false) {
  const token = window.__BLOCKHASH_TOKEN__ || window.localStorage.getItem("blockhash_dashboard_token");
  const headers = token ? { "X-API-Token": token } : {};
  if (json) headers["Content-Type"] = "application/json";
  return headers;
}

// ---------------------------------------------------------------
// Appels API de gestion des clients (POST/PATCH/DELETE)
// ---------------------------------------------------------------
async function apiRequest(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: buildHeaders(true),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let payload = null;
  try {
    payload = await res.json();
  } catch (err) {
    /* reponse vide (ex. 204) -> ignore */
  }
  if (!res.ok) {
    throw new Error((payload && payload.error) || `Erreur ${res.status}`);
  }
  return payload;
}

// ---------------------------------------------------------------
// Notifications (toasts)
// ---------------------------------------------------------------
function showToast(message, variant = "success") {
  const toast = document.createElement("div");
  toast.className = `toast toast--${variant}`;
  toast.textContent = message;
  els.toastStack.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("is-visible"));
  setTimeout(() => {
    toast.classList.remove("is-visible");
    setTimeout(() => toast.remove(), 300);
  }, 4200);
}

// ---------------------------------------------------------------
// Modale generique (formulaires clients)
// ---------------------------------------------------------------
function openModal(title, bodyHtml) {
  els.modalTitle.textContent = title;
  els.modalBody.innerHTML = bodyHtml;
  els.modalOverlay.hidden = false;
  document.body.classList.add("no-scroll");
}

function closeModal() {
  els.modalOverlay.hidden = true;
  els.modalBody.innerHTML = "";
}

els.modalClose.addEventListener("click", closeModal);
els.modalOverlay.addEventListener("click", (e) => {
  if (e.target === els.modalOverlay) closeModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeModal();
    closeDrawer();
  }
});

// ---------------------------------------------------------------
// Tiroir de detail / historique client
// ---------------------------------------------------------------
let historyChart = null;

function closeDrawer() {
  els.drawerOverlay.hidden = true;
  els.drawerBody.innerHTML = "";
  if (historyChart) {
    historyChart.destroy();
    historyChart = null;
  }
}

els.drawerClose.addEventListener("click", closeDrawer);
els.drawerOverlay.addEventListener("click", (e) => {
  if (e.target === els.drawerOverlay) closeDrawer();
});

async function openClientHistory(name) {
  els.drawerTitle.textContent = name;
  els.drawerOverlay.hidden = false;
  els.drawerBody.innerHTML = `<p class="drawer-loading">Chargement de l'historique…</p>`;

  try {
    const history = await apiRequest("GET", `/api/clients/${encodeURIComponent(name)}/history`);
    els.drawerBody.innerHTML = `
      <div class="drawer-stats">
        <div><span>Reconnexions estimées</span><strong>${history.reconnect_count}</strong></div>
        <div><span>Dernier endpoint vu</span><strong>${history.last_endpoint || "—"}</strong></div>
      </div>
      <h4>Débit dédié</h4>
      <canvas id="history-chart" height="160"></canvas>
      <h4>Dernières connexions</h4>
      <ul class="event-list" id="history-events"></ul>
    `;

    const series = history.throughput_series || [];
    const ctx = document.getElementById("history-chart");
    historyChart = new Chart(ctx, {
      type: "line",
      data: {
        labels: series.map((p) => p.t),
        datasets: [
          { label: "Reçu", data: series.map((p) => p.rx), borderColor: "#4C7FFF", backgroundColor: "rgba(76,127,255,0.12)", fill: true, tension: 0.35, pointRadius: 0, borderWidth: 2 },
          { label: "Émis", data: series.map((p) => p.tx), borderColor: "#34D399", backgroundColor: "rgba(52,211,153,0.10)", fill: true, tension: 0.35, pointRadius: 0, borderWidth: 2 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: true, labels: { color: "#8A96AD", boxWidth: 10, font: { size: 11 } } } },
        scales: {
          x: { grid: { display: false }, ticks: { color: "#5B6785", font: { size: 10 }, autoSkip: true, maxTicksLimit: 10, maxRotation: 0 } },
          y: { grid: { color: "#1C2740" }, ticks: { color: "#5B6785", font: { size: 10 }, callback: (v) => formatBytes(v) } },
        },
      },
    });

    const eventsList = document.getElementById("history-events");
    eventsList.innerHTML = (history.logs || [])
      .slice(0, 20)
      .map(
        (log) => `
        <li>
          <span class="event-dot"></span>
          <div class="event-main">
            <strong>${log.endpoint || "endpoint inconnu"}</strong>
            <span>${formatBytes(log.rx_bytes)} reçus · ${formatBytes(log.tx_bytes)} émis</span>
          </div>
          <span class="event-time">${log.timestamp}</span>
        </li>`
      )
      .join("") || `<li><div class="event-main"><span>Aucune connexion enregistrée.</span></div></li>`;
  } catch (err) {
    els.drawerBody.innerHTML = `<p class="drawer-loading">Erreur : ${err.message}</p>`;
  }
}

// ---------------------------------------------------------------
// Rendu global
// ---------------------------------------------------------------
function render() {
  document.body.classList.remove("is-loading");
  renderConnectionStatus();
  renderKpis();
  safeRender("throughput chart", renderThroughputChart);
  safeRender("recent events", renderRecentEvents);
  safeRender("distribution chart", renderDistributionChart);
  safeRender("client grid", renderClientGrid);
  if (document.querySelector('[data-view="journal"]').classList.contains("is-active")) {
    safeRender("journal", loadJournalPage);
  }
}

function safeRender(label, fn) {
  try {
    fn();
  } catch (err) {
    console.error(`Erreur d'affichage (${label}) :`, err);
  }
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
        x: { grid: { display: false }, ticks: { color: "#5B6785", font: { family: "JetBrains Mono", size: 10 }, autoSkip: true, maxTicksLimit: 10, maxRotation: 0 } },
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

// ---------------------------------------------------------------
// Journal : pagination REELLE cote serveur (voir /api/logs)
// ---------------------------------------------------------------
async function loadJournalPage() {
  if (state.isDemo) {
    // Mode demo : pas de backend -> on retombe sur les logs embarques dans sample-data.json,
    // pagines cote client pour garder une UI coherente sans API reelle.
    let rows = [...(state.data.logs || [])];
    if (state.statusFilter !== "all") rows = rows.filter((r) => getPeerStatus(r.peer) === state.statusFilter);
    if (state.search) {
      const q = state.search.toLowerCase();
      rows = rows.filter((r) => [r.peer, r.endpoint, r.allowed_ips].some((v) => (v || "").toLowerCase().includes(q)));
    }
    state.journal.total = rows.length;
    const start = state.journal.page * state.journal.pageSize;
    renderJournalRows(rows.slice(start, start + state.journal.pageSize));
    return;
  }

  try {
    const params = new URLSearchParams({
      limit: state.journal.pageSize,
      offset: state.journal.page * state.journal.pageSize,
      sort_key: state.sort.key,
      sort_dir: state.sort.dir,
    });
    if (state.search) params.set("search", state.search);
    if (state.statusFilter !== "all") params.set("status", state.statusFilter);

    const result = await apiRequest("GET", `/api/logs?${params.toString()}`);
    state.journal.total = result.total;
    renderJournalRows(result.rows);
  } catch (err) {
    showToast(`Journal indisponible : ${err.message}`, "error");
  }
}

function renderJournalRows(rows) {
  state.journal.currentRows = rows;
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

  const { page, pageSize, total } = state.journal;
  const from = total === 0 ? 0 : page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  els.journalPaginationInfo.textContent = `${from}–${to} sur ${total}`;
  els.journalPrevPage.disabled = page === 0;
  els.journalNextPage.disabled = to >= total;
}

function getFilteredSortedLogs() {
  // Reutilise pour les exports CSV/PDF : exporte la page actuellement
  // affichee (coherent avec "ce que vous voyez est ce que vous exportez",
  // voir README 7.9.1). Pour un export complet, augmenter la taille de
  // page avant d'exporter.
  return state.journal.currentRows || [];
}

// ---------------------------------------------------------------
// Clients : grille de cartes + actions de gestion
// ---------------------------------------------------------------
function renderClientGrid() {
  els.mgmtDisabledNote.hidden = state.clientManagementEnabled;
  els.addClientBtn.disabled = !state.clientManagementEnabled;

  let peers = [...(state.data.peers || [])];
  if (state.clientSearch) {
    const q = state.clientSearch.toLowerCase();
    peers = peers.filter((p) => p.name.toLowerCase().includes(q));
  }

  els.clientGrid.innerHTML = peers
    .map((p) => {
      const exp = expiryState(p.expires);
      const bw = p.bw_up_mbit || p.bw_down_mbit
        ? `↑${p.bw_up_mbit ?? "∞"} / ↓${p.bw_down_mbit ?? "∞"} Mb/s`
        : null;
      const mgmt = state.clientManagementEnabled;

      return `
      <div class="client-card" data-name="${p.name}">
        <div class="client-card-head">
          <span class="client-name">${p.name}</span>
          <span class="status-badge status-badge--${p.status}"><span class="dot"></span>${statusLabel(p.status)}</span>
        </div>
        <div class="client-meta">
          <span>Tunnel : <strong>${p.allowed_ips}</strong></span>
          <span>Endpoint : <strong>${p.endpoint || "—"}</strong></span>
          <span>Dernier handshake : <strong>${formatRelativeTime(p.last_handshake)}</strong></span>
          ${p.expires ? `<span class="exp exp--${exp}">Expire le ${formatDate(p.expires)}${exp === "expired" ? " (expiré)" : ""}</span>` : ""}
          ${bw ? `<span>Débit limité : <strong>${bw}</strong></span>` : ""}
        </div>
        <div class="client-transfer">
          <div><span>Reçu</span><strong>${formatBytes(p.rx_bytes)}</strong></div>
          <div><span>Émis</span><strong>${formatBytes(p.tx_bytes)}</strong></div>
        </div>
        <div class="client-actions">
          <button class="chip-btn" data-action="history" title="Historique et débit dédié">Historique</button>
          <button class="chip-btn" data-action="config" title="Revoir la config / le QR code">QR / Config</button>
          ${mgmt ? `
          <button class="chip-btn" data-action="${p.enabled ? "disable" : "enable"}">${p.enabled ? "Désactiver" : "Activer"}</button>
          <button class="chip-btn" data-action="rename">Renommer</button>
          <button class="chip-btn" data-action="expiry">Expiration</button>
          <button class="chip-btn" data-action="bandwidth">Bande passante</button>
          <button class="chip-btn" data-action="regenerate">Régénérer</button>
          <button class="chip-btn chip-btn--danger" data-action="revoke">Révoquer</button>
          ` : ""}
        </div>
      </div>`;
    })
    .join("") || `<p class="table-empty">Aucun client ne correspond à votre recherche.</p>`;
}

// ---------------------------------------------------------------
// Formulaires de gestion (modale) : ajout, renommage, expiration, debit
// ---------------------------------------------------------------
function showClientConfigResult(title, result) {
  const qrSrc = `data:image/png;base64,${result.qr_base64}`;
  const blob = new Blob([result.conf_text], { type: "text/plain" });
  const downloadUrl = URL.createObjectURL(blob);
  openModal(title, `
    <div class="qr-result">
      <img src="${qrSrc}" alt="QR code de configuration WireGuard" width="220" height="220" />
      <p class="qr-hint">Scannez avec l'app mobile WireGuard, ou téléchargez le fichier <code>.conf</code> pour l'importer sur desktop.</p>
      <a class="btn btn-primary" href="${downloadUrl}" download="${result.name || "client"}.conf">Télécharger le .conf</a>
    </div>
  `);
}

function openAddClientModal() {
  openModal("Ajouter un client", `
    <form id="form-add-client" class="form">
      <label>Nom du client
        <input type="text" name="name" placeholder="ex. laptop-marie" maxlength="32" pattern="[A-Za-z0-9_-]+" required autofocus />
      </label>
      <label>Expiration (optionnel)
        <select name="expires_days">
          <option value="">Pas d'expiration</option>
          <option value="1">1 jour</option>
          <option value="7">7 jours</option>
          <option value="30">30 jours</option>
          <option value="90">90 jours</option>
        </select>
      </label>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary">Créer le client</button>
      </div>
    </form>
  `);

  document.getElementById("form-add-client").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    try {
      const result = await apiRequest("POST", "/api/clients", {
        name: form.get("name").trim(),
        expires_days: form.get("expires_days") || null,
      });
      showToast(`Client « ${result.name} » créé.`);
      showClientConfigResult(`Client « ${result.name} » créé`, result);
      await loadData();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}

function openRenameModal(name) {
  openModal(`Renommer « ${name} »`, `
    <form id="form-rename" class="form">
      <label>Nouveau nom
        <input type="text" name="new_name" value="${name}" maxlength="32" pattern="[A-Za-z0-9_-]+" required autofocus />
      </label>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary">Renommer</button>
      </div>
    </form>
  `);

  document.getElementById("form-rename").addEventListener("submit", async (e) => {
    e.preventDefault();
    const newName = new FormData(e.target).get("new_name").trim();
    try {
      await apiRequest("PATCH", `/api/clients/${encodeURIComponent(name)}`, { new_name: newName });
      showToast(`Client renommé en « ${newName} ».`);
      closeModal();
      await loadData();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}

function openExpiryModal(name, currentExpires) {
  openModal(`Expiration — ${name}`, `
    <form id="form-expiry" class="form">
      <label>Date d'expiration (laisser vide = pas d'expiration)
        <input type="date" name="expires" value="${currentExpires || ""}" />
      </label>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary">Enregistrer</button>
      </div>
    </form>
  `);

  document.getElementById("form-expiry").addEventListener("submit", async (e) => {
    e.preventDefault();
    const expires = new FormData(e.target).get("expires") || null;
    try {
      await apiRequest("PATCH", `/api/clients/${encodeURIComponent(name)}`, { expires });
      showToast(`Expiration mise à jour pour « ${name} ».`);
      closeModal();
      await loadData();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}

function openBandwidthModal(name, upMbit, downMbit) {
  openModal(`Bande passante — ${name}`, `
    <form id="form-bandwidth" class="form">
      <p class="form-hint">Limitation avancée (tc/HTB), best effort — laisser vide pour aucune limite.</p>
      <label>Débit montant max (Mb/s, upload client)
        <input type="number" name="bw_up_mbit" min="1" max="1000" value="${upMbit ?? ""}" />
      </label>
      <label>Débit descendant max (Mb/s, download client)
        <input type="number" name="bw_down_mbit" min="1" max="1000" value="${downMbit ?? ""}" />
      </label>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary">Appliquer</button>
      </div>
    </form>
  `);

  document.getElementById("form-bandwidth").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    try {
      const result = await apiRequest("PATCH", `/api/clients/${encodeURIComponent(name)}`, {
        bw_up_mbit: form.get("bw_up_mbit") || null,
        bw_down_mbit: form.get("bw_down_mbit") || null,
      });
      const applied = result.results?.bandwidth?.tc_applied;
      showToast(
        applied === false
          ? `Limite enregistrée pour « ${name} », mais tc n'a pas pu l'appliquer (voir logs serveur).`
          : `Bande passante mise à jour pour « ${name} ».`,
        applied === false ? "error" : "success"
      );
      closeModal();
      await loadData();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
}

async function handleClientAction(action, name, peer) {
  try {
    switch (action) {
      case "history":
        await openClientHistory(name);
        return;
      case "config": {
        const result = await apiRequest("GET", `/api/clients/${encodeURIComponent(name)}/config`);
        showClientConfigResult(`Configuration — ${name}`, { ...result, name });
        return;
      }
      case "rename":
        openRenameModal(name);
        return;
      case "expiry":
        openExpiryModal(name, peer.expires);
        return;
      case "bandwidth":
        openBandwidthModal(name, peer.bw_up_mbit, peer.bw_down_mbit);
        return;
      case "enable":
        await apiRequest("PATCH", `/api/clients/${encodeURIComponent(name)}`, { enabled: true });
        showToast(`Client « ${name} » activé.`);
        await loadData();
        return;
      case "disable":
        await apiRequest("PATCH", `/api/clients/${encodeURIComponent(name)}`, { enabled: false });
        showToast(`Client « ${name} » désactivé.`);
        await loadData();
        return;
      case "regenerate": {
        if (!confirm(`Régénérer les clés de « ${name} » ? L'ancienne configuration cessera immédiatement de fonctionner.`)) return;
        const result = await apiRequest("POST", `/api/clients/${encodeURIComponent(name)}/regenerate`);
        showToast(`Clés régénérées pour « ${name} ».`);
        showClientConfigResult(`Nouvelle configuration — ${name}`, result);
        await loadData();
        return;
      }
      case "revoke": {
        if (!confirm(`Révoquer définitivement « ${name} » ? Cette action est irréversible.`)) return;
        await apiRequest("DELETE", `/api/clients/${encodeURIComponent(name)}`);
        showToast(`Client « ${name} » révoqué.`);
        await loadData();
        return;
      }
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

els.clientGrid.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-action]");
  if (!btn) return;
  const card = e.target.closest(".client-card");
  const name = card?.dataset.name;
  const peer = (state.data.peers || []).find((p) => p.name === name);
  if (name && peer) handleClientAction(btn.dataset.action, name, peer);
});

els.addClientBtn.addEventListener("click", () => {
  if (state.clientManagementEnabled) openAddClientModal();
});

els.clientSearch.addEventListener("input", (e) => {
  state.clientSearch = e.target.value.trim();
  renderClientGrid();
});

// ---------------------------------------------------------------
// Monitoring avancé : débit long terme, système, anomalies
// ---------------------------------------------------------------
let rangeChart = null;

async function loadMonitoringView() {
  if (state.isDemo) {
    els.systemStats.innerHTML = `<p class="table-empty">Indisponible en mode démonstration (nécessite le backend).</p>`;
    els.anomaliesList.innerHTML = "";
    document.getElementById("geoip-empty").hidden = false;
    document.getElementById("geoip-empty").textContent = "Indisponible en mode démonstration.";
    return;
  }
  await Promise.all([loadRangeChart(), loadSystemStats(), loadAnomalies(), loadGeoipMap()]);
}

let geoipMap = null;
let geoipMarkers = [];

async function loadGeoipMap() {
  const mapEl = document.getElementById("geoip-map");
  const emptyEl = document.getElementById("geoip-empty");
  try {
    const data = await apiRequest("GET", "/api/geoip");
    const points = data.points || [];

    if (!geoipMap) {
      geoipMap = L.map(mapEl, { worldCopyJump: true }).setView([20, 10], 2);
      L.Icon.Default.mergeOptions({
        iconUrl: "css/images/marker-icon.png",
        iconRetinaUrl: "css/images/marker-icon-2x.png",
        shadowUrl: "css/images/marker-shadow.png",
      });
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "© OpenStreetMap",
        maxZoom: 18,
      }).addTo(geoipMap);
    }

    geoipMarkers.forEach((m) => geoipMap.removeLayer(m));
    geoipMarkers = points.map((p) => {
      const marker = L.marker([p.lat, p.lon]).addTo(geoipMap);
      marker.bindPopup(
        `<div class="geoip-popup"><strong>${p.name}</strong>${p.city || "Ville inconnue"}, ${p.country || "?"}<br>${p.ip} · ${statusLabel(p.status)}</div>`
      );
      return marker;
    });

    emptyEl.hidden = points.length > 0;
    if (points.length > 0) {
      geoipMap.invalidateSize();
      const bounds = L.latLngBounds(points.map((p) => [p.lat, p.lon]));
      geoipMap.fitBounds(bounds.pad(0.3), { maxZoom: 6 });
    }
  } catch (err) {
    emptyEl.hidden = false;
    emptyEl.textContent = `Carte indisponible : ${err.message}`;
  }
}

async function loadRangeChart() {
  try {
    const data = await apiRequest("GET", `/api/throughput?range=${state.throughputRange}`);
    const series = data.series || [];
    const ctx = els.rangeChartCanvas;
    const cfg = {
      type: "line",
      data: {
        labels: series.map((p) => p.t),
        datasets: [
          { label: "Reçu", data: series.map((p) => p.rx), borderColor: "#4C7FFF", backgroundColor: "rgba(76,127,255,0.12)", fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
          { label: "Émis", data: series.map((p) => p.tx), borderColor: "#34D399", backgroundColor: "rgba(52,211,153,0.10)", fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: true, labels: { color: "#8A96AD", boxWidth: 10, font: { size: 11 } } }, tooltip: { callbacks: { label: (c) => `${c.dataset.label} : ${formatBytes(c.raw)}` } } },
        scales: {
          x: { grid: { display: false }, ticks: { color: "#5B6785", font: { size: 10 }, autoSkip: true, maxTicksLimit: 10, maxRotation: 0 } },
          y: { grid: { color: "#1C2740" }, ticks: { color: "#5B6785", font: { size: 10 }, callback: (v) => formatBytes(v) } },
        },
      },
    };
    if (rangeChart) {
      rangeChart.data = cfg.data;
      rangeChart.update();
    } else {
      rangeChart = new Chart(ctx, cfg);
    }
  } catch (err) {
    showToast(`Débit long terme indisponible : ${err.message}`, "error");
  }
}

async function loadSystemStats() {
  try {
    const sys = await apiRequest("GET", "/api/system");
    const serviceRow = (unit, status) => `
      <div class="system-card">
        <span class="system-label">${unit}</span>
        <span class="status-badge status-badge--${status === "active" ? "online" : "never"}">
          <span class="dot"></span>${status}
        </span>
      </div>`;

    const metricCard = (label, value, percent) => `
      <div class="system-card">
        <span class="system-label">${label}</span>
        <span class="system-value">${value}</span>
        ${percent != null ? `<div class="system-bar"><div class="system-bar-fill" style="width:${Math.min(100, percent)}%"></div></div>` : ""}
      </div>`;

    let html = "";
    if (sys.psutil_available) {
      html += metricCard("CPU", sys.cpu_percent != null ? `${sys.cpu_percent.toFixed(0)} %` : "—", sys.cpu_percent);
      html += metricCard("Mémoire", `${sys.memory.percent.toFixed(0)} %`, sys.memory.percent);
      html += metricCard("Disque (/)", `${sys.disk.percent.toFixed(0)} %`, sys.disk.percent);
      html += metricCard("Uptime", formatUptime(sys.uptime_seconds), null);
    } else {
      html += `<p class="table-empty">psutil non installé côté serveur.</p>`;
    }
    Object.entries(sys.services).forEach(([unit, status]) => {
      html += serviceRow(unit, status);
    });
    els.systemStats.innerHTML = html;
  } catch (err) {
    els.systemStats.innerHTML = `<p class="table-empty">Erreur : ${err.message}</p>`;
  }
}

function formatUptime(seconds) {
  if (!seconds) return "—";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  return days > 0 ? `${days} j ${hours} h` : `${hours} h`;
}

async function loadAnomalies() {
  try {
    const data = await apiRequest("GET", "/api/anomalies");
    const findings = data.anomalies || [];
    els.anomaliesList.innerHTML = findings
      .map(
        (a) => `
        <li>
          <span class="event-dot event-dot--${a.severity}"></span>
          <div class="event-main">
            <strong>${a.peer}</strong>
            <span>${a.message}</span>
          </div>
        </li>`
      )
      .join("") || `<li><div class="event-main"><span>Aucune anomalie détectée.</span></div></li>`;
  } catch (err) {
    els.anomaliesList.innerHTML = `<li><div class="event-main"><span>Erreur : ${err.message}</span></div></li>`;
  }
}

els.rangeSelector.addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  document.querySelectorAll("#range-selector .chip").forEach((c) => c.classList.remove("is-active"));
  chip.classList.add("is-active");
  state.throughputRange = chip.dataset.range;
  loadRangeChart();
});

// ---------------------------------------------------------------
// Alertes : réglages, règles, canaux (secrets masqués), historique
// ---------------------------------------------------------------
async function loadAlertsView() {
  if (state.isDemo) {
    [els.formSettings, els.formAlertRules, els.formAlertChannels].forEach((f) => {
      f.querySelectorAll("input, button").forEach((el) => (el.disabled = true));
    });
    els.alertsHistoryList.innerHTML = `<li><div class="event-main"><span>Indisponible en mode démonstration.</span></div></li>`;
    els.dedupList.innerHTML = `<li><div class="event-main"><span>Indisponible en mode démonstration.</span></div></li>`;
    els.dedupClearAllBtn.disabled = true;
    return;
  }

  try {
    const settings = await apiRequest("GET", "/api/settings");
    els.formSettings.online_threshold_sec.value = settings.online_threshold_sec;
  } catch (err) {
    showToast(`Réglages indisponibles : ${err.message}`, "error");
  }

  try {
    const config = await apiRequest("GET", "/api/alerts/config");
    els.alertsEnabledToggle.checked = !!config.enabled;
    els.formAlertRules.inactive_days.value = config.rules.inactive_days ?? "";
    els.formAlertRules.bandwidth_alert_mb_5min.value = config.rules.bandwidth_alert_mb_5min ?? "";
    els.formAlertRules.service_down.checked = !!config.rules.service_down;

    const ch = config.channels;
    const f = els.formAlertChannels;
    f.email_enabled.checked = !!ch.email.enabled;
    f.smtp_host.value = ch.email.smtp_host || "";
    f.smtp_port.value = ch.email.smtp_port || "";
    f.smtp_user.value = ch.email.smtp_user || "";
    f.smtp_password.value = ch.email.smtp_password || "";
    f.from_addr.value = ch.email.from_addr || "";
    f.to_addr.value = ch.email.to_addr || "";
    f.slack_webhook_url.value = ch.slack_webhook_url || "";
    f.discord_webhook_url.value = ch.discord_webhook_url || "";
    f.telegram_bot_token.value = ch.telegram.bot_token || "";
    f.telegram_chat_id.value = ch.telegram.chat_id || "";
  } catch (err) {
    showToast(`Configuration d'alertes indisponible : ${err.message}`, "error");
  }

  loadAlertsHistory();
  loadDedupList();
}

function formatDuration(seconds) {
  if (seconds < 60) return `${seconds} s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h`;
  return `${Math.floor(seconds / 86400)} j`;
}

async function loadDedupList() {
  try {
    const entries = await apiRequest("GET", "/api/alerts/dedup");
    els.dedupList.innerHTML = entries
      .map(
        (e) => `
        <li>
          <span class="event-dot"></span>
          <div class="event-main">
            <strong>${e.rule_key}</strong>
            <span>Dernière notification il y a ${formatDuration(e.age_sec)}</span>
          </div>
          <button class="chip-btn" data-clear-rule="${e.rule_key}">Réinitialiser</button>
        </li>`
      )
      .join("") || `<li><div class="event-main"><span>Aucune règle en pause actuellement.</span></div></li>`;
  } catch (err) {
    els.dedupList.innerHTML = `<li><div class="event-main"><span>Erreur : ${err.message}</span></div></li>`;
  }
}

els.dedupList.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-clear-rule]");
  if (!btn) return;
  const ruleKey = btn.dataset.clearRule;
  try {
    await apiRequest("DELETE", `/api/alerts/dedup/${encodeURIComponent(ruleKey)}`);
    showToast(`Déduplication réinitialisée pour « ${ruleKey} ».`);
    loadDedupList();
  } catch (err) {
    showToast(err.message, "error");
  }
});

els.dedupClearAllBtn.addEventListener("click", async () => {
  if (!confirm("Réinitialiser la déduplication de TOUTES les règles d'alerte ?")) return;
  try {
    const result = await apiRequest("DELETE", "/api/alerts/dedup");
    showToast(`${result.deleted} règle(s) réinitialisée(s).`);
    loadDedupList();
  } catch (err) {
    showToast(err.message, "error");
  }
});

async function loadAlertsHistory() {
  try {
    const history = await apiRequest("GET", "/api/alerts/history?limit=30");
    els.alertsHistoryList.innerHTML = history
      .map(
        (a) => `
        <li>
          <span class="event-dot event-dot--${a.level === "critical" ? "critical" : "warning"}"></span>
          <div class="event-main">
            <strong>${a.source}</strong>
            <span>${a.message}</span>
          </div>
          <span class="event-time">${new Date(a.ts * 1000).toLocaleString("fr-FR")}</span>
        </li>`
      )
      .join("") || `<li><div class="event-main"><span>Aucune alerte envoyée pour le moment.</span></div></li>`;
  } catch (err) {
    els.alertsHistoryList.innerHTML = `<li><div class="event-main"><span>Erreur : ${err.message}</span></div></li>`;
  }
}

els.formSettings.addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await apiRequest("PATCH", "/api/settings", {
      online_threshold_sec: Number(els.formSettings.online_threshold_sec.value),
    });
    showToast("Réglages enregistrés.");
  } catch (err) {
    showToast(err.message, "error");
  }
});

els.alertsEnabledToggle.addEventListener("change", async () => {
  try {
    await apiRequest("PATCH", "/api/alerts/config", { enabled: els.alertsEnabledToggle.checked });
    showToast(els.alertsEnabledToggle.checked ? "Alerting activé." : "Alerting désactivé.");
  } catch (err) {
    showToast(err.message, "error");
    els.alertsEnabledToggle.checked = !els.alertsEnabledToggle.checked;
  }
});

els.formAlertRules.addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    await apiRequest("PATCH", "/api/alerts/config", {
      rules: {
        inactive_days: f.get("inactive_days") ? Number(f.get("inactive_days")) : null,
        bandwidth_alert_mb_5min: f.get("bandwidth_alert_mb_5min") ? Number(f.get("bandwidth_alert_mb_5min")) : null,
        service_down: f.get("service_down") === "on",
      },
    });
    showToast("Règles d'alerte enregistrées.");
  } catch (err) {
    showToast(err.message, "error");
  }
});

els.formAlertChannels.addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    await apiRequest("PATCH", "/api/alerts/config", {
      channels: {
        email: {
          enabled: f.get("email_enabled") === "on",
          smtp_host: f.get("smtp_host") || "",
          smtp_port: f.get("smtp_port") ? Number(f.get("smtp_port")) : 587,
          smtp_user: f.get("smtp_user") || "",
          smtp_password: f.get("smtp_password") || "",
          from_addr: f.get("from_addr") || "",
          to_addr: f.get("to_addr") || "",
        },
        slack_webhook_url: f.get("slack_webhook_url") || "",
        discord_webhook_url: f.get("discord_webhook_url") || "",
        telegram: {
          bot_token: f.get("telegram_bot_token") || "",
          chat_id: f.get("telegram_chat_id") || "",
        },
      },
    });
    showToast("Canaux de notification enregistrés.");
  } catch (err) {
    showToast(err.message, "error");
  }
});

els.formAlertChannels.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-test-channel]");
  if (!btn) return;
  const channel = btn.dataset.testChannel;
  btn.disabled = true;
  try {
    await apiRequest("POST", "/api/alerts/test", { channel });
    showToast(`Notification de test envoyée sur ${channel}.`);
  } catch (err) {
    showToast(`Échec du test ${channel} : ${err.message}`, "error");
  } finally {
    btn.disabled = false;
  }
});

// ---------------------------------------------------------------
// Export CSV/PDF génériques
// ---------------------------------------------------------------
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportCsv(columns, rows, filename) {
  const escape = (v) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [columns.map(escape).join(","), ...rows.map((r) => r.map(escape).join(","))];
  downloadBlob(new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8" }), filename);
}

async function exportPdf(title, subtitle, columns, rows, filename) {
  try {
    const res = await fetch("/api/reports/pdf", {
      method: "POST",
      headers: buildHeaders(true),
      body: JSON.stringify({ title, subtitle, columns, rows }),
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload.error || `Erreur ${res.status}`);
    }
    downloadBlob(await res.blob(), filename);
  } catch (err) {
    showToast(`Export PDF impossible : ${err.message}`, "error");
  }
}

els.exportLogCsvBtn.addEventListener("click", () => {
  const rows = getFilteredSortedLogs();
  exportCsv(
    ["Horodatage", "Client", "Endpoint", "IP tunnel", "Reçu (octets)", "Émis (octets)"],
    rows.map((r) => [r.timestamp, r.peer, r.endpoint || "", r.allowed_ips || "", r.rx_bytes, r.tx_bytes]),
    "blockhash-journal.csv"
  );
});

els.exportLogPdfBtn.addEventListener("click", () => {
  const rows = getFilteredSortedLogs();
  const subtitle = `Filtre : ${state.statusFilter === "all" ? "Tous" : state.statusFilter}${state.search ? ` · recherche "${state.search}"` : ""} · ${rows.length} ligne(s)`;
  exportPdf(
    "Journal des connexions - BLOCKHash",
    subtitle,
    ["Horodatage", "Client", "Endpoint", "IP tunnel", "Reçu", "Émis"],
    rows.map((r) => [r.timestamp, r.peer, r.endpoint || "—", r.allowed_ips || "—", formatBytes(r.rx_bytes), formatBytes(r.tx_bytes)]),
    "blockhash-journal.pdf"
  );
});

// ---------------------------------------------------------------
// Rapport hebdomadaire
// ---------------------------------------------------------------
async function loadWeeklyReportConfig() {
  try {
    const cfg = await apiRequest("GET", "/api/reports/weekly-config");
    els.formWeeklyReport.weekly_enabled.checked = !!cfg.weekly_enabled;
    els.formWeeklyReport.to_addr.value = cfg.to_addr || "";
  } catch (err) {
    showToast(`Réglages du rapport indisponibles : ${err.message}`, "error");
  }
}

els.formWeeklyReport.addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    await apiRequest("PATCH", "/api/reports/weekly-config", {
      weekly_enabled: f.get("weekly_enabled") === "on",
      to_addr: f.get("to_addr") || "",
    });
    showToast("Réglages du rapport hebdomadaire enregistrés.");
  } catch (err) {
    showToast(err.message, "error");
  }
});

els.sendWeeklyNowBtn.addEventListener("click", async () => {
  els.sendWeeklyNowBtn.disabled = true;
  try {
    const result = await apiRequest("POST", "/api/reports/weekly-send");
    if (result.sent) {
      showToast(`Rapport envoyé à ${result.to}.`);
    } else {
      showToast(result.reason || "Rapport non envoyé.", "error");
    }
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    els.sendWeeklyNowBtn.disabled = false;
  }
});

// ---------------------------------------------------------------
// Conformité : clients inactifs, candidats à la révocation
// ---------------------------------------------------------------
let complianceCache = [];

function bucketLabel(bucket) {
  return bucket === "never" ? "Jamais connecté" : `≥ ${bucket} jours`;
}

async function loadComplianceView() {
  if (state.isDemo) {
    els.complianceTableBody.innerHTML = "";
    els.complianceEmpty.hidden = false;
    els.complianceEmpty.textContent = "Indisponible en mode démonstration.";
    return;
  }
  try {
    const data = await apiRequest("GET", "/api/compliance");
    complianceCache = data.clients || [];
    els.complianceEmpty.hidden = complianceCache.length > 0;
    els.complianceTableBody.innerHTML = complianceCache
      .map(
        (c) => `
        <tr>
          <td>${c.name}</td>
          <td>${c.allowed_ips || "—"}</td>
          <td>${formatDate(c.created) || "—"}</td>
          <td>${c.last_handshake ? formatRelativeTime(c.last_handshake) : "Jamais"}</td>
          <td><span class="exp exp--${c.bucket === "never" || c.bucket >= 30 ? "expired" : "soon"}">${bucketLabel(c.bucket)}</span></td>
          <td class="client-actions" style="border:none; margin:0; padding:0;">
            <button class="chip-btn" data-compliance-action="disable" data-name="${c.name}">Désactiver</button>
            <button class="chip-btn chip-btn--danger" data-compliance-action="revoke" data-name="${c.name}">Révoquer</button>
          </td>
        </tr>`
      )
      .join("");
  } catch (err) {
    showToast(`Vue Conformité indisponible : ${err.message}`, "error");
  }
}

els.complianceTableBody.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-compliance-action]");
  if (!btn) return;
  const name = btn.dataset.name;
  const action = btn.dataset.complianceAction;
  try {
    if (action === "disable") {
      await apiRequest("PATCH", `/api/clients/${encodeURIComponent(name)}`, { enabled: false });
      showToast(`Client « ${name} » désactivé.`);
    } else if (action === "revoke") {
      if (!confirm(`Révoquer définitivement « ${name} » ? Cette action est irréversible.`)) return;
      await apiRequest("DELETE", `/api/clients/${encodeURIComponent(name)}`);
      showToast(`Client « ${name} » révoqué.`);
    }
    loadComplianceView();
  } catch (err) {
    showToast(err.message, "error");
  }
});

els.exportComplianceCsvBtn.addEventListener("click", () => {
  exportCsv(
    ["Client", "IP tunnel", "Créé le", "Dernier handshake", "Inactivité"],
    complianceCache.map((c) => [c.name, c.allowed_ips, c.created, c.last_handshake || "jamais", bucketLabel(c.bucket)]),
    "blockhash-conformite.csv"
  );
});

els.exportCompliancePdfBtn.addEventListener("click", () => {
  exportPdf(
    "Conformité - clients inactifs",
    `${complianceCache.length} client(s) candidat(s) à la révocation`,
    ["Client", "IP tunnel", "Créé le", "Dernier handshake", "Inactivité"],
    complianceCache.map((c) => [c.name, c.allowed_ips, formatDate(c.created) || "—", c.last_handshake || "Jamais", bucketLabel(c.bucket)]),
    "blockhash-conformite.pdf"
  );
});

// ---------------------------------------------------------------
// Système : sauvegardes, rotation de clés, redémarrage, export, serveurs
// ---------------------------------------------------------------
async function loadSystemView() {
  if (state.isDemo) {
    els.backupsList.innerHTML = `<li><div class="event-main"><span>Indisponible en mode démonstration.</span></div></li>`;
    els.serversList.innerHTML = "";
    [els.createBackupBtn, els.rotateKeysBtn, els.restartTunnelBtn, els.exportAuditBtn, els.addServerBtn].forEach(
      (b) => (b.disabled = true)
    );
    return;
  }
  loadBackupsList();
  loadServersList();
}

async function loadBackupsList() {
  try {
    const result = await apiRequest("GET", "/api/system/backups");
    const backups = result.backups || [];
    els.backupsList.innerHTML = backups
      .map(
        (b) => `
        <li>
          <span class="event-dot"></span>
          <div class="event-main">
            <strong>${b.filename}</strong>
            <span>${b.peer_count ?? "?"} pair(s) · ${(b.size_bytes / 1024).toFixed(1)} Ko</span>
          </div>
          <div class="event-trailing">
            <span class="event-time">${new Date(b.modified).toLocaleString("fr-FR")}</span>
            <button class="chip-btn" data-backup-action="diff" data-filename="${b.filename}">Diff</button>
            <button class="chip-btn" data-backup-action="restore" data-filename="${b.filename}">Restaurer</button>
          </div>
        </li>`
      )
      .join("") || `<li><div class="event-main"><span>Aucune sauvegarde pour le moment.</span></div></li>`;
  } catch (err) {
    els.backupsList.innerHTML = `<li><div class="event-main"><span>Erreur : ${err.message}</span></div></li>`;
  }
}

els.createBackupBtn.addEventListener("click", async () => {
  try {
    const result = await apiRequest("POST", "/api/system/backups", { label: "manuel" });
    showToast(`Sauvegarde créée : ${result.filename}`);
    loadBackupsList();
  } catch (err) {
    showToast(err.message, "error");
  }
});

els.backupsList.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-backup-action]");
  if (!btn) return;
  const filename = btn.dataset.filename;
  const action = btn.dataset.backupAction;

  if (action === "diff") {
    try {
      const result = await apiRequest("GET", `/api/system/backups/${encodeURIComponent(filename)}/diff`);
      openModal(
        `Diff — ${filename}`,
        `<pre class="diff-view">${(result.diff || "Aucune différence avec wg0.conf actuel.").replace(/</g, "&lt;")}</pre>`
      );
    } catch (err) {
      showToast(err.message, "error");
    }
  } else if (action === "restore") {
    if (!confirm(`Restaurer « ${filename} » ? La configuration actuelle sera d'abord sauvegardée par sécurité.`)) return;
    try {
      const result = await apiRequest("POST", `/api/system/backups/${encodeURIComponent(filename)}/restore`);
      showToast(`Configuration restaurée depuis « ${filename} » (sécurité : ${result.safety_backup}).`);
      loadBackupsList();
    } catch (err) {
      showToast(err.message, "error");
    }
  }
});

els.rotateKeysBtn.addEventListener("click", async () => {
  if (
    !confirm(
      "Générer de nouvelles clés serveur ? Chaque client existant sera régénéré et devra réimporter sa configuration. Une sauvegarde de sécurité sera créée avant toute modification."
    )
  )
    return;
  els.rotateKeysBtn.disabled = true;
  try {
    const result = await apiRequest("POST", "/api/system/rotate-server-keys");
    showToast(`Clés serveur régénérées. ${result.regenerated_clients.length} client(s) mis à jour.`);
    openModal(
      "Rotation des clés terminée",
      `<p>${result.warning}</p><p class="form-hint">Clients concernés : ${result.regenerated_clients.join(", ") || "aucun"}</p>
       <p class="form-hint">Sauvegarde de sécurité : <code>${result.safety_backup}</code></p>`
    );
    loadBackupsList();
    loadData();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    els.rotateKeysBtn.disabled = false;
  }
});

els.restartTunnelBtn.addEventListener("click", async () => {
  if (!confirm("Redémarrer le tunnel WireGuard maintenant ? Une brève coupure est à prévoir.")) return;
  els.restartTunnelBtn.disabled = true;
  try {
    await apiRequest("POST", "/api/system/restart-tunnel");
    showToast("Tunnel redémarré.");
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    els.restartTunnelBtn.disabled = false;
  }
});

els.exportAuditBtn.addEventListener("click", async () => {
  try {
    const res = await fetch("/api/system/export", { headers: buildHeaders() });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload.error || `Erreur ${res.status}`);
    }
    downloadBlob(await res.blob(), "blockhash-audit-export.zip");
  } catch (err) {
    showToast(`Export impossible : ${err.message}`, "error");
  }
});

async function loadServersList() {
  try {
    const servers = await apiRequest("GET", "/api/servers");
    if (!servers.length) {
      els.serversList.innerHTML = `<li><div class="event-main"><span>Aucun serveur distant enregistré.</span></div></li>`;
      return;
    }
    els.serversList.innerHTML = servers
      .map(
        (s) => `
        <li data-server-row="${s.name}">
          <span class="event-dot"></span>
          <div class="event-main">
            <strong>${s.name}</strong>
            <span>${s.base_url} — <span class="server-status" data-server-status="${s.name}">vérification…</span></span>
          </div>
          <div class="event-trailing">
            <a class="chip-btn" href="${s.base_url}" target="_blank" rel="noopener">Ouvrir</a>
            <button class="chip-btn chip-btn--danger" data-remove-server="${s.name}">Retirer</button>
          </div>
        </li>`
      )
      .join("");

    servers.forEach(async (s) => {
      const el = els.serversList.querySelector(`[data-server-status="${CSS.escape(s.name)}"]`);
      if (!el) return;
      try {
        const result = await apiRequest("GET", `/api/servers/${encodeURIComponent(s.name)}/overview`);
        if (result.ok) {
          const active = result.data.stats?.active_tunnels ?? "?";
          const total = result.data.stats?.total_peers ?? "?";
          el.textContent = `en ligne · ${active}/${total} tunnels actifs`;
          el.classList.add("server-status--ok");
        } else {
          el.textContent = `injoignable (${result.error})`;
          el.classList.add("server-status--error");
        }
      } catch (err) {
        el.textContent = "injoignable";
        el.classList.add("server-status--error");
      }
    });
  } catch (err) {
    els.serversList.innerHTML = `<li><div class="event-main"><span>Erreur : ${err.message}</span></div></li>`;
  }
}

els.serversList.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-remove-server]");
  if (!btn) return;
  const name = btn.dataset.removeServer;
  if (!confirm(`Retirer le serveur « ${name} » de la liste ? (n'affecte pas le serveur lui-même)`)) return;
  try {
    await apiRequest("DELETE", `/api/servers/${encodeURIComponent(name)}`);
    showToast(`Serveur « ${name} » retiré.`);
    loadServersList();
  } catch (err) {
    showToast(err.message, "error");
  }
});

els.addServerBtn.addEventListener("click", () => {
  openModal(
    "Ajouter un serveur",
    `
    <form id="form-add-server" class="form">
      <label>Nom
        <input type="text" name="name" placeholder="ex. site-lyon" maxlength="40" required autofocus />
      </label>
      <label>URL du dashboard distant
        <input type="text" name="base_url" placeholder="https://vpn-lyon.entreprise.com" required />
      </label>
      <label>Jeton d'API (optionnel, celui du serveur distant)
        <input type="password" name="api_token" placeholder="••••••••" />
      </label>
      <div class="form-actions">
        <button type="submit" class="btn btn-primary">Ajouter</button>
      </div>
    </form>
  `
  );
  document.getElementById("form-add-server").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await apiRequest("POST", "/api/servers", {
        name: f.get("name").trim(),
        base_url: f.get("base_url").trim(),
        api_token: f.get("api_token") || "",
      });
      showToast(`Serveur « ${f.get("name")} » ajouté.`);
      closeModal();
      loadServersList();
    } catch (err) {
      showToast(err.message, "error");
    }
  });
});

// ---------------------------------------------------------------
// Navigation entre vues
// ---------------------------------------------------------------
function switchView(view) {
  document.querySelectorAll(".nav-item").forEach((btn) => btn.classList.toggle("is-active", btn.dataset.view === view));
  document.querySelectorAll(".view").forEach((sec) => sec.classList.toggle("is-active", sec.dataset.view === view));
  els.viewTitle.textContent = VIEW_META[view].title;
  els.viewSubtitle.textContent = VIEW_META[view].subtitle;
  closeMobileMenu();

  if (view === "monitoring") loadMonitoringView();
  if (view === "journal") loadJournalPage();
  if (view === "alerts") {
    loadAlertsView();
    loadWeeklyReportConfig();
  }
  if (view === "compliance") loadComplianceView();
  if (view === "system") loadSystemView();
}

document.querySelectorAll(".nav-item").forEach((btn) => btn.addEventListener("click", () => switchView(btn.dataset.view)));
document.querySelectorAll("[data-goto]").forEach((btn) => btn.addEventListener("click", () => switchView(btn.dataset.goto)));

// ---------------------------------------------------------------
// Interactions : recherche, filtres, tri, rafraîchissement
// ---------------------------------------------------------------
els.logSearch.addEventListener("input", (e) => {
  state.search = e.target.value.trim();
  state.journal.page = 0;
  loadJournalPage();
});

els.statusFilters.addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  document.querySelectorAll("#status-filters .chip").forEach((c) => c.classList.remove("is-active"));
  chip.classList.add("is-active");
  state.statusFilter = chip.dataset.status;
  state.journal.page = 0;
  loadJournalPage();
});

document.querySelectorAll("#log-table thead th").forEach((th) => {
  th.addEventListener("click", () => {
    const key = th.dataset.sort;
    if (state.sort.key === key) {
      state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
    } else {
      state.sort = { key, dir: "desc" };
    }
    state.journal.page = 0;
    loadJournalPage();
  });
});

els.journalPageSize.addEventListener("change", (e) => {
  state.journal.pageSize = Number(e.target.value);
  state.journal.page = 0;
  loadJournalPage();
});

els.journalPrevPage.addEventListener("click", () => {
  if (state.journal.page > 0) {
    state.journal.page -= 1;
    loadJournalPage();
  }
});

els.journalNextPage.addEventListener("click", () => {
  if ((state.journal.page + 1) * state.journal.pageSize < state.journal.total) {
    state.journal.page += 1;
    loadJournalPage();
  }
});

els.refreshBtn.addEventListener("click", () => {
  els.refreshBtn.classList.add("is-spinning");
  loadData().finally(() => setTimeout(() => els.refreshBtn.classList.remove("is-spinning"), 400));
});

// ---------------------------------------------------------------
// Menu mobile (hamburger)
// ---------------------------------------------------------------
function openMobileMenu() {
  els.sidebar.classList.add("is-open");
  els.sidebarBackdrop.classList.add("is-open");
}
function closeMobileMenu() {
  els.sidebar.classList.remove("is-open");
  els.sidebarBackdrop.classList.remove("is-open");
}
els.hamburgerBtn.addEventListener("click", openMobileMenu);
els.sidebarBackdrop.addEventListener("click", closeMobileMenu);

// ---------------------------------------------------------------
// Thème clair/sombre
// ---------------------------------------------------------------
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  els.themeIconDark.hidden = theme === "light";
  els.themeIconLight.hidden = theme !== "light";
  localStorage.setItem("blockhash_theme", theme);
}

els.themeToggleBtn.addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
  applyTheme(current === "light" ? "dark" : "light");
});

applyTheme(localStorage.getItem("blockhash_theme") || "dark");

// ---------------------------------------------------------------
// Mode NOC / plein écran
// ---------------------------------------------------------------
els.nocModeBtn.addEventListener("click", async () => {
  document.body.classList.add("noc-mode");
  try {
    await document.documentElement.requestFullscreen();
  } catch (err) {
    // Plein ecran refuse par le navigateur (ex. iframe) -> le mode NOC visuel reste actif
  }
});

document.addEventListener("fullscreenchange", () => {
  if (!document.fullscreenElement) {
    document.body.classList.remove("noc-mode");
  }
});

// ---------------------------------------------------------------
// Recherche globale (clients + journal)
// ---------------------------------------------------------------
let globalSearchDebounce = null;

function renderGlobalSearchResults(clientMatches, logMatches, query) {
  if (!clientMatches.length && !logMatches.length) {
    els.globalSearchResults.innerHTML = `<div class="gsr-empty">Aucun résultat pour « ${query} ».</div>`;
    els.globalSearchResults.hidden = false;
    return;
  }

  let html = "";
  if (clientMatches.length) {
    html += `<div class="gsr-group-label">Clients</div>`;
    html += clientMatches
      .slice(0, 5)
      .map((p) => `<div class="gsr-item" data-goto-client="${p.name}"><strong>${p.name}</strong><span>${p.allowed_ips} · ${statusLabel(p.status)}</span></div>`)
      .join("");
  }
  if (logMatches.length) {
    html += `<div class="gsr-group-label">Journal des connexions</div>`;
    html += logMatches
      .slice(0, 5)
      .map((r) => `<div class="gsr-item" data-goto-journal="${query}"><strong>${r.peer}</strong><span>${r.endpoint || "—"} · ${r.timestamp}</span></div>`)
      .join("");
  }
  els.globalSearchResults.innerHTML = html;
  els.globalSearchResults.hidden = false;
}

els.globalSearch.addEventListener("input", (e) => {
  const query = e.target.value.trim();
  clearTimeout(globalSearchDebounce);
  if (!query) {
    els.globalSearchResults.hidden = true;
    return;
  }
  globalSearchDebounce = setTimeout(async () => {
    const q = query.toLowerCase();
    const clientMatches = (state.data.peers || []).filter(
      (p) => p.name.toLowerCase().includes(q) || (p.allowed_ips || "").includes(q) || (p.endpoint || "").includes(q)
    );
    let logMatches = [];
    try {
      const result = state.isDemo
        ? { rows: (state.data.logs || []).filter((r) => [r.peer, r.endpoint, r.allowed_ips].some((v) => (v || "").toLowerCase().includes(q))) }
        : await apiRequest("GET", `/api/logs?search=${encodeURIComponent(query)}&limit=5`);
      logMatches = result.rows || [];
    } catch (err) {
      logMatches = [];
    }
    renderGlobalSearchResults(clientMatches, logMatches, query);
  }, 250);
});

els.globalSearchResults.addEventListener("click", (e) => {
  const clientItem = e.target.closest("[data-goto-client]");
  const journalItem = e.target.closest("[data-goto-journal]");
  if (clientItem) {
    switchView("clients");
    els.clientSearch.value = clientItem.dataset.gotoClient;
    state.clientSearch = clientItem.dataset.gotoClient;
    renderClientGrid();
  } else if (journalItem) {
    switchView("journal");
    els.logSearch.value = journalItem.dataset.gotoJournal;
    state.search = journalItem.dataset.gotoJournal;
    state.journal.page = 0;
    loadJournalPage();
  }
  els.globalSearchResults.hidden = true;
  els.globalSearch.value = "";
});

document.addEventListener("click", (e) => {
  if (!e.target.closest(".global-search-wrap")) {
    els.globalSearchResults.hidden = true;
  }
});

// ---------------------------------------------------------------
// Temps réel : Server-Sent Events (voir README 7.10.3)
// Complète le rafraîchissement périodique par des notifications
// quasi instantanées ; si la connexion SSE échoue (proxy qui la bloque,
// navigateur ancien), le polling périodique ci-dessous reste le filet
// de sécurité et continue de fonctionner normalement.
// ---------------------------------------------------------------
function connectEventStream() {
  if (state.isDemo || typeof EventSource === "undefined") return;

  const token = window.__BLOCKHASH_TOKEN__ || window.localStorage.getItem("blockhash_dashboard_token");
  const url = token ? `/api/events/stream?token=${encodeURIComponent(token)}` : "/api/events/stream";
  const source = new EventSource(url);

  source.addEventListener("peer_connected", (e) => {
    const data = JSON.parse(e.data);
    showToast(`« ${data.name} » vient de se connecter (${data.endpoint || "endpoint inconnu"}).`);
    loadData();
  });

  source.addEventListener("peer_disconnected", (e) => {
    const data = JSON.parse(e.data);
    showToast(`« ${data.name} » s'est déconnecté.`);
    loadData();
  });

  source.addEventListener("alert", (e) => {
    const data = JSON.parse(e.data);
    showToast(data.message, data.level === "critical" ? "error" : "success");
  });

  source.onerror = () => {
    // EventSource retente seul la reconnexion (backoff natif du navigateur) ;
    // rien a faire ici sinon laisser le polling classique prendre le relais.
  };
}

// ---------------------------------------------------------------
// Horloge + rafraîchissement automatique
// ---------------------------------------------------------------
function tickClock() {
  els.clock.textContent = new Date().toLocaleTimeString("fr-FR");
}
setInterval(tickClock, 1000);
tickClock();

loadData().then(connectEventStream);
setInterval(loadData, REFRESH_INTERVAL_MS);
