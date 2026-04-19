// ================================================================
// desktop.organizer — frontend logic
// talks to Python via window.pywebview.api (see bridge.py)
// ================================================================

const MODE_COLORS = ["#8fa3ff", "#5dcaa5", "#ef9f27", "#d4537e", "#F0997B"];
const PRESET_COLORS = {
  left_half:   "#8fa3ff",
  right_half:  "#5dcaa5",
  top_half:    "#ef9f27",
  bottom_half: "#d4537e",
  maximized:   "#F0997B",
  custom:      "#8fa3ff",
};
const PRESETS = ["left_half", "right_half", "top_half", "bottom_half", "maximized", "custom"];

const state = {
  modes: [],
  selected: null,
  monitors: [],
  openWindows: [],
  editIndex: null,
  statsTimer: null,
};

// --- helpers ----------------------------------------------------

const $ = (id) => document.getElementById(id);

const api = () => (window.pywebview && window.pywebview.api) || null;

function waitForApi() {
  return new Promise((resolve) => {
    if (api()) return resolve();
    const t = setInterval(() => {
      if (api()) { clearInterval(t); resolve(); }
    }, 50);
  });
}

function toast(msg, ms = 1600) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add("hidden"), ms);
}

function modeColor(name) {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return MODE_COLORS[h % MODE_COLORS.length];
}

function hexWithAlpha(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
  return `rgba(${r},${g},${b},${alpha})`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function shortProcName(p) {
  if (!p) return "—";
  return p.replace(/^.*[\\/]/, "").toLowerCase();
}

// --- data loading ----------------------------------------------

async function loadAll() {
  const [modesDoc, monitors] = await Promise.all([
    api().get_modes(),
    api().get_monitors(),
  ]);
  state.modes = (modesDoc && modesDoc.modes) || [];
  state.monitors = monitors || [];
  renderSidebar();
  updateMonitorStatus();
  if (state.selected && !state.modes.find(m => m.name === state.selected)) {
    state.selected = null;
  }
  if (!state.selected && state.modes.length) {
    state.selected = state.modes[0].name;
  }
  renderDetail();
}

function updateMonitorStatus() {
  const n = state.monitors.length;
  const label = $("mon-label");
  const dot = $("mon-dot");
  if (n === 0) {
    label.textContent = "no monitors";
    dot.classList.add("warn");
  } else {
    label.textContent = `${n} monitor${n > 1 ? "s" : ""} · ${n > 1 ? "docked" : "undocked"}`;
    dot.classList.remove("warn");
  }
}

// --- sidebar ----------------------------------------------------

function renderSidebar() {
  const list = $("mode-list");
  list.innerHTML = "";
  if (!state.modes.length) {
    const empty = document.createElement("div");
    empty.style.cssText = "color: var(--muted-3); font-size: 11px; padding: 16px 4px; text-align: center;";
    empty.textContent = "no modes yet";
    list.appendChild(empty);
    return;
  }
  for (const mode of state.modes) {
    const btn = document.createElement("button");
    btn.className = "mode-item" + (mode.name === state.selected ? " active" : "");
    btn.type = "button";
    const count = (mode.apps || []).length;
    const color = modeColor(mode.name);
    btn.innerHTML = `
      <span class="dot" style="background:${color}"></span>
      <span>${escapeHtml(mode.name.toLowerCase())}</span>
      <span class="count">${count}</span>
    `;
    btn.onclick = () => { state.selected = mode.name; renderSidebar(); renderDetail(); };
    list.appendChild(btn);
  }
}

// --- detail pane ------------------------------------------------

function currentMode() {
  return state.modes.find(m => m.name === state.selected) || null;
}

function renderDetail() {
  const mode = currentMode();
  const titleEl = $("mode-title-text");
  const statsEl = $("stats-line");
  const hasMode = !!mode;

  // disable action buttons when no mode selected
  for (const id of ["btn-rename", "btn-delete", "btn-capture", "btn-apply", "btn-add-app"]) {
    $(id).disabled = !hasMode;
  }

  if (!hasMode) {
    titleEl.textContent = "no mode selected";
    statsEl.innerHTML = `<span class="t-ok">$</span> idle`;
    $("preview").innerHTML = `<div class="empty-preview">select or create a mode</div>`;
    $("apps-list").innerHTML = "";
    return;
  }

  titleEl.textContent = mode.name.toLowerCase();
  refreshStats();
  renderPreview();
  renderApps();
}

async function refreshStats() {
  const mode = currentMode();
  if (!mode) return;
  try {
    const s = await api().get_mode_stats(mode.name);
    $("stats-line").innerHTML =
      `<span class="t-ok">$</span> last_applied=<span class="t-warn">${s.last_applied}</span>` +
      ` · apps=<span class="t-warn">${s.apps}</span>` +
      ` · monitors=<span class="t-warn">${s.monitors}</span>`;
  } catch (e) { /* ignore */ }
}

// --- preview ----------------------------------------------------

function renderPreview() {
  const wrap = $("preview");
  wrap.innerHTML = "";
  const mode = currentMode();
  if (!mode || !state.monitors.length) {
    wrap.innerHTML = `<div class="empty-preview">no monitors detected</div>`;
    return;
  }

  // compute scale so widest arrangement fits in ~560px, heights bounded too
  const maxW = 560, maxH = 140;
  let totalW = 0, maxMonH = 0;
  for (const m of state.monitors) { totalW += m.width; maxMonH = Math.max(maxMonH, m.height); }
  const scale = Math.min(maxW / Math.max(1, totalW + (state.monitors.length - 1) * 20), maxH / Math.max(1, maxMonH));

  // group each monitor with a caption
  const container = document.createElement("div");
  container.style.cssText = "display:flex; gap:16px; justify-content:center; align-items:flex-start; width:100%;";
  for (const m of state.monitors) {
    const g = document.createElement("div");
    g.className = "mon-group";

    const rect = document.createElement("div");
    rect.className = "mon-rect";
    rect.style.width = Math.round(m.width * scale) + "px";
    rect.style.height = Math.round(m.height * scale) + "px";

    // place app rects for this monitor
    for (const app of (mode.apps || [])) {
      if (app.monitor_index !== m.index) continue;
      const geo = resolveAppGeometry(app, m);
      if (!geo) continue;
      const el = document.createElement("div");
      el.className = "app-rect";
      const color = PRESET_COLORS[app.preset] || "#8fa3ff";
      el.style.background = hexWithAlpha(color, 0.10);
      el.style.border = `0.5px solid ${color}`;
      el.style.color = color;
      // position relative to monitor origin
      const relX = Math.max(0, (geo.x - m.x) * scale);
      const relY = Math.max(0, (geo.y - m.y) * scale);
      const relW = Math.min(m.width * scale - relX, geo.w * scale);
      const relH = Math.min(m.height * scale - relY, geo.h * scale);
      el.style.left = Math.round(relX) + "px";
      el.style.top = Math.round(relY) + "px";
      el.style.width = Math.max(8, Math.round(relW)) + "px";
      el.style.height = Math.max(8, Math.round(relH)) + "px";
      el.textContent = shortProcName(app.process_name).replace(".exe", "");
      rect.appendChild(el);
    }

    g.appendChild(rect);
    const cap = document.createElement("div");
    cap.className = "mon-caption";
    cap.textContent = `mon_${m.index + 1} · ${m.width}×${m.height}${m.is_primary ? " · primary" : ""}`;
    g.appendChild(cap);
    container.appendChild(g);
  }
  wrap.appendChild(container);
}

function resolveAppGeometry(app, mon) {
  const preset = (app.preset || "custom").toLowerCase();
  const { x, y, width, height } = mon;
  if (preset === "maximized") return { x, y, w: width, h: height };
  if (preset === "left_half") return { x, y, w: Math.floor(width / 2), h: height };
  if (preset === "right_half") return { x: x + Math.floor(width / 2), y, w: width - Math.floor(width / 2), h: height };
  if (preset === "top_half") return { x, y, w: width, h: Math.floor(height / 2) };
  if (preset === "bottom_half") return { x, y: y + Math.floor(height / 2), w: width, h: height - Math.floor(height / 2) };
  const p = app.position || {};
  return { x: p.x ?? x, y: p.y ?? y, w: p.width ?? width, h: p.height ?? height };
}

// --- apps list --------------------------------------------------

function renderApps() {
  const list = $("apps-list");
  list.innerHTML = "";
  const mode = currentMode();
  const apps = (mode && mode.apps) || [];
  if (!apps.length) {
    list.innerHTML = `<div class="empty-apps">no apps yet — click <span style="color:var(--accent)">+ add</span> to define one</div>`;
    return;
  }
  apps.forEach((app, idx) => {
    const row = document.createElement("div");
    row.className = "app-row";
    row.innerHTML = `
      <span class="arrow">▸</span>
      <span class="pname">${escapeHtml(shortProcName(app.process_name))}</span>
      <span class="mon">mon_${(app.monitor_index ?? 0) + 1}</span>
      <span class="preset">${escapeHtml((app.preset || "custom").toLowerCase())}</span>
      <span class="menu" data-idx="${idx}">···</span>
    `;
    const menuBtn = row.querySelector(".menu");
    menuBtn.onclick = (e) => { e.stopPropagation(); openRowMenu(menuBtn, idx); };
    list.appendChild(row);
  });
}

function openRowMenu(anchor, idx) {
  document.querySelectorAll(".menu-dd").forEach(n => n.remove());
  const dd = document.createElement("div");
  dd.className = "menu-dd";
  dd.innerHTML = `
    <button type="button" data-act="edit">edit</button>
    <button type="button" class="danger" data-act="delete">delete</button>
  `;
  anchor.appendChild(dd);
  const closeOn = (ev) => { if (!dd.contains(ev.target)) { dd.remove(); document.removeEventListener("click", closeOn); } };
  setTimeout(() => document.addEventListener("click", closeOn), 0);
  dd.querySelectorAll("button").forEach(b => {
    b.onclick = async () => {
      const act = b.dataset.act;
      dd.remove();
      if (act === "edit") openAppModal(idx);
      if (act === "delete") {
        const mode = currentMode();
        await api().remove_app_from_mode(mode.name, idx);
        await loadAll();
      }
    };
  });
}

// --- add / edit app modal --------------------------------------

async function openAppModal(editIdx = null) {
  state.editIndex = editIdx;
  state.openWindows = await api().get_open_windows();
  const mode = currentMode();

  $("modal-add-title").textContent = editIdx === null ? "» add app" : "» edit app";

  // running windows dropdown
  const sel = $("fld-win");
  sel.innerHTML = `<option value="">— pick one —</option>`;
  for (const w of state.openWindows) {
    const opt = document.createElement("option");
    opt.value = w.process_name + "|" + w.title;
    const label = `${w.process_name}${w.title ? " · " + w.title.slice(0, 50) : ""}`;
    opt.textContent = label;
    sel.appendChild(opt);
  }
  sel.onchange = () => {
    const v = sel.value;
    if (!v) return;
    const [proc, title] = v.split("|");
    $("fld-proc").value = proc;
    $("fld-title").value = title || "";
  };

  // monitors
  const monBox = $("fld-monitors");
  monBox.innerHTML = "";
  state.monitors.forEach(m => {
    const lbl = document.createElement("label");
    lbl.innerHTML = `<input type="radio" name="mon" value="${m.index}" /> mon_${m.index + 1} · ${m.width}×${m.height}${m.is_primary ? " · primary" : ""}`;
    monBox.appendChild(lbl);
  });

  // presets
  const preBox = $("fld-presets");
  preBox.innerHTML = "";
  PRESETS.forEach(p => {
    const lbl = document.createElement("label");
    lbl.innerHTML = `<input type="radio" name="preset" value="${p}" /> ${p}`;
    preBox.appendChild(lbl);
  });
  preBox.onchange = () => {
    const val = preBox.querySelector('input[name="preset"]:checked')?.value;
    $("fld-custom").classList.toggle("hidden", val !== "custom");
  };

  // populate for edit
  if (editIdx !== null) {
    const app = mode.apps[editIdx];
    $("fld-proc").value = app.process_name || "";
    $("fld-title").value = app.window_title_match || "";
    $("fld-launch").value = app.launch_path || "";
    const monR = monBox.querySelector(`input[name="mon"][value="${app.monitor_index ?? 0}"]`);
    if (monR) monR.checked = true; else monBox.querySelector('input[name="mon"]')?.click();
    const preR = preBox.querySelector(`input[name="preset"][value="${app.preset || "custom"}"]`);
    if (preR) preR.checked = true;
    $("fld-custom").classList.toggle("hidden", (app.preset || "custom") !== "custom");
    const p = app.position || {};
    $("cx").value = p.x ?? ""; $("cy").value = p.y ?? "";
    $("cw").value = p.width ?? ""; $("ch").value = p.height ?? "";
  } else {
    $("fld-proc").value = ""; $("fld-title").value = ""; $("fld-launch").value = "";
    const firstMon = monBox.querySelector('input[name="mon"]'); if (firstMon) firstMon.checked = true;
    const lh = preBox.querySelector('input[name="preset"][value="left_half"]'); if (lh) lh.checked = true;
    $("fld-custom").classList.add("hidden");
    $("cx").value = ""; $("cy").value = ""; $("cw").value = ""; $("ch").value = "";
  }

  showModal("modal-add");
}

function readAppFromModal() {
  const proc = $("fld-proc").value.trim();
  if (!proc) { toast("process name required"); return null; }
  const monR = document.querySelector('input[name="mon"]:checked');
  const preR = document.querySelector('input[name="preset"]:checked');
  const monitor_index = monR ? parseInt(monR.value, 10) : 0;
  const preset = preR ? preR.value : "custom";
  const pos = {
    x: parseInt($("cx").value) || 0,
    y: parseInt($("cy").value) || 0,
    width: parseInt($("cw").value) || 0,
    height: parseInt($("ch").value) || 0,
  };
  return {
    process_name: proc,
    window_title_match: $("fld-title").value.trim(),
    launch_path: $("fld-launch").value.trim(),
    monitor_index,
    preset,
    position: pos,
  };
}

// --- modal helpers ---------------------------------------------

function showModal(id) {
  $("backdrop").classList.remove("hidden");
  $(id).classList.remove("hidden");
}
function hideModals() {
  $("backdrop").classList.add("hidden");
  document.querySelectorAll(".modal").forEach(m => m.classList.add("hidden"));
}

function promptInput(title, initial = "") {
  return new Promise((resolve) => {
    $("prompt-title").textContent = title;
    const input = $("prompt-input");
    input.value = initial;
    showModal("modal-prompt");
    setTimeout(() => input.focus(), 50);
    const ok = () => { hideModals(); cleanup(); resolve(input.value.trim() || null); };
    const cancel = () => { hideModals(); cleanup(); resolve(null); };
    const key = (e) => { if (e.key === "Enter") ok(); if (e.key === "Escape") cancel(); };
    const cleanup = () => {
      $("prompt-ok").onclick = null;
      $("prompt-cancel").onclick = null;
      input.removeEventListener("keydown", key);
    };
    $("prompt-ok").onclick = ok;
    $("prompt-cancel").onclick = cancel;
    input.addEventListener("keydown", key);
  });
}

// --- monitor-change picker (from Python) ------------------------

window.__onMonitorChanged = (data) => {
  const count = (data && data.count) || 0;
  $("picker-hint").textContent = `detected ${count} monitor${count !== 1 ? "s" : ""}. pick a mode to apply:`;
  const box = $("picker-modes");
  box.innerHTML = "";
  for (const m of state.modes) {
    const b = document.createElement("button");
    b.type = "button";
    b.innerHTML = `<span class="dot" style="background:${modeColor(m.name)}"></span><span>${escapeHtml(m.name.toLowerCase())}</span>`;
    b.onclick = async () => {
      hideModals();
      await api().apply_mode(m.name);
      toast(`applying ${m.name.toLowerCase()}…`);
    };
    box.appendChild(b);
  }
  if (!state.modes.length) {
    box.innerHTML = `<div style="color:var(--muted);font-size:11px;padding:8px 0;">no modes saved yet</div>`;
  }
  showModal("modal-picker");
  // also refresh sidebar status
  loadAll();
};

// --- wire up UI -------------------------------------------------

function wire() {
  $("btn-new-mode").onclick = async () => {
    const name = await promptInput("» new mode");
    if (!name) return;
    const res = await api().create_mode(name);
    if (!res.ok) { toast(res.error || "failed"); return; }
    state.selected = name;
    await loadAll();
  };

  $("btn-rename").onclick = async () => {
    const mode = currentMode(); if (!mode) return;
    const name = await promptInput("» rename", mode.name);
    if (!name || name === mode.name) return;
    const res = await api().rename_mode(mode.name, name);
    if (!res.ok) { toast(res.error || "failed"); return; }
    state.selected = name;
    await loadAll();
  };

  $("btn-delete").onclick = async () => {
    const mode = currentMode(); if (!mode) return;
    const ok = await promptInput(`» delete ${mode.name.toLowerCase()}? type YES`);
    if (ok !== "YES") { toast("cancelled"); return; }
    await api().delete_mode(mode.name);
    state.selected = null;
    await loadAll();
  };

  $("btn-capture").onclick = async () => {
    const mode = currentMode(); if (!mode) return;
    const res = await api().capture_current_layout(mode.name);
    if (res.ok) toast(`captured ${res.count} apps`);
    else toast(res.error || "capture failed");
    await loadAll();
  };

  $("btn-apply").onclick = async () => {
    const mode = currentMode(); if (!mode) return;
    await api().apply_mode(mode.name);
    toast(`applying ${mode.name.toLowerCase()}…`);
    setTimeout(refreshStats, 1200);
  };

  $("btn-add-app").onclick = () => openAppModal(null);

  $("modal-add-cancel").onclick = hideModals;
  $("modal-add-save").onclick = async () => {
    const cfg = readAppFromModal();
    if (!cfg) return;
    const mode = currentMode();
    if (state.editIndex === null) {
      await api().add_app_to_mode(mode.name, cfg);
    } else {
      await api().update_app_in_mode(mode.name, state.editIndex, cfg);
    }
    hideModals();
    await loadAll();
  };

  $("btn-refresh-wins").onclick = async () => {
    state.openWindows = await api().get_open_windows();
    const sel = $("fld-win");
    sel.innerHTML = `<option value="">— pick one —</option>`;
    for (const w of state.openWindows) {
      const opt = document.createElement("option");
      opt.value = w.process_name + "|" + w.title;
      opt.textContent = `${w.process_name}${w.title ? " · " + w.title.slice(0, 50) : ""}`;
      sel.appendChild(opt);
    }
    toast(`${state.openWindows.length} windows`);
  };

  $("picker-dismiss").onclick = hideModals;
  $("btn-quit").onclick = () => api().minimize_to_tray();

  // close modals on backdrop click
  $("backdrop").onclick = hideModals;

  // escape closes any modal
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") hideModals();
  });

  // periodic stats refresh (for relative time in stats line)
  state.statsTimer = setInterval(refreshStats, 15000);
}

// --- boot ------------------------------------------------------

(async function boot() {
  await waitForApi();
  wire();
  await loadAll();
})();