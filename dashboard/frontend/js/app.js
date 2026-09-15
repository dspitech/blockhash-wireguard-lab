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
  currentUser: { username: "?", role: "admin" },
  demoMode: null,          // null = inconnu, true/false une fois déterminé
  theme: localStorage.getItem("blockhash_theme") || "light",
  collapsed: localStorage.getItem("blockhash_sidebar_collapsed") === "1",
  currentView: "overview",
  overview: null,
  peers: [],
  clientsFilter: loadClientsFilter(),
  clientsSelected: new Set(),
  journal: { offset: 0, limit: 50, search: "", status: "all", total: 0 },
  alertsPage: { offset: 0, limit: 25 },
  throughputRange: "24h",
  clientManagementEnabled: false,
  charts: {},
  map: null,
  mapMarkers: [],
  sse: null,
};

const DEMO_URL = "data/sample-data.json";
const TOKEN_STORAGE_KEY = "blockhash_dashboard_token";
const CLIENTS_FILTER_STORAGE_KEY = "blockhash_clients_filter";

function loadClientsFilter() {
  const defaults = {
    status: "all", search: "", page: 1, pageSize: 25, sort: "name", sortDir: "asc",
    created: "", expiry: "", contact: "",
  };
  try {
    const saved = JSON.parse(localStorage.getItem(CLIENTS_FILTER_STORAGE_KEY) || "{}");
    return { ...defaults, ...saved, page: 1 }; // on ne persiste jamais la page courante
  } catch { return defaults; }
}
function saveClientsFilter() {
  const { status, search, pageSize, sort, sortDir, created, expiry, contact } = STATE.clientsFilter;
  localStorage.setItem(CLIENTS_FILTER_STORAGE_KEY, JSON.stringify({ status, search, pageSize, sort, sortDir, created, expiry, contact }));
}

// ---------------------------------------------------------------
// Couche API
// ---------------------------------------------------------------
function authHeaders() {
  const token = window.__BLOCKHASH_TOKEN__ || window.localStorage.getItem(TOKEN_STORAGE_KEY);
  return token ? { "X-API-Token": token } : {};
}

/**
 * Telecharge un fichier depuis une route /api/* protegee par jeton.
 * window.open()/window.location sur une URL /api ne transmet PAS le header
 * X-API-Token : la requete est alors rejetee en 401 et rien ne se passe,
 * sans le moindre message d'erreur visible (bug corrige - voir historique).
 * Cette fonction fait un fetch authentifie, puis declenche le telechargement
 * via un lien <a download> temporaire sur le blob recu.
 */
async function downloadWithAuth(url, filename) {
  try {
    const resp = await fetch(url, { headers: authHeaders() });
    if (!resp.ok) {
      let message = `Erreur API (${resp.status})`;
      try { message = (await resp.json()).error || message; } catch { /* reponse non-JSON, on garde le message par defaut */ }
      throw new Error(message);
    }
    const blob = await resp.blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = filename || "export";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objectUrl);
  } catch (err) {
    toast("danger", "Échec du téléchargement", err.message);
  }
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
    online: ["success", "status.online"],
    idle: ["warning", "status.idle"],
    never: ["neutral", "status.never"],
    disabled: ["danger", "status.disabled"],
  };
  const [cls, key] = map[status] || ["neutral", null];
  const label = key ? t(key) : (status || t("status.unknown"));
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

function resolvedTheme() {
  if (STATE.theme === "auto") {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return STATE.theme;
}

function applyTheme() {
  const resolved = resolvedTheme();
  document.documentElement.setAttribute("data-theme", resolved);
  const icon = document.getElementById("theme-icon");
  const btn = document.getElementById("btn-theme");
  if (STATE.theme === "auto") {
    icon.innerHTML = '<path d="M10 3a7 7 0 1 0 0 14V3Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" fill="currentColor" fill-opacity=".25"/><circle cx="10" cy="10" r="6.5" stroke="currentColor" stroke-width="1.4"/>';
    btn.title = "Thème : auto (suit le système) — cliquer pour clair";
  } else if (resolved === "dark") {
    icon.innerHTML = '<path d="M10 3v1.5M10 15.5V17M17 10h-1.5M4.5 10H3M14.8 5.2l-1 1M6.2 13.8l-1 1M14.8 14.8l-1-1M6.2 6.2l-1-1" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><circle cx="10" cy="10" r="3.4" stroke="currentColor" stroke-width="1.5"/>';
    btn.title = "Thème : sombre — cliquer pour auto";
  } else {
    icon.innerHTML = '<path d="M16.5 11.8A6.5 6.5 0 0 1 8.2 3.5 6.5 6.5 0 1 0 16.5 11.8Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>';
    btn.title = "Thème : clair — cliquer pour sombre";
  }
}
if (window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (STATE.theme === "auto") applyTheme(); });
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
  system: "Système", settings: "Réglages", users: "Utilisateurs", tokens: "Tokens API", help: "Aide", audit: "Journal d'audit",
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
    case "journal": renderJournal(); return renderJournalHeatmap();
    case "monitoring": return renderMonitoring();
    case "alerts": return renderAlerts();
    case "compliance": return renderCompliance();
    case "system": renderSystem(); return renderAuditPreview();
    case "audit": return renderAudit();
    case "settings": return renderSettings();
    case "users": return renderUsers();
    case "tokens": return renderTokens();
    case "help": return renderHelp();
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
const ROLE_RANK = { reader: 0, operator: 1, admin: 2 };
function applyRoleVisibility() {
  const role = (STATE.currentUser && STATE.currentUser.role) || "admin";
  document.querySelectorAll("[data-role-min]").forEach(el => {
    const required = el.getAttribute("data-role-min");
    el.hidden = (ROLE_RANK[role] ?? 2) < (ROLE_RANK[required] ?? 0);
  });
}

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
      try {
        STATE.currentUser = await apiGet("/api/auth/me");
      } catch { STATE.currentUser = { username: "?", role: "admin" }; }
      applyRoleVisibility();
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
  maybeShowOnboarding();
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
    // EventSource ne peut pas envoyer d'en-tete X-API-Token (contrairement a
    // fetch/apiGet) : le jeton doit etre passe en parametre d'URL, que le
    // backend accepte UNIQUEMENT pour cette route precise (voir
    // enforce_auth dans app.py). Sans ce parametre, chaque tentative de
    // connexion echoue en 401 et le navigateur la retente indefiniment
    // (EventSource se reconnecte automatiquement), inondant la console.
    const token = window.__BLOCKHASH_TOKEN__ || window.localStorage.getItem(TOKEN_STORAGE_KEY);
    const url = token ? `/api/events/stream?token=${encodeURIComponent(token)}` : "/api/events/stream";
    const src = new EventSource(url);
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
      maybeShowDesktopNotification("BLOCKHash - Alerte", d.message || d.rule_key || "Nouvelle alerte");
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

// ---------------------------------------------------------------
// Raccourcis clavier globaux
// ---------------------------------------------------------------
let _kbLastKey = null, _kbLastKeyTime = 0;
document.addEventListener("keydown", e => {
  const tag = (e.target.tagName || "").toLowerCase();
  const typing = tag === "input" || tag === "textarea" || e.target.isContentEditable;

  if (!typing && e.key === "/") {
    e.preventDefault();
    document.getElementById("global-search").focus();
    return;
  }
  if (!typing && e.key === "?") {
    e.preventDefault();
    toast("info", "Raccourcis clavier", "g c: Clients · g a: Alertes · g m: Monitoring · / : rechercher · Échap : fermer une modale");
    return;
  }
  if (e.key === "Escape") {
    document.querySelectorAll(".modal-overlay.is-open").forEach(m => closeModal(m.id));
    return;
  }
  if (typing) return;

  const now = Date.now();
  if (_kbLastKey === "g" && now - _kbLastKeyTime < 800) {
    const map = { c: "clients", a: "alerts", m: "monitoring" };
    if (map[e.key]) { e.preventDefault(); switchView(map[e.key]); }
    _kbLastKey = null;
    return;
  }
  if (e.key === "g") { _kbLastKey = "g"; _kbLastKeyTime = now; }
});

// ---------------------------------------------------------------
// i18n (item 57) : traduction de l'UI statique (nav, titres, boutons,
// en-tetes de colonnes, libelles de champs). Les messages generes cote
// serveur (alertes, journal d'audit, erreurs API) restent en francais -
// les traduire necessiterait que le backend gere aussi une locale, hors
// scope pour cette iteration (voir discussion avec l'utilisateur).
// ---------------------------------------------------------------
const I18N_STORAGE_KEY = "blockhash_lang";
let I18N_DICT = {};
let I18N_FALLBACK = {}; // francais, toujours charge en secours si une cle manque dans la langue active

async function loadTranslations(lang) {
  try {
    if (!Object.keys(I18N_FALLBACK).length) {
      I18N_FALLBACK = await fetch("i18n/fr.json").then(r => r.json());
    }
    I18N_DICT = lang === "fr" ? I18N_FALLBACK : await fetch(`i18n/${lang}.json`).then(r => r.json());
  } catch {
    I18N_DICT = I18N_FALLBACK; // echec reseau : on reste en francais plutot que d'afficher des cles brutes
  }
}

function t(key) {
  return I18N_DICT[key] || I18N_FALLBACK[key] || key;
}

function applyI18n() {
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const translated = t(el.getAttribute("data-i18n"));
    // Cherche le dernier noeud texte non-vide (permet de traduire le libelle
    // d'un bouton contenant une icone <svg> sans l'ecraser).
    let node = el.lastChild;
    while (node && !(node.nodeType === Node.TEXT_NODE && node.textContent.trim())) node = node.previousSibling;
    if (node) node.textContent = translated;
    else el.textContent = translated;
  });
  document.documentElement.lang = CURRENT_LANG;
}

let CURRENT_LANG = localStorage.getItem(I18N_STORAGE_KEY) || "fr";

async function setLanguage(lang) {
  CURRENT_LANG = lang;
  localStorage.setItem(I18N_STORAGE_KEY, lang);
  await loadTranslations(lang);
  applyI18n();
}

document.addEventListener("DOMContentLoaded", async () => {
  await loadTranslations(CURRENT_LANG);
  applyI18n();
  bootstrap();
});

// ---------------------------------------------------------------
// Comptes utilisateurs (item 49)
// ---------------------------------------------------------------
function fmtRole(role) {
  return { reader: "Lecteur", operator: "Opérateur", admin: "Admin" }[role] || role;
}

async function renderUsers() {
  const tbody = document.querySelector("#table-users tbody");
  try {
    const users = await apiGet("/api/users");
    tbody.innerHTML = users.map(u => `
      <tr>
        <td class="cell-primary">${escapeHtml(u.username)}${u.username === STATE.currentUser.username ? ' <span class="cell-muted">(vous)</span>' : ""}</td>
        <td>${fmtRole(u.role)}</td>
        <td>${u.active ? statusBadge("online") : statusBadge("disabled")}</td>
        <td class="cell-muted">${u.last_login_ts ? fmtDate(u.last_login_ts * 1000) : "jamais"}</td>
        <td>
          <div style="display:flex;gap:6px;">
            <button class="btn ghost sm" data-user-action="edit" data-username="${escapeHtml(u.username)}">Modifier</button>
            <button class="btn ghost sm" data-user-action="delete" data-username="${escapeHtml(u.username)}" ${u.username === STATE.currentUser.username ? "disabled" : ""}>Supprimer</button>
          </div>
        </td>
      </tr>`).join("");
    tbody.querySelectorAll('[data-user-action="edit"]').forEach(btn => btn.addEventListener("click", () => openUserModal(btn.dataset.username, users)));
    tbody.querySelectorAll('[data-user-action="delete"]').forEach(btn => btn.addEventListener("click", () => deleteUser(btn.dataset.username)));
  } catch (err) { tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><strong>Erreur</strong><span>${escapeHtml(err.message)}</span></div></td></tr>`; }
}

function openUserModal(username, users) {
  const user = username ? users.find(u => u.username === username) : null;
  document.getElementById("modal-user-title").textContent = user ? `Modifier ${username}` : "Ajouter un utilisateur";
  document.getElementById("field-user-username").value = username || "";
  document.getElementById("field-user-username").disabled = !!user;
  document.getElementById("field-user-password").value = "";
  document.getElementById("field-user-password").placeholder = user ? "Laisser vide pour ne pas changer" : "";
  document.getElementById("user-password-hint").textContent = user ? "(laisser vide pour ne pas changer)" : "(8 caractères minimum)";
  document.getElementById("field-user-role").value = user ? user.role : "reader";
  document.getElementById("field-user-active").checked = user ? !!user.active : true;
  document.getElementById("btn-confirm-user").dataset.editing = username || "";
  openModal("modal-user");
}
document.getElementById("btn-add-user").addEventListener("click", () => openUserModal(null, []));
document.getElementById("btn-confirm-user").addEventListener("click", async () => {
  const editing = document.getElementById("btn-confirm-user").dataset.editing;
  const username = document.getElementById("field-user-username").value.trim();
  const password = document.getElementById("field-user-password").value;
  const role = document.getElementById("field-user-role").value;
  const active = document.getElementById("field-user-active").checked;
  try {
    if (editing) {
      const body = { role, active };
      if (password) body.password = password;
      await apiSend("PATCH", `/api/users/${encodeURIComponent(editing)}`, body);
    } else {
      if (!username) return toast("danger", "Nom d'utilisateur requis");
      if (password.length < 8) return toast("danger", "Mot de passe trop court", "8 caractères minimum.");
      await apiSend("POST", "/api/users", { username, password, role });
    }
    toast("success", "Utilisateur enregistré");
    closeModal("modal-user");
    renderUsers();
  } catch (err) { toast("danger", "Échec", err.message); }
});
async function deleteUser(username) {
  if (!confirm(`Supprimer le compte « ${username} » ?`)) return;
  try { await apiSend("DELETE", `/api/users/${encodeURIComponent(username)}`); toast("success", "Utilisateur supprimé"); renderUsers(); }
  catch (err) { toast("danger", "Échec", err.message); }
}

// ---------------------------------------------------------------
// Tokens API (item 52)
// ---------------------------------------------------------------
async function renderTokens() {
  const tbody = document.querySelector("#table-tokens tbody");
  try {
    const tokens = await apiGet("/api/tokens");
    const active = tokens.filter(t => !t.revoked);
    tbody.innerHTML = active.length ? active.map(t => `
      <tr>
        <td class="cell-primary">${escapeHtml(t.name)}</td>
        <td>${fmtRole(t.scope)}</td>
        <td class="cell-muted">${escapeHtml(t.created_by || "—")}</td>
        <td class="cell-muted">${t.expires_ts ? fmtDate(t.expires_ts * 1000) : "jamais"}</td>
        <td class="cell-muted">${t.last_used_ts ? fmtDate(t.last_used_ts * 1000) : "jamais"}</td>
        <td><button class="btn ghost sm" data-token-revoke="${t.rowid}">Révoquer</button></td>
      </tr>`).join("") : `<tr><td colspan="6"><div class="empty-state"><strong>Aucun token actif</strong></div></td></tr>`;
    tbody.querySelectorAll("[data-token-revoke]").forEach(btn => btn.addEventListener("click", async () => {
      if (!confirm("Révoquer ce token ? Toute intégration qui l'utilise cessera de fonctionner immédiatement.")) return;
      try { await apiSend("DELETE", `/api/tokens/${btn.dataset.tokenRevoke}`); toast("success", "Token révoqué"); renderTokens(); }
      catch (err) { toast("danger", "Échec", err.message); }
    }));
  } catch (err) { tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><strong>Erreur</strong><span>${escapeHtml(err.message)}</span></div></td></tr>`; }
}
document.getElementById("btn-add-token").addEventListener("click", () => {
  document.getElementById("field-token-name").value = "";
  document.getElementById("field-token-scope").value = "reader";
  document.getElementById("field-token-expires-days").value = "";
  openModal("modal-new-token");
});
document.getElementById("btn-confirm-token").addEventListener("click", async () => {
  const name = document.getElementById("field-token-name").value.trim();
  const scope = document.getElementById("field-token-scope").value;
  const expiresDays = document.getElementById("field-token-expires-days").value;
  if (!name) return toast("danger", "Un nom est requis");
  try {
    const result = await apiSend("POST", "/api/tokens", { name, scope, expires_days: expiresDays ? parseInt(expiresDays, 10) : null });
    closeModal("modal-new-token");
    document.getElementById("field-new-token-value").value = result.token;
    openModal("modal-token-created");
    renderTokens();
  } catch (err) { toast("danger", "Échec de la génération", err.message); }
});
document.getElementById("btn-copy-new-token").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(document.getElementById("field-new-token-value").value); toast("success", "Copié"); }
  catch { toast("danger", "Impossible de copier"); }
});

document.getElementById("btn-help").addEventListener("click", () => {
  switchView("help");
});
document.getElementById("btn-feedback").addEventListener("click", () => {
  const context = `Page actuelle : ${STATE.currentView || "inconnue"}\nNavigateur : ${navigator.userAgent}\nURL : ${window.location.href}`;
  const subject = encodeURIComponent("[BLOCKHash] Signalement");
  const body = encodeURIComponent(`Décrivez le problème ou la suggestion ici :\n\n\n---\nContexte technique (pré-rempli, ne pas modifier) :\n${context}`);
  window.open(`mailto:?subject=${subject}&body=${body}`, "_blank");
});

const ONBOARDING_FLAG_KEY = "blockhash_onboarded_v1";
async function maybeShowOnboarding() {
  if (localStorage.getItem(ONBOARDING_FLAG_KEY) || STATE.demoMode) return;
  localStorage.setItem(ONBOARDING_FLAG_KEY, "1");
  openModal("modal-onboarding");
  const el = document.getElementById("onboarding-checks");
  try {
    const data = await apiGet("/api/system/diagnostics");
    el.innerHTML = data.checks.slice(0, 4).map(c => `<div>${c.ok ? "✅" : "⚠️"} ${escapeHtml(c.name)}</div>`).join("");
  } catch {
    el.innerHTML = `<span class="cell-muted">Diagnostic non disponible pour le moment — tout le reste du dashboard fonctionne normalement.</span>`;
  }
}

// ---------------------------------------------------------------
// Aide (item B1) : cartes thematiques -> modale de detail pas-a-pas
// ---------------------------------------------------------------
const HELP_TOPICS = [
  {
    id: "create-client", title: "Créer un client", icon: "👤",
    summary: "Ajouter un nouveau client WireGuard et récupérer sa configuration.",
    steps: [
      "Ouvrez la page <strong>Clients</strong>.",
      "Cliquez sur <strong>Ajouter un client</strong> en haut à droite.",
      "Renseignez le nom (obligatoire) et, si besoin, les champs de contact (email, téléphone, fonction…) et une date d'expiration.",
      "Cliquez sur <strong>Créer</strong> : les clés WireGuard et l'adresse IP sont générées automatiquement.",
      "Utilisez le bouton <strong>QR</strong> pour scanner directement depuis l'app mobile WireGuard, ou <strong>Config</strong> pour télécharger le fichier <code>.conf</code>.",
    ],
  },
  {
    id: "bulk-import", title: "Importer des clients en masse", icon: "📥",
    summary: "Créer plusieurs clients d'un coup, en collant une liste ou en important un CSV.",
    steps: [
      "Sur la page <strong>Clients</strong>, cliquez sur <strong>Ajouter plusieurs clients</strong>.",
      "Onglet <strong>Coller une liste</strong> : un client par ligne (<code>nom,email,téléphone</code>).",
      "Onglet <strong>Importer un fichier CSV</strong> : téléchargez d'abord le modèle, remplissez-le, puis importez-le.",
      "Cliquez sur <strong>Aperçu (dry-run)</strong> pour valider le contenu sans rien créer.",
      "Si tout est correct, cliquez sur <strong>Créer les clients</strong>. Un rapport indique les lignes en erreur le cas échéant.",
    ],
  },
  {
    id: "download-config", title: "Télécharger une configuration", icon: "⬇️",
    summary: "Récupérer le fichier .conf ou le QR code d'un client existant.",
    steps: [
      "Page <strong>Clients</strong>, repérez la ligne du client concerné.",
      "Bouton <strong>Config</strong> : télécharge le fichier <code>.conf</code> prêt à importer dans l'application WireGuard.",
      "Bouton <strong>QR</strong> : affiche le QR code à scanner depuis un mobile, avec option de téléchargement en PNG ou de copie du texte de config.",
    ],
  },
  {
    id: "view-logs", title: "Consulter les logs", icon: "📜",
    summary: "Explorer l'historique des connexions et sessions.",
    steps: [
      "Ouvrez la page <strong>Journal</strong>.",
      "Utilisez la recherche et le filtre de statut pour restreindre l'affichage.",
      "Cliquez sur <strong>Filtres avancés</strong> pour affiner par plage de dates ou par volume.",
      "Cliquez sur une ligne pour voir le détail complet d'une session (endpoint, clé publique, volumes).",
      "La <strong>heatmap</strong> en bas de page montre les créneaux horaires les plus actifs sur 30 jours.",
    ],
  },
  {
    id: "create-alert", title: "Créer une alerte", icon: "🔔",
    summary: "Configurer les règles et canaux de notification.",
    steps: [
      "Ouvrez la page <strong>Alertes</strong> puis cliquez sur <strong>Configurer les canaux</strong>.",
      "Activez les alertes automatiques, puis cochez les règles souhaitées (connexion/déconnexion, hors-horaires, inactivité, expiration proche…).",
      "Renseignez au moins un canal de notification (webhook Slack/Discord, e-mail) et testez-le avec le bouton <strong>Tester</strong>.",
      "Enregistrez : les alertes déclenchées apparaissent ensuite dans l'historique, avec filtres et export CSV.",
    ],
  },
  {
    id: "restore-backup", title: "Restaurer une sauvegarde", icon: "🗄️",
    summary: "Revenir à une configuration antérieure du tunnel.",
    steps: [
      "Ouvrez la page <strong>Système</strong>.",
      "Repérez la sauvegarde souhaitée dans la liste (date, description, empreinte SHA-256).",
      "Cliquez sur <strong>Restaurer</strong>, saisissez votre mot de passe et tapez <strong>RESTORE</strong> pour confirmer.",
      "Une sauvegarde de sécurité de l'état actuel est créée automatiquement avant toute restauration, pour pouvoir annuler si besoin.",
    ],
  },
  {
    id: "manage-users", title: "Gérer les utilisateurs", icon: "🔑",
    summary: "Ajouter des comptes, définir des rôles, générer des tokens API.",
    steps: [
      "Ouvrez la page <strong>Utilisateurs</strong> (réservée aux comptes admin).",
      "Cliquez sur <strong>Ajouter un utilisateur</strong>, choisissez un rôle : lecteur, opérateur ou admin.",
      "Pour désactiver ou changer le rôle d'un compte, utilisez <strong>Modifier</strong> sur sa ligne.",
      "Pour l'automatisation, générez un <strong>Token API</strong> scopé depuis la page dédiée — il ne s'affiche qu'une seule fois, copiez-le immédiatement.",
    ],
  },
];

function renderHelp() {
  const grid = document.getElementById("help-cards-grid");
  grid.innerHTML = HELP_TOPICS.map(topic => `
    <button class="help-card" data-help-topic="${topic.id}">
      <span class="help-card-icon">${topic.icon}</span>
      <span class="help-card-title">${escapeHtml(topic.title)}</span>
      <span class="help-card-summary">${escapeHtml(topic.summary)}</span>
    </button>`).join("");
  grid.querySelectorAll("[data-help-topic]").forEach(btn => btn.addEventListener("click", () => openHelpDetail(btn.dataset.helpTopic)));
}

function openHelpDetail(topicId) {
  const topic = HELP_TOPICS.find(t => t.id === topicId);
  if (!topic) return;
  document.getElementById("help-detail-title").textContent = topic.title;
  document.getElementById("help-detail-body").innerHTML = `<ol class="help-steps">${topic.steps.map(s => `<li>${s}</li>`).join("")}</ol>`;
  openModal("modal-help-detail");
}

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
  const next = { light: "dark", dark: "auto", auto: "light" };
  STATE.theme = next[STATE.theme] || "light";
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
  if (typeof ChartZoom !== "undefined" && !Chart.registry.plugins.get("zoom")) {
    Chart.register(ChartZoom);
  }
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
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: c => `${c.dataset.label}: ${fmtBytes(c.parsed.y)}` } },
        zoom: typeof ChartZoom === "undefined" ? undefined : {
          // Molette = zoom, glisser = pan (item 33). Pas de pincement tactile
          // (necessiterait de vendoriser hammerjs en plus - non fait, cout/
          // benefice faible pour un dashboard majoritairement desktop).
          zoom: { wheel: { enabled: true }, pinch: { enabled: false }, mode: "x" },
          pan: { enabled: true, mode: "x" },
          limits: { x: { minRange: 5 } },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: chartTextColor(), font: { size: 10 }, maxTicksLimit: 8 } },
        y: { grid: { color: chartGridColor() }, ticks: { color: chartTextColor(), font: { size: 10 }, callback: v => fmtBytes(v) } },
      },
    },
  });
}
document.getElementById("btn-chart-reset-zoom")?.addEventListener("click", () => {
  const chart = STATE.charts["chart-longterm"];
  if (chart && chart.resetZoom) chart.resetZoom();
});

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

function clientMatchesAdvanced(p, f) {
  if (f.created) {
    if (!p.created) return false;
    const days = (Date.now() - new Date(p.created).getTime()) / 86400000;
    if (f.created === "today" && days > 1) return false;
    if (f.created === "7d" && days > 7) return false;
    if (f.created === "30d" && days > 30) return false;
  }
  if (f.expiry) {
    if (!p.expires) return false;
    const days = (new Date(p.expires).getTime() - Date.now()) / 86400000;
    if (f.expiry === "expired" && days > 0) return false;
    if (f.expiry === "7d" && (days < 0 || days > 7)) return false;
    if (f.expiry === "30d" && (days < 0 || days > 30)) return false;
  }
  if (f.contact === "email" && !p.email) return false;
  if (f.contact === "telephone" && !p.telephone) return false;
  return true;
}

function filteredClients() {
  const f = STATE.clientsFilter;
  let rows = STATE.peers.slice();
  if (f.status !== "all") rows = rows.filter(p => peerStatus(p) === f.status);
  if (f.search) {
    const q = f.search.toLowerCase();
    rows = rows.filter(p =>
      (p.name || "").toLowerCase().includes(q) ||
      (p.email || "").toLowerCase().includes(q) ||
      (p.allowed_ips || "").includes(q) ||
      (p.endpoint || "").includes(q)
    );
  }
  rows = rows.filter(p => clientMatchesAdvanced(p, f));

  const dir = f.sortDir === "desc" ? -1 : 1;
  rows.sort((a, b) => {
    let va = a[f.sort], vb = b[f.sort];
    if (f.sort === "name") { va = (va || "").toLowerCase(); vb = (vb || "").toLowerCase(); }
    else { va = va || 0; vb = vb || 0; }
    if (va < vb) return -1 * dir;
    if (va > vb) return 1 * dir;
    return 0;
  });
  return rows;
}

function updateClientsChipCounts() {
  const all = STATE.peers;
  const counts = { all: all.length, online: 0, idle: 0, disabled: 0 };
  all.forEach(p => { const s = peerStatus(p); if (s in counts) counts[s]++; });
  document.querySelectorAll("#clients-status-filter .chip-count").forEach(el => {
    el.textContent = `(${counts[el.dataset.count] ?? 0})`;
  });
}

function drawClientsTable() {
  const f = STATE.clientsFilter;
  const rows = filteredClients();
  updateClientsChipCounts();
  document.getElementById("clients-filtered-count").textContent = rows.length;

  const pageCount = Math.max(1, Math.ceil(rows.length / f.pageSize));
  f.page = Math.min(f.page, pageCount);
  const start = (f.page - 1) * f.pageSize;
  const pageRows = rows.slice(start, start + f.pageSize);

  document.getElementById("clients-page-indicator").textContent =
    rows.length ? `${start + 1}–${Math.min(start + f.pageSize, rows.length)} sur ${rows.length}` : "0–0 sur 0";
  document.getElementById("clients-prev").disabled = f.page <= 1;
  document.getElementById("clients-next").disabled = f.page >= pageCount;

  const tbody = document.querySelector("#table-clients tbody");
  if (!pageRows.length) {
    tbody.innerHTML = `<tr><td colspan="10"><div class="empty-state">
      <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="7" r="3" stroke="currentColor" stroke-width="1.4"/><path d="M4.5 17c0-3.3 2.5-5.5 5.5-5.5s5.5 2.2 5.5 5.5" stroke="currentColor" stroke-width="1.4"/></svg>
      <strong>Aucun client ne correspond</strong><span>Ajustez les filtres ou ajoutez un nouveau client.</span>
    </div></td></tr>`;
    updateBulkBar();
    return;
  }
  tbody.innerHTML = pageRows.map(p => `
    <tr>
      <td><input type="checkbox" class="client-select" data-name="${escapeHtml(p.name)}" ${STATE.clientsSelected.has(p.name) ? "checked" : ""} /></td>
      <td class="row-flex"><span class="peer-avatar">${initials(p.name)}</span><span class="cell-primary">${escapeHtml(p.name)}</span></td>
      <td>${statusBadge(peerStatus(p))}</td>
      <td class="cell-muted">${escapeHtml(p.email || p.telephone || "—")}</td>
      <td class="mono cell-muted">${escapeHtml(p.allowed_ips || "—")}</td>
      <td class="mono cell-muted">${escapeHtml(p.endpoint || "—")}</td>
      <td class="mono cell-muted">${fmtBytes(p.rx_bytes)} / ${fmtBytes(p.tx_bytes)}</td>
      <td class="cell-muted">${fmtDate(p.created)}</td>
      <td class="cell-muted">${p.expires ? fmtDate(p.expires) : "—"}</td>
      <td>
        <div class="row-actions">
          <button class="icon-btn sm" data-action="toggle" data-name="${escapeHtml(p.name)}" data-enabled="${p.enabled}" title="${p.enabled ? "Désactiver" : "Activer"}">
            ${p.enabled
              ? '<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.5"/><path d="M7 10h6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>'
              : '<svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="7" stroke="currentColor" stroke-width="1.5"/><path d="M10 7v6M7 10h6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>'}
          </button>
          <div class="kebab-wrap">
            <button class="icon-btn sm" data-action="kebab-toggle" title="Plus d'actions">
              <svg viewBox="0 0 20 20" fill="none"><circle cx="10" cy="4.5" r="1.3" fill="currentColor"/><circle cx="10" cy="10" r="1.3" fill="currentColor"/><circle cx="10" cy="15.5" r="1.3" fill="currentColor"/></svg>
            </button>
            <div class="kebab-menu" hidden>
              <button data-action="edit" data-name="${escapeHtml(p.name)}">
                <svg viewBox="0 0 20 20" fill="none"><path d="M13.5 3.5 16.5 6.5 7 16H4V13L13.5 3.5Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>
                Modifier
              </button>
              <button data-action="detail" data-name="${escapeHtml(p.name)}">
                <svg viewBox="0 0 20 20" fill="none"><path d="M4 10c1.5-3.5 4-5 6-5s4.5 1.5 6 5c-1.5 3.5-4 5-6 5s-4.5-1.5-6-5Z" stroke="currentColor" stroke-width="1.4"/><circle cx="10" cy="10" r="1.8" stroke="currentColor" stroke-width="1.4"/></svg>
                Détails
              </button>
              <button data-action="qr" data-name="${escapeHtml(p.name)}">
                <svg viewBox="0 0 20 20" fill="none"><rect x="3" y="3" width="5" height="5" stroke="currentColor" stroke-width="1.4"/><rect x="12" y="3" width="5" height="5" stroke="currentColor" stroke-width="1.4"/><rect x="3" y="12" width="5" height="5" stroke="currentColor" stroke-width="1.4"/><rect x="12.5" y="12.5" width="1.8" height="1.8" fill="currentColor"/><rect x="15.5" y="12.5" width="1.8" height="1.8" fill="currentColor"/><rect x="12.5" y="15.5" width="1.8" height="1.8" fill="currentColor"/><rect x="15.5" y="15.5" width="1.8" height="1.8" fill="currentColor"/></svg>
                QR code
              </button>
              <button data-action="config" data-name="${escapeHtml(p.name)}">
                <svg viewBox="0 0 20 20" fill="none"><path d="M10 3v9M6.5 9 10 12.5 13.5 9" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M4 14v2.5h12V14" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>
                Config (.conf)
              </button>
              <button data-action="regenerate" data-name="${escapeHtml(p.name)}">
                <svg viewBox="0 0 20 20" fill="none"><path d="M16 10a6 6 0 1 1-1.8-4.3M16 3.5V7h-3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
                Régénérer les clés
              </button>
              <button data-action="revoke" data-name="${escapeHtml(p.name)}" class="danger">
                <svg viewBox="0 0 20 20" fill="none"><path d="M4 6h12M8 6V4.5h4V6M6 6v9.5h8V6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>
                Révoquer
              </button>
            </div>
          </div>
        </div>
      </td>
    </tr>
  `).join("");

  tbody.querySelectorAll('[data-action="kebab-toggle"]').forEach(btn => btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const menu = btn.parentElement.querySelector(".kebab-menu");
    const wasOpen = !menu.hidden;
    document.querySelectorAll(".kebab-menu").forEach(m => m.hidden = true);
    menu.hidden = wasOpen;
  }));
  if (!STATE._kebabDocListenerAttached) {
    document.addEventListener("click", () => document.querySelectorAll(".kebab-menu").forEach(m => m.hidden = true));
    STATE._kebabDocListenerAttached = true;
  }
  tbody.querySelectorAll('[data-action="toggle"]').forEach(btn => btn.addEventListener("click", () => toggleClient(btn.dataset.name, btn.dataset.enabled === "true")));
  tbody.querySelectorAll('[data-action="edit"]').forEach(btn => btn.addEventListener("click", () => openEditClientModal(btn.dataset.name)));
  tbody.querySelectorAll('[data-action="detail"]').forEach(btn => btn.addEventListener("click", () => showClientDetail(btn.dataset.name)));
  tbody.querySelectorAll('[data-action="qr"]').forEach(btn => btn.addEventListener("click", () => showClientQr(btn.dataset.name)));
  tbody.querySelectorAll('[data-action="config"]').forEach(btn => btn.addEventListener("click", () => downloadClientConfig(btn.dataset.name)));
  tbody.querySelectorAll('[data-action="regenerate"]').forEach(btn => btn.addEventListener("click", () => regenerateClient(btn.dataset.name)));
  tbody.querySelectorAll('[data-action="revoke"]').forEach(btn => btn.addEventListener("click", () => revokeClient(btn.dataset.name)));
  tbody.querySelectorAll(".client-select").forEach(cb => cb.addEventListener("change", () => {
    if (cb.checked) STATE.clientsSelected.add(cb.dataset.name); else STATE.clientsSelected.delete(cb.dataset.name);
    updateBulkBar();
  }));
  updateBulkBar();
}

function updateBulkBar() {
  const n = STATE.clientsSelected.size;
  document.getElementById("clients-bulk-bar").hidden = n === 0;
  document.getElementById("clients-selected-count").textContent = n;
  document.getElementById("clients-select-all").checked =
    n > 0 && document.querySelectorAll(".client-select").length > 0 &&
    document.querySelectorAll(".client-select:checked").length === document.querySelectorAll(".client-select").length;
}
document.getElementById("clients-select-all").addEventListener("change", e => {
  document.querySelectorAll(".client-select").forEach(cb => {
    cb.checked = e.target.checked;
    if (e.target.checked) STATE.clientsSelected.add(cb.dataset.name); else STATE.clientsSelected.delete(cb.dataset.name);
  });
  updateBulkBar();
});
document.getElementById("btn-clear-selection").addEventListener("click", () => {
  STATE.clientsSelected.clear();
  drawClientsTable();
});
document.querySelectorAll("[data-bulk-do]").forEach(btn => {
  btn.addEventListener("click", async () => {
    const action = btn.dataset.bulkDo;
    const names = Array.from(STATE.clientsSelected);
    if (!names.length) return;
    if (action === "export") {
      const rows = STATE.peers.filter(p => STATE.clientsSelected.has(p.name));
      const header = "name,status,allowed_ips,email,telephone";
      const csv = [header, ...rows.map(p => [p.name, p.enabled ? peerStatus(p) : "disabled", p.allowed_ips || "", p.email || "", p.telephone || ""].join(","))].join("\n");
      const blob = new Blob([csv], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = "clients-selection.csv";
      document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
      return;
    }
    if (action === "revoke" && !confirm(`Révoquer définitivement ${names.length} client(s) ?`)) return;
    if (STATE.demoMode) return toast("info", "Mode démonstration", "Action indisponible sans API connectée.");
    let okCount = 0, errCount = 0;
    for (const name of names) {
      try {
        if (action === "enable") await apiSend("PATCH", `/api/clients/${encodeURIComponent(name)}`, { enabled: true });
        else if (action === "disable") await apiSend("PATCH", `/api/clients/${encodeURIComponent(name)}`, { enabled: false });
        else if (action === "revoke") await apiSend("DELETE", `/api/clients/${encodeURIComponent(name)}`);
        okCount++;
      } catch { errCount++; }
    }
    toast(errCount ? "warning" : "success", `${okCount} client(s) traité(s)`, errCount ? `${errCount} échec(s).` : "");
    STATE.clientsSelected.clear();
    renderClients();
  });
});

function showClientDetail(name) {
  if (STATE.demoMode) return toast("info", "Mode démonstration", "Action indisponible sans API connectée.");
  document.getElementById("detail-client-title").textContent = `Détail — ${name}`;
  document.getElementById("detail-client-body").innerHTML = `<div class="empty-state"><strong>Chargement…</strong></div>`;
  openModal("modal-client-detail");
  apiGet(`/api/clients/${encodeURIComponent(name)}/history?range=24h`).then(data => {
    const peer = STATE.peers.find(p => p.name === name) || {};
    const lastSeen = peer.last_handshake ? fmtDate(peer.last_handshake) : "jamais";
    document.getElementById("detail-client-body").innerHTML = `
      <div class="grid-2" style="margin-bottom:14px;">
        <div><span class="cell-muted">Statut</span><div>${statusBadge(peerStatus(peer))}</div></div>
        <div><span class="cell-muted">Dernier handshake</span><div>${lastSeen}</div></div>
        <div><span class="cell-muted">Reconnexions (24h)</span><div class="cell-primary">${data.reconnect_count ?? 0}</div></div>
        <div><span class="cell-muted">Dernier endpoint</span><div class="mono">${escapeHtml(data.last_endpoint || "—")}</div></div>
      </div>
      <h4 style="margin:12px 0 6px;">Sessions récentes</h4>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>Horodatage</th><th>Endpoint</th><th>Rx / Tx</th></tr></thead>
          <tbody>${(data.logs || []).slice(0, 20).map(l => `<tr><td class="mono cell-muted">${fmtDate(l.ts)}</td><td class="mono cell-muted">${escapeHtml(l.endpoint || "—")}</td><td class="mono cell-muted">${fmtBytes(l.rx_bytes)} / ${fmtBytes(l.tx_bytes)}</td></tr>`).join("") || `<tr><td colspan="3" class="cell-muted">Aucune session enregistrée.</td></tr>`}</tbody>
        </table>
      </div>`;
  }).catch(err => {
    document.getElementById("detail-client-body").innerHTML = `<div class="empty-state"><strong>Erreur</strong><span>${escapeHtml(err.message)}</span></div>`;
  });
}

document.getElementById("clients-prev").addEventListener("click", () => { STATE.clientsFilter.page--; drawClientsTable(); });
document.getElementById("clients-next").addEventListener("click", () => { STATE.clientsFilter.page++; drawClientsTable(); });
document.getElementById("clients-page-size").addEventListener("change", e => {
  STATE.clientsFilter.pageSize = parseInt(e.target.value, 10);
  STATE.clientsFilter.page = 1;
  saveClientsFilter();
  drawClientsTable();
});
document.getElementById("btn-toggle-advanced-filters").addEventListener("click", () => {
  const panel = document.getElementById("clients-advanced-filters");
  panel.hidden = !panel.hidden;
});
["filter-created", "filter-expiry", "filter-contact"].forEach(id => {
  document.getElementById(id).addEventListener("change", e => {
    const key = id.replace("filter-", "");
    STATE.clientsFilter[key] = e.target.value;
    STATE.clientsFilter.page = 1;
    saveClientsFilter();
    drawClientsTable();
  });
});
document.getElementById("filter-sort").addEventListener("change", e => {
  STATE.clientsFilter.sort = e.target.value;
  saveClientsFilter();
  drawClientsTable();
});
document.getElementById("btn-reset-filters").addEventListener("click", () => {
  localStorage.removeItem(CLIENTS_FILTER_STORAGE_KEY);
  STATE.clientsFilter = loadClientsFilter();
  document.getElementById("clients-search").value = "";
  document.getElementById("filter-created").value = "";
  document.getElementById("filter-expiry").value = "";
  document.getElementById("filter-contact").value = "";
  document.getElementById("filter-sort").value = "name";
  document.querySelectorAll("#clients-status-filter .chip").forEach(c => c.classList.toggle("is-active", c.dataset.status === "all"));
  drawClientsTable();
});
document.querySelectorAll("#table-clients [data-client-sort]").forEach(th => {
  th.style.cursor = "pointer";
  th.addEventListener("click", () => {
    const key = th.dataset.clientSort;
    const f = STATE.clientsFilter;
    f.sortDir = (f.sort === key && f.sortDir === "asc") ? "desc" : "asc";
    f.sort = key;
    saveClientsFilter();
    drawClientsTable();
  });
});

function showClientQr(name) {
  if (STATE.demoMode) return toast("info", "Mode démonstration", "Action indisponible sans API connectée.");
  document.getElementById("modal-qr-title").textContent = `QR code — ${name}`;
  const img = document.getElementById("qr-image");
  img.removeAttribute("src");
  openModal("modal-client-qr");
  apiGet(`/api/clients/${encodeURIComponent(name)}/config`).then(data => {
    img.src = `data:image/png;base64,${data.qr_base64}`;
    img.dataset.filename = `${name}-qrcode.png`;
    document.getElementById("btn-download-qr").dataset.filename = `${name}-qrcode.png`;
    document.getElementById("btn-download-qr").dataset.base64 = data.qr_base64;
    document.getElementById("btn-copy-config").dataset.conf = data.conf_text;
    document.getElementById("btn-download-conf-from-qr").dataset.name = name;
    document.getElementById("btn-download-conf-from-qr").dataset.conf = data.conf_text;
  }).catch(err => { closeModal("modal-client-qr"); toast("danger", "Échec du chargement du QR code", err.message); });
}
document.getElementById("btn-download-qr").addEventListener("click", e => {
  const b64 = e.target.dataset.base64;
  if (!b64) return;
  const a = document.createElement("a");
  a.href = `data:image/png;base64,${b64}`;
  a.download = e.target.dataset.filename || "qrcode.png";
  document.body.appendChild(a); a.click(); a.remove();
});
document.getElementById("btn-copy-config").addEventListener("click", async e => {
  const conf = e.target.dataset.conf;
  if (!conf) return;
  try { await navigator.clipboard.writeText(conf); toast("success", "Configuration copiée dans le presse-papier"); }
  catch { toast("danger", "Impossible de copier (accès presse-papier refusé)"); }
});
document.getElementById("btn-download-conf-from-qr").addEventListener("click", e => {
  const conf = e.target.dataset.conf, name = e.target.dataset.name;
  if (!conf) return;
  const blob = new Blob([conf], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `${name}.conf`;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
});

document.getElementById("btn-export-clients").addEventListener("click", () => {
  const status = STATE.clientsFilter.status;
  downloadWithAuth(`/api/clients/export?status=${encodeURIComponent(status)}`, "clients.csv");
});

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
  document.getElementById("field-edit-rgpd-consent").checked = !!(peer && peer.rgpd_consent);
  ["prenom", "email", "telephone", "adresse", "tags", "notes", "fonction"].forEach(f => {
    const el = document.getElementById(`field-edit-${f}`);
    if (el) el.value = (peer && peer[f]) || "";
  });
  openModal("modal-client-edit");
}
document.getElementById("btn-gdpr-export").addEventListener("click", () => {
  const name = document.getElementById("field-edit-name").dataset.originalName;
  if (!name) return;
  downloadWithAuth(`/api/clients/${encodeURIComponent(name)}/gdpr-export`, `${name}-export-rgpd.json`);
});

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
  ["prenom", "email", "telephone", "adresse", "tags", "notes", "fonction"].forEach(f => {
    const el = document.getElementById(`field-edit-${f}`);
    if (el) body[f] = el.value.trim();
  });
  body.rgpd_consent = document.getElementById("field-edit-rgpd-consent").checked;

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
    toast("success", `Configuration de ${name} téléchargée`, "Le bouton « QR » affiche aussi le code d'appairage.");
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
    STATE.clientsFilter.page = 1;
    saveClientsFilter();
    drawClientsTable();
  });
});
document.getElementById("clients-search").addEventListener("input", e => {
  STATE.clientsFilter.search = e.target.value.trim();
  STATE.clientsFilter.page = 1;
  saveClientsFilter();
  drawClientsTable();
});
document.getElementById("btn-add-client").addEventListener("click", () => {
  document.getElementById("modal-client-title").textContent = "Ajouter un client";
  document.getElementById("field-client-name").value = "";
  document.getElementById("field-client-expires").value = "";
  document.getElementById("field-client-rgpd-consent").checked = false;
  ["prenom", "email", "telephone", "adresse", "tags", "notes", "fonction"].forEach(f => {
    const el = document.getElementById(`field-client-${f}`);
    if (el) el.value = "";
  });
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
    const body = { name, expires_days: expiresDays, rgpd_consent: document.getElementById("field-client-rgpd-consent").checked };
    ["prenom", "email", "telephone", "adresse", "tags", "notes", "fonction"].forEach(f => {
      const el = document.getElementById(`field-client-${f}`);
      if (el && el.value.trim()) body[f] = el.value.trim();
    });
    await apiSend("POST", "/api/clients", body);
    toast("success", `Client ${name} créé`);
    closeModal("modal-client");
    renderClients();
  } catch (err) { toast("danger", "Échec de la création", err.message); }
});

// ---------------------------------------------------------------
// Ajout multiple / import CSV
// ---------------------------------------------------------------
function parseCsv(text) {
  // Parseur CSV minimal (gere les guillemets doubles) - suffisant pour le
  // format simple du modele (pas de RFC4180 complet, pas de retours a la
  // ligne a l'interieur d'un champ).
  const lines = text.split(/\r?\n/).filter(l => l.trim().length);
  if (!lines.length) return [];
  const splitLine = line => {
    const cells = []; let cur = ""; let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (inQuotes) {
        if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; }
        else if (c === '"') inQuotes = false;
        else cur += c;
      } else if (c === '"') inQuotes = true;
      else if (c === ',') { cells.push(cur); cur = ""; }
      else cur += c;
    }
    cells.push(cur);
    return cells.map(c => c.trim());
  };
  const header = splitLine(lines[0]).map(h => h.toLowerCase());
  return lines.slice(1).map(line => {
    const cells = splitLine(line);
    const row = {};
    header.forEach((h, i) => { row[h] = cells[i] || ""; });
    return row;
  });
}

let _bulkParsedRows = [];

document.querySelectorAll("[data-bulk-tab]").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("[data-bulk-tab]").forEach(t => t.classList.remove("is-active"));
    tab.classList.add("is-active");
    document.getElementById("bulk-tab-paste").hidden = tab.dataset.bulkTab !== "paste";
    document.getElementById("bulk-tab-import").hidden = tab.dataset.bulkTab !== "import";
    document.getElementById("bulk-preview").innerHTML = "";
    _bulkParsedRows = [];
  });
});
document.getElementById("btn-bulk-clients").addEventListener("click", () => {
  document.getElementById("bulk-textarea").value = "";
  document.getElementById("bulk-file-input").value = "";
  document.getElementById("bulk-preview").innerHTML = "";
  _bulkParsedRows = [];
  openModal("modal-bulk-clients");
});
document.getElementById("btn-download-template").addEventListener("click", () => {
  downloadWithAuth("/api/clients/import-template", "modele-import-clients.csv");
});
document.getElementById("bulk-file-input").addEventListener("change", e => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    _bulkParsedRows = parseCsv(String(reader.result));
    toast("info", `${_bulkParsedRows.length} ligne(s) lues du fichier`, "Cliquez sur « Aperçu » pour valider avant création.");
  };
  reader.readAsText(file, "utf-8");
});

function collectBulkRows() {
  const pasteVisible = !document.getElementById("bulk-tab-paste").hidden;
  if (pasteVisible) {
    const text = document.getElementById("bulk-textarea").value;
    return text.split(/\r?\n/).map(l => l.trim()).filter(Boolean).map(line => {
      const [name, email, telephone] = line.split(",").map(s => (s || "").trim());
      return { name, email, telephone };
    });
  }
  return _bulkParsedRows.map(r => ({
    name: r.nom || r.name,
    prenom: r.prenom,
    email: r.email,
    telephone: r.telephone,
    adresse: r.adresse,
    fonction: r.fonction,
    expires_days: r.expires_days ? parseInt(r.expires_days, 10) : undefined,
  }));
}

function renderBulkPreview(result) {
  const el = document.getElementById("bulk-preview");
  const okCount = result.created.length, errCount = result.errors.length;
  let html = `<p class="cell-muted">${okCount} ligne(s) valide(s)${errCount ? `, ${errCount} erreur(s)` : ""}.</p>`;
  if (errCount) {
    html += `<table class="data-table"><thead><tr><th>Ligne</th><th>Nom</th><th>Erreur</th></tr></thead><tbody>` +
      result.errors.map(e => `<tr><td>${e.row}</td><td class="mono">${escapeHtml(e.name || "—")}</td><td class="cell-muted">${escapeHtml(e.error)}</td></tr>`).join("") +
      `</tbody></table>`;
  }
  el.innerHTML = html;
}

document.getElementById("btn-bulk-preview").addEventListener("click", async () => {
  const clients = collectBulkRows();
  if (!clients.length) return toast("danger", "Aucune ligne à traiter");
  try {
    const result = await apiSend("POST", "/api/clients/bulk", { clients, dry_run: true });
    renderBulkPreview(result);
  } catch (err) { toast("danger", "Échec de l'aperçu", err.message); }
});
document.getElementById("btn-bulk-submit").addEventListener("click", async () => {
  if (STATE.demoMode) return toast("info", "Mode démonstration", "Création indisponible sans API connectée.");
  const clients = collectBulkRows();
  if (!clients.length) return toast("danger", "Aucune ligne à traiter");
  try {
    const result = await apiSend("POST", "/api/clients/bulk", { clients, dry_run: false });
    renderBulkPreview(result);
    toast(result.errors.length ? "warning" : "success", `${result.created.length} client(s) créé(s)`, result.errors.length ? `${result.errors.length} ligne(s) en erreur.` : "");
    if (result.created.length) renderClients();
  } catch (err) { toast("danger", "Échec de la création groupée", err.message); }
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
    const dateFrom = document.getElementById("journal-date-from").value;
    const dateTo = document.getElementById("journal-date-to").value;
    const volMin = document.getElementById("journal-volume-min").value;
    const volMax = document.getElementById("journal-volume-max").value;
    if (dateFrom) params.set("date_from", Math.floor(new Date(dateFrom).getTime() / 1000));
    if (dateTo) params.set("date_to", Math.floor(new Date(dateTo).getTime() / 1000));
    if (volMin) params.set("volume_min_mb", volMin);
    if (volMax) params.set("volume_max_mb", volMax);
    STATE.journal.lastQuery = params.toString();
    const data = await apiGet(`/api/logs?${params.toString()}`);
    STATE.journal.total = data.total ?? (data.rows || []).length;
    STATE.journal.lastRows = data.rows || [];
    renderJournalTable(data.rows || [], offset);
  } catch (err) { toast("danger", "Impossible de charger le journal", err.message); }
}

document.getElementById("btn-toggle-journal-filters").addEventListener("click", () => {
  const panel = document.getElementById("journal-advanced-filters");
  panel.hidden = !panel.hidden;
});
["journal-date-from", "journal-date-to", "journal-volume-min", "journal-volume-max"].forEach(id => {
  document.getElementById(id).addEventListener("change", () => { STATE.journal.offset = 0; renderJournal(); });
});
document.getElementById("btn-journal-reset-filters").addEventListener("click", () => {
  ["journal-date-from", "journal-date-to", "journal-volume-min", "journal-volume-max"].forEach(id => document.getElementById(id).value = "");
  STATE.journal.offset = 0;
  renderJournal();
});
document.getElementById("btn-journal-export").addEventListener("click", () => {
  const rows = STATE.journal.lastRows || [];
  if (!rows.length) return toast("info", "Rien à exporter", "Aucune ligne affichée sur cette page.");
  const header = "horodatage,client,endpoint,ip_autorisees,rx_bytes,tx_bytes";
  const csv = [header, ...rows.map(l => [new Date(l.timestamp * 1000 || l.ts * 1000).toISOString(), l.peer || l.name || "", l.endpoint || "", l.allowed_ips || "", l.rx_bytes || 0, l.tx_bytes || 0].map(v => `"${String(v).replace(/"/g, '""')}"`).join(","))].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a"); a.href = url; a.download = "journal-page.csv";
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
});

// Recherches sauvegardees (localStorage) : memorise la combinaison texte +
// statut + filtres avances sous un nom choisi par l'utilisateur.
const JOURNAL_SAVED_SEARCHES_KEY = "blockhash_journal_saved_searches";
function loadSavedSearches() { try { return JSON.parse(localStorage.getItem(JOURNAL_SAVED_SEARCHES_KEY) || "[]"); } catch { return []; } }
function renderSavedSearchesOptions() {
  const select = document.getElementById("journal-saved-searches");
  const searches = loadSavedSearches();
  select.innerHTML = `<option value="">Recherches sauvegardées…</option>` + searches.map((s, i) => `<option value="${i}">${escapeHtml(s.name)}</option>`).join("");
}
document.getElementById("btn-journal-save-search").addEventListener("click", () => {
  const name = prompt("Nom de cette recherche :", document.getElementById("journal-search").value || "Ma recherche");
  if (!name) return;
  const searches = loadSavedSearches();
  searches.push({
    name,
    search: document.getElementById("journal-search").value,
    status: document.getElementById("journal-status").value,
    dateFrom: document.getElementById("journal-date-from").value,
    dateTo: document.getElementById("journal-date-to").value,
    volumeMin: document.getElementById("journal-volume-min").value,
    volumeMax: document.getElementById("journal-volume-max").value,
  });
  localStorage.setItem(JOURNAL_SAVED_SEARCHES_KEY, JSON.stringify(searches));
  renderSavedSearchesOptions();
  toast("success", "Recherche sauvegardée");
});
document.getElementById("journal-saved-searches").addEventListener("change", e => {
  if (e.target.value === "") return;
  const s = loadSavedSearches()[parseInt(e.target.value, 10)];
  if (!s) return;
  document.getElementById("journal-search").value = s.search || "";
  document.getElementById("journal-status").value = s.status || "all";
  document.getElementById("journal-date-from").value = s.dateFrom || "";
  document.getElementById("journal-date-to").value = s.dateTo || "";
  document.getElementById("journal-volume-min").value = s.volumeMin || "";
  document.getElementById("journal-volume-max").value = s.volumeMax || "";
  document.getElementById("journal-advanced-filters").hidden = !(s.dateFrom || s.dateTo || s.volumeMin || s.volumeMax);
  STATE.journal.search = s.search || "";
  STATE.journal.status = s.status || "all";
  STATE.journal.offset = 0;
  renderJournal();
});
renderSavedSearchesOptions();

function renderJournalTable(rows, offset) {
  const tbody = document.querySelector("#table-journal tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><strong>Aucune entrée</strong><span>Aucune connexion ne correspond à ces filtres.</span></div></td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map((l, i) => `
    <tr class="row-clickable" data-journal-row="${i}">
      <td class="mono cell-muted">${fmtDate(l.timestamp)}</td>
      <td class="cell-primary">${escapeHtml(l.peer || l.name || "—")}</td>
      <td class="mono cell-muted">${escapeHtml(l.endpoint || "—")}</td>
      <td class="mono cell-muted">${escapeHtml(l.allowed_ips || "—")}</td>
      <td class="mono cell-muted">${fmtBytes(l.rx_bytes)} / ${fmtBytes(l.tx_bytes)}</td>
    </tr>
  `).join("");
  tbody.querySelectorAll("[data-journal-row]").forEach(tr => {
    tr.style.cursor = "pointer";
    tr.addEventListener("click", () => showSessionDetail(rows[parseInt(tr.dataset.journalRow, 10)]));
  });
}

function showSessionDetail(l) {
  document.getElementById("session-detail-body").innerHTML = `
    <div class="field"><label>Client</label><div class="cell-primary">${escapeHtml(l.peer || l.name || "—")}</div></div>
    <div class="field"><label>Horodatage</label><div class="mono">${fmtDate(l.timestamp)}</div></div>
    <div class="field"><label>Endpoint</label><div class="mono">${escapeHtml(l.endpoint || "—")}</div></div>
    <div class="field"><label>IP autorisées</label><div class="mono">${escapeHtml(l.allowed_ips || "—")}</div></div>
    <div class="field"><label>Volume</label><div class="mono">${fmtBytes(l.rx_bytes)} reçus / ${fmtBytes(l.tx_bytes)} envoyés</div></div>
    <div class="field"><label>Clé publique</label><div class="mono" style="word-break:break-all;">${escapeHtml(l.public_key || "—")}</div></div>`;
  openModal("modal-session-detail");
}

async function renderJournalHeatmap() {
  const el = document.getElementById("journal-heatmap");
  if (STATE.demoMode) { el.innerHTML = `<span class="cell-muted">Heatmap indisponible en mode démonstration.</span>`; return; }
  try {
    const { grid } = await apiGet("/api/logs/heatmap?days=30");
    const days = ["Dim", "Lun", "Mar", "Mer", "Jeu", "Ven", "Sam"];
    const max = Math.max(1, ...grid.flat());
    const cellColor = n => {
      if (!n) return "var(--bg-inset)";
      const ratio = n / max;
      return `color-mix(in srgb, var(--teal-mid) ${Math.round(20 + ratio * 80)}%, var(--bg-inset))`;
    };
    let html = `<div style="display:grid;grid-template-columns:36px repeat(24, 20px);gap:2px;font-size:10px;align-items:center;">`;
    html += `<div></div>` + Array.from({ length: 24 }, (_, h) => `<div class="cell-muted" style="text-align:center;">${h % 3 === 0 ? h : ""}</div>`).join("");
    for (let d = 0; d < 7; d++) {
      html += `<div class="cell-muted">${days[d]}</div>`;
      for (let h = 0; h < 24; h++) {
        const n = grid[d][h];
        html += `<div title="${days[d]} ${h}h : ${n} évènement(s)" style="width:20px;height:16px;border-radius:2px;background:${cellColor(n)};"></div>`;
      }
    }
    html += `</div>`;
    el.innerHTML = html;
  } catch (err) { el.innerHTML = `<span class="cell-muted">Heatmap indisponible : ${escapeHtml(err.message)}</span>`; }
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
    renderTopCountries(points);
  } catch (err) { /* carte non bloquante */ }
  setTimeout(() => STATE.map.invalidateSize(), 200);
}

function renderTopCountries(points) {
  const el = document.getElementById("geoip-top-countries");
  const counts = {};
  points.forEach(p => { const c = p.country || "?"; counts[c] = (counts[c] || 0) + 1; });
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 10);
  if (!top.length) { el.innerHTML = ""; return; }
  const max = top[0][1];
  el.innerHTML = `<span class="cell-muted" style="margin-bottom:6px;display:block;">Top ${top.length} pays</span>` +
    top.map(([country, n]) => `
      <div class="row-flex" style="justify-content:space-between;gap:8px;margin-bottom:4px;">
        <span style="flex:0 0 90px;">${escapeHtml(country)}</span>
        <div style="flex:1;background:var(--bg-inset);border-radius:3px;overflow:hidden;height:8px;align-self:center;">
          <div style="width:${(n / max) * 100}%;background:var(--teal-mid);height:100%;"></div>
        </div>
        <span class="cell-muted" style="flex:0 0 24px;text-align:right;">${n}</span>
      </div>`).join("");
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
        `<tr><td colspan="6"><div class="empty-state"><strong>Mode démonstration</strong><span>Historique indisponible sans API connectée.</span></div></td></tr>`;
      document.getElementById("dedup-list").innerHTML = "";
      document.getElementById("alerts-stats-body").innerHTML = "";
      return;
    }
    const params = new URLSearchParams({ limit: STATE.alertsPage.limit, offset: STATE.alertsPage.offset });
    const severity = document.getElementById("alerts-filter-severity").value;
    const client = document.getElementById("alerts-filter-client").value.trim();
    const rule = document.getElementById("alerts-filter-rule").value.trim();
    if (severity) params.set("severity", severity);
    if (client) params.set("client", client);
    if (rule) params.set("rule", rule);
    if (document.getElementById("alerts-filter-archived").checked) params.set("archived", "true");
    const [history, dedup, stats] = await Promise.all([
      apiGet(`/api/alerts/history?${params.toString()}`),
      apiGet("/api/alerts/dedup"),
      apiGet("/api/alerts/stats?days=7"),
    ]);
    renderAlertsHistory(history);
    renderDedupList(dedup);
    renderAlertsStats(stats);
  } catch (err) { toast("danger", "Impossible de charger les alertes", err.message); }
}

function renderAlertsStats(stats) {
  const el = document.getElementById("alerts-stats-body");
  const totalsByDay = {};
  (stats.by_day || []).forEach(r => { totalsByDay[r.day] = (totalsByDay[r.day] || 0) + r.n; });
  const days = Object.keys(totalsByDay).sort();
  const maxN = Math.max(1, ...Object.values(totalsByDay));
  const barChart = days.length
    ? `<div style="display:flex;gap:4px;align-items:flex-end;height:60px;">${days.map(d => `<div title="${d} : ${totalsByDay[d]}" style="flex:1;background:var(--teal-mid);border-radius:2px;height:${Math.max(4, (totalsByDay[d] / maxN) * 60)}px;"></div>`).join("")}</div>`
    : `<span class="cell-muted">Aucune alerte sur la période.</span>`;
  const topClients = (stats.top_clients || []).map(c => `<div class="row-flex" style="justify-content:space-between;"><span>${escapeHtml(c.peer_name)}</span><span class="cell-muted">${c.n}</span></div>`).join("") || `<span class="cell-muted">—</span>`;
  const mtta = stats.mtta_seconds != null ? `${Math.round(stats.mtta_seconds / 60)} min` : "—";
  el.innerHTML = `
    <div><span class="cell-muted">Volume par jour</span>${barChart}</div>
    <div><span class="cell-muted">Top clients alertés</span>${topClients}</div>
    <div><span class="cell-muted">Délai moyen avant lecture (MTTA)</span><div class="cell-primary">${mtta}</div></div>`;
}

function renderAlertsHistory(data) {
  const rows = data.rows || data; // compat retro si jamais l'API renvoie encore une liste brute
  const total = data.total ?? rows.length;
  const tbody = document.querySelector("#table-alerts-history tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><strong>Aucune alerte</strong><span>Rien à signaler pour le moment.</span></div></td></tr>`;
  } else {
    tbody.innerHTML = rows.map(a => `
      <tr style="${a.read_at ? "opacity:.65;" : ""}">
        <td class="mono cell-muted">${fmtDate(a.ts)}</td>
        <td class="cell-primary">${escapeHtml(a.rule_key || "—")}</td>
        <td class="cell-muted">${escapeHtml(a.peer_name || "—")}</td>
        <td>${statusBadge(a.level === "critical" ? "disabled" : a.level === "info" ? "online" : "idle")}</td>
        <td class="cell-muted">${escapeHtml(a.message || "—")}</td>
        <td>
          <div style="display:flex;gap:4px;">
            ${a.read_at ? "" : `<button class="btn ghost sm" data-alert-action="read" data-id="${a.id}" title="Marquer comme lue">Lu</button>`}
            <button class="btn ghost sm" data-alert-action="archive" data-id="${a.id}" data-archived="${a.archived}" title="${a.archived ? "Désarchiver" : "Archiver"}">${a.archived ? "Désarchiver" : "Archiver"}</button>
            <button class="btn ghost sm" data-alert-action="delete" data-id="${a.id}" title="Supprimer">✕</button>
          </div>
        </td>
      </tr>`).join("");
    tbody.querySelectorAll('[data-alert-action="read"]').forEach(btn => btn.addEventListener("click", async () => {
      try { await apiSend("PATCH", `/api/alerts/history/${btn.dataset.id}`, { read: true }); renderAlerts(); } catch (err) { toast("danger", "Échec", err.message); }
    }));
    tbody.querySelectorAll('[data-alert-action="archive"]').forEach(btn => btn.addEventListener("click", async () => {
      try { await apiSend("PATCH", `/api/alerts/history/${btn.dataset.id}`, { archived: btn.dataset.archived !== "1" }); renderAlerts(); } catch (err) { toast("danger", "Échec", err.message); }
    }));
    tbody.querySelectorAll('[data-alert-action="delete"]').forEach(btn => btn.addEventListener("click", async () => {
      if (!confirm("Supprimer définitivement cette alerte de l'historique ?")) return;
      try { await apiSend("DELETE", `/api/alerts/history/${btn.dataset.id}`); renderAlerts(); } catch (err) { toast("danger", "Échec", err.message); }
    }));
  }
  const { offset, limit } = STATE.alertsPage;
  document.getElementById("alerts-page-indicator").textContent =
    total ? `${offset + 1}–${Math.min(offset + limit, total)} sur ${total}` : "0–0 sur 0";
  document.getElementById("alerts-prev").disabled = offset <= 0;
  document.getElementById("alerts-next").disabled = offset + limit >= total;
}
document.getElementById("alerts-prev").addEventListener("click", () => {
  STATE.alertsPage.offset = Math.max(0, STATE.alertsPage.offset - STATE.alertsPage.limit);
  renderAlerts();
});
document.getElementById("alerts-next").addEventListener("click", () => {
  STATE.alertsPage.offset += STATE.alertsPage.limit;
  renderAlerts();
});
["alerts-filter-severity", "alerts-filter-client", "alerts-filter-rule", "alerts-filter-archived"].forEach(id => {
  const el = document.getElementById(id);
  el.addEventListener(el.type === "checkbox" ? "change" : "input", () => { STATE.alertsPage.offset = 0; renderAlerts(); });
});
document.getElementById("btn-alerts-export").addEventListener("click", () => downloadWithAuth("/api/alerts/history/export", "alertes.csv"));

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
  const c = cfg || { enabled: false, rules: { inactive_days: 7, service_down: true, connect_disconnect: true }, channels: { email: {}, telegram: {} } };
  document.getElementById("alert-config-body").innerHTML = `
    <div class="field"><label><input type="checkbox" id="cfg-enabled" ${c.enabled ? "checked" : ""} /> Activer les alertes automatiques</label></div>
    <div class="field"><label><input type="checkbox" id="cfg-connect-disconnect" ${c.rules?.connect_disconnect !== false ? "checked" : ""} /> Alerter à chaque connexion / déconnexion d'un client</label></div>
    <div class="field"><label><input type="checkbox" id="cfg-off-hours" ${c.rules?.off_hours?.enabled ? "checked" : ""} /> Alerter si connexion hors plage horaire</label>
      <div style="display:flex;gap:8px;margin-top:6px;">
        <input class="input" type="time" id="cfg-off-hours-start" value="${c.rules?.off_hours?.start || "22:00"}" style="width:120px;" />
        <span class="cell-muted" style="align-self:center;">à</span>
        <input class="input" type="time" id="cfg-off-hours-end" value="${c.rules?.off_hours?.end || "06:00"}" style="width:120px;" />
      </div></div>
    <div class="field"><label><input type="checkbox" id="cfg-failed-auth" ${c.rules?.failed_auth_attempts !== false ? "checked" : ""} /> Alerter sur tentatives d'authentification échouées répétées</label></div>
    <div class="field"><label><input type="checkbox" id="cfg-new-ip" ${c.rules?.new_ip !== false ? "checked" : ""} /> Alerter si un client se connecte depuis une IP jamais vue</label></div>
    <div class="field"><label>Expiration client — alerter N jours avant (0 = désactivé)</label>
      <input class="input" type="number" min="0" id="cfg-client-expiry-days" value="${c.rules?.client_expiry_days ?? 3}" style="max-width:120px;" /></div>
    <div class="field"><label>Maximum d'alertes envoyées par heure (0 = illimité)</label>
      <input class="input" type="number" min="0" id="cfg-max-per-hour" value="${c.max_alerts_per_hour ?? 0}" style="max-width:120px;" /></div>
    <div class="field"><label>Seuil CPU (%) — vide pour désactiver</label>
      <input class="input" type="number" min="1" max="100" id="cfg-cpu-threshold" value="${c.rules?.cpu_percent_threshold ?? ""}" style="max-width:120px;" /></div>
    <div class="field"><label>Seuil disque (%) — vide pour désactiver</label>
      <input class="input" type="number" min="1" max="100" id="cfg-disk-threshold" value="${c.rules?.disk_percent_threshold ?? ""}" style="max-width:120px;" /></div>
    <div class="field"><label><input type="checkbox" id="cfg-service-down" ${c.rules?.service_down !== false ? "checked" : ""} /> Alerter si le service WireGuard tombe</label></div>
    <div class="field"><label>Inactivité (jours) avant alerte — 0 pour désactiver</label>
      <input class="input" id="cfg-inactive-days" type="number" min="0" value="${c.rules?.inactive_days ?? 7}" /></div>
    <div class="field"><label>Webhook Slack</label>
      <div style="display:flex;gap:8px;align-items:center;">
        <input type="checkbox" id="cfg-slack-enabled" ${c.channels?.slack_enabled !== false ? "checked" : ""} title="Activer ce canal" />
        <input class="input" id="cfg-slack" placeholder="https://hooks.slack.com/…" value="${escapeHtml(c.channels?.slack_webhook_url || "")}" />
        <button class="btn ghost sm" data-test-channel="slack">Tester</button>
      </div></div>
    <div class="field"><label>Webhook Discord</label>
      <div style="display:flex;gap:8px;align-items:center;">
        <input type="checkbox" id="cfg-discord-enabled" ${c.channels?.discord_enabled !== false ? "checked" : ""} title="Activer ce canal" />
        <input class="input" id="cfg-discord" placeholder="https://discord.com/api/webhooks/…" value="${escapeHtml(c.channels?.discord_webhook_url || "")}" />
        <button class="btn ghost sm" data-test-channel="discord">Tester</button>
      </div></div>
    <div class="field"><label>E-mail destinataire</label>
      <div style="display:flex;gap:8px;align-items:center;">
        <input type="checkbox" id="cfg-email-enabled" ${c.channels?.email?.enabled ? "checked" : ""} title="Activer ce canal" />
        <input class="input" id="cfg-email-to" placeholder="ops@exemple.com" value="${escapeHtml(c.channels?.email?.to_addr || "")}" />
        <button class="btn ghost sm" data-test-channel="email">Tester</button>
      </div></div>`;
  document.querySelectorAll("[data-test-channel]").forEach(btn => btn.addEventListener("click", async () => {
    const channel = btn.dataset.testChannel;
    btn.disabled = true;
    try {
      await apiSend("POST", "/api/alerts/test", { channel });
      toast("success", `Test envoyé sur ${channel}`, "Vérifiez la réception (peut prendre quelques secondes).");
    } catch (err) { toast("danger", `Échec du test ${channel}`, err.message); }
    finally { btn.disabled = false; }
  }));
}

document.getElementById("btn-save-alert-config").addEventListener("click", async () => {
  if (STATE.demoMode) { closeModal("modal-alert-config"); return toast("info", "Mode démonstration", "Enregistrement indisponible sans API connectée."); }
  const body = {
    enabled: document.getElementById("cfg-enabled").checked,
    max_alerts_per_hour: parseInt(document.getElementById("cfg-max-per-hour").value, 10) || 0,
    rules: {
      inactive_days: parseInt(document.getElementById("cfg-inactive-days").value, 10) || 0,
      connect_disconnect: document.getElementById("cfg-connect-disconnect").checked,
      service_down: document.getElementById("cfg-service-down").checked,
      failed_auth_attempts: document.getElementById("cfg-failed-auth").checked,
      new_ip: document.getElementById("cfg-new-ip").checked,
      client_expiry_days: parseInt(document.getElementById("cfg-client-expiry-days").value, 10) || 0,
      cpu_percent_threshold: document.getElementById("cfg-cpu-threshold").value ? parseInt(document.getElementById("cfg-cpu-threshold").value, 10) : null,
      disk_percent_threshold: document.getElementById("cfg-disk-threshold").value ? parseInt(document.getElementById("cfg-disk-threshold").value, 10) : null,
      off_hours: {
        enabled: document.getElementById("cfg-off-hours").checked,
        start: document.getElementById("cfg-off-hours-start").value || "22:00",
        end: document.getElementById("cfg-off-hours-end").value || "06:00",
      },
    },
    channels: {
      slack_webhook_url: document.getElementById("cfg-slack").value.trim(),
      slack_enabled: document.getElementById("cfg-slack-enabled").checked,
      discord_webhook_url: document.getElementById("cfg-discord").value.trim(),
      discord_enabled: document.getElementById("cfg-discord-enabled").checked,
      email: { to_addr: document.getElementById("cfg-email-to").value.trim(), enabled: document.getElementById("cfg-email-enabled").checked },
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
    STATE.complianceClients = clients; // reutilise par l'export PDF
    if (!clients.length) {
      el.innerHTML = `<div class="empty-state"><strong>Tout est conforme</strong><span>Aucun client inactif au-delà des seuils configurés.</span></div>`;
    } else {
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
    }
    const weeklyCfg = await apiGet("/api/reports/weekly-config");
    document.getElementById("cfg-weekly-enabled").checked = !!weeklyCfg.weekly_enabled;
    document.getElementById("cfg-weekly-to").value = weeklyCfg.to_addr || "";
  } catch (err) { el.innerHTML = `<div class="empty-state"><strong>Erreur</strong><span>${escapeHtml(err.message)}</span></div>`; }
}

document.getElementById("btn-report-pdf").addEventListener("click", async () => {
  const clients = STATE.complianceClients || [];
  const body = {
    title: "Rapport de conformité BLOCKHash",
    subtitle: `Généré le ${new Date().toLocaleString("fr-FR")}`,
    columns: ["Client", "IP", "Jours d'inactivité", "Seuil"],
    rows: clients.map(c => [c.name, c.allowed_ips || "—", String(c.days_inactive ?? "—"), c.bucket === "never" ? "jamais connecté" : `${c.bucket}+ j`]),
  };
  try {
    const resp = await fetch("/api/reports/pdf", { method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() }, body: JSON.stringify(body) });
    if (!resp.ok) { const j = await resp.json().catch(() => ({})); throw new Error(j.error || `Erreur API (${resp.status})`); }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "rapport-conformite.pdf";
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  } catch (err) { toast("danger", "Échec de l'export PDF", err.message); }
});
document.getElementById("btn-weekly-save").addEventListener("click", async () => {
  try {
    await apiSend("PATCH", "/api/reports/weekly-config", {
      weekly_enabled: document.getElementById("cfg-weekly-enabled").checked,
      to_addr: document.getElementById("cfg-weekly-to").value.trim(),
    });
    toast("success", "Configuration du rapport hebdomadaire enregistrée");
  } catch (err) { toast("danger", "Échec de l'enregistrement", err.message); }
});
document.getElementById("btn-weekly-send-now").addEventListener("click", async () => {
  try { await apiSend("POST", "/api/reports/weekly-send"); toast("success", "Rapport hebdomadaire envoyé"); }
  catch (err) { toast("danger", "Échec de l'envoi", err.message); }
});

// ---------------------------------------------------------------
// VUE : Système
// ---------------------------------------------------------------
async function renderSystem() {
  const tbody = document.querySelector("#table-backups tbody");
  if (STATE.demoMode) {
    tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><strong>Mode démonstration</strong><span>Les opérations système nécessitent l'API connectée.</span></div></td></tr>`;
    return;
  }
  try {
    const [data, settings] = await Promise.all([apiGet("/api/system/backups"), apiGet("/api/settings")]);
    document.getElementById("backup-schedule").value = settings.backup_schedule || "disabled";
    const backups = data.backups || data || [];
    if (!backups.length) { tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><strong>Aucune sauvegarde</strong></div></td></tr>`; return; }
    tbody.innerHTML = backups.map(b => `<tr>
      <td class="mono cell-primary">${escapeHtml(b.filename || b.name)}</td>
      <td class="cell-muted">${escapeHtml(b.description || "—")}</td>
      <td class="cell-muted">${fmtDate(b.modified || b.created_at || b.date)}</td>
      <td class="mono cell-muted" style="font-size:11px;" title="${escapeHtml(b.sha256 || "")}">${escapeHtml((b.sha256 || "").slice(0, 12))}…</td>
      <td>
        <div style="display:flex;gap:6px;">
          <button class="btn ghost sm" data-action="download-backup" data-filename="${escapeHtml(b.filename || b.name)}">Télécharger</button>
          <button class="btn ghost sm" data-action="restore-backup" data-filename="${escapeHtml(b.filename || b.name)}">Restaurer</button>
        </div>
      </td>
    </tr>`).join("");
    tbody.querySelectorAll('[data-action="download-backup"]').forEach(btn =>
      btn.addEventListener("click", () => promptBackupDownload(btn.dataset.filename))
    );
    tbody.querySelectorAll('[data-action="restore-backup"]').forEach(btn =>
      btn.addEventListener("click", () => promptBackupRestore(btn.dataset.filename))
    );
  } catch (err) { tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><strong>Erreur</strong><span>${escapeHtml(err.message)}</span></div></td></tr>`; }
}

document.getElementById("btn-backup-schedule-save").addEventListener("click", async () => {
  try {
    await apiSend("PATCH", "/api/settings", { backup_schedule: document.getElementById("backup-schedule").value });
    toast("success", "Planning de sauvegardes enregistré");
  } catch (err) { toast("danger", "Échec de l'enregistrement", err.message); }
});

// Restauration a double confirmation : mot de passe admin + saisie de RESTORE
// (verifie aussi cote serveur, voir app.py:/api/system/backups/<f>/restore).
let _pendingRestoreFilename = null;

function promptBackupRestore(filename) {
  _pendingRestoreFilename = filename;
  document.getElementById("restore-filename").textContent = filename;
  document.getElementById("restore-password").value = "";
  document.getElementById("restore-confirm-word").value = "";
  document.getElementById("restore-error").textContent = "";
  openModal("modal-restore-confirm");
}

document.getElementById("btn-confirm-restore").addEventListener("click", async () => {
  const password = document.getElementById("restore-password").value;
  const word = document.getElementById("restore-confirm-word").value;
  const errEl = document.getElementById("restore-error");
  if (word !== "RESTORE") { errEl.textContent = "Tapez exactement RESTORE pour confirmer."; return; }
  if (!password) { errEl.textContent = "Mot de passe requis."; return; }
  try {
    const result = await apiSend("POST", `/api/system/backups/${encodeURIComponent(_pendingRestoreFilename)}/restore`, { password });
    closeModal("modal-restore-confirm");
    toast("success", "Configuration restaurée", `Sauvegarde de sécurité créée avant restauration : ${result.safety_backup}`);
    renderSystem();
  } catch (err) {
    if (err.message.includes("invalid_password")) errEl.textContent = "Mot de passe incorrect.";
    else if (err.message.includes("too_many_attempts")) errEl.textContent = "Trop de tentatives, réessayez dans quelques minutes.";
    else errEl.textContent = err.message;
  }
});

// Telechargement de sauvegarde : exige de ressaisir le mot de passe admin
// (voir app.py:/api/system/backups/<f>/download). La reponse est un binaire
// brut (pas du JSON) -> on ne peut pas utiliser apiSend ici, fetch direct.
let _pendingBackupFilename = null;

function promptBackupDownload(filename) {
  _pendingBackupFilename = filename;
  document.getElementById("field-admin-password").value = "";
  document.getElementById("admin-password-error").textContent = "";
  openModal("modal-admin-password");
  setTimeout(() => document.getElementById("field-admin-password").focus(), 50);
}

async function confirmBackupDownload() {
  const password = document.getElementById("field-admin-password").value;
  const errEl = document.getElementById("admin-password-error");
  if (!password) { errEl.textContent = "Mot de passe requis."; return; }
  try {
    const resp = await fetch(`/api/system/backups/${encodeURIComponent(_pendingBackupFilename)}/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ password }),
    });
    if (resp.status === 401) { errEl.textContent = "Mot de passe incorrect."; return; }
    if (resp.status === 429) { const j = await resp.json().catch(() => ({})); errEl.textContent = `Trop de tentatives. Réessayez dans ${j.retry_after_seconds || 300}s.`; return; }
    if (!resp.ok) { errEl.textContent = "Échec du téléchargement."; return; }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = _pendingBackupFilename;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    closeModal("modal-admin-password");
    toast("success", `Sauvegarde ${_pendingBackupFilename} téléchargée`);
  } catch (err) { errEl.textContent = err.message; }
}
document.getElementById("btn-confirm-admin-password").addEventListener("click", confirmBackupDownload);
document.getElementById("field-admin-password").addEventListener("keydown", e => { if (e.key === "Enter") confirmBackupDownload(); });

document.getElementById("btn-backup-create").addEventListener("click", async () => {
  if (STATE.demoMode) return toast("info", "Mode démonstration");
  const description = prompt("Description de la sauvegarde (optionnel) :", "") || "";
  try { await apiSend("POST", "/api/system/backups", { label: "manuel", description }); toast("success", "Sauvegarde créée"); renderSystem(); }
  catch (err) { toast("danger", "Échec", err.message); }
});
document.getElementById("btn-restart-tunnel").addEventListener("click", async () => {
  if (STATE.demoMode) return toast("info", "Mode démonstration");
  const onlineCount = (STATE.peers || []).filter(p => peerStatus(p) === "online").length;
  if (!confirm(`Redémarrer le tunnel WireGuard maintenant ? ${onlineCount} client(s) actuellement connecté(s) seront brièvement déconnectés.`)) return;
  try { await apiSend("POST", "/api/system/restart-tunnel"); toast("success", "Tunnel redémarré"); }
  catch (err) { toast("danger", "Échec", err.message); }
});
document.getElementById("btn-rotate-keys").addEventListener("click", async () => {
  if (STATE.demoMode) return toast("info", "Mode démonstration");
  const total = (STATE.peers || []).length;
  if (!confirm(`Régénérer les clés du serveur ? ${total} client(s) devront recevoir une nouvelle configuration (ancienne configuration invalidée immédiatement).`)) return;
  try { await apiSend("POST", "/api/system/rotate-server-keys"); toast("success", "Clés régénérées"); }
  catch (err) { toast("danger", "Échec", err.message); }
});
document.getElementById("btn-export").addEventListener("click", () => {
  if (STATE.demoMode) return toast("info", "Mode démonstration", "Export indisponible sans API connectée.");
  downloadWithAuth("/api/system/export", `blockhash-export-${new Date().toISOString().slice(0, 10)}.zip`);
});
document.getElementById("qa-export")?.addEventListener("click", () => document.getElementById("btn-export").click());

document.getElementById("btn-run-diagnostics").addEventListener("click", async () => {
  if (STATE.demoMode) return toast("info", "Mode démonstration", "Diagnostic indisponible sans API connectée.");
  const el = document.getElementById("diagnostics-body");
  el.innerHTML = `<span class="cell-muted">Diagnostic en cours…</span>`;
  try {
    const data = await apiGet("/api/system/diagnostics");
    el.innerHTML = `<div class="cell-primary" style="margin-bottom:8px;">${escapeHtml(data.summary)}</div>` +
      data.checks.map(c => `
        <div class="row-flex" style="justify-content:space-between;border-bottom:1px solid var(--border-subtle);padding:4px 0;">
          <span>${c.ok ? "✅" : "⚠️"} ${escapeHtml(c.name)}</span>
          <span class="cell-muted mono" style="font-size:12px;">${escapeHtml(c.detail)}</span>
        </div>`).join("");
  } catch (err) { el.innerHTML = `<div class="empty-state"><strong>Erreur</strong><span>${escapeHtml(err.message)}</span></div>`; }
});

async function renderAuditPreview() {
  const tbody = document.querySelector("#table-audit-preview tbody");
  if (STATE.demoMode) {
    tbody.innerHTML = `<tr><td><div class="empty-state"><strong>Mode démonstration</strong></div></td></tr>`;
    return;
  }
  try {
    const data = await apiGet("/api/system/audit?limit=5&offset=0");
    tbody.innerHTML = data.rows.length
      ? data.rows.map(r => `<tr><td class="mono cell-muted" style="font-size:12px;">${escapeHtml(r.raw)}</td></tr>`).join("")
      : `<tr><td><div class="empty-state"><strong>Aucune entrée</strong></div></td></tr>`;
  } catch (err) { tbody.innerHTML = `<tr><td><div class="empty-state"><strong>Erreur</strong><span>${escapeHtml(err.message)}</span></div></td></tr>`; }
}

STATE.auditPage = { offset: 0, limit: 50 };
async function renderAudit() {
  const tbody = document.querySelector("#table-audit tbody");
  if (STATE.demoMode) {
    tbody.innerHTML = `<tr><td colspan="4"><div class="empty-state"><strong>Mode démonstration</strong></div></td></tr>`;
    return;
  }
  try {
    const params = new URLSearchParams({ limit: STATE.auditPage.limit, offset: STATE.auditPage.offset });
    const action = document.getElementById("audit-filter-action").value.trim();
    const ip = document.getElementById("audit-filter-ip").value.trim();
    const dateFrom = document.getElementById("audit-filter-date-from").value;
    const dateTo = document.getElementById("audit-filter-date-to").value;
    if (action) params.set("action", action);
    if (ip) params.set("ip", ip);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);

    const data = await apiGet(`/api/system/audit?${params.toString()}`);
    tbody.innerHTML = data.rows.length
      ? data.rows.map(r => `
          <tr>
            <td class="mono cell-muted">${escapeHtml(r.date || "—")}</td>
            <td class="mono cell-muted">${escapeHtml(r.ip || "—")}</td>
            <td class="cell-primary">${escapeHtml(r.action || "—")}</td>
            <td class="cell-muted" style="font-size:12px;">${escapeHtml(r.detail || "")}</td>
          </tr>`).join("")
      : `<tr><td colspan="4"><div class="empty-state"><strong>Aucune entrée</strong><span>Aucun événement ne correspond à ces filtres.</span></div></td></tr>`;
    const { offset, limit } = STATE.auditPage;
    document.getElementById("audit-page-indicator").textContent =
      data.total ? `${offset + 1}–${Math.min(offset + limit, data.total)} sur ${data.total}` : "0–0 sur 0";
    document.getElementById("audit-prev").disabled = offset <= 0;
    document.getElementById("audit-next").disabled = offset + limit >= data.total;
  } catch (err) { tbody.innerHTML = `<tr><td colspan="4"><div class="empty-state"><strong>Erreur</strong><span>${escapeHtml(err.message)}</span></div></td></tr>`; }
}
document.getElementById("audit-prev").addEventListener("click", () => { STATE.auditPage.offset = Math.max(0, STATE.auditPage.offset - STATE.auditPage.limit); renderAudit(); });
document.getElementById("audit-next").addEventListener("click", () => { STATE.auditPage.offset += STATE.auditPage.limit; renderAudit(); });
document.getElementById("btn-audit-export").addEventListener("click", () => downloadWithAuth("/api/system/audit/export", "audit.log"));
["audit-filter-action", "audit-filter-ip", "audit-filter-date-from", "audit-filter-date-to"].forEach(id => {
  document.getElementById(id).addEventListener("change", () => { STATE.auditPage.offset = 0; renderAudit(); });
});
document.getElementById("btn-audit-reset-filters").addEventListener("click", () => {
  ["audit-filter-action", "audit-filter-ip", "audit-filter-date-from", "audit-filter-date-to"].forEach(id => document.getElementById(id).value = "");
  STATE.auditPage.offset = 0;
  renderAudit();
});

// ---------------------------------------------------------------
// VUE : Réglages
// ---------------------------------------------------------------
async function renderSettings() {
  try {
    const s = STATE.demoMode ? { online_threshold_sec: 120 } : await apiGet("/api/settings");
    document.getElementById("setting-online-threshold").value = s.online_threshold_sec ?? 120;
    document.getElementById("setting-retention-days").value = s.retention_days ?? 35;
    document.getElementById("setting-desktop-notifications").checked = !!s.desktop_notifications_enabled;
    document.getElementById("setting-date-format").value = s.date_format || "DD/MM/YYYY";
    document.getElementById("setting-timezone").value = s.timezone || "Europe/Paris";
    document.getElementById("setting-language").value = s.language || CURRENT_LANG || "fr";

    if (!STATE.demoMode) {
      const policies = await apiGet("/api/compliance/policies");
      document.getElementById("policy-default-days").value = policies.default_inactive_days ?? 90;
      document.getElementById("policy-by-tag").value = Object.entries(policies.by_tag || {}).map(([t, d]) => `${t}:${d}`).join("\n");
      document.getElementById("policy-exceptions").value = (policies.exceptions || []).join("\n");
    }

    const hint = document.getElementById("webpush-hint");
    const checkbox = document.getElementById("setting-webpush");
    if (STATE.demoMode) {
      hint.textContent = "Indisponible en mode démonstration.";
      checkbox.disabled = true;
    } else if (!(await isWebPushSupported())) {
      hint.textContent = "Non pris en charge par ce navigateur.";
      checkbox.disabled = true;
    } else {
      const { available } = await apiGet("/api/push/vapid-public-key");
      if (!available) {
        hint.textContent = "Dépendances serveur non installées (pywebpush) — voir requirements.txt.";
        checkbox.disabled = true;
      } else {
        const sub = await getCurrentPushSubscription();
        checkbox.checked = !!sub;
        checkbox.disabled = false;
        hint.textContent = "Fonctionne même onglet fermé, une fois activé dans ce navigateur.";
        document.getElementById("btn-webpush-test").hidden = !sub;
      }
    }
  } catch (err) { toast("danger", "Impossible de charger les réglages", err.message); }
}
document.getElementById("setting-language").addEventListener("change", e => setLanguage(e.target.value));
document.getElementById("btn-save-settings").addEventListener("click", async () => {
  if (STATE.demoMode) return toast("info", "Mode démonstration");
  const desktopWanted = document.getElementById("setting-desktop-notifications").checked;
  if (desktopWanted && window.Notification && Notification.permission === "default") {
    await Notification.requestPermission();
  }
  const body = {
    online_threshold_sec: parseInt(document.getElementById("setting-online-threshold").value, 10),
    retention_days: parseInt(document.getElementById("setting-retention-days").value, 10),
    desktop_notifications_enabled: desktopWanted,
    date_format: document.getElementById("setting-date-format").value,
    timezone: document.getElementById("setting-timezone").value.trim(),
    language: document.getElementById("setting-language").value,
  };
  try {
    await apiSend("PATCH", "/api/settings", body);
    await setLanguage(body.language);
    toast("success", "Réglages enregistrés");
  }
  catch (err) { toast("danger", "Échec", err.message); }
});
document.getElementById("btn-purge-now").addEventListener("click", async () => {
  if (STATE.demoMode) return toast("info", "Mode démonstration");
  if (!confirm("Purger immédiatement les données plus anciennes que la rétention configurée ? Cette action est irréversible.")) return;
  try { const r = await apiSend("POST", "/api/system/purge"); toast("success", `Purge effectuée (rétention : ${r.retention_days} j)`); }
  catch (err) { toast("danger", "Échec", err.message); }
});
document.getElementById("btn-save-policies").addEventListener("click", async () => {
  if (STATE.demoMode) return toast("info", "Mode démonstration");
  const by_tag = {};
  document.getElementById("policy-by-tag").value.split("\n").forEach(line => {
    const [tag, days] = line.split(":").map(s => (s || "").trim());
    if (tag && days) by_tag[tag] = parseInt(days, 10);
  });
  const exceptions = document.getElementById("policy-exceptions").value.split("\n")
    .map(l => l.split("#")[0].trim()).filter(Boolean);
  try {
    await apiSend("PATCH", "/api/compliance/policies", {
      default_inactive_days: parseInt(document.getElementById("policy-default-days").value, 10) || 90,
      by_tag, exceptions,
    });
    toast("success", "Politiques de conformité enregistrées");
  } catch (err) { toast("danger", "Échec", err.message); }
});

// ---------------------------------------------------------------
// Web Push (item 55, vrai) : fonctionne meme onglet ferme, contrairement aux
// notifications "desktop" ci-dessus qui ne sont qu'un fallback Notification
// API basique. Necessite un navigateur compatible (Service Worker + Push
// API) et un contexte securise (https, deja le cas via Caddy).
// ---------------------------------------------------------------
function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  return Uint8Array.from([...rawData].map(c => c.charCodeAt(0)));
}

async function isWebPushSupported() {
  return "serviceWorker" in navigator && "PushManager" in window;
}

async function getCurrentPushSubscription() {
  if (!(await isWebPushSupported())) return null;
  const reg = await navigator.serviceWorker.getRegistration();
  return reg ? reg.pushManager.getSubscription() : null;
}

async function enableWebPush() {
  const reg = await navigator.serviceWorker.register("/sw.js");
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Permission navigateur refusée.");
  const { available, public_key } = await apiGet("/api/push/vapid-public-key");
  if (!available) throw new Error("Web Push indisponible côté serveur (dépendances non installées).");
  const subscription = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(public_key),
  });
  await apiSend("POST", "/api/push/subscribe", subscription.toJSON());
}

async function disableWebPush() {
  const sub = await getCurrentPushSubscription();
  if (sub) {
    await apiSend("POST", "/api/push/unsubscribe", { endpoint: sub.endpoint });
    await sub.unsubscribe();
  }
}

document.getElementById("setting-webpush").addEventListener("change", async (e) => {
  const checkbox = e.target;
  try {
    if (checkbox.checked) { await enableWebPush(); toast("success", "Web Push activé"); }
    else { await disableWebPush(); toast("success", "Web Push désactivé"); }
    document.getElementById("btn-webpush-test").hidden = !checkbox.checked;
  } catch (err) {
    checkbox.checked = !checkbox.checked; // annule visuellement si l'operation a echoue
    toast("danger", "Échec Web Push", err.message);
  }
});
document.getElementById("btn-webpush-test").addEventListener("click", async () => {
  try { const r = await apiSend("POST", "/api/push/test"); toast("success", `Notification de test envoyée (${r.sent} abonnement(s))`); }
  catch (err) { toast("danger", "Échec du test", err.message); }
});

// Notifications desktop (item 55, fallback) : degrade proprement si la
// permission n'est pas accordee ou si l'API Notification est absente. Ne
// fonctionne que tant que cet onglet reste ouvert - voir enableWebPush()
// ci-dessus pour la version qui fonctionne aussi onglet ferme.
async function maybeShowDesktopNotification(title, body) {
  try {
    if (STATE.demoMode || !window.Notification) return;
    const settings = STATE._cachedSettings || (STATE._cachedSettings = await apiGet("/api/settings").catch(() => ({})));
    if (!settings.desktop_notifications_enabled) return;
    if (Notification.permission === "granted") new Notification(title, { body });
  } catch { /* best effort, ne doit jamais casser le flux SSE */ }
}