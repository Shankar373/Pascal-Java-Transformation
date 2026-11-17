/* Stage 1 dashboard. All DOM is built with createElement/textContent: data is
 * never parsed as markup. No inline script or style, no external resources. */
"use strict";

(function () {
  const ID_RE = /^[0-9a-f]{16}$/;
  const SVG_NS = "http://www.w3.org/2000/svg";
  const MAX_ROWS = 200;
  const POLL_MIN_MS = 1000;
  const POLL_MAX_MS = 8000;
  const STEP_DEFS = [
    ["ingestion", "Ingestion"], ["checkpoint", "Checkpoint"],
    ["scanning_inventory", "Scanning & Inventory"],
    ["dependency_analysis", "Dependency Analysis"], ["blueprint", "Application Blueprint"],
  ];
  const DONE_TEXT = {
    ingestion: "Completed", checkpoint: "Created", scanning_inventory: "Completed",
    dependency_analysis: "Completed", blueprint: "Generated",
  };
  const SOURCE_LABEL = { git: "Git Repository", zip: "ZIP Archive", directory: "Local Directory" };
  const ORIGIN_LABEL = { git: "Repository", zip: "Archive", directory: "Directory" };
  const COMPONENT_ICON = {
    gui_application: "monitor", database: "database", com_activex: "gear", reports: "chart",
    scheduled_jobs: "calendar", services: "gear", build_scripts: "terminal",
    documentation: "book", integrations: "link",
  };

  const ICONS = {
    logo: [["polyline", { points: "16 18 22 12 16 6" }], ["polyline", { points: "8 6 2 12 8 18" }], ["line", { x1: 14, y1: 4, x2: 10, y2: 20 }]],
    home: [["path", { d: "M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" }], ["polyline", { points: "9 22 9 12 15 12 15 22" }]],
    folder: [["path", { d: "M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" }]],
    file: [["path", { d: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" }], ["polyline", { points: "14 2 14 8 20 8" }], ["line", { x1: 8, y1: 13, x2: 16, y2: 13 }], ["line", { x1: 8, y1: 17, x2: 16, y2: 17 }]],
    report: [["path", { d: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" }], ["polyline", { points: "14 2 14 8 20 8" }], ["polyline", { points: "9 15 11 17 15 13" }]],
    gear: [["circle", { cx: 12, cy: 12, r: 3 }], ["path", { d: "M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1" }]],
    upload: [["path", { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" }], ["polyline", { points: "17 8 12 3 7 8" }], ["line", { x1: 12, y1: 3, x2: 12, y2: 15 }]],
    download: [["path", { d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" }], ["polyline", { points: "7 10 12 15 17 10" }], ["line", { x1: 12, y1: 15, x2: 12, y2: 3 }]],
    calendar: [["rect", { x: 3, y: 4, width: 18, height: 18, rx: 2 }], ["line", { x1: 16, y1: 2, x2: 16, y2: 6 }], ["line", { x1: 8, y1: 2, x2: 8, y2: 6 }], ["line", { x1: 3, y1: 10, x2: 21, y2: 10 }]],
    diamond: [["polygon", { points: "12 2 22 12 12 22 2 12", class: "fill-accent" }], ["circle", { cx: 12, cy: 12, r: 2.2, class: "fill-white" }]],
    zip: [["path", { d: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" }], ["polyline", { points: "14 2 14 8 20 8" }], ["path", { d: "M10 12h2M10 15h2M10 18h2" }]],
    play: [["polygon", { points: "6 3 20 12 6 21 6 3" }]],
    check: [["polyline", { points: "20 6 9 17 4 12" }]],
    x: [["line", { x1: 18, y1: 6, x2: 6, y2: 18 }], ["line", { x1: 6, y1: 6, x2: 18, y2: 18 }]],
    warn: [["path", { d: "M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" }], ["line", { x1: 12, y1: 9, x2: 12, y2: 13 }], ["line", { x1: 12, y1: 17, x2: 12.01, y2: 17 }]],
    copy: [["rect", { x: 9, y: 9, width: 13, height: 13, rx: 2 }], ["path", { d: "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" }]],
    down: [["polyline", { points: "6 9 12 15 18 9" }]],
    right: [["polyline", { points: "9 18 15 12 9 6" }]],
    info: [["circle", { cx: 12, cy: 12, r: 10 }], ["line", { x1: 12, y1: 16, x2: 12, y2: 12 }], ["line", { x1: 12, y1: 8, x2: 12.01, y2: 8 }]],
    layers: [["polygon", { points: "12 2 2 7 12 12 22 7 12 2" }], ["polyline", { points: "2 17 12 22 22 17" }], ["polyline", { points: "2 12 12 17 22 12" }]],
    database: [["ellipse", { cx: 12, cy: 5, rx: 9, ry: 3 }], ["path", { d: "M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" }], ["path", { d: "M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" }]],
    puzzle: [["path", { d: "M10 4a2 2 0 1 1 4 0v2h4a1 1 0 0 1 1 1v4h-2a2 2 0 1 0 0 4h2v4a1 1 0 0 1-1 1h-4v-2a2 2 0 1 0-4 0v2H6a1 1 0 0 1-1-1v-4h2a2 2 0 1 0 0-4H5V7a1 1 0 0 1 1-1h4z" }]],
    link: [["path", { d: "M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" }], ["path", { d: "M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" }]],
    grid: [["rect", { x: 3, y: 3, width: 7, height: 7 }], ["rect", { x: 14, y: 3, width: 7, height: 7 }], ["rect", { x: 14, y: 14, width: 7, height: 7 }], ["rect", { x: 3, y: 14, width: 7, height: 7 }]],
    tree: [["rect", { x: 9, y: 2, width: 6, height: 5, rx: 1 }], ["rect", { x: 2, y: 17, width: 6, height: 5, rx: 1 }], ["rect", { x: 16, y: 17, width: 6, height: 5, rx: 1 }], ["path", { d: "M12 7v4M5 17v-3h14v3" }]],
    award: [["circle", { cx: 12, cy: 8, r: 7 }], ["polyline", { points: "8.21 13.89 7 23 12 20 17 23 15.79 13.88" }]],
    monitor: [["rect", { x: 2, y: 3, width: 20, height: 14, rx: 2 }], ["line", { x1: 8, y1: 21, x2: 16, y2: 21 }], ["line", { x1: 12, y1: 17, x2: 12, y2: 21 }]],
    terminal: [["polyline", { points: "4 17 10 11 4 5" }], ["line", { x1: 12, y1: 19, x2: 20, y2: 19 }]],
    book: [["path", { d: "M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" }], ["path", { d: "M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" }]],
    chart: [["line", { x1: 6, y1: 20, x2: 6, y2: 12 }], ["line", { x1: 12, y1: 20, x2: 12, y2: 5 }], ["line", { x1: 18, y1: 20, x2: 18, y2: 9 }]],
    help: [["circle", { cx: 12, cy: 12, r: 10 }], ["path", { d: "M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" }], ["line", { x1: 12, y1: 17, x2: 12.01, y2: 17 }]],
    bell: [["path", { d: "M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" }], ["path", { d: "M13.73 21a2 2 0 0 1-3.46 0" }]],
    dot: [["circle", { cx: 12, cy: 12, r: 4 }]],
  };

  const state = {
    config: { local_directory_enabled: false, ssh_enabled: false, max_upload_bytes: 0 },
    jobId: null, timer: null, delay: POLL_MIN_MS, errors: 0, zipFile: null, busy: false,
  };

  const byId = (id) => document.getElementById(id);

  // ------------------------------------------------------------ DOM helpers

  function h(tag, cls, text, attrs) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (attrs) Object.keys(attrs).forEach((k) => node.setAttribute(k, attrs[k]));
    return node;
  }

  function add(parent) {
    for (let i = 1; i < arguments.length; i += 1) {
      if (arguments[i]) parent.appendChild(arguments[i]);
    }
    return parent;
  }

  function svg(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach((k) => node.setAttribute(k, attrs[k]));
    return node;
  }

  function icon(name, cls) {
    const root = svg("svg", {
      viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 2,
      "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false",
      class: "icon" + (cls ? " " + cls : ""),
    });
    (ICONS[name] || ICONS.dot).forEach((part) => root.appendChild(svg(part[0], part[1])));
    return root;
  }

  function put(id, name, cls) {
    const target = byId(id);
    if (target) target.replaceChildren(icon(name, cls));
  }

  function fmt(n) {
    return typeof n === "number" ? n.toLocaleString("en-US") : "—";
  }

  function fmtBytes(n) {
    if (n < 1024) return n + " B";
    if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
    return (n / 1048576).toFixed(1) + " MB";
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  function evShort(list) {
    const e = Array.isArray(list) && list.length ? list[0] : null;
    if (!e || !e.file) return "—";
    return e.file + (e.line ? ":" + e.line : "");
  }

  // -------------------------------------------------------------------- API

  async function api(path, opts) {
    const o = opts || {};
    const init = { method: o.method || "GET", headers: {}, credentials: "same-origin" };
    if (init.method === "POST") init.headers["X-P1-Request"] = "1";
    if (o.json) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(o.json);
    }
    let resp;
    try {
      resp = await fetch(path, init);
    } catch (err) {
      throw new Error("Cannot reach the server.");
    }
    let data = null;
    try { data = await resp.json(); } catch (err) { data = null; }
    if (!resp.ok) {
      const e = data && data.error;
      throw new Error(e ? e.message + " (" + e.code + ")" : "Request failed (" + resp.status + ").");
    }
    return data;
  }

  function uploadZip(file, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/discoveries/upload?name=" + encodeURIComponent(file.name));
      xhr.setRequestHeader("X-P1-Request", "1");
      xhr.setRequestHeader("Content-Type", "application/zip");
      xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) onProgress(ev.loaded / ev.total); };
      xhr.onerror = () => reject(new Error("Upload failed: cannot reach the server."));
      xhr.onload = () => {
        let data = null;
        try { data = JSON.parse(xhr.responseText); } catch (err) { data = null; }
        if (xhr.status >= 200 && xhr.status < 300 && data && data.id) resolve(data);
        else reject(new Error(data && data.error ? data.error.message + " (" + data.error.code + ")" : "Upload failed (" + xhr.status + ")."));
      };
      xhr.send(file);
    });
  }

  // ---------------------------------------------------------- status / steps

  function summarise(job) {
    if (!job) return { state: "idle", text: "Idle" };
    if (job.status === "failed") return { state: "failed", text: "Failed" };
    if (job.status !== "completed") return { state: "running", text: "Running" };
    const bp = job.blueprint || {};
    const blockers = bp.summary && typeof bp.summary.blockers === "number" ? bp.summary.blockers : (bp.blockers || []).length;
    const flagged = blockers > 0 || (bp.stage && bp.stage.status === "COMPLETED_WITH_BLOCKERS");
    if (!flagged) return { state: "completed", text: "Completed" };
    const label = blockers === 1 ? "1 blocker" : blockers > 1 ? blockers + " blockers" : "blockers";
    return { state: "blocked", text: "Completed with " + label };
  }

  function renderBadge(job) {
    const s = summarise(job);
    const badge = byId("stage-badge");
    badge.dataset.state = s.state;
    byId("stage-badge-text").textContent = "Stage 1 – " + s.text;
    const glyph = { idle: "dot", running: "dot", failed: "x", blocked: "warn", completed: "check" }[s.state];
    byId("stage-badge-icon").replaceChildren(icon(glyph));
    const marker = byId("stage-1-marker");
    marker.dataset.state = s.state;
    if (s.state === "idle" || s.state === "running") marker.replaceChildren();
    else marker.replaceChildren(icon(glyph));
  }

  function stepText(step) {
    const map = { pending: "Pending", running: "In progress", failed: "Failed", warning: "Completed with warnings" };
    if (step.status === "completed") return DONE_TEXT[step.id] || "Completed";
    return map[step.status] || step.status;
  }

  function renderSteps(job) {
    const steps = job ? job.steps : STEP_DEFS.map((d) => ({ id: d[0], name: d[1], status: "pending", message: "" }));
    const list = byId("progress-steps");
    list.replaceChildren();
    steps.forEach((step) => {
      const li = h("li", "step", null, { "data-state": step.status });
      const glyph = { completed: "check", warning: "warn", failed: "x" }[step.status];
      const mark = h("span", "step-icon");
      if (glyph) mark.appendChild(icon(glyph));
      const text = h("span", "step-text");
      add(text, h("strong", null, step.name), h("small", null, stepText(step)));
      if (step.message) li.title = step.message;
      add(li, mark, text);
      list.appendChild(li);
    });
    const live = job ? "Discovery " + job.status + ". " + steps.map((s) => s.name + ": " + stepText(s)).join(". ") : "";
    byId("progress-live").textContent = live;
    const err = byId("job-error");
    err.hidden = !(job && job.error);
    err.textContent = job && job.error ? "Discovery failed: " + job.error.message + " (" + job.error.code + ")" : "";
  }

  // --------------------------------------------------------------- polling

  function stopPolling() {
    if (state.timer) window.clearTimeout(state.timer);
    state.timer = null;
  }

  async function poll() {
    if (!state.jobId) return;
    try {
      const job = await api("/api/discoveries/" + state.jobId);
      state.errors = 0;
      renderJob(job);
      if (job.status === "queued" || job.status === "running") {
        state.delay = Math.min(POLL_MAX_MS, Math.round(state.delay * 1.15));
        state.timer = window.setTimeout(poll, state.delay);
      }
    } catch (err) {
      state.errors += 1;
      if (state.errors > 6) {
        showJobError("Lost contact with the server: " + err.message);
        return;
      }
      state.delay = Math.min(POLL_MAX_MS, state.delay * 2);
      state.timer = window.setTimeout(poll, state.delay);
    }
  }

  function showJobError(message) {
    const err = byId("job-error");
    err.hidden = false;
    err.textContent = message;
  }

  function startJob(id) {
    stopPolling();
    state.jobId = id;
    state.delay = POLL_MIN_MS;
    state.errors = 0;
    byId("blueprint-section").hidden = true;
    byId("details").hidden = true;
    try { window.history.replaceState(null, "", "?job=" + id); } catch (err) { /* ignore */ }
    poll();
  }

  function renderJob(job) {
    renderBadge(job);
    renderSteps(job);
    if (job.status === "completed" && job.blueprint) renderBlueprint(job);
    else {
      byId("blueprint-section").hidden = true;
      byId("details").hidden = true;
    }
  }

  // ----------------------------------------------------------- panel builders

  function panel(title, iconName, body, cls) {
    const section = h("section", "panel " + (cls || ""));
    const head = h("header", "panel-head");
    add(head, h("span", "panel-icon", null, { "aria-hidden": "true" }), h("h3", null, title));
    head.firstChild.appendChild(icon(iconName));
    return add(section, head, body);
  }

  function copyButton(value, label) {
    const btn = h("button", "icon-btn", null, { type: "button", "aria-label": "Copy " + label, title: "Copy " + label });
    btn.appendChild(icon("copy"));
    btn.addEventListener("click", () => {
      const done = () => { byId("copy-live").textContent = label + " copied"; };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(value).then(done, () => fallbackCopy(value, done));
      else fallbackCopy(value, done);
    });
    return btn;
  }

  function fallbackCopy(value, done) {
    const area = h("textarea", "visually-hidden", value, { "aria-hidden": "true", tabindex: "-1" });
    document.body.appendChild(area);
    area.select();
    try { if (document.execCommand("copy")) done(); } catch (err) { /* ignore */ }
    area.remove();
  }

  function kvRow(dl, label, value, extra) {
    const dt = h("dt", null, label);
    const dd = h("dd");
    dd.appendChild(typeof value === "string" ? document.createTextNode(value) : value);
    if (extra) dd.appendChild(extra);
    add(dl, dt, dd);
  }

  // --------------------------------------------------------------- blueprint

  function projectInfo(job, bp) {
    const proj = bp.project || {};
    const src = proj.ingestion_source || {};
    const cp = proj.checkpoint || {};
    const dl = h("dl", "kv");
    kvRow(dl, "Project Name", proj.name || "—");
    kvRow(dl, "Ingestion Source", SOURCE_LABEL[src.kind] || src.kind || "—");
    kvRow(dl, ORIGIN_LABEL[src.kind] || "Origin", src.origin || "—");
    const commit = src.commit ? String(src.commit) : "";
    const refText = (src.ref || "—") + (commit ? " (" + commit.slice(0, 7) + ")" : "");
    kvRow(dl, "Branch / Commit", refText, commit ? copyButton(commit, "commit") : null);
    kvRow(dl, "Checkpoint ID", cp.id || "—", cp.id ? copyButton(cp.id, "checkpoint ID") : null);
    kvRow(dl, "Ingested On", fmtDate(job.run && job.run.ingested_at));
    return panel("Project Information", "info", dl, "area-info");
  }

  function tiles(bp) {
    const s = bp.summary || {};
    const defs = [
      ["Total Files", s.total_files, "file", "blue"], ["Directories", s.directories, "folder", "amber"],
      ["Pascal Sources", s.pascal_sources, "logo", "blue"], ["Projects", s.projects, "layers", "violet"],
      ["Database Artifacts", s.database_artifacts, "database", "violet"],
      ["External Dependencies", s.external_dependencies, "puzzle", "green"],
    ];
    const grid = h("ul", "tiles area-tiles");
    defs.forEach((d) => {
      const li = h("li", "tile");
      const mark = h("span", "tile-icon tone-" + d[3], null, { "aria-hidden": "true" });
      mark.appendChild(icon(d[2]));
      const text = h("span", "tile-text");
      add(text, h("span", "tile-label", d[0]), h("strong", "tile-value", fmt(d[1])));
      grid.appendChild(add(li, mark, text));
    });
    return grid;
  }

  function donut(dist) {
    const groups = (dist && dist.groups) || [];
    const total = (dist && dist.total) || 0;
    const wrap = h("div", "donut-wrap");
    const r = 62;
    const circ = 2 * Math.PI * r;
    const chart = svg("svg", { viewBox: "0 0 160 160", class: "donut", role: "img", "aria-label": "File distribution of " + fmt(total) + " files" });
    const ring = svg("g", { transform: "rotate(-90 80 80)" });
    ring.appendChild(svg("circle", { cx: 80, cy: 80, r: r, class: "donut-track", fill: "none", "stroke-width": 24 }));
    let offset = 0;
    groups.forEach((g, i) => {
      const len = total > 0 ? (g.count / total) * circ : 0;
      if (len <= 0) return;
      const seg = svg("circle", {
        cx: 80, cy: 80, r: r, fill: "none", "stroke-width": 24, class: "donut-seg seg-" + (i % 5),
        "stroke-dasharray": Math.max(0, len - (groups.length > 1 ? 1.2 : 0)).toFixed(3) + " " + circ.toFixed(3),
        "stroke-dashoffset": (-offset).toFixed(3),
      });
      ring.appendChild(seg);
      offset += len;
    });
    chart.appendChild(ring);
    const big = svg("text", { x: 80, y: 80, "text-anchor": "middle", class: "donut-total" });
    big.textContent = fmt(total);
    const small = svg("text", { x: 80, y: 98, "text-anchor": "middle", class: "donut-caption" });
    small.textContent = "Files";
    add(chart, big, small);
    const legend = h("ul", "legend");
    groups.forEach((g, i) => {
      const li = h("li");
      const pct = typeof g.percent === "number" ? g.percent.toFixed(1) + "%" : "—";
      add(li, h("span", "dot seg-bg-" + (i % 5), null, { "aria-hidden": "true" }), h("span", "legend-label", g.label), h("span", "legend-pct", pct));
      legend.appendChild(li);
    });
    return panel("File Distribution", "chart", add(wrap, chart, legend), "area-dist");
  }

  function dialectPanel(bp) {
    const d = bp.dialect || {};
    const body = h("div", "dialect");
    body.appendChild(h("span", "chip chip-dialect", d.label || "Unknown"));
    const dl = h("dl", "kv kv-wide");
    const texts = [];
    (d.evidence || []).forEach((e) => { if (e.text && texts.indexOf(e.text) < 0 && texts.length < 3) texts.push(e.text); });
    kvRow(dl, "Evidence", texts.length ? texts.join(", ") : "—");
    const comp = d.compiler || {};
    const named = comp.name && comp.name !== "unknown";
    kvRow(dl, "Compiler", named ? comp.name + " (detected)" : "Not determined");
    const ver = d.version || {};
    kvRow(dl, "Version (in config)", ver.value && ver.value !== "unknown" ? ver.value + " (indicated)" : "Not stated in project files");
    body.appendChild(dl);
    return panel("Detected Pascal Dialect", "award", body, "area-dialect");
  }

  function nodeLabel(node) {
    const files = node.counts && typeof node.counts.files === "number" ? node.counts.files : null;
    return node.kind === "group" && files !== null ? node.name + " (" + fmt(files) + ")" : node.name;
  }

  function treeItem(node, depth) {
    const li = h("li", "tree-item");
    const kids = Array.isArray(node.children) ? node.children : [];
    if (!kids.length && !node.truncated) {
      const leaf = h("span", "tree-leaf");
      add(leaf, icon(node.kind === "group" || node.kind === "application" ? "folder" : "file", "tree-icon"), h("span", "tree-label", nodeLabel(node)));
      return add(li, leaf);
    }
    const open = depth < 1;
    const btn = h("button", "tree-toggle", null, { type: "button", "aria-expanded": String(open) });
    add(btn, icon("right", "tree-caret"), icon("folder", "tree-icon"), h("span", "tree-label", nodeLabel(node)));
    const sub = h("ul", "tree-children");
    sub.hidden = !open;
    kids.forEach((k) => sub.appendChild(treeItem(k, depth + 1)));
    if (node.truncated) sub.appendChild(h("li", "tree-more", "More items not shown"));
    btn.addEventListener("click", () => {
      const expanded = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", String(!expanded));
      sub.hidden = expanded;
    });
    return add(li, btn, sub);
  }

  function structurePanel(bp) {
    const root = bp.structure;
    const list = h("ul", "tree");
    if (root) {
      const top = Array.isArray(root.children) && root.children.length === 1 ? root.children[0] : root;
      list.appendChild(treeItem(top, 0));
    } else list.appendChild(h("li", "muted", "No structure available."));
    return panel("Application Structure", "tree", list, "area-tree");
  }

  function keyDepsPanel(bp) {
    const keys = ((bp.dependencies || {}).key || []).slice(0, 5);
    const list = h("ul", "keydeps");
    if (!keys.length) list.appendChild(h("li", "muted", "No key dependencies detected."));
    keys.forEach((d) => {
      const li = h("li", null, null, { title: d.reason || "" });
      const ok = d.status === "resolved";
      add(li, h("span", "keydep-name", d.name), h("span", "pill " + (ok ? "pill-ok" : "pill-bad"), ok ? "Resolved" : "Unresolved"));
      list.appendChild(li);
    });
    return panel("Key Dependencies (Top 5)", "link", list, "area-deps");
  }

  function componentsPanel(bp) {
    const wrap = h("ul", "chips");
    (bp.components || []).forEach((c) => {
      const li = h("li", "chip chip-comp " + (c.present ? "is-present" : "is-absent"));
      li.title = c.present ? c.label + ": " + fmt(c.count) + " found" : c.label + ": not detected";
      add(li, icon(COMPONENT_ICON[c.id] || "dot"), h("span", null, c.label));
      if (!c.present) li.appendChild(h("span", "visually-hidden", " (not detected)"));
      wrap.appendChild(li);
    });
    return panel("Discovered Components", "grid", wrap, "area-comps");
  }

  function renderActions(job) {
    const id = job.id;
    byId("btn-report").setAttribute("href", "/api/discoveries/" + id + "/report");
    const menu = byId("download-menu");
    menu.replaceChildren();
    [["Blueprint (JSON)", "/api/discoveries/" + id + "/blueprint"],
      ["Unresolved dependencies (JSON)", "/api/discoveries/" + id + "/artifacts/unresolved-dependencies.json"],
      ["Diagnostics (JSON)", "/api/discoveries/" + id + "/artifacts/diagnostics.json"],
      ["Inventory (CSV)", "/api/discoveries/" + id + "/artifacts/inventory.csv"]].forEach((item) => {
      const li = h("li", null, null, { role: "none" });
      li.appendChild(h("a", null, item[0], { role: "menuitem", href: item[1], download: "" }));
      menu.appendChild(li);
    });
    toggleMenu(false);
  }

  function renderBlueprint(job) {
    const bp = job.blueprint;
    const grid = byId("bp-grid");
    grid.replaceChildren(projectInfo(job, bp), tiles(bp), donut(bp.file_distribution), dialectPanel(bp),
      structurePanel(bp), keyDepsPanel(bp), componentsPanel(bp));
    renderActions(job);
    const banner = byId("blocker-banner");
    const blockers = bp.blockers || [];
    banner.hidden = !blockers.length;
    banner.replaceChildren();
    blockers.forEach((b) => banner.appendChild(h("p", null, (b.code ? b.code + ": " : "") + (b.detail || b.message || ""))));
    renderDetails(bp);
    byId("blueprint-section").hidden = false;
  }

  // ----------------------------------------------------------------- details

  function table(columns, rows) {
    const wrap = h("div", "table-wrap");
    const t = h("table", "data-table");
    const head = h("tr");
    columns.forEach((c) => head.appendChild(h("th", null, c.label, { scope: "col" })));
    t.appendChild(add(h("thead"), head));
    const body = h("tbody");
    rows.slice(0, MAX_ROWS).forEach((row) => {
      const tr = h("tr");
      columns.forEach((c) => {
        const td = h("td");
        const v = c.get(row);
        td.appendChild(v instanceof Node ? v : document.createTextNode(v === undefined || v === null || v === "" ? "—" : String(v)));
        tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    add(wrap, add(t, body));
    if (rows.length > MAX_ROWS) wrap.appendChild(h("p", "muted", "Showing the first " + MAX_ROWS + " of " + rows.length + " rows. The full data is in the downloads."));
    return wrap;
  }

  function detail(title, count, body) {
    const sec = h("section", "card detail");
    const head = h("h2", "section-title", title);
    if (count !== null) head.appendChild(h("span", "count", String(count)));
    return add(sec, head, body);
  }

  function pill(value) {
    const sev = String(value || "info").toLowerCase();
    return h("span", "pill sev-" + sev, sev);
  }

  function yesNo(value) { return value ? "Yes" : "No"; }

  function listCell(items) { return Array.isArray(items) && items.length ? items.join(", ") : "—"; }

  function detailSections(bp) {
    const dep = bp.dependencies || {};
    const build = dep.build || {};
    const dbRows = (dep.databases || []).map((d) => ({ name: d.name, type: d.kind || "database", info: d.engine, ev: d.evidence }))
      .concat((dep.sql_files || []).map((f) => ({ name: f.path, type: "SQL file", info: (f.statements || 0) + " statements, " + (f.tables || 0) + " tables", ev: f.evidence })));
    const ev = { label: "Evidence", get: (r) => evShort(r.evidence || r.ev) };
    return [
      ["Projects", bp.projects, [
        { label: "Project", get: (r) => r.path }, { label: "Kind", get: (r) => r.kind }, { label: "Shape", get: (r) => r.shape },
        { label: "Units", get: (r) => fmt(r.unit_count) }, { label: "Forms", get: (r) => fmt(r.form_count) },
        { label: "Packages", get: (r) => fmt(r.package_count) }, { label: "Status", get: (r) => r.status }, ev]],
      ["Libraries", dep.libraries, [
        { label: "Library", get: (r) => r.name }, { label: "Category", get: (r) => r.category }, { label: "Origin", get: (r) => r.origin },
        { label: "References", get: (r) => fmt(r.references) }, ev]],
      ["Databases", dbRows, [
        { label: "Name", get: (r) => r.name }, { label: "Type", get: (r) => r.type }, { label: "Detail", get: (r) => r.info }, ev]],
      ["External Integrations", dep.integrations, [
        { label: "Category", get: (r) => r.category }, { label: "Name", get: (r) => r.name },
        { label: "Endpoints", get: (r) => listCell(r.endpoints) }, { label: "Count", get: (r) => fmt(r.count) }, ev]],
      ["Runtime Dependencies", dep.runtime, [
        { label: "Kind", get: (r) => r.kind }, { label: "Name", get: (r) => r.name },
        { label: "Present in input", get: (r) => yesNo(r.resolved_in_input) }, ev]],
      ["Native Libraries", dep.native_libraries, [
        { label: "Library", get: (r) => r.name }, { label: "Present in input", get: (r) => yesNo(r.resolved_in_input) },
        { label: "References", get: (r) => fmt(r.references) }, ev]],
      ["Build Scripts", build.scripts, [
        { label: "Script", get: (r) => r.path }, { label: "Kind", get: (r) => r.kind },
        { label: "Tools", get: (r) => listCell(r.tools) }, { label: "Projects", get: (r) => listCell(r.projects) }, ev]],
      ["Compiler Configuration", build.compiler_configs, [
        { label: "File", get: (r) => r.path }, { label: "Kind", get: (r) => r.kind }, { label: "Switches", get: (r) => listCell(r.switches) },
        { label: "Defines", get: (r) => listCell(r.defines) }, { label: "Search paths", get: (r) => listCell(r.search_paths) }, ev]],
      ["Unresolved Dependencies", bp.unresolved, [
        { label: "Id", get: (r) => r.id }, { label: "Kind", get: (r) => r.kind }, { label: "Name", get: (r) => r.name },
        { label: "Severity", get: (r) => pill(r.severity) }, { label: "Reason", get: (r) => r.reason },
        { label: "Referenced by", get: (r) => evShort(r.referenced_by) }]],
    ];
  }

  function requirementsBlock(build) {
    const reqs = build.requirements || {};
    const keys = Object.keys(reqs);
    if (!keys.length) return null;
    const dl = h("dl", "kv kv-wide");
    keys.forEach((k) => {
      const v = reqs[k];
      kvRow(dl, k.replace(/_/g, " "), Array.isArray(v) ? listCell(v) : String(v));
    });
    return dl;
  }

  function diagnosticsBlock(bp) {
    const counts = (bp.summary && bp.summary.diagnostics) || {};
    const box = h("div");
    const chips = h("ul", "chips");
    ["error", "warning", "info"].forEach((k) => {
      const li = h("li", "chip sev-" + k);
      li.textContent = (counts[k] || 0) + " " + k;
      chips.appendChild(li);
    });
    box.appendChild(chips);
    box.appendChild(table([
      { label: "Severity", get: (r) => pill(r.severity) }, { label: "Code", get: (r) => r.code },
      { label: "Message", get: (r) => r.message }, { label: "Location", get: (r) => (r.file ? r.file + (r.line ? ":" + r.line : "") : "") }],
    bp.diagnostics || []));
    return box;
  }

  function renderDetails(bp) {
    const host = byId("details");
    host.replaceChildren();
    detailSections(bp).forEach((s) => {
      const rows = Array.isArray(s[1]) ? s[1] : [];
      host.appendChild(detail(s[0], rows.length, rows.length ? table(s[2], rows) : h("p", "muted", "None detected.")));
    });
    const req = requirementsBlock(((bp.dependencies || {}).build) || {});
    if (req) host.appendChild(detail("Build Requirements", null, req));
    host.appendChild(detail("Diagnostics", (bp.diagnostics || []).length, diagnosticsBlock(bp)));
    const lim = h("ul", "bullets");
    (bp.limitations || []).forEach((l) => lim.appendChild(h("li", null, l)));
    host.appendChild(detail("Limitations", null, lim));
    host.hidden = false;
  }

  // ------------------------------------------------------------- menu / tabs

  function toggleMenu(open) {
    byId("download-menu").hidden = !open;
    byId("btn-download").setAttribute("aria-expanded", String(open));
  }

  function selectTab(name) {
    const ingest = name === "ingest";
    [["tab-ingest", ingest], ["tab-recent", !ingest]].forEach((t) => {
      const el = byId(t[0]);
      el.setAttribute("aria-selected", String(t[1]));
      el.classList.toggle("is-selected", t[1]);
      el.tabIndex = t[1] ? 0 : -1;
    });
    byId("panel-ingest").hidden = !ingest;
    byId("panel-recent").hidden = ingest;
    byId("progress-section").hidden = !ingest;
    byId("blueprint-section").classList.toggle("is-off", !ingest);
    byId("details").classList.toggle("is-off", !ingest);
    if (!ingest) loadRecent();
  }

  async function loadRecent() {
    const err = byId("recent-error");
    err.hidden = true;
    try {
      const data = await api("/api/discoveries");
      renderRecent(data.items || []);
    } catch (e) {
      err.hidden = false;
      err.textContent = e.message;
    }
  }

  function renderRecent(items) {
    byId("recent-empty").hidden = items.length > 0;
    byId("recent-wrap").hidden = items.length === 0;
    const head = h("tr");
    ["Application", "Source", "Status", "Started", "Files", ""].forEach((l) => head.appendChild(h("th", null, l, { scope: "col" })));
    byId("recent-head").replaceChildren(head);
    const body = byId("recent-body");
    body.replaceChildren();
    items.forEach((it) => {
      const tr = h("tr");
      const sum = it.summary || {};
      const stateName = it.status === "completed" ? "completed" : it.status === "failed" ? "failed" : "running";
      add(tr, h("td", null, sum.project || it.label || it.id), h("td", null, SOURCE_LABEL[it.kind] || it.kind || "—"),
        add(h("td"), h("span", "pill st-" + stateName, it.status)), h("td", null, fmtDate(it.created_at)),
        h("td", null, fmt(sum.total_files)));
      const open = h("button", "btn btn-small", "Open", { type: "button", "aria-label": "Open discovery " + (sum.project || it.id) });
      open.addEventListener("click", () => { selectTab("ingest"); startJob(it.id); });
      tr.appendChild(add(h("td"), open));
      body.appendChild(tr);
    });
  }

  // ------------------------------------------------------------------ forms

  function setError(message) {
    const el = byId("ingest-error");
    el.hidden = !message;
    el.textContent = message || "";
  }

  function setBusy(busy) {
    state.busy = busy;
    ["btn-git", "btn-zip", "btn-directory"].forEach((id) => { byId(id).disabled = busy; });
  }

  async function submit(work) {
    if (state.busy) return;
    setError("");
    setBusy(true);
    try {
      const accepted = await work();
      startJob(accepted.id);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
      byId("zip-progress").hidden = true;
    }
  }

  function onGit(ev) {
    ev.preventDefault();
    const url = byId("repo-url").value.trim();
    if (!url) { setError("Enter a repository URL."); byId("repo-url").focus(); return; }
    const ref = byId("repo-ref").value.trim();
    submit(() => api("/api/discoveries", { method: "POST", json: { kind: "git", url: url, ref: ref || null } }));
  }

  function onDirectory(ev) {
    ev.preventDefault();
    const path = byId("dir-path").value.trim();
    if (!path) { setError("Enter a directory path."); return; }
    submit(() => api("/api/discoveries", { method: "POST", json: { kind: "directory", path: path } }));
  }

  function onZip(ev) {
    ev.preventDefault();
    const file = state.zipFile;
    if (!file) { setError("Choose a ZIP file first."); return; }
    const bar = byId("zip-progress");
    submit(() => {
      bar.hidden = false;
      bar.value = 0;
      return uploadZip(file, (fraction) => { bar.value = Math.round(fraction * 100); });
    });
  }

  function chooseZip(file) {
    setError("");
    if (!file) return;
    if (!/\.zip$/i.test(file.name)) { setError("The file must be a .zip archive."); return; }
    if (state.config.max_upload_bytes && file.size > state.config.max_upload_bytes) {
      setError("The file is larger than the server limit of " + fmtBytes(state.config.max_upload_bytes) + ".");
      return;
    }
    state.zipFile = file;
    byId("zip-name").textContent = file.name + " (" + fmtBytes(file.size) + ")";
  }

  function wireZip() {
    const drop = byId("zip-drop");
    const input = byId("zip-input");
    drop.addEventListener("click", () => input.click());
    drop.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); input.click(); }
    });
    input.addEventListener("change", () => chooseZip(input.files && input.files[0]));
    ["dragenter", "dragover"].forEach((n) => drop.addEventListener(n, (ev) => { ev.preventDefault(); drop.classList.add("is-over"); }));
    ["dragleave", "drop"].forEach((n) => drop.addEventListener(n, (ev) => { ev.preventDefault(); drop.classList.remove("is-over"); }));
    drop.addEventListener("drop", (ev) => chooseZip(ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0]));
  }

  function selectSource(kind) {
    [["git", "form-git"], ["zip", "form-zip"], ["directory", "form-directory"]].forEach((p) => {
      byId(p[1]).hidden = p[0] !== kind;
      byId("card-" + p[0]).classList.toggle("is-selected", p[0] === kind);
    });
    setError("");
  }

  function applyConfig(cfg) {
    state.config = cfg;
    const enabled = !!cfg.local_directory_enabled;
    byId("radio-directory").disabled = !enabled;
    byId("card-directory").classList.toggle("is-disabled", !enabled);
    const hint = byId("directory-hint");
    if (!enabled) {
      const why = "Disabled: start the server with --allow-local-root to enable local directories.";
      byId("card-directory").title = why;
      hint.textContent = "Disabled by server configuration";
    }
  }

  function wireTabs() {
    byId("tab-ingest").addEventListener("click", () => selectTab("ingest"));
    byId("tab-recent").addEventListener("click", () => selectTab("recent"));
    ["tab-ingest", "tab-recent"].forEach((id) => byId(id).addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowRight" || ev.key === "ArrowLeft" || ev.key === "Home" || ev.key === "End") {
        ev.preventDefault();
        const next = id === "tab-ingest" ? "recent" : "ingest";
        selectTab(next);
        byId("tab-" + next).focus();
      }
    }));
  }

  function wireMenu() {
    const button = byId("btn-download");
    button.addEventListener("click", () => toggleMenu(byId("download-menu").hidden));
    document.addEventListener("click", (ev) => {
      if (!byId("download-dropdown").contains(ev.target)) toggleMenu(false);
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && !byId("download-menu").hidden) { toggleMenu(false); button.focus(); }
    });
  }

  function decorate() {
    put("brand-mark", "logo");
    put("tool-help", "help");
    put("tool-bell", "bell");
    [["nav-dashboard", "home"], ["nav-projects", "folder"], ["nav-reports", "report"], ["nav-settings", "gear"]].forEach((p) => {
      byId(p[0]).prepend(icon(p[1]));
    });
    byId("tab-ingest").prepend(icon("upload"));
    byId("tab-recent").prepend(icon("calendar"));
    put("icon-git", "diamond");
    put("icon-zip", "zip");
    put("icon-directory", "folder");
    put("btn-git-icon", "play");
    put("btn-zip-icon", "play");
    put("btn-dir-icon", "play");
    put("zip-drop-icon", "upload");
    put("bp-head-icon", "report");
    put("btn-report-icon", "file");
    put("btn-download-icon", "download");
    put("btn-download-caret", "down");
  }

  async function init() {
    decorate();
    renderSteps(null);
    renderBadge(null);
    wireTabs();
    wireMenu();
    wireZip();
    byId("form-git").addEventListener("submit", onGit);
    byId("form-zip").addEventListener("submit", onZip);
    byId("form-directory").addEventListener("submit", onDirectory);
    document.querySelectorAll("input[name=source]").forEach((r) => r.addEventListener("change", () => selectSource(r.value)));
    try {
      applyConfig(await api("/api/config"));
    } catch (err) {
      setError(err.message);
    }
    const wanted = new URLSearchParams(window.location.search).get("job");
    if (wanted && ID_RE.test(wanted)) startJob(wanted);
  }

  init();
})();
