/* Panneau de contrôle Phoenix — logique (vanilla JS, zéro build) */
"use strict";

const $ = (id) => document.getElementById(id);

// ── Auth (Basic) ─────────────────────────────────────────────────────────
let credentials = null;

function ensureAuth() {
  if (credentials) return;
  const user = prompt("Utilisateur (Phoenix) :");
  if (user === null) return;
  const pass = prompt("Mot de passe :");
  credentials = btoa(user + ":" + pass);
}

function authHeaders(json) {
  const h = {};
  if (json) h["Content-Type"] = "application/json";
  if (credentials) h["Authorization"] = "Basic " + credentials;
  return h;
}

async function api(path, options = {}) {
  ensureAuth();
  const opts = { ...options, headers: authHeaders(Boolean(options.body)) };
  const r = await fetch(path, opts);
  if (r.status === 401) {
    credentials = null;
    ensureAuth();
    return api(path, options);
  }
  return r.json();
}

const apiGet = (p) => api(p);
const apiPost = (p, body) => api(p, { method: "POST", body: JSON.stringify(body) });

// ── État des providers (édité localement) ────────────────────────────────
let aiConfig = { enabled: false, priority: 6, timeout_s: 10, providers: [] };

const PROVIDER_TYPES = [
  "local", "ollama", "mycroft", "opencode", "openai", "anthropic",
];

function typeLabel(t) {
  return { local: "Local (pipeline)", ollama: "Ollama (LAN)", mycroft: "Satellite Phoenix",
           opencode: "OpenCode (dev)", openai: "OpenAI (cloud)", anthropic: "Anthropic (cloud)" }[t] || t;
}

function renderProviders() {
  const box = $("providers");
  box.innerHTML = "";
  aiConfig.providers.forEach((p, i) => {
    const div = document.createElement("div");
    div.className = "provider";
    div.innerHTML = `
      <div class="prov-head">
        <span class="tag">${typeLabel(p.type || "")}</span>
        <input type="text" placeholder="id" value="${esc(p.id || "")}" data-i="${i}" data-f="id" style="width:130px" />
        <button class="danger" data-del="${i}">Supprimer</button>
      </div>
      <div class="prov-grid">${providerFields(p, i)}</div>`;
    box.appendChild(div);
  });
}

function providerFields(p, i) {
  const t = p.type || "local";
  const fields = [
    ["type", "Type", selectType(t)],
  ];
  if (t === "ollama") {
    fields.push(["host", "Host", p.host || "localhost"], ["port", "Port", p.port || 11434],
                ["model", "Modèle", p.model || "qwen2.5:1.5b"]);
  } else if (t === "mycroft") {
    fields.push(["url", "URL", p.url || "http://localhost:8090"],
                ["api_key_env", "Clé (env)", p.api_key_env || "PHOENIX_TOKEN"]);
  } else if (t === "opencode") {
    fields.push(["directory", "Répertoire projet", p.directory || ""],
                ["agent", "Agent", p.agent || "build"]);
  } else if (t === "openai" || t === "anthropic") {
    fields.push(["model", "Modèle", p.model || (t === "openai" ? "gpt-4o-mini" : "claude-3-5-haiku-latest")],
                ["api_key_env", "Clé (variable env)", p.api_key_env || (t === "openai" ? "OPENAI_API_KEY" : "ANTHROPIC_API_KEY")]);
  }
  const html = fields.map(([f, label, val]) => `
      <label>${label}
        ${f === "type" ? val : `<input type="text" value="${esc(String(val))}" data-i="${i}" data-f="${f}" />`}
      </label>`).join("");
  if (t !== "local" && t !== "opencode") {
    html += `<label>Timeout (s)<input type="number" value="${p.timeout_s || 10}" data-i="${i}" data-f="timeout_s" /></label>`;
  }
  return html;
}

function selectType(current) {
  return `<select data-i="-1" data-f="type">
    ${PROVIDER_TYPES.map((t) => `<option value="${t}" ${t === current ? "selected" : ""}>${typeLabel(t)}</option>`).join("")}
  </select>`;
}

const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ── Chargement ───────────────────────────────────────────────────────────
async function load() {
  try {
    const r = await apiGet("/api/config/ai");
    if (!r.ok) throw new Error(r.error || "erreur");
    aiConfig = r.ai;
    $("ai-enabled").checked = !!aiConfig.enabled;
    $("ai-priority").value = aiConfig.priority ?? 6;
    $("ai-timeout").value = aiConfig.timeout_s ?? 10;
    renderProviders();
    $("conn").textContent = "Connecté";
    $("conn").className = "badge ok";
    await refreshAll();
  } catch (e) {
    $("conn").textContent = "Hors ligne";
    $("conn").className = "badge ko";
    console.error(e);
  }
}

async function refreshAll() {
  await Promise.all([refreshStatus(), refreshSystem(), refreshMemory(), refreshDiagnostic()]);
}

// ── Santé ────────────────────────────────────────────────────────────────
async function refreshStatus() {
  const r = await apiGet("/api/config/ai/status");
  const tbody = document.querySelector("#tbl-status tbody");
  tbody.innerHTML = "";
  const list = r.status || [];
  if (!list.length) {
    tbody.innerHTML = "<tr><td colspan='4'>Aucun backend externe configuré (local uniquement).</td></tr>";
    return;
  }
  list.forEach((s) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${esc(s.id)}</td><td>${esc(s.type)}</td>
      <td class="${s.healthy ? "ok" : "ko"}">${s.healthy ? "✓ dispo" : "✗ injoignable"}</td>
      <td><button data-test="${esc(s.id)}">Tester</button></td>`;
    tbody.appendChild(tr);
  });
}

async function testBackend(id) {
  const r = await apiPost("/api/config/ai/test", { id });
  const out = r.reply ? `Réponse : ${r.reply}` : (r.error || "pas de réponse");
  const tag = r.healthy ? "✓ " : "✗ ";
  alert(`${tag}${r.id} (${r.type})\n${out}`);
  refreshStatus();
}

// ── Système / Mémoire / Diagnostic ───────────────────────────────────────
async function refreshSystem() {
  const r = await apiGet("/api/system");
  $("sys-info").textContent = JSON.stringify(r, null, 2).replace(/\{|\}|"/g, (m) => m).replace(/,/g, " ");
}

async function refreshMemory() {
  const r = await apiGet("/api/memory");
  const m = r.chatterbot || {};
  $("mem-info").textContent = m.corpus_statements != null
    ? `Langue : ${m.lang}\nCorpus : ${m.corpus_statements} énoncés\nApprentissage : ${m.user_statements} énoncés\nBases : ${m.corpus_db}`
    : "LadybugChatter non configuré.";
}

async function refreshDiagnostic() {
  const r = await apiGet("/api/diagnostic");
  $("diag-info").textContent = JSON.stringify({
    dossier: r.base_dir, config: r.config_present, langues: r.languages,
    ai_activé: r.ai_enabled, pipeline_connecté: r.pipeline_attached,
  }, null, 2);
}

// ── Sauvegarde ───────────────────────────────────────────────────────────
$("btn-add").addEventListener("click", () => {
  aiConfig.providers.push({ id: "", type: "ollama", host: "localhost", port: 11434, model: "qwen2.5:1.5b" });
  renderProviders();
});

document.addEventListener("input", (e) => {
  const el = e.target;
  if (!el.dataset || el.dataset.i === undefined) return;
  const i = Number(el.dataset.i);
  const f = el.dataset.f;
  if (i === -1) { // select type dans un provider
    const id = el.id && el.id.startsWith("prov-type-") ? Number(el.id.slice(10)) : null;
    return;
  }
  if (f === "type") { const prov = el.closest(".provider"); const idx = [...prov.parentNode.children].indexOf(prov); aiConfig.providers[idx].type = el.value; renderProviders(); return; }
  let v = el.value;
  if (f === "port" || f === "timeout_s" || f === "priority") v = Number(v);
  if (!aiConfig.providers[i]) return;
  aiConfig.providers[i][f] = v;
});

$("btn-save").addEventListener("click", async () => {
  const body = {
    enabled: $("ai-enabled").checked,
    priority: Number($("ai-priority").value) || 6,
    timeout_s: Number($("ai-timeout").value) || 10,
    providers: aiConfig.providers,
  };
  const r = await apiPost("/api/config/ai", body);
  $("save-msg").textContent = r.ok ? "✓ Enregistré" : "✗ Erreur";
  if (r.ok) { aiConfig = r.ai; renderProviders(); refreshAll(); }
  setTimeout(() => ($("save-msg").textContent = ""), 2500);
});

document.addEventListener("click", (e) => {
  if (e.target.dataset && e.target.dataset.del !== undefined) {
    aiConfig.providers.splice(Number(e.target.dataset.del), 1);
    renderProviders();
  }
  if (e.target.dataset && e.target.dataset.test !== undefined) {
    testBackend(e.target.dataset.test);
  }
});

// ── Chat ─────────────────────────────────────────────────────────────────
$("btn-chat").addEventListener("click", sendChat);
$("chat-input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendChat(); });

async function sendChat() {
  const text = $("chat-input").value.trim();
  if (!text) return;
  const out = $("chat-out");
  out.innerHTML += `<div><b>Vous :</b> ${esc(text)}</div>`;
  $("chat-input").value = "";
  const r = await apiPost("/api/chat", { text });
  out.innerHTML += `<div><b>Phoenix</b> <span class="tag">${esc(r.source || "")}</span> : ${esc(r.text || "")}</div>`;
  out.scrollTop = out.scrollHeight;
}

$("btn-refresh-status").addEventListener("click", refreshStatus);

load();
