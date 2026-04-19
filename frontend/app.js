/**
 * desktop organizer — webview frontend
 */

const MODE_DOTS = ["#5dcaa5", "#ef9f27", "#d4537e"];

function api() {
  const p = window.pywebview && window.pywebview.api;
  if (!p) throw new Error("pywebview api not ready");
  return p;
}

async function callApi(name, ...args) {
  const fn = api()[name];
  if (typeof fn !== "function") throw new Error("missing api: " + name);
  return await fn(...args);
}

let selectedMode = null;
let editAppIndex = null;

function $(id) {
  return document.getElementById(id);
}

function rectForPreset(bounds, preset, position) {
  const [mx, my, mw, mh] = bounds;
  const key = (preset || "custom").toLowerCase();
  if (key === "maximized") return [mx, my, mw, mh];
  if (key === "left_half") return [mx, my, Math.floor(mw / 2), mh];
  if (key === "right_half") {
    const w = mw - Math.floor(mw / 2);
    return [mx + Math.floor(mw / 2), my, w, mh];
  }
  if (key === "top_half") return [mx, my, mw, Math.floor(mh / 2)];
  if (key === "bottom_half") {
    const h = mh - Math.floor(mh / 2);
    return [mx, my + Math.floor(mh / 2), mw, h];
  }
  const pos = position || {};
  const x = Number(pos.x ?? mx);
  const y = Number(pos.y ?? my);
  const w = Math.max(1, Number(pos.width ?? mw));
  const h = Math.max(1, Number(pos.height ?? mh));
  return [x, y, w, h];
}

async function refreshMonitorBadge() {
  try {
    const n = await callApi("get_monitor_count");
    $("mon-label").textContent = "monitors: " + n;
  } catch (e) {
    $("mon-label").textContent = "monitors: ?";
  }
}

async function loadModeList() {
  const data = await callApi("get_modes");
  const modes = data.modes || [];
  const el = $("mode-list");
  el.innerHTML = "";
  modes.forEach((m, i) => {
    const name = (m.name || "").toLowerCase();
    const apps = (m.apps || []).length;
    const dot = MODE_DOTS[i % MODE_DOTS.length];
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "mode-item" + (selectedMode === m.name ? " active" : "");
    btn.dataset.name = m.name;
    btn.innerHTML =
      '<span class="mode-dot" style="background:' +
      dot +
      '"></span><span>' +
      escapeHtml(name) +
      '</span><span class="mode-meta">' +
      apps +
      "</span>";
    btn.addEventListener("click", () => selectMode(m.name));
    el.appendChild(btn);
  });
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

async function selectMode(name) {
  selectedMode = name;
  $("mode-title-text").textContent = (name || "").toLowerCase();
  await refreshStats();
  await renderPreview();
  await renderApps();
  await loadModeList();
}

async function refreshStats() {
  if (!selectedMode) {
    try {
      const mons = await callApi("get_monitors");
      $("stats-line").innerHTML =
        "$ idle · apps=<span class='hl'>0</span> · monitors=<span class='hl'>" +
        mons.length +
        "</span>";
    } catch (_) {
      $("stats-line").innerHTML =
        "$ idle · apps=<span class='hl'>0</span> · monitors=<span class='hl'>?</span>";
    }
    return;
  }
  const st = await callApi("get_mode_stats", selectedMode);
  $("stats-line").innerHTML =
    "$ last_applied=<span class='hl'>" +
    escapeHtml(st.last_applied) +
    "</span> · apps=<span class='hl'>" +
    st.apps +
    "</span> · monitors=<span class='hl'>" +
    st.monitors +
    "</span>";
}

async function renderPreview() {
  const box = $("preview");
  box.innerHTML = "";
  const mons = await callApi("get_monitors");
  if (!mons.length) {
    box.textContent = "// no monitors";
    return;
  }
  let minX = Infinity,
    minY = Infinity,
    maxX = -Infinity,
    maxY = -Infinity;
  mons.forEach((m) => {
    minX = Math.min(minX, m.x);
    minY = Math.min(minY, m.y);
    maxX = Math.max(maxX, m.x + m.width);
    maxY = Math.max(maxY, m.y + m.height);
  });
  const totalW = maxX - minX;
  const totalH = maxY - minY;
  const wrap = $("preview-wrap");
  const pw = Math.max(wrap.clientWidth - 8, 120);
  const ph = 200;
  const pad = 10;
  const scale = Math.min((pw - 2 * pad) / totalW, (ph - 2 * pad) / totalH, 1);
  box.style.height = ph + "px";

  mons.forEach((m) => {
    const d = document.createElement("div");
    d.className = "mon-rect";
    const x = pad + (m.x - minX) * scale;
    const y = pad + (m.y - minY) * scale;
    const w = m.width * scale;
    const h = m.height * scale;
    d.style.left = x + "px";
    d.style.top = y + "px";
    d.style.width = w + "px";
    d.style.height = h + "px";
    const lab = document.createElement("div");
    lab.className = "mon-label";
    lab.textContent = m.width + "×" + m.height + (m.is_primary ? " · primary" : "");
    d.appendChild(lab);
    box.appendChild(d);
  });

  const mode = selectedMode ? await callApi("get_mode", selectedMode) : null;
  const apps = (mode && mode.apps) || [];
  for (const app of apps) {
    let bounds = null;
    for (const mon of mons) {
      if (Number(mon.index) === Number(app.monitor_index)) {
        bounds = [mon.x, mon.y, mon.width, mon.height];
        break;
      }
    }
    if (!bounds && mons[0]) bounds = [mons[0].x, mons[0].y, mons[0].width, mons[0].height];
    if (!bounds) continue;
    const [rx, ry, rw, rh] = rectForPreset(
      bounds,
      app.preset || "custom",
      app.position || {}
    );
    const d = document.createElement("div");
    d.className = "app-rect";
    d.style.left = pad + (rx - minX) * scale + "px";
    d.style.top = pad + (ry - minY) * scale + "px";
    d.style.width = Math.max(2, rw * scale) + "px";
    d.style.height = Math.max(2, rh * scale) + "px";
    box.appendChild(d);
  }
}

async function renderApps() {
  const el = $("apps-list");
  el.innerHTML = "";
  if (!selectedMode) {
    el.innerHTML = '<div class="hint">select a mode from the sidebar</div>';
    return;
  }
  const mode = await callApi("get_mode", selectedMode);
  const apps = (mode && mode.apps) || [];
  if (!apps.length) {
    el.innerHTML = '<div class="hint">no apps — use + add or capture</div>';
    return;
  }
  apps.forEach((app, idx) => {
    const row = document.createElement("div");
    row.className = "app-row";
    const proc = (app.process_name || "").toLowerCase();
    const meta =
      "m" +
      (app.monitor_index ?? 0) +
      " · " +
      (app.preset || "custom").toLowerCase();
    row.innerHTML =
      '<span class="arrow">▸</span><span class="pname">' +
      escapeHtml(proc) +
      '</span><span class="meta">' +
      escapeHtml(meta) +
      '</span><div class="menu-wrap"><button type="button" class="menu-btn">···</button><div class="menu-dd hidden"></div></div>';

    const btn = row.querySelector(".menu-btn");
    const dd = row.querySelector(".menu-dd");
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const willOpen = dd.classList.contains("hidden");
      document.querySelectorAll(".menu-dd").forEach((x) => {
        if (x !== dd) x.classList.add("hidden");
      });
      if (!willOpen) {
        dd.classList.add("hidden");
        return;
      }
      dd.innerHTML =
        '<button type="button" data-act="edit">edit</button><button type="button" data-act="del">delete</button>';
      dd.querySelector('[data-act="edit"]').onclick = () => {
        dd.classList.add("hidden");
        openAddDialog(idx);
      };
      dd.querySelector('[data-act="del"]').onclick = async () => {
        dd.classList.add("hidden");
        await callApi("remove_app_from_mode", selectedMode, idx);
        await selectMode(selectedMode);
      };
      dd.classList.remove("hidden");
    });
    el.appendChild(row);
  });
}

document.addEventListener("click", () => {
  document.querySelectorAll(".menu-dd").forEach((d) => d.classList.add("hidden"));
});

function showModal(id, show) {
  const m = $(id);
  const bd = $("backdrop");
  if (show) {
    m.classList.remove("hidden");
    bd.classList.remove("hidden");
  } else {
    m.classList.add("hidden");
    if (!document.querySelector(".modal:not(.hidden)")) bd.classList.add("hidden");
  }
}

async function fillWindowSelect() {
  const wins = await callApi("get_open_windows");
  const sel = $("fld-win");
  sel.innerHTML = "";
  wins.forEach((w) => {
    const o = document.createElement("option");
    const t = (w.title || "").slice(0, 80);
    o.value = JSON.stringify({ process_name: w.process_name, title: t });
    o.textContent = (w.process_name || "") + " — " + t;
    sel.appendChild(o);
  });
  if (!wins.length) {
    const o = document.createElement("option");
    o.value = "{}";
    o.textContent = "(no windows)";
    sel.appendChild(o);
  }
}

function onWinSelectChange() {
  try {
    const v = JSON.parse($("fld-win").value || "{}");
    if (v.process_name) $("fld-proc").value = v.process_name;
  } catch (_) {}
}

async function fillMonitorsRadios() {
  const mons = await callApi("get_monitors");
  const host = $("fld-monitors");
  host.innerHTML = "";
  mons.forEach((m) => {
    const id = "mon-" + m.index;
    const lab = document.createElement("label");
    lab.innerHTML =
      '<input type="radio" name="mon" value="' +
      m.index +
      '" id="' +
      id +
      '" ' +
      (m.is_primary ? "checked" : "") +
      " /> " +
      m.index +
      " · " +
      m.width +
      "×" +
      m.height +
      (m.is_primary ? " · primary" : "");
    host.appendChild(lab);
  });
}

function fillPresets() {
  const host = $("fld-presets");
  const presets = [
    ["left_half", "left half"],
    ["right_half", "right half"],
    ["top_half", "top half"],
    ["bottom_half", "bottom half"],
    ["maximized", "maximized"],
    ["custom", "custom"],
  ];
  host.innerHTML = "";
  presets.forEach(([val, label], i) => {
    const id = "pr-" + val;
    const lab = document.createElement("label");
    lab.innerHTML =
      '<input type="radio" name="preset" value="' +
      val +
      '" id="' +
      id +
      '" ' +
      (i === 0 ? "checked" : "") +
      " /> " +
      label;
    host.appendChild(lab);
  });
  host.querySelectorAll('input[name="preset"]').forEach((r) => {
    r.addEventListener("change", () => {
      const c = $("fld-custom");
      const v = (host.querySelector('input[name="preset"]:checked') || {}).value;
      c.classList.toggle("hidden", v !== "custom");
    });
  });
}

function presetRadio(value) {
  return $("fld-presets").querySelector('input[name="preset"][value="' + value + '"]');
}

async function openAddDialog(editIndex) {
  editAppIndex = editIndex == null ? null : Number(editIndex);
  $("modal-add-title").textContent = editAppIndex == null ? "» add app" : "» edit app";
  $("fld-proc").value = "";
  $("fld-title").value = "";
  $("fld-launch").value = "";
  $("cx").value = $("cy").value = $("cw").value = $("ch").value = "";

  await fillWindowSelect();
  await fillMonitorsRadios();
  fillPresets();
  $("fld-win").onchange = onWinSelectChange;
  onWinSelectChange();

  if (editAppIndex != null && selectedMode) {
    const mode = await callApi("get_mode", selectedMode);
    const app = (mode.apps || [])[editAppIndex];
    if (app) {
      $("fld-proc").value = (app.process_name || "").toLowerCase();
      $("fld-title").value = app.window_title_match || "";
      $("fld-launch").value = app.launch_path || "";
      const pr = (app.preset || "custom").toLowerCase();
      const prEl = presetRadio(pr);
      if (prEl) prEl.checked = true;
      const pos = app.position || {};
      $("cx").value = pos.x ?? "";
      $("cy").value = pos.y ?? "";
      $("cw").value = pos.width ?? "";
      $("ch").value = pos.height ?? "";
      const mi = String(app.monitor_index ?? 0);
      const mr = $("fld-monitors").querySelector('input[name="mon"][value="' + mi + '"]');
      if (mr) mr.checked = true;
    }
  }
  const v = ($("fld-presets").querySelector('input[name="preset"]:checked') || {}).value;
  $("fld-custom").classList.toggle("hidden", v !== "custom");
  showModal("modal-add", true);
}

async function saveAddDialog() {
  const proc = $("fld-proc").value.trim().toLowerCase();
  if (!proc) return;
  let procNorm = proc.split(/[/\\]/).pop();
  if (!procNorm.toLowerCase().endsWith(".exe")) procNorm = procNorm + ".exe";
  const mon = ($("fld-monitors").querySelector('input[name="mon"]:checked') || {}).value || "0";
  const preset = ($("fld-presets").querySelector('input[name="preset"]:checked') || {}).value || "custom";
  const cfg = {
    process_name: procNorm,
    window_title_match: $("fld-title").value.trim(),
    launch_path: $("fld-launch").value.trim(),
    monitor_index: Number(mon),
    preset: preset,
    position: {
      x: Number($("cx").value || 0),
      y: Number($("cy").value || 0),
      width: Number($("cw").value || 800),
      height: Number($("ch").value || 600),
    },
  };
  let res;
  if (editAppIndex == null) {
    res = await callApi("add_app_to_mode", selectedMode, cfg);
  } else {
    res = await callApi("update_app_in_mode", selectedMode, editAppIndex, cfg);
  }
  if (!res.ok) return;
  showModal("modal-add", false);
  await selectMode(selectedMode);
}

function openMonitorPicker(count) {
  $("picker-hint").textContent =
    "monitor count is now " + count + ". pick a mode to apply:";
  const host = $("picker-modes");
  host.innerHTML = "";
  callApi("get_modes").then((data) => {
    (data.modes || []).forEach((m) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = (m.name || "").toLowerCase();
      b.addEventListener("click", async () => {
        await callApi("apply_mode", m.name);
        showModal("modal-picker", false);
        if (selectedMode === m.name) await refreshStats();
      });
      host.appendChild(b);
    });
    showModal("modal-picker", true);
  });
}

window.__onMonitorChanged = function (payload) {
  openMonitorPicker(payload.count);
};

async function init() {
  $("btn-new-mode").onclick = async () => {
    const name = prompt("new mode name:");
    if (!name) return;
    const r = await callApi("create_mode", name.trim());
    if (!r.ok) {
      alert(r.error || "could not create");
      return;
    }
    await loadModeList();
    await selectMode(name.trim());
  };

  $("btn-rename").onclick = async () => {
    if (!selectedMode) return;
    const nn = prompt("rename mode to:", selectedMode);
    if (!nn || nn === selectedMode) return;
    const r = await callApi("rename_mode", selectedMode, nn.trim());
    if (!r.ok) {
      alert(r.error || "rename failed");
      return;
    }
    await loadModeList();
    await selectMode(nn.trim());
  };

  $("btn-capture").onclick = async () => {
    if (!selectedMode) return;
    const r = await callApi("capture_current_layout", selectedMode);
    if (!r.ok) alert(r.error || "capture failed");
    await selectMode(selectedMode);
  };

  $("btn-apply").onclick = async () => {
    if (!selectedMode) return;
    await callApi("apply_mode", selectedMode);
    await refreshStats();
  };

  $("btn-add-app").onclick = () => openAddDialog(null);
  $("btn-refresh-wins").onclick = async () => {
    await fillWindowSelect();
    onWinSelectChange();
  };
  $("modal-add-cancel").onclick = () => showModal("modal-add", false);
  $("modal-add-save").onclick = saveAddDialog;
  $("picker-dismiss").onclick = () => showModal("modal-picker", false);

  await loadModeList();
  const modes = (await callApi("get_modes")).modes || [];
  if (modes.length && modes[0].name) await selectMode(modes[0].name);
  else await refreshStats();

  setInterval(() => {
    refreshMonitorBadge().catch(() => {});
  }, 4000);
  await refreshMonitorBadge();
  window.addEventListener("resize", () => {
    if (selectedMode) renderPreview();
  });
}

window.addEventListener("pywebviewready", () => {
  init().catch((e) => console.error(e));
});
