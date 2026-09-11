"use strict";
/* ==========================================================
   BLOCKHash — app.js
   Console vanilla JS : pas de framework, un seul fichier chargé
   après config.js (jeton) et les vendors (Chart.js, Leaflet).
   ========================================================== */

// ---------------------------------------------------------------
// État global
// ---------------------------------------------------------------
const STATE = {
  demoMode: null,          // null = inconnu, true/false une fois déterminé
  theme: localStorage.getItem("blockhash_theme") || "light",
  collapsed: localStorage.getItem("blockhash_sidebar_collapsed") === "1",
  currentView: "overview",
  overview: null,
  peers: [],
  clientsFilter: { status: "all", search: "" },
  journal: { offset: 0, limit: 50, search: "", status: "all", total: 0 },
  throughputRange: "24h",
  clientManagementEnabled: false,
  charts: {},
  map: null,
  mapMarkers: [],
  sse: null,
};

const DEMO_URL = "data/sample-data.json";
const TOKEN_STORAGE_KEY = "blockhash_dashboard_token";

// ---------------------------------------------------------------
// Couche API
// ---------------------------------------------------------------
function authHeaders() {
  const token = window.__BLOCKHASH_TOKEN__ || window.localStorage.getItem(TOKEN_STORAGE_KEY);
  return token ? { "X-API-Token": token } : {};
}

async function apiGet(path) {
  const res = await fetch(path, { headers: authHeaders(), cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = new Error(body.error || `Erreur API (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

async function apiSend(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Erreur API (${res.status})`);
  return data;
}

async function loadDemoOverview() {
  const res = await fetch(DEMO_URL, { cache: "no-store" });
  return res.json();
}

// ---------------------------------------------------------------
// Formatage
// ---------------------------------------------------------------
function fmtBytes(n) {
  if (n === null || n === undefined) return "—";
  const units = ["o", "Ko", "Mo", "Go", "To"];
  let v = n, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function parseTs(iso) {
  // Accepte à la fois l'ISO 8601 ("...T...") et le format "YYYY-MM-DD HH:MM:SS"
  // renvoyé par _row_to_log_dict (voir wgstate.py) : Safari/Firefox n'analysent
  // pas ce second format sans le "T", d'où la normalisation ici.
  if (typeof iso === "string" && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/.test(iso)) {
    return new Date(iso.replace(" ", "T") + "Z");
  }
  return new Date(iso);
}

function fmtRelative(iso) {
  if (!iso) return "Jamais";
  const then = parseTs(iso).getTime();
  const diffSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (diffSec < 60) return `il y a ${diffSec}s`;
  if (diffSec < 3600) return `il y a ${Math.floor(diffSec / 60)} min`;
  if (diffSec < 86400) return `il y a ${Math.floor(diffSec / 3600)} h`;
  return `il y a ${Math.floor(diffSec / 86400)} j`;
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = parseTs(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString("fr-FR", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function initials(name) {
  return (name || "?").split(/[-_ ]/).filter(Boolean).slice(0, 2).map(s => s[0].toUpperCase()).join("");
}

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function statusBadge(status) {
  const map = {
    online: ["success", "En ligne"],
    idle: ["warning", "Inactif"],
    never: ["neutral", "Jamais connecté"],
    disabled: ["danger", "Désactivé"],
  };
  const [cls, label] = map[status] || ["neutral", status || "Inconnu"];
  return `<span class="badge ${cls}"><span class="dot"></span>${label}</span>`;
}

function peerStatus(peer) {
  if (!peer.enabled) return "disabled";
  return peer.status;
}

// ---------------------------------------------------------------
// Toasts
// ---------------------------------------------------------------
function toast(kind, title, message) {
  const stack = document.getElementById("toast-stack");
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `<div class="feed-body"><strong>${escapeHtml(title)}</strong>${message ? `<span>${escapeHtml(message)}</span>` : ""}</div>`;
  stack.appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .2s"; setTimeout(() => el.remove(), 200); }, 5000);
}

// ---------------------------------------------------------------
// Connexion / thème / sidebar
// ---------------------------------------------------------------
function setConnPill(mode) {
  const pill = document.getElementById("conn-pill");
  const label = document.getElementById("conn-label");
  const envBadge = document.getElementById("env-badge");
  pill.classList.remove("is-live", "is-demo", "is-down");
  if (mode === "live") { pill.classList.add("is-live"); label.textContent = "API connectée"; envBadge.textContent = "Production"; }
  else if (mode === "demo") { pill.classList.add("is-demo"); label.textContent = "Mode démonstration"; envBadge.textContent = "Démo"; }
  else { pill.classList.add("is-down"); label.textContent = "API injoignable"; envBadge.textContent = "Hors ligne"; }
}

function applyTheme() {
  document.documentElement.setAttribute("data-theme", STATE.theme);
  const icon = document.getElementById("theme-icon");
  icon.innerHTML = STATE.theme === "dark"
    ? '<path d="M10 3v1.5M10 15.5V17M17 10h-1.5M4.5 10H3M14.8 5.2l-1 1M6.2 13.8l-1 1M14.8 14.8l-1-1M6.2 6.2l-1-1" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="10" cy="10" r="3.4" stroke="currentColor" stroke-width="1.5"/>'
    : '<path d="M16.5 11.8A6.5 6.5 0 0 1 8.2 3.5 6.5 6.5 0 1 0 16.5 11.8Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>';
}

function applySidebar() {
  document.getElementById("shell").classList.toggle("is-collapsed", STATE.collapsed);
}

// ---------------------------------------------------------------
// Router de vues
// ---------------------------------------------------------------
const VIEW_TITLES = {
  overview: "Vue d'ensemble", clients: "Clients", journal: "Journal des connexions",
  monitoring: "Monitoring", alerts: "Alertes", compliance: "Conformité",
  system: "Système", settings: "Réglages",
};

function switchView(view) {
  STATE.currentView = view;
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("is-active", v.id === `view-${view}`));
  document.querySelectorAll(".nav-item[data-view]").forEach(b => b.classList.toggle("is-active", b.dataset.view === view));
  document.getElementById("topbar-title").textContent = VIEW_TITLES[view] || view;
  document.getElementById("shell").classList.remove("is-mobile-open");
  loadView(view);
}

function loadView(view) {
  switch (view) {
    case "overview": return renderOverview();
    case "clients": return renderClients();
    case "journal": return renderJournal();
    case "monitoring": return renderMonitoring();
    case "alerts": return renderAlerts();
    case "compliance": return renderCompliance();
    case "system": return renderSystem();
    case "settings": return renderSettings();
  }
}

// ---------------------------------------------------------------
// Authentification (écran de connexion)
// ---------------------------------------------------------------
// Le dashboard est joignable directement via l'IP publique de la VM
// (voir README 7.3bis) : on n'affiche donc plus le tableau de bord tant
// qu'un jeton valide (obtenu via /api/login) n'est pas en localStorage.
// window.__BLOCKHASH_TOKEN__ reste supporté pour compat/tests locaux mais
// n'est plus injecté par le script d'installation (config.js le laisse vide).
function hasStoredToken() {
  return !!(window.__BLOCKHASH_TOKEN__ || window.localStorage.getItem(TOKEN_STORAGE_KEY));
}

function showLoginScreen(message) {
  document.body.classList.remove("is-loading");
  document.getElementById("login-screen").hidden = false;
  document.getElementById("shell").style.display = "none";
  const errBox = document.getElementById("login-error");
  if (message) {
    errBox.textContent = message;
    errBox.hidden = false;
  } else {
    errBox.hidden = true;
  }
  document.getElementById("login-username").focus();
}

function hideLoginScreen() {
  document.getElementById("login-screen").hidden = true;
  document.getElementById("shell").style.display = "";
}

async function handleLoginSubmit(e) {
  e.preventDefault();
  const btn = document.getElementById("btn-login");
  const username = document.getElementById("login-username").value.trim();
  const password = document.getElementById("login-password").value;
  btn.disabled = true;
  btn.textContent = "Connexion…";
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 429) {
        const secs = body.retry_after_seconds || 300;
        throw new Error(`Trop de tentatives échouées. Réessayez dans ${Math.ceil(secs / 60)} min.`);
      }
      throw new Error("Identifiant ou clé incorrect.");
    }
    window.localStorage.setItem(TOKEN_STORAGE_KEY, body.token);
    hideLoginScreen();
    document.body.classList.add("is-loading");
    await runDashboard();
  } catch (err) {
    document.getElementById("login-error").textContent = err.message;
    document.getElementById("login-error").hidden = false;
  } finally {
    btn.disabled = false;
    btn.textContent = "Se connecter";
  }
}

function handleLogout() {
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  if (STATE.sse) { try { STATE.sse.close(); } catch { /* noop */ } }
  STATE.demoMode = null;
  showLoginScreen();
}

// ---------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------
async function runDashboard(forceDemo) {
  applyTheme();
  applySidebar();

  if (forceDemo) {
    STATE.demoMode = true;
    setConnPill("demo");
  } else {
  try {
    const version = await apiGet("/api/version");
    STATE.demoMode = false;
    STATE.clientManagementEnabled = !!version.client_management_enabled;
    document.getElementById("wg-if-name").textContent = version.wg_interface || "wg0";
    setConnPill("live");
    connectSSE();
  } catch (err) {
    if (err.status === 401) {
      // Jeton présent mais invalide/expiré côté serveur (ex: dashboard.env
      // régénéré) : on le purge et on renvoie au formulaire de connexion
      // plutôt que de basculer silencieusement en mode démo.
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
      showLoginScreen("Session expirée, reconnectez-vous.");
      return;
    }
    try {
      await apiGet("/api/health");
      STATE.demoMode = false;
      setConnPill("live");
    } catch {
      STATE.demoMode = true;
      setConnPill("demo");
    }
  }
  }

  document.getElementById("btn-logout").hidden = STATE.demoMode === true;
  document.body.classList.remove("is-loading");
  switchView("overview");
}

async function bootstrap() {
  document.getElementById("login-form").addEventListener("submit", handleLoginSubmit);
  document.getElementById("btn-login-demo").addEventListener("click", () => {
    hideLoginScreen();
    document.body.classList.add("is-loading");
    runDashboard(true);
  });
  document.getElementById("btn-logout").addEventListener("click", handleLogout);

  if (!hasStoredToken()) {
    showLoginScreen();
    return;
  }
  await runDashboard(false);
}

function connectSSE() {
  if (STATE.demoMode) return;
  try {
    const src = new EventSource("/api/events/stream");
    src.addEventListener("peer_connected", e => {
      const d = JSON.parse(e.data);
      toast("success", `${d.name} connecté`, d.endpoint);
      if (STATE.currentView === "overview") renderOverview();
      if (STATE.currentView === "clients") renderClients();
    });
    src.addEventListener("peer_disconnected", e => {
      const d = JSON.parse(e.data);
      toast("info", `${d.name} déconnecté`);
      if (STATE.currentView === "overview") renderOverview();
      if (STATE.currentView === "clients") renderClients();
    });
    src.addEventListener("alert", e => {
      const d = JSON.parse(e.data);
      toast("danger", "Nouvelle alerte", d.message || d.rule_key || "");
      bumpAlertBadge();
    });
    src.onerror = () => { /* le navigateur reconnecte automatiquement */ };
    STATE.sse = src;
  } catch { /* EventSource indisponible : dégrade silencieusement vers le polling */ }
}

function bumpAlertBadge() {
  const el = document.getElementById("nav-alert-badge");
  const n = (parseInt(el.textContent, 10) || 0) + 1;
  el.textContent = n;
  el.hidden = false;
}

document.addEventListener("DOMContentLoaded", bootstrap);

// ---------------------------------------------------------------
// Chrome global : nav, thème, sidebar, recherche, refresh
// ---------------------------------------------------------------
document.querySelectorAll(".nav-item[data-view]").forEach(btn => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});
document.querySelectorAll("[data-view-link]").forEach(btn => {
  btn.addEventListener("click", () => switchView(btn.dataset.viewLink));
});
document.getElementById("btn-theme").addEventListener("click", () => {
  STATE.theme = STATE.theme === "dark" ? "light" : "dark";
  localStorage.setItem("blockhash_theme", STATE.theme);
  applyTheme();
});
document.getElementById("btn-collapse").addEventListener("click", () => {
  STATE.collapsed = !STATE.collapsed;
  localStorage.setItem("blockhash_sidebar_collapsed", STATE.collapsed ? "1" : "0");
  applySidebar();
});
document.getElementById("btn-refresh").addEventListener("click", () => {
  const btn = document.getElementById("btn-refresh");
  btn.classList.remove("is-spinning");
  void btn.offsetWidth; // force le redémarrage de l'animation CSS
  btn.classList.add("is-spinning");
  loadView(STATE.currentView);
});
document.getElementById("global-search").addEventListener("keydown", e => {
  if (e.key === "Enter" && e.target.value.trim()) {
    STATE.clientsFilter.search = e.target.value.trim();
    switchView("clients");
    document.getElementById("clients-search").value = e.target.value.trim();
  }
});
document.querySelectorAll("[data-close-modal]").forEach(btn => {
  btn.addEventListener("click", () => closeModal(btn.closest(".modal-overlay").id));
});

function openModal(id) { document.getElementById(id).classList.add("is-open"); }
function closeModal(id) { document.getElementById(id).classList.remove("is-open"); }

// ---------------------------------------------------------------
// Chargement des données de fond (overview / peers), partagées par
// plusieurs vues pour éviter de refaire l'appel à chaque bascule.
// ---------------------------------------------------------------
async function fetchOverview() {
  if (STATE.demoMode) {
    const demo = await loadDemoOverview();
    STATE.overview = demo;
    STATE.peers = demo.peers || [];
    return demo;
  }
  const data = await apiGet("/api/overview");
  STATE.overview = data;
  STATE.peers = data.peers || [];
  return data;
}

// ---------------------------------------------------------------
// KPI cards
// ---------------------------------------------------------------
function kpiIcon(name) {
  const icons = {
    tunnels: '<path d="M4 10h12M4 6h8M4 14h5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
    peers: '<circle cx="10" cy="7" r="3" stroke="currentColor" stroke-width="1.5"/><path d="M4.5 17c0-3.3 2.5-5.5 5.5-5.5s5.5 2.2 5.5 5.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
    data: '<path d="M10 3v9m0 0 3-3m-3 3-3-3M4 15h12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
    alerts: '<path d="M10 3c-3.5 4-4.5 6-4.5 9a4.5 4.5 0 0 0 9 0c0-3-1-5-4.5-9Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>',
  };
  return icons[name] || "";
}

function renderKpiGrid(stats) {
  const cards = [
    { label: "Tunnels actifs", value: stats.active_tunnels, of: stats.total_peers, icon: "tunnels", tone: "accent" },
    { label: "Total clients", value: stats.total_peers, icon: "peers", tone: "neutral" },
    { label: "Volume total", value: (stats.total_rx_bytes || 0) + (stats.total_tx_bytes || 0), isBytes: true, icon: "data", tone: "success" },
    { label: "Alertes actives", value: stats.alerts, icon: "alerts", tone: stats.alerts > 0 ? "danger" : "success" },
  ];
  document.getElementById("kpi-grid").innerHTML = cards.map((c, i) => `
    <div class="kpi-card">
      <div class="kpi-icon" style="background:var(--${c.tone}-dim, var(--neutral-dim));color:var(--${c.tone}, var(--text-secondary));">${kpiIcon(c.icon)}</div>
      <div class="kpi-label">${c.label}</div>
      <div class="kpi-value" id="kpi-value-${i}" data-target="${c.value}" data-bytes="${!!c.isBytes}">0</div>
      ${c.of !== undefined ? `<div class="kpi-delta flat">sur ${c.of} au total</div>` : ""}
    </div>
  `).join("");

  // Compteurs animés : partent de 0 et montent vers la valeur réelle. Rejoué
  // à chaque rendu de la vue (pas seulement au premier chargement) pour un
  // effet "tableau de bord vivant" plutôt qu'un simple remplacement de texte.
  cards.forEach((c, i) => {
    const el = document.getElementById(`kpi-value-${i}`);
    animateValue(el, c.value, c.isBytes);
  });
}

function animateValue(el, target, isBytes, duration = 900) {
  if (!el) return;
  const start = performance.now();
  el.classList.add("is-counting");
  function tick(now) {
    const progress = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
    const current = target * eased;
    el.textContent = isBytes ? fmtBytes(current) : Math.round(current).toLocaleString("fr-FR");
    if (progress < 1) requestAnimationFrame(tick);
    else { el.textContent = isBytes ? fmtBytes(target) : Math.round(target).toLocaleString("fr-FR"); el.classList.remove("is-counting"); }
  }
  requestAnimationFrame(tick);
}

// ---------------------------------------------------------------
// VUE : Overview
// ---------------------------------------------------------------
async function renderOverview() {
  const root = document.getElementById("view-overview");
  try {
    const data = await fetchOverview();
    document.getElementById("overview-updated").textContent = `mis à jour ${fmtRelative(data.generated_at)}`;
    renderKpiGrid(data.stats);
    renderThroughputChart(data.throughput_series || []);
    renderActivityFeed(data.logs || []);
    renderOverviewPeersTable(data.peers || []);
    renderStatusDonut(data.peers || []);
    renderExpiringFeed(data.peers || []);
    if (STATE.demoMode) toast("info", "Mode démonstration", "L'API ne répond pas : données d'exemple affichées.");
  } catch (err) {
    toast("danger", "Impossible de charger la vue d'ensemble", err.message);
  }
}

function renderStatusDonut(peers) {
  const canvas = document.getElementById("chart-status-donut");
  if (!canvas || typeof Chart === "undefined") return;
  const buckets = { online: 0, idle: 0, never: 0, disabled: 0 };
  peers.forEach(p => { buckets[peerStatus(p)] = (buckets[peerStatus(p)] || 0) + 1; });
  const labels = { online: "En ligne", idle: "Inactif", never: "Jamais connecté", disabled: "Désactivé" };
  const colors = { online: "#12878a", idle: "#d98a12", never: "#a9b6bc", disabled: "#ec1e79" };
  const keys = Object.keys(buckets).filter(k => buckets[k] > 0);

  document.getElementById("status-donut-total").textContent = `${peers.length} au total`;

  if (STATE.charts["chart-status-donut"]) STATE.charts["chart-status-donut"].destroy();
  if (!keys.length) {
    document.getElementById("status-donut-legend").innerHTML = `<div class="empty-state"><strong>Aucun client</strong></div>`;
    return;
  }
  STATE.charts["chart-status-donut"] = new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: keys.map(k => labels[k]),
      datasets: [{ data: keys.map(k => buckets[k]), backgroundColor: keys.map(k => colors[k]), borderWidth: 2, borderColor: getComputedStyle(document.documentElement).getPropertyValue("--bg-surface").trim() || "#fff" }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: "68%",
      animation: { animateRotate: true, animateScale: true, duration: 900, easing: "easeOutCubic" },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `${c.label}: ${c.parsed}` } } },
    },
  });

  document.getElementById("status-donut-legend").innerHTML = keys.map(k => `
    <div class="row-flex" style="justify-content:space-between;font-size:var(--fs-sm);">
      <span class="row-flex" style="gap:8px;"><i style="width:9px;height:9px;border-radius:2px;background:${colors[k]};display:inline-block;"></i>${labels[k]}</span>
      <span class="cell-primary mono">${buckets[k]}</span>
    </div>`).join("");
}

function renderExpiringFeed(peers) {
  const el = document.getElementById("expiring-feed");
  const now = Date.now();
  const soon = peers
    .filter(p => p.enabled && p.expires)
    .map(p => ({ ...p, daysLeft: Math.ceil((new Date(p.expires).getTime() - now) / 86400000) }))
    .filter(p => p.daysLeft <= 14)
    .sort((a, b) => a.daysLeft - b.daysLeft);

  if (!soon.length) {
    el.innerHTML = `<div class="empty-state"><strong>Rien à signaler</strong><span>Aucune expiration dans les 14 prochains jours.</span></div>`;
    return;
  }
  el.innerHTML = soon.slice(0, 6).map(p => {
    const expired = p.daysLeft < 0;
    const tone = expired ? "danger" : p.daysLeft <= 3 ? "warning" : "accent";
    return `
    <div class="feed-item">
      <div class="feed-icon" style="background:var(--${tone}-dim);color:var(--${tone});">
        <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="6.5" stroke="currentColor" stroke-width="1.5"/><path d="M10 6.5V10l2.5 1.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
      </div>
      <div class="feed-body">
        <div class="feed-title">${escapeHtml(p.name)}</div>
        <div class="feed-meta">${expired ? "Expiré" : `Expire dans ${p.daysLeft} j`} · ${fmtDate(p.expires)}</div>
      </div>
    </div>`;
  }).join("");
}

function renderThroughputChart(series) {
  const ctx = document.getElementById("chart-throughput");
  const labels = series.map(p => new Date(p.ts || p.t).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }));
  const rx = series.map(p => p.rx_bytes ?? p.rx ?? 0);
  const tx = series.map(p => p.tx_bytes ?? p.tx ?? 0);
  buildLineChart("chart-throughput", labels, [
    { label: "Rx", data: rx, color: "#0e3a46" },
    { label: "Tx", data: tx, color: "#ec1e79" },
  ]);
}

function renderActivityFeed(logs) {
  const el = document.getElementById("activity-feed");
  if (!logs.length) {
    el.innerHTML = `<div class="empty-state"><strong>Aucune activité récente</strong><span>Les connexions apparaîtront ici.</span></div>`;
    return;
  }
  el.innerHTML = logs.slice(0, 8).map(l => `
    <div class="feed-item">
      <div class="feed-icon" style="background:var(--accent-dim);color:var(--accent);">
        <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="4" stroke="currentColor" stroke-width="1.6"/></svg>
      </div>
      <div class="feed-body">
        <div class="feed-title">${escapeHtml(l.peer || l.name || "Client")}</div>
        <div class="feed-meta">${escapeHtml(l.endpoint || "")} · ${fmtRelative(l.timestamp)}</div>
      </div>
    </div>
  `).join("");
}

function renderOverviewPeersTable(peers) {
  const tbody = document.querySelector("#table-overview-peers tbody");
  const online = peers.filter(p => p.status === "online").concat(peers.filter(p => p.status !== "online")).slice(0, 8);
  if (!online.length) {
    tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><strong>Aucun client</strong></div></td></tr>`;
    return;
  }
  tbody.innerHTML = online.map(p => `
    <tr>
      <td class="row-flex"><span class="peer-avatar">${initials(p.name)}</span><span class="cell-primary">${escapeHtml(p.name)}</span></td>
      <td>${statusBadge(peerStatus(p))}</td>
      <td class="mono cell-muted">${escapeHtml(p.endpoint || "—")}</td>
      <td class="cell-muted">${fmtRelative(p.last_handshake)}</td>
      <td class="mono cell-muted">${fmtBytes(p.rx_bytes)} / ${fmtBytes(p.tx_bytes)}</td>
    </tr>
  `).join("");
}

// ---------------------------------------------------------------
// Graphiques (Chart.js)
// ---------------------------------------------------------------
function chartTextColor() {
  return getComputedStyle(document.documentElement).getPropertyValue("--text-tertiary").trim() || "#8b9ab8";
}
function chartGridColor() {
  return getComputedStyle(document.documentElement).getPropertyValue("--border-subtle").trim() || "#1c2740";
}

function buildLineChart(canvasId, labels, datasets) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || typeof Chart === "undefined") return;
  if (STATE.charts[canvasId]) STATE.charts[canvasId].destroy();
  STATE.charts[canvasId] = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: datasets.map(d => ({
        label: d.label, data: d.data, borderColor: d.color, backgroundColor: d.color + "22",
        borderWidth: 2, tension: 0.35, pointRadius: 0, pointHoverRadius: 4, fill: true,
      })),
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => `${c.dataset.label}: ${fmtBytes(c.parsed.y)}` } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: chartTextColor(), font: { size: 10 }, maxTicksLimit: 8 } },
        y: { grid: { color: chartGridColor() }, ticks: { color: chartTextColor(), font: { size: 10 }, callback: v => fmtBytes(v) } },
      },
    },
  });
}

// ---------------------------------------------------------------
// VUE : Clients
// ---------------------------------------------------------------
async function renderClients() {
  try {
    if (!STATE.overview) await fetchOverview();
    else await fetchOverview(); // toujours rafraîchi pour rester à jour
    document.getElementById("clients-count").textContent = STATE.peers.length;
    drawClientsTable();
  } catch (err) {
    toast("danger", "Impossible de charger les clients", err.message);
  }
}

function drawClientsTable() {
  const { status, search } = STATE.clientsFilter;
  let rows = STATE.peers.slice();
  if (status !== "all") rows = rows.filter(p => peerStatus(p) === status);
  if (search) {
    const q = search.toLowerCase();
    rows = rows.filter(p => (p.name || "").toLowerCase().includes(q) || (p.allowed_ips || "").includes(q) || (p.endpoint || "").includes(q));
  }
  const tbody = document.querySelector("#table-clients tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="8"><div class="empty-state">
      <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="7" r="3" stroke="currentColor" stroke-width="1.4"/><path d="M4.5 17c0-3.3 2.5-5.5 5.5-5.5s5.5 2.2 5.5 5.5" stroke="currentColor" stroke-width="1.4"/></svg>
      <strong>Aucun client ne correspond</strong><span>Ajustez les filtres ou ajoutez un nouveau client.</span>
    </div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(p => `
    <tr>
      <td class="row-flex"><span class="peer-avatar">${initials(p.name)}</span><span class="cell-primary">${escapeHtml(p.name)}</span></td>
      <td>${statusBadge(peerStatus(p))}</td>
      <td class="mono cell-muted">${escapeHtml(p.allowed_ips || "—")}</td>
      <td class="mono cell-muted">${escapeHtml(p.endpoint || "—")}</td>
      <td class="mono cell-muted">${fmtBytes(p.rx_bytes)} / ${fmtBytes(p.tx_bytes)}</td>
      <td class="cell-muted">${fmtDate(p.created)}</td>
      <td class="cell-muted">${p.expires ? fmtDate(p.expires) : "—"}</td>
      <td>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          <button class="btn ghost sm" data-action="toggle" data-name="${escapeHtml(p.name)}" data-enabled="${p.enabled}">${p.enabled ? "Désactiver" : "Activer"}</button>
          <button class="btn ghost sm" data-action="edit" data-name="${escapeHtml(p.name)}" title="Renommer / expiration / bande passante">Modifier</button>
          <button class="btn ghost sm" data-action="config" data-name="${escapeHtml(p.name)}" title="Télécharger la configuration (.conf) et le QR code">Config</button>
          <button class="btn ghost sm" data-action="regenerate" data-name="${escapeHtml(p.name)}" title="Régénérer les clés (invalide l'ancienne configuration)">Régénérer</button>
          <button class="btn ghost sm" data-action="revoke" data-name="${escapeHtml(p.name)}" title="Révoquer">✕</button>
        </div>
      </td>
    </tr>
  `).join("");

  tbody.querySelectorAll('[data-action="toggle"]').forEach(btn => btn.addEventListener("click", () => toggleClient(btn.dataset.name, btn.dataset.enabled === "true")));
  tbody.querySelectorAll('[data-action="edit"]').forEach(btn => btn.addEventListener("click", () => openEditClientModal(btn.dataset.name)));
  tbody.querySelectorAll('[data-action="config"]').forEach(btn => btn.addEventListener("click", () => downloadClientConfig(btn.dataset.name)));
  tbody.querySelectorAll('[data-action="regenerate"]').forEach(btn => btn.addEventListener("click", () => regenerateClient(btn.dataset.name)));
  tbody.querySelectorAll('[data-action="revoke"]').forEach(btn => btn.addEventListener("click", () => revokeClient(btn.dataset.name)));
}

async function toggleClient(name, currentlyEnabled) {
  if (STATE.demoMode) return toast("info", "Mode démonstration", "Action indisponible sans API connectée.");
  try {
    await apiSend("PATCH", `/api/clients/${encodeURIComponent(name)}`, { enabled: !currentlyEnabled });
    toast("success", `${name} ${!currentlyEnabled ? "activé" : "désactivé"}`);
    renderClients();
  } catch (err) { toast("danger", "Échec de l'opération", err.message); }
}

function openEditClientModal(name) {
  if (STATE.demoMode) return toast("info", "Mode démonstration", "Action indisponible sans API connectée.");
  const peer = STATE.peers.find(p => p.name === name);
  document.getElementById("field-edit-name").value = name;
  document.getElementById("field-edit-name").dataset.originalName = name;
  document.getElementById("field-edit-expires").value = peer && peer.expires ? String(peer.expires).slice(0, 10) : "";
  document.getElementById("field-edit-bandwidth").value = peer && peer.bw_down_mbit ? peer.bw_down_mbit : "";
  openModal("modal-client-edit");
}

async function submitEditClient() {
  const originalName = document.getElementById("field-edit-name").dataset.originalName;
  const newName = document.getElementById("field-edit-name").value.trim();
  const expires = document.getElementById("field-edit-expires").value; // "" ou "YYYY-MM-DD"
  const bandwidth = document.getElementById("field-edit-bandwidth").value.trim();

  const body = {};
  if (newName && newName !== originalName) body.new_name = newName;
  body.expires = expires || null;
  if (bandwidth) {
    body.bw_up_mbit = bandwidth;
    body.bw_down_mbit = bandwidth;
  } else {
    body.bw_up_mbit = null;
    body.bw_down_mbit = null;
  }

  try {
    await apiSend("PATCH", `/api/clients/${encodeURIComponent(originalName)}`, body);
    toast("success", `${newName || originalName} mis à jour`);
    closeModal("modal-client-edit");
    renderClients();
  } catch (err) { toast("danger", "Échec de la mise à jour", err.message); }
}
document.getElementById("btn-confirm-client-edit").addEventListener("click", submitEditClient);

async function downloadClientConfig(name) {
  if (STATE.demoMode) return toast("info", "Mode démonstration", "Action indisponible sans API connectée.");
  try {
    const data = await apiGet(`/api/clients/${encodeURIComponent(name)}/config`);
    const blob = new Blob([data.conf_text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name}.conf`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast("success", `Configuration de ${name} téléchargée`, "Le QR code d'appairage est aussi disponible via l'API (/config).");
  } catch (err) { toast("danger", "Échec du téléchargement", err.message); }
}

async function regenerateClient(name) {
  if (STATE.demoMode) return toast("info", "Mode démonstration", "Action indisponible sans API connectée.");
  if (!confirm(`Régénérer les clés de « ${name} » ? L'ancienne configuration cessera de fonctionner immédiatement.`)) return;
  try {
    await apiSend("POST", `/api/clients/${encodeURIComponent(name)}/regenerate`);
    toast("success", `Clés régénérées pour ${name}`, "Pensez à redistribuer la nouvelle configuration.");
    renderClients();
  } catch (err) { toast("danger", "Échec de la régénération", err.message); }
}

async function revokeClient(name) {
  if (STATE.demoMode) return toast("info", "Mode démonstration", "Action indisponible sans API connectée.");
  if (!confirm(`Révoquer définitivement « ${name} » ? Cette action supprime sa configuration WireGuard.`)) return;
  try {
    await apiSend("DELETE", `/api/clients/${encodeURIComponent(name)}`);
    toast("success", `${name} révoqué`);
    renderClients();
  } catch (err) { toast("danger", "Échec de la révocation", err.message); }
}

document.querySelectorAll("#clients-status-filter .chip").forEach(chip => {
  chip.addEventListener("click", () => {
    document.querySelectorAll("#clients-status-filter .chip").forEach(c => c.classList.remove("is-active"));
    chip.classList.add("is-active");
    STATE.clientsFilter.status = chip.dataset.status;
    drawClientsTable();
  });
});
document.getElementById("clients-search").addEventListener("input", e => {
  STATE.clientsFilter.search = e.target.value.trim();
  drawClientsTable();
});
document.getElementById("btn-add-client").addEventListener("click", () => {
  document.getElementById("modal-client-title").textContent = "Ajouter un client";
  document.getElementById("field-client-name").value = "";
  document.getElementById("field-client-expires").value = "";
  openModal("modal-client");
});
document.getElementById("btn-confirm-client").addEventListener("click", async () => {
  const name = document.getElementById("field-client-name").value.trim();
  const expiresDate = document.getElementById("field-client-expires").value;
  if (!name) return toast("danger", "Nom requis");
  if (STATE.demoMode) { closeModal("modal-client"); return toast("info", "Mode démonstration", "Création indisponible sans API connectée."); }
  try {
    let expiresDays;
    if (expiresDate) expiresDays = Math.max(1, Math.ceil((new Date(expiresDate) - new Date()) / 86400000));
    await apiSend("POST", "/api/clients", { name, expires_days: expiresDays });
    toast("success", `Client ${name} créé`);
    closeModal("modal-client");
    renderClients();
  } catch (err) { toast("danger", "Échec de la création", err.message); }
});

// ---------------------------------------------------------------
// VUE : Journal
// ---------------------------------------------------------------
async function renderJournal() {
  try {
    if (STATE.demoMode) {
      const demo = STATE.overview || await fetchOverview();
      renderJournalTable((demo.logs || []).map(l => ({ ts: l.ts, name: l.name, endpoint: l.endpoint, allowed_ips: l.allowed_ips, rx_bytes: l.rx_bytes, tx_bytes: l.tx_bytes })), 0);
      return;
    }
    const { offset, limit, search, status } = STATE.journal;
    const params = new URLSearchParams({ limit, offset, sort_key: "ts", sort_dir: "desc" });
    if (search) params.set("search", search);
    if (status !== "all") params.set("status", status);
    const data = await apiGet(`/api/logs?${params.toString()}`);
    STATE.journal.total = data.total ?? (data.rows || []).length;
    renderJournalTable(data.rows || [], offset);
  } catch (err) { toast("danger", "Impossible de charger le journal", err.message); }
}

function renderJournalTable(rows, offset) {
  const tbody = document.querySelector("#table-journal tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><strong>Aucune entrée</strong><span>Aucune connexion ne correspond à ces filtres.</span></div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(l => `
    <tr>
      <td class="mono cell-muted">${fmtDate(l.timestamp)}</td>
      <td class="cell-primary">${escapeHtml(l.peer || l.name || "—")}</td>
      <td class="mono cell-muted">${escapeHtml(l.endpoint || "—")}</td>
      <td class="mono cell-muted">${escapeHtml(l.allowed_ips || "—")}</td>
      <td class="mono cell-muted">${fmtBytes(l.rx_bytes)} / ${fmtBytes(l.tx_bytes)}</td>
    </tr>
  `).join("");
}

document.getElementById("journal-search").addEventListener("input", e => { STATE.journal.search = e.target.value.trim(); STATE.journal.offset = 0; renderJournal(); });
document.getElementById("journal-status").addEventListener("change", e => { STATE.journal.status = e.target.value; STATE.journal.offset = 0; renderJournal(); });
document.getElementById("journal-prev").addEventListener("click", () => { STATE.journal.offset = Math.max(0, STATE.journal.offset - STATE.journal.limit); renderJournal(); });
document.getElementById("journal-next").addEventListener("click", () => { STATE.journal.offset += STATE.journal.limit; renderJournal(); });

// ---------------------------------------------------------------
// VUE : Monitoring (débit long terme, système, geoip, anomalies)
// ---------------------------------------------------------------
async function renderMonitoring() {
  await Promise.all([renderLongTermChart(), renderSystemPanel(), renderGeoipMap(), renderAnomalies()]);
}

async function renderLongTermChart() {
  try {
    let series;
    if (STATE.demoMode) {
      series = (STATE.overview?.throughput_series || []);
    } else {
      const data = await apiGet(`/api/throughput?range=${encodeURIComponent(STATE.throughputRange)}`);
      series = data.series || [];
    }
    const labels = series.map(p => {
      const d = new Date(p.ts || p.t);
      return STATE.throughputRange === "1h" || STATE.throughputRange === "24h"
        ? d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })
        : d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short" });
    });
    buildLineChart("chart-longterm", labels, [
      { label: "Rx", data: series.map(p => p.rx_bytes ?? p.rx ?? 0), color: "#0e3a46" },
      { label: "Tx", data: series.map(p => p.tx_bytes ?? p.tx ?? 0), color: "#ec1e79" },
    ]);
  } catch (err) { toast("danger", "Débit indisponible", err.message); }
}

document.querySelectorAll("#throughput-range .chip").forEach(chip => {
  chip.addEventListener("click", () => {
    document.querySelectorAll("#throughput-range .chip").forEach(c => c.classList.remove("is-active"));
    chip.classList.add("is-active");
    STATE.throughputRange = chip.dataset.range;
    renderLongTermChart();
  });
});

async function renderSystemPanel() {
  const el = document.getElementById("system-meters");
  try {
    const snap = STATE.demoMode ? { psutil_available: false } : await apiGet("/api/system");
    if (!snap.psutil_available) {
      el.innerHTML = `<div class="empty-state"><strong>Métriques hôte indisponibles</strong><span>psutil n'est pas installé côté serveur, ou mode démonstration actif.</span></div>`;
      return;
    }
    const rows = [
      { label: "CPU", value: snap.cpu_percent, of: `${snap.cpu_count} cœurs` },
      { label: "Mémoire", value: snap.memory?.percent, of: `${fmtBytes(snap.memory?.used_bytes)} / ${fmtBytes(snap.memory?.total_bytes)}` },
      { label: "Disque", value: snap.disk?.percent, of: `${fmtBytes(snap.disk?.used_bytes)} / ${fmtBytes(snap.disk?.total_bytes)}` },
    ];
    el.innerHTML = rows.map(r => {
      const pct = r.value === null || r.value === undefined ? 0 : r.value;
      const tone = pct > 85 ? "danger" : pct > 65 ? "warn" : "";
      return `
        <div>
          <div style="display:flex;justify-content:space-between;font-size:var(--fs-xs);margin-bottom:6px;">
            <span style="font-weight:600;color:var(--text-secondary);">${r.label}</span>
            <span class="cell-muted mono">${r.value === null || r.value === undefined ? "—" : r.value.toFixed(0) + "%"} · ${r.of}</span>
          </div>
          <div class="meter ${tone}"><i style="width:${pct}%"></i></div>
        </div>`;
    }).join("") + `
      <div style="border-top:1px solid var(--border-subtle);padding-top:var(--sp-3);margin-top:var(--sp-1);">
        <div class="kpi-label" style="margin-bottom:6px;">Services</div>
        ${Object.entries(snap.services || {}).map(([svc, ok]) => `
          <div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;font-size:var(--fs-xs);">
            <span class="mono">${escapeHtml(svc)}</span>${statusBadge(ok ? "online" : "disabled")}
          </div>`).join("")}
      </div>`;
  } catch (err) {
    el.innerHTML = `<div class="empty-state"><strong>Erreur</strong><span>${escapeHtml(err.message)}</span></div>`;
  }
}

async function renderGeoipMap() {
  const mapEl = document.getElementById("geoip-map");
  if (typeof L === "undefined") { mapEl.innerHTML = "Leaflet indisponible."; return; }
  if (!STATE.map) {
    STATE.map = L.map(mapEl, { worldCopyJump: true }).setView([20, 10], 2);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      attribution: "&copy; OpenStreetMap, &copy; CARTO", maxZoom: 18,
    }).addTo(STATE.map);
  }
  STATE.mapMarkers.forEach(m => STATE.map.removeLayer(m));
  STATE.mapMarkers = [];

  try {
    let points = [];
    if (!STATE.demoMode) {
      const data = await apiGet("/api/geoip");
      points = data.points || [];
    }
    if (!points.length) return;
    points.forEach(pt => {
      if (pt.lat === undefined || pt.lon === undefined) return;
      const marker = L.circleMarker([pt.lat, pt.lon], {
        radius: 6, color: "#ec1e79", fillColor: "#ec1e79", fillOpacity: 0.6, weight: 1.5,
      }).bindTooltip(`${pt.name || pt.peer_name || "Client"} — ${pt.city || pt.country || ""}`);
      marker.addTo(STATE.map);
      STATE.mapMarkers.push(marker);
    });
    const group = L.featureGroup(STATE.mapMarkers);
    if (STATE.mapMarkers.length) STATE.map.fitBounds(group.getBounds().pad(0.3));
  } catch (err) { /* carte non bloquante */ }
  setTimeout(() => STATE.map.invalidateSize(), 200);
}

async function renderAnomalies() {
  const el = document.getElementById("anomalies-feed");
  try {
    if (STATE.demoMode) {
      el.innerHTML = `<div class="empty-state"><strong>Mode démonstration</strong><span>La détection d'anomalies nécessite l'API connectée.</span></div>`;
      return;
    }
    const data = await apiGet("/api/anomalies");
    const findings = data.anomalies || [];
    if (!findings.length) {
      el.innerHTML = `<div class="empty-state"><strong>Aucune anomalie</strong><span>Tout est nominal.</span></div>`;
      return;
    }
    el.innerHTML = findings.map(a => `
      <div class="feed-item">
        <div class="feed-icon" style="background:var(--warning-dim);color:var(--warning);">
          <svg viewBox="0 0 20 20" fill="none"><path d="M10 7v4M10 14h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        </div>
        <div class="feed-body">
          <div class="feed-title">${escapeHtml(a.title || a.type || "Anomalie")}</div>
          <div class="feed-meta">${escapeHtml(a.detail || a.message || "")}</div>
        </div>
      </div>`).join("");
  } catch (err) { el.innerHTML = `<div class="empty-state"><strong>Erreur</strong><span>${escapeHtml(err.message)}</span></div>`; }
}

// ---------------------------------------------------------------
// VUE : Alertes
// ---------------------------------------------------------------
async function renderAlerts() {
  document.getElementById("nav-alert-badge").hidden = true;
  document.getElementById("nav-alert-badge").textContent = "0";
  try {
    if (STATE.demoMode) {
      document.querySelector("#table-alerts-history tbody").innerHTML =
        `<tr><td colspan="4"><div class="empty-state"><strong>Mode démonstration</strong><span>Historique indisponible sans API connectée.</span></div></td></tr>`;
      document.getElementById("dedup-list").innerHTML = "";
      return;
    }
    const [history, dedup] = await Promise.all([
      apiGet("/api/alerts/history?limit=50"),
      apiGet("/api/alerts/dedup"),
    ]);
    renderAlertsHistory(history);
    renderDedupList(dedup);
  } catch (err) { toast("danger", "Impossible de charger les alertes", err.message); }
}

function renderAlertsHistory(rows) {
  const tbody = document.querySelector("#table-alerts-history tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="4"><div class="empty-state"><strong>Aucune alerte</strong><span>Rien à signaler pour le moment.</span></div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map(a => `
    <tr>
      <td class="mono cell-muted">${fmtDate(a.ts || a.created_at)}</td>
      <td class="cell-primary">${escapeHtml(a.rule_key || a.rule || "—")}</td>
      <td>${statusBadge(a.severity === "critical" ? "disabled" : "idle")}</td>
      <td class="cell-muted">${escapeHtml(a.message || a.detail || "—")}</td>
    </tr>`).join("");
}

function renderDedupList(entries) {
  const el = document.getElementById("dedup-list");
  document.getElementById("dedup-hint").textContent = `${entries.length} règle(s) en cooldown`;
  if (!entries.length) {
    el.innerHTML = `<div class="empty-state"><strong>Aucune règle en cooldown</strong></div>`;
    return;
  }
  el.innerHTML = entries.map(e => `
    <div class="feed-item">
      <div class="feed-body">
        <div class="feed-title mono">${escapeHtml(e.rule_key)}</div>
        <div class="feed-meta">Dernier envoi il y a ${Math.floor((e.age_sec || 0) / 60)} min</div>
      </div>
      <button class="btn ghost sm" data-clear="${escapeHtml(e.rule_key)}">Effacer</button>
    </div>`).join("");
  el.querySelectorAll("[data-clear]").forEach(btn => btn.addEventListener("click", async () => {
    try { await apiSend("DELETE", `/api/alerts/dedup/${encodeURIComponent(btn.dataset.clear)}`); renderAlerts(); }
    catch (err) { toast("danger", "Échec", err.message); }
  }));
}

document.getElementById("btn-alert-config").addEventListener("click", async () => {
  try {
    const cfg = STATE.demoMode ? null : await apiGet("/api/alerts/config");
    renderAlertConfigForm(cfg);
    openModal("modal-alert-config");
  } catch (err) { toast("danger", "Impossible de charger la configuration", err.message); }
});

function renderAlertConfigForm(cfg) {
  const c = cfg || { rules: { inactive_days: 7 }, channels: { email: {}, telegram: {} } };
  document.getElementById("alert-config-body").innerHTML = `
    <div class="field"><label>Inactivité (jours) avant alerte</label>
      <input class="input" id="cfg-inactive-days" type="number" min="0" value="${c.rules?.inactive_days ?? 7}" /></div>
    <div class="field"><label>Webhook Slack</label>
      <input class="input" id="cfg-slack" placeholder="https://hooks.slack.com/…" value="${escapeHtml(c.channels?.slack_webhook_url || "")}" /></div>
    <div class="field"><label>Webhook Discord</label>
      <input class="input" id="cfg-discord" placeholder="https://discord.com/api/webhooks/…" value="${escapeHtml(c.channels?.discord_webhook_url || "")}" /></div>
    <div class="field"><label>E-mail destinataire</label>
      <input class="input" id="cfg-email-to" placeholder="ops@exemple.com" value="${escapeHtml(c.channels?.email?.to_addr || "")}" /></div>`;
}

document.getElementById("btn-save-alert-config").addEventListener("click", async () => {
  if (STATE.demoMode) { closeModal("modal-alert-config"); return toast("info", "Mode démonstration", "Enregistrement indisponible sans API connectée."); }
  const body = {
    rules: { inactive_days: parseInt(document.getElementById("cfg-inactive-days").value, 10) || 0 },
    channels: {
      slack_webhook_url: document.getElementById("cfg-slack").value.trim(),
      discord_webhook_url: document.getElementById("cfg-discord").value.trim(),
      email: { to_addr: document.getElementById("cfg-email-to").value.trim() },
    },
  };
  try {
    await apiSend("PATCH", "/api/alerts/config", body);
    toast("success", "Configuration enregistrée");
    closeModal("modal-alert-config");
  } catch (err) { toast("danger", "Échec de l'enregistrement", err.message); }
});

// ---------------------------------------------------------------
// VUE : Conformité
// ---------------------------------------------------------------
async function renderCompliance() {
  const el = document.getElementById("compliance-card");
  try {
    if (STATE.demoMode) {
      el.innerHTML = `<div class="empty-state"><strong>Mode démonstration</strong><span>Les contrôles de conformité nécessitent l'API connectée.</span></div>`;
      return;
    }
    const data = await apiGet("/api/compliance");
    const clients = data.clients || [];
    if (!clients.length) {
      el.innerHTML = `<div class="empty-state"><strong>Tout est conforme</strong><span>Aucun client inactif au-delà des seuils configurés.</span></div>`;
      return;
    }
    el.innerHTML = `<div class="table-wrap"><table class="data-table">
      <thead><tr><th>Client</th><th>IP</th><th>Jours d'inactivité</th><th>Seuil dépassé</th><th>Créé le</th></tr></thead>
      <tbody>${clients.map(c => `
        <tr>
          <td class="cell-primary">${escapeHtml(c.name)}</td>
          <td class="mono cell-muted">${escapeHtml(c.allowed_ips || "—")}</td>
          <td class="mono">${c.days_inactive ?? "—"}</td>
          <td>${c.bucket === "never" ? statusBadge("disabled") : `<span class="badge warning"><span class="dot"></span>${c.bucket}+ j</span>`}</td>
          <td class="cell-muted">${fmtDate(c.created)}</td>
        </tr>`).join("")}</tbody>
    </table></div>`;
  } catch (err) { el.innerHTML = `<div class="empty-state"><strong>Erreur</strong><span>${escapeHtml(err.message)}</span></div>`; }
}

// ---------------------------------------------------------------
// VUE : Système
// ---------------------------------------------------------------
async function renderSystem() {
  const tbody = document.querySelector("#table-backups tbody");
  if (STATE.demoMode) {
    tbody.innerHTML = `<tr><td colspan="2"><div class="empty-state"><strong>Mode démonstration</strong><span>Les opérations système nécessitent l'API connectée.</span></div></td></tr>`;
    return;
  }
  try {
    const data = await apiGet("/api/system/backups");
    const backups = data.backups || data || [];
    if (!backups.length) { tbody.innerHTML = `<tr><td colspan="2"><div class="empty-state"><strong>Aucune sauvegarde</strong></div></td></tr>`; return; }
    tbody.innerHTML = backups.map(b => `<tr><td class="mono cell-primary">${escapeHtml(b.filename || b.name)}</td><td class="cell-muted">${fmtDate(b.created_at || b.date)}</td></tr>`).join("");
  } catch (err) { tbody.innerHTML = `<tr><td colspan="2"><div class="empty-state"><strong>Erreur</strong><span>${escapeHtml(err.message)}</span></div></td></tr>`; }
}

document.getElementById("btn-backup-create").addEventListener("click", async () => {
  if (STATE.demoMode) return toast("info", "Mode démonstration");
  try { await apiSend("POST", "/api/system/backups", { label: "manuel" }); toast("success", "Sauvegarde créée"); renderSystem(); }
  catch (err) { toast("danger", "Échec", err.message); }
});
document.getElementById("btn-restart-tunnel").addEventListener("click", async () => {
  if (STATE.demoMode) return toast("info", "Mode démonstration");
  if (!confirm("Redémarrer le tunnel WireGuard maintenant ? Les clients seront brièvement déconnectés.")) return;
  try { await apiSend("POST", "/api/system/restart-tunnel"); toast("success", "Tunnel redémarré"); }
  catch (err) { toast("danger", "Échec", err.message); }
});
document.getElementById("btn-rotate-keys").addEventListener("click", async () => {
  if (STATE.demoMode) return toast("info", "Mode démonstration");
  if (!confirm("Régénérer les clés du serveur ? Tous les clients devront être reconfigurés.")) return;
  try { await apiSend("POST", "/api/system/rotate-server-keys"); toast("success", "Clés régénérées"); }
  catch (err) { toast("danger", "Échec", err.message); }
});
document.getElementById("btn-export").addEventListener("click", () => {
  if (STATE.demoMode) return toast("info", "Mode démonstration", "Export indisponible sans API connectée.");
  window.location.href = "/api/system/export";
});
document.getElementById("qa-export")?.addEventListener("click", () => document.getElementById("btn-export").click());

// ---------------------------------------------------------------
// VUE : Réglages
// ---------------------------------------------------------------
async function renderSettings() {
  try {
    const s = STATE.demoMode ? { online_threshold_sec: 120 } : await apiGet("/api/settings");
    document.getElementById("setting-online-threshold").value = s.online_threshold_sec ?? 120;
  } catch (err) { toast("danger", "Impossible de charger les réglages", err.message); }
}
document.getElementById("btn-save-settings").addEventListener("click", async () => {
  if (STATE.demoMode) return toast("info", "Mode démonstration");
  const value = parseInt(document.getElementById("setting-online-threshold").value, 10);
  try { await apiSend("PATCH", "/api/settings", { online_threshold_sec: value }); toast("success", "Réglages enregistrés"); }
  catch (err) { toast("danger", "Échec", err.message); }
});
