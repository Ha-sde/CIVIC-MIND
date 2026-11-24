(() => {
  "use strict";

  /* ------------------------------------------------------------------ helpers */
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const app = () => $("#app");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const debounce = (fn, ms = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  const state = {
    token: localStorage.getItem("cm_token"),
    user: JSON.parse(localStorage.getItem("cm_user") || "null"),
    config: null, taxonomy: null, map: null, pop: null,
  };

  const fmt = (iso) => iso ? new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "-";
  const fmtDay = (iso) => iso ? new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" }) : "-";
  const ago = (iso) => {
    const m = Math.max(0, (Date.now() - new Date(iso).getTime()) / 60000);
    if (m < 60) return Math.floor(m) + "m";
    if (m < 1440) return Math.floor(m / 60) + "h";
    return Math.floor(m / 1440) + "d";
  };

  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => t.classList.remove("show"), 3600);
  }

  function errMsg(data, fallback) {
    if (!data) return fallback;
    const d = data.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (x.loc ? x.loc.slice(1).join(".") + ": " : "") + x.msg).join("; ");
    return fallback;
  }

  async function api(path, opts = {}) {
    const headers = {};
    if (state.token) headers.Authorization = "Bearer " + state.token;
    let body;
    if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(opts.json); }
    else if (opts.form) body = opts.form;
    const res = await fetch("/api" + path, { method: opts.method || (body ? "POST" : "GET"), headers, body });
    let data = null;
    try { data = await res.json(); } catch (_) { /* empty body */ }
    if (!res.ok) {
      if (res.status === 401 && state.token) { logout(true); }
      throw new Error(errMsg(data, "Something went wrong (" + res.status + ")."));
    }
    return data;
  }

  async function ensureConfig() { if (!state.config) state.config = await api("/config"); return state.config; }
  async function ensureTaxonomy() { if (!state.taxonomy) state.taxonomy = await api("/taxonomy"); return state.taxonomy; }

  function saveSession(token, user) {
    state.token = token; state.user = user;
    localStorage.setItem("cm_token", token);
    localStorage.setItem("cm_user", JSON.stringify(user));
  }
  function logout(silent) {
    state.token = null; state.user = null;
    localStorage.removeItem("cm_token"); localStorage.removeItem("cm_user");
    if (!silent) toast("Logged out.");
    location.hash = "#/";
    renderTopbar();
  }

  const ICON = {
    bell: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#0a0a0a" stroke-width="1.6"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 8 3 8H3s3-1 3-8"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/></svg>',
    search: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#555" stroke-width="1.6"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  };

  const priChip = (p) => `<span class="chip ${["critical", "high"].includes(p.label) ? "fill" : ""}">${esc(p.label)} ${p.score}</span>`;
  const loadingHTML = (txt = "Loading") => `<div class="wrap"><p class="muted" style="padding:60px 0">${esc(txt)}...</p></div>`;

  function card(c, extra = "") {
    const img = c.image ? `<img src="${esc(c.image)}" alt="" loading="lazy">` : `<div class="ph">${esc(c.sub_category)}</div>`;
    const done = c.stage === "completed";
    return `<a class="card" href="#/issue/${c.id}"><div class="card-media">${img}</div><div class="card-body">
      <div class="tagline"><span>{ ${esc(c.category)} / ${esc(c.sub_category)} }</span><span class="live">${done ? "· RESOLVED" : "· LIVE"}</span></div>
      <h3>${esc(c.title)}</h3>
      <div class="meta"><span>${c.reports} report${c.reports > 1 ? "s" : ""}</span><span>${esc(c.stage_label)}</span><span>${esc(c.department)}</span>${c.overdue ? '<span class="chip fill">overdue</span>' : ""}${done ? "" : priChip(c.priority)}</div>
      ${extra}
      <div class="bar"><i style="width:${c.progress}%"></i></div></div></a>`;
  }

  /* ------------------------------------------------------------------ top bar + notifications */
  function renderTopbar() {
    const u = state.user, h = location.hash || "#/";
    let links;
    if (!u) links = [["#/", "Issues"], ["#/how", "How it works"]];
    else if (u.role === "official") links = [["#/queue", "Queue"], ["#/map", "Map"], ["#/analytics", "Analytics"], ["#/", "Public feed"]];
    else links = [["#/", "Issues"], ["#/report", "Report"], ["#/my", "My complaints"], ["#/how", "How it works"]];
    const active = (href) => (href === "#/" ? h === "#/" || h === "#" || h === "" : h.startsWith(href));
    const right = !u
      ? '<a class="btn" href="#/login">Login / Register</a>'
      : `<button class="icon-btn" id="bell" aria-label="Notifications">${ICON.bell}<span class="badge" id="badge" hidden>0</span></button>
         <div class="user-chip"><b>${esc(u.name)}</b><span>${u.role === "official" ? esc(u.department) : "Citizen"}</span></div>
         <button class="btn sm" id="logout">Logout</button>`;
    $("#topbar").innerHTML = `<a class="logo" href="#/">[CivicMind]</a>
      <nav class="nav">${links.map(([href, label]) => `<a href="${href}" class="${active(href) ? "active" : ""}">${label}</a>`).join("")}</nav>
      <div class="right">${right}</div>`;
    if (u) {
      $("#logout").onclick = () => logout();
      $("#bell").onclick = toggleNotifications;
      refreshBadge();
    }
  }

  async function refreshBadge() {
    if (!state.user) return;
    try {
      const n = await api("/notifications");
      const b = $("#badge");
      if (b) { b.textContent = n.unread; b.hidden = n.unread === 0; }
    } catch (_) { /* ignore */ }
  }

  async function toggleNotifications() {
    if (state.pop) { state.pop.remove(); state.pop = null; return; }
    const data = await api("/notifications");
    const pop = document.createElement("div");
    pop.className = "pop";
    pop.innerHTML = `<h5>Notifications</h5>` + (data.items.length
      ? data.items.map((n) => `<a href="#/issue/${n.cluster_id}" class="${n.read ? "" : "unread"}">${esc(n.message)}<small>${fmt(n.at)}</small></a>`).join("")
      : '<p class="muted small" style="padding:18px">Nothing yet.</p>');
    document.body.appendChild(pop);
    state.pop = pop;
    pop.addEventListener("click", () => { pop.remove(); state.pop = null; });
    if (data.unread) { await api("/notifications/read", { method: "POST" }); refreshBadge(); }
  }

  /* ------------------------------------------------------------------ home (public feed) */
  async function viewHome() {
    app().innerHTML = loadingHTML();
    const [stats, tax] = await Promise.all([api("/public/stats"), ensureTaxonomy()]);
    const u = state.user;
    const ctas = !u
      ? '<a class="btn solid" href="#/login">Report an issue</a><a class="btn" href="#/how">How it works</a>'
      : u.role === "official"
        ? '<a class="btn solid" href="#/queue">Open priority queue</a><a class="btn" href="#/map">View map</a>'
        : '<a class="btn solid" href="#/report">Report an issue</a><a class="btn" href="#/my">My complaints</a>';
    const f = { department: "", status: "all", q: "" };
    app().innerHTML = `<div class="wrap">
      <section class="hero"><h1>Civic Mind</h1>
        <p>Report a problem in your neighbourhood in under two minutes. AI routes it to the right department, merges duplicate reports, ranks urgency - and you watch it get fixed, with proof.</p>
        <div class="hero-actions">${ctas}</div></section>
      <div class="stats">
        <div class="stat"><b>${stats.total}</b><span>Issues tracked</span></div>
        <div class="stat"><b>${stats.reports}</b><span>Citizen reports</span></div>
        <div class="stat"><b>${stats.resolved}</b><span>Resolved</span></div>
        <div class="stat"><b>${stats.open}</b><span>Open now</span></div>
        <div class="stat"><b>${stats.avg_resolve_days ?? "-"}${stats.avg_resolve_days != null ? "d" : ""}</b><span>Avg. time to resolve</span></div>
      </div>
      <div class="split">
        <aside class="side">
          <label class="search">${ICON.search}<input id="q" placeholder="Search issues" autocomplete="off"></label>
          <div class="filter" id="f-status"><h4>Status</h4>
            ${[["all", "All"], ["open", "Open"], ["resolved", "Resolved"]].map(([v, l]) => `<button data-v="${v}" class="${v === "all" ? "on" : ""}">${l}</button>`).join("")}</div>
          <div class="filter" id="f-dept"><h4>Department</h4>
            <button data-v="" class="on">All</button>${tax.departments.map((d) => `<button data-v="${esc(d)}">${esc(d)}</button>`).join("")}</div>
        </aside>
        <section><div class="grid" id="grid"></div></section>
      </div></div>`;

    const load = async () => {
      const qs = new URLSearchParams({ department: f.department, status: f.status, q: f.q });
      const items = await api("/public/issues?" + qs);
      $("#grid").innerHTML = items.length ? items.map((c) => card(c)).join("") : '<div class="empty">No issues match these filters yet.</div>';
    };
    const bind = (id, key) => $(id).addEventListener("click", (e) => {
      const b = e.target.closest("button"); if (!b) return;
      f[key] = b.dataset.v; $$("button", $(id)).forEach((x) => x.classList.toggle("on", x === b)); load();
    });
    bind("#f-status", "status"); bind("#f-dept", "department");
    $("#q").addEventListener("input", debounce((e) => { f.q = e.target.value; load(); }));
    await load();
  }

  /* ------------------------------------------------------------------ how it works */
  async function viewHow() {
    const w = await api("/public/weights");
    const cfg = await ensureConfig();
    const steps = [
      ["01", "Report", "Describe the problem, add photos or video, and drop a pin. Written in English, Hinglish, Hindi or Marathi - all understood."],
      ["02", "AI classifies", "The engine reads text and photos, picks the category and sub-category, estimates severity from 1 to 5, and routes to the responsible department."],
      ["03", "Duplicates merge", "Reports of the same problem within " + 150 + " m merge into one issue. More reports means more urgency - never more clutter."],
      ["04", "Priority ranks", "Officials see a ranked queue. Every score is a transparent formula, so any officer can see exactly why an issue ranks where it does."],
      ["05", "Department acts", "An officer acknowledges with a target date, posts progress with photos, and must upload a photo to mark it complete. Stages cannot be skipped."],
      ["06", "You confirm", "Reporters confirm the fix - or reopen within " + cfg.reopen_days + " days if it is not really fixed. Unacknowledged issues turn overdue after " + cfg.ack_sla_hours + " hours."],
    ];
    app().innerHTML = `<div class="wrap">
      <div class="page-head"><h2 class="section">How it works</h2><p>From a photo on your phone to a verified fix.</p></div>
      <div class="steps">${steps.map(([n, t, d]) => `<div class="step"><span class="n">${n}</span><h3>${t}</h3><p>${d}</p></div>`).join("")}</div>
      <div class="box"><h4>Priority score (0-100) - fully explainable</h4>
        <div class="code">priority = 100 × ( ${w.reports}·reports + ${w.severity}·severity + ${w.category}·category + ${w.age}·age + ${w.vulnerability}·vulnerability )</div>
        <p class="hint" style="margin-top:12px">reports = log-scaled count of merged citizen reports · severity = AI estimate (1-5) · category = inherent importance · age = days unresolved (caps at 14) · vulnerability = mentions a school, hospital or transit stop. Officers can override any score with a recorded reason.</p></div>
      <div class="box" style="margin-bottom:80px"><h4>AI engine</h4>
        <p style="font-size:14px">Current mode: <b class="mono">${esc(cfg.ai)}</b>. A built-in multilingual classifier always runs offline. When a Claude API key is configured, Claude also reads the photos and the two results are blended - and if Claude is ever unavailable, the built-in engine keeps working.</p></div></div>`;
  }

  /* ------------------------------------------------------------------ login / register (OTP) */
  async function viewLogin() {
    if (state.user) { location.hash = state.user.role === "official" ? "#/queue" : "#/report"; return; }
    const [cfg, tax] = await Promise.all([ensureConfig(), ensureTaxonomy()]);
    const S = { role: "citizen", mode: "login", step: 1, contact: "", name: "", department: "", ward: "", invite: "", demoOtp: null, busy: false };

    const draw = () => {
      const reg = S.mode === "register", off = S.role === "official";
      let body;
      if (S.step === 1) {
        body = `
          <div class="seg" id="s-role"><button data-v="citizen" class="${!off ? "on" : ""}">Citizen</button><button data-v="official" class="${off ? "on" : ""}">Government official</button></div>
          <div class="seg" id="s-mode"><button data-v="login" class="${!reg ? "on" : ""}">Login</button><button data-v="register" class="${reg ? "on" : ""}">Register</button></div>
          ${reg ? `<label class="f"><span>Full name</span><input class="in" id="name" value="${esc(S.name)}" autocomplete="name" maxlength="120"></label>` : ""}
          <label class="f"><span>Mobile number or email</span><input class="in" id="contact" value="${esc(S.contact)}" placeholder="9876543210 or you@example.com" autocomplete="username"></label>
          ${reg && off ? `<label class="f"><span>Department</span><select class="in" id="dept"><option value="">Select department</option>${tax.departments.map((d) => `<option ${S.department === d ? "selected" : ""}>${esc(d)}</option>`).join("")}</select></label>
             <label class="f"><span>Ward / zone (optional)</span><input class="in" id="ward" value="${esc(S.ward)}" maxlength="80"></label>
             ${cfg.invite_required ? `<label class="f"><span>Official invite code</span><input class="in" id="invite" value="${esc(S.invite)}"></label>` : ""}` : ""}
          <button class="btn solid" id="send" style="width:100%" ${S.busy ? "disabled" : ""}>${S.busy ? '<span class="spinner"></span>' : "Send OTP"}</button>`;
      } else {
        body = `
          ${cfg.otp_mode === "demo" ? `<div class="demo-box"><div><div class="small muted">DEMO MODE - no SMS is sent</div>Use this OTP</div><b>${esc(S.demoOtp || cfg.demo_otp)}</b></div>` : `<p class="hint" style="margin-bottom:16px">We sent a 6-digit code to ${esc(S.contact)}.</p>`}
          <label class="f"><span>Enter OTP</span><input class="in otp" id="code" inputmode="numeric" maxlength="6" autocomplete="one-time-code" placeholder="••••••"></label>
          <button class="btn solid" id="verify" style="width:100%" ${S.busy ? "disabled" : ""}>${S.busy ? '<span class="spinner"></span>' : (reg ? "Verify & create account" : "Verify & login")}</button>
          <div class="row" style="margin-top:12px"><button class="btn sm" id="back">Back</button><button class="btn sm" id="resend">Resend OTP</button></div>`;
      }
      app().innerHTML = `<div class="wrap"><div class="form-card">
        <h2 class="section" style="font-size:clamp(34px,5vw,54px);margin-bottom:8px">${S.step === 1 ? (reg ? "Register" : "Login") : "Verify"}</h2>
        <p class="muted" style="margin-bottom:26px">${S.step === 1 ? (off ? "Official access for department staff." : "Report and track issues in your area.") : "One-time password sent to " + esc(S.contact)}</p>${body}</div></div>`;
      bind();
    };

    const sync = () => {
      const g = (id) => ($(id) ? $(id).value : null);
      S.contact = g("#contact") ?? S.contact; S.name = g("#name") ?? S.name; S.department = g("#dept") ?? S.department;
      S.ward = g("#ward") ?? S.ward; S.invite = g("#invite") ?? S.invite;
    };
    const requestOtp = async () => {
      sync(); S.busy = true; draw();
      try {
        const r = await api("/auth/request-otp", { json: { contact: S.contact, role: S.role, mode: S.mode, name: S.name, department: S.department || null, ward: S.ward, invite_code: S.invite || null } });
        S.demoOtp = r.demo_otp || null; S.step = 2; toast(cfg.otp_mode === "demo" ? "Demo OTP is shown on screen." : "OTP sent.");
      } catch (e) { toast(e.message); }
      S.busy = false; draw();
      if (S.step === 2) { const c = $("#code"); if (c) c.focus(); }
    };
    const verify = async () => {
      const code = $("#code").value.trim();
      if (code.length !== 6) { toast("Enter the 6-digit OTP."); return; }
      S.busy = true; draw(); $("#code") && ($("#code").value = code);
      try {
        const r = await api("/auth/verify-otp", { json: { contact: S.contact, code } });
        saveSession(r.token, r.user); toast("Welcome, " + r.user.name + ".");
        location.hash = r.user.role === "official" ? "#/queue" : "#/report";
      } catch (e) { toast(e.message); S.busy = false; draw(); }
    };
    function bind() {
      const seg = (id, key) => $(id) && $(id).addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; sync(); S[key] = b.dataset.v; draw(); });
      seg("#s-role", "role"); seg("#s-mode", "mode");
      $("#send") && ($("#send").onclick = requestOtp);
      $("#verify") && ($("#verify").onclick = verify);
      $("#back") && ($("#back").onclick = () => { S.step = 1; draw(); });
      $("#resend") && ($("#resend").onclick = async () => { S.step = 1; await requestOtp(); });
      $$(".in").forEach((i) => i.addEventListener("keydown", (e) => { if (e.key === "Enter") { S.step === 1 ? requestOtp() : verify(); } }));
      const code = $("#code"); if (code) code.addEventListener("input", () => { code.value = code.value.replace(/\D/g, "").slice(0, 6); });
    }
    draw();
  }

  /* ------------------------------------------------------------------ citizen: report */
  const pinIcon = () => L.divIcon({ className: "", html: '<div style="width:20px;height:20px;border-radius:50%;background:#000;border:3px solid #fff;box-shadow:0 0 0 1px #000"></div>', iconSize: [20, 20], iconAnchor: [10, 10] });

  async function viewReport() {
    const cfg = await ensureConfig();
    let files = [];
    app().innerHTML = `<div class="wrap">
      <div class="page-head"><h2 class="section">Report an issue</h2><p>Describe what is wrong, add a photo, and confirm the location. AI does the routing.</p></div>
      <div class="form-card form-wide" id="report-card" style="margin-top:24px">
        <form id="rf" novalidate>
          <label class="f"><span>What is the problem?</span><textarea class="in" id="text" maxlength="2000" placeholder="e.g. Large pothole near the school gate on Station Road, two bikes already fell."></textarea><div class="hint">English, Hinglish, Hindi or Marathi - all work.</div></label>
          <div class="f"><span class="small muted" style="display:block;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">Photos / video (optional, up to ${cfg.max_files})</span>
            <label class="drop" for="file">Tap to add photos or video · max ${cfg.max_mb} MB each</label>
            <input type="file" id="file" accept="image/*,video/*" multiple hidden><div class="thumbs" id="thumbs"></div></div>
          <div class="f" style="margin-top:22px"><span class="small muted" style="display:block;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">Location</span>
            <div id="picker"></div>
            <div class="row" style="margin-bottom:12px"><button type="button" class="btn sm" id="locate">Use my current location</button></div>
            <div class="row"><label class="f" style="margin:0"><span>Latitude</span><input class="in" id="lat" inputmode="decimal"></label>
              <label class="f" style="margin:0"><span>Longitude</span><input class="in" id="lon" inputmode="decimal"></label></div>
            <label class="f" style="margin-top:16px"><span>Landmark / address</span><input class="in" id="address" maxlength="300" placeholder="Near Station Road school gate"></label></div>
          <button class="btn solid" id="submit" style="width:100%" type="submit">Submit complaint</button>
        </form></div></div>`;

    // map picker
    const [clat, clon] = cfg.map_center;
    $("#lat").value = clat.toFixed(6); $("#lon").value = clon.toFixed(6);
    let marker = null;
    const setPoint = (lat, lon, pan) => {
      $("#lat").value = (+lat).toFixed(6); $("#lon").value = (+lon).toFixed(6);
      if (marker) marker.setLatLng([lat, lon]);
      if (pan && state.map) state.map.setView([lat, lon], 17);
    };
    if (window.L) {
      state.map = L.map("picker").setView([clat, clon], 14);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" }).addTo(state.map);
      marker = L.marker([clat, clon], { draggable: true, icon: pinIcon() }).addTo(state.map);
      marker.on("dragend", () => { const p = marker.getLatLng(); setPoint(p.lat, p.lng); });
      state.map.on("click", (e) => setPoint(e.latlng.lat, e.latlng.lng));
    } else { $("#picker").outerHTML = '<p class="hint">Map could not load - enter coordinates manually below.</p>'; }
    const manual = () => { const la = parseFloat($("#lat").value), lo = parseFloat($("#lon").value); if (!isNaN(la) && !isNaN(lo) && marker) { marker.setLatLng([la, lo]); state.map.setView([la, lo]); } };
    $("#lat").addEventListener("change", manual); $("#lon").addEventListener("change", manual);
    $("#locate").onclick = () => {
      if (!navigator.geolocation) return toast("Location is not supported on this device.");
      toast("Finding your location...");
      navigator.geolocation.getCurrentPosition((p) => { setPoint(p.coords.latitude, p.coords.longitude, true); toast("Location set."); },
        () => toast("Could not get your location. Drag the pin on the map instead."), { enableHighAccuracy: true, timeout: 12000 });
    };

    // files
    const drawThumbs = () => {
      $("#thumbs").innerHTML = files.map((f, i) => `<div class="thumb">${f.type.startsWith("video") ? "VIDEO" : `<img src="${URL.createObjectURL(f)}" alt="">`}<button type="button" data-i="${i}" aria-label="Remove">×</button></div>`).join("");
    };
    $("#file").addEventListener("change", (e) => {
      for (const f of e.target.files) {
        if (files.length >= cfg.max_files) { toast("Maximum " + cfg.max_files + " files."); break; }
        if (f.size > cfg.max_mb * 1048576) { toast(f.name + " is larger than " + cfg.max_mb + " MB."); continue; }
        files.push(f);
      }
      e.target.value = ""; drawThumbs();
    });
    $("#thumbs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { files.splice(+b.dataset.i, 1); drawThumbs(); } });

    $("#rf").addEventListener("submit", async (e) => {
      e.preventDefault();
      const text = $("#text").value.trim();
      if (text.length < 5 && !files.length) return toast("Please describe the problem or add a photo.");
      const lat = parseFloat($("#lat").value), lon = parseFloat($("#lon").value);
      if (isNaN(lat) || isNaN(lon)) return toast("Please set the location.");
      const fd = new FormData();
      fd.append("text", text); fd.append("lat", lat); fd.append("lon", lon); fd.append("address", $("#address").value.trim());
      files.forEach((f) => fd.append("files", f));
      const btn = $("#submit"); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Analysing with AI';
      try { showResult(await api("/complaints", { form: fd })); }
      catch (err) { toast(err.message); btn.disabled = false; btn.textContent = "Submit complaint"; }
    });
  }

  function showResult(r) {
    const i = r.issue, ai = r.ai;
    $("#report-card").innerHTML = `
      <p class="chip fill">${r.merged ? "Merged with existing issue" : "Complaint received"}</p>
      <h2 class="section" style="font-size:clamp(30px,4vw,48px);margin:16px 0 8px">${esc(i.title)}</h2>
      <p class="muted">${r.merged ? "Others have already reported this problem here - your report strengthens its priority." : "Routed automatically. You will be notified at every stage."}</p>
      <div class="box" style="margin-top:24px"><h4>What the AI understood</h4><dl class="kv">
        <dt>Category</dt><dd>${esc(ai.category)} / ${esc(ai.sub_category)}</dd>
        <dt>Routed to</dt><dd>${esc(ai.department)}</dd>
        <dt>Severity</dt><dd>${ai.severity} / 5</dd>
        <dt>Confidence</dt><dd>${Math.round(ai.confidence * 100)}%${ai.needs_review ? " - an officer will double-check" : ""}</dd>
        <dt>Reports on this issue</dt><dd>${i.reports}</dd>
        <dt>Engine</dt><dd class="mono">${esc(ai.engine)}</dd></dl></div>
      <div class="row"><a class="btn solid" href="#/issue/${i.id}">Track this issue</a><a class="btn" href="#/report" onclick="setTimeout(()=>location.reload(),0)">Report another</a></div>`;
    window.scrollTo(0, 0);
  }

  /* ------------------------------------------------------------------ citizen: my complaints */
  async function viewMy() {
    app().innerHTML = loadingHTML();
    const rows = await api("/complaints/mine");
    app().innerHTML = `<div class="wrap"><div class="page-head"><h2 class="section">My complaints</h2><p>${rows.length} report${rows.length === 1 ? "" : "s"} filed by you.</p></div>
      <div class="grid" style="margin:28px 0 90px">${rows.length
        ? rows.map((r) => card(r.issue, `<p class="small muted">Filed ${fmt(r.complaint.created_at)} - “${esc(r.complaint.text.slice(0, 90))}${r.complaint.text.length > 90 ? "…" : ""}”</p>`)).join("")
        : '<div class="empty">You have not filed any complaints yet.<br><br><a class="btn solid" href="#/report">Report an issue</a></div>'}</div></div>`;
  }

  /* ------------------------------------------------------------------ issue detail */
  const ORDER = ["received", "acknowledged", "in_progress", "completed"];
  const LABEL = { received: "Received", acknowledged: "Acknowledged", in_progress: "In progress", completed: "Completed", reopened: "Reopened" };

  function timelineHTML(d) {
    let pending = [];
    if (d.stage === "reopened") pending = ["in_progress", "completed"];
    else if (d.stage !== "completed") pending = ORDER.slice(ORDER.indexOf(d.stage) + 1);
    const done = d.timeline.map((e) => `<li class="tl ${e.stage === "merged" ? "merged" : "done"}">
      <b>${esc(e.label)}${e.progress != null && e.stage === "in_progress" ? " · " + e.progress + "%" : ""}</b><time>${fmt(e.at)} · ${esc(e.actor)}</time>
      ${e.note ? `<p>${esc(e.note)}</p>` : ""}${e.photo ? `<a href="${esc(e.photo)}" target="_blank" rel="noopener"><img src="${esc(e.photo)}" alt="Evidence photo" loading="lazy"></a>` : ""}</li>`).join("");
    const next = pending.map((s) => `<li class="tl pending"><b>${LABEL[s]}</b><time>pending</time></li>`).join("");
    return `<ul class="timeline">${done}${next}</ul>`;
  }

  async function viewIssue(id) {
    app().innerHTML = loadingHTML();
    const d = await api("/issues/" + id);
    const tax = await ensureTaxonomy();
    const u = state.user, isOff = u && u.role === "official", cfg = await ensureConfig();
    const p = d.priority;
    const gallery = d.media.length ? `<div class="gallery">${d.media.map((m) => m.type === "video"
      ? `<video src="${esc(m.url)}" controls preload="metadata"></video>`
      : `<a href="${esc(m.url)}" target="_blank" rel="noopener"><img src="${esc(m.url)}" alt="Reported issue photo" loading="lazy"></a>`).join("")}</div>` : "";
    const reopenOpen = d.can_reopen_until && new Date(d.can_reopen_until) > new Date();

    let citizenBox = "";
    if (u && u.role === "citizen" && d.is_reporter && d.stage === "completed") {
      citizenBox = `<div class="box"><h4>Was this actually fixed?</h4>
        <p class="small muted" style="margin-bottom:14px">${d.confirmations} reporter${d.confirmations === 1 ? " has" : "s have"} confirmed the fix. ${reopenOpen ? "You can reopen until " + fmtDay(d.can_reopen_until) + "." : "The reopen window has closed."}</p>
        <div class="row"><button class="btn solid" id="confirm">Yes, it is fixed</button></div>
        ${reopenOpen ? `<label class="f" style="margin-top:18px"><span>Not fixed? Tell us what is still wrong</span><textarea class="in" id="reopen-reason" style="min-height:90px"></textarea></label><button class="btn" id="reopen">Reopen issue</button>` : ""}</div>`;
    }

    let officerBox = "";
    if (isOff) {
      if (!d.can_act) {
        officerBox = `<div class="box"><h4>Read only</h4><p class="small">This issue belongs to <b>${esc(d.department)}</b>. Only that department can act on it.</p></div>`;
      } else {
        let forms = "";
        if (d.stage === "received") {
          forms = `<h4>Take up this issue</h4>
            <label class="f"><span>Target resolution date</span><input class="in" type="date" id="ack-date" min="${new Date().toISOString().slice(0, 10)}"></label>
            <label class="f"><span>Note to citizens (optional)</span><input class="in" id="ack-note" maxlength="300" placeholder="e.g. Road gang assigned"></label>
            <button class="btn solid" id="ack">Acknowledge</button>`;
        } else if (["acknowledged", "in_progress", "reopened"].includes(d.stage)) {
          forms = `<h4>Post progress</h4>
            <label class="f"><span>Work completed: <b id="pv">${Math.max(d.progress, 10)}</b>%</span><input type="range" id="pr" min="1" max="99" value="${Math.max(d.progress, 10)}" style="width:100%;accent-color:#000"></label>
            <label class="f"><span>Update note</span><input class="in" id="pr-note" maxlength="300"></label>
            <label class="f"><span>Photo (optional)</span><input class="in" type="file" id="pr-photo" accept="image/*"></label>
            <button class="btn solid" id="prog">Post update</button>`;
          if (d.stage === "in_progress") {
            forms += `<hr style="border:0;border-top:1px solid var(--line);margin:26px 0"><h4>Mark completed</h4>
              <label class="f"><span>Closing note</span><input class="in" id="cp-note" maxlength="300"></label>
              <label class="f"><span>Photo of finished work (required)</span><input class="in" type="file" id="cp-photo" accept="image/*"></label>
              <button class="btn solid" id="comp">Mark as completed</button>`;
          }
        } else {
          forms = `<h4>Resolved</h4><p class="small">Waiting for reporters to confirm. ${d.confirmations} confirmation${d.confirmations === 1 ? "" : "s"} so far.</p>`;
        }
        const cats = Object.keys(tax.categories);
        forms += `<details style="margin-top:26px"><summary class="small" style="cursor:pointer;text-transform:uppercase;letter-spacing:.08em">Override AI decision</summary>
          <div style="margin-top:16px"><label class="f"><span>Re-categorise</span><select class="in" id="ov-cat"><option value="">Keep current</option>${cats.map((c) => `<option>${esc(c)}</option>`).join("")}</select></label>
          <label class="f"><span>Sub-category</span><select class="in" id="ov-sub"><option value="">-</option></select></label>
          <label class="f"><span>Priority (0-100)</span><input class="in" type="number" id="ov-pri" min="0" max="100" placeholder="${p.computed}"></label>
          <label class="f"><span><input type="checkbox" id="ov-clear"> Clear priority override</span></label>
          <label class="f"><span>Reason (recorded in timeline)</span><input class="in" id="ov-reason" maxlength="300"></label>
          <button class="btn" id="ov">Apply override</button></div></details>`;
        officerBox = `<div class="box">${forms}</div>`;
      }
    }

    app().innerHTML = `<div class="wrap"><div class="detail" style="padding-top:clamp(24px,3vw,44px)">
      <section>
        <div class="tagline" style="justify-content:flex-start;gap:18px"><span>{ ${esc(d.category)} / ${esc(d.sub_category)} }</span><span>${d.stage === "completed" ? "· RESOLVED" : "· LIVE"}</span></div>
        <h1>${esc(d.title)}</h1>
        <div class="meta" style="margin-bottom:6px"><span>${esc(d.address || "Location pinned on map")}</span><span>${d.reports} report${d.reports > 1 ? "s" : ""}</span><span>Opened ${fmtDay(d.created_at)}</span><span>${esc(d.department)}</span></div>
        <div class="row" style="margin:14px 0 4px;flex:none;gap:8px">${priChip(p)}<span class="chip soft">${esc(d.stage_label)}</span>${d.overdue ? '<span class="chip fill">overdue</span>' : ""}${d.reopen_count ? `<span class="chip soft">reopened ×${d.reopen_count}</span>` : ""}${d.target_date ? `<span class="chip soft">target ${fmtDay(d.target_date)}</span>` : ""}</div>
        <div class="progress-line"><i style="width:${d.progress}%"></i></div><p class="small muted">${d.progress}% complete</p>
        ${gallery}
        ${d.my_reports.length ? `<div class="box"><h4>Your report</h4>${d.my_reports.map((r) => `<p style="font-size:14px">“${esc(r.text) || "(photo only)"}”</p><p class="small muted">${fmt(r.created_at)}</p>`).join("")}</div>` : ""}
        <div class="box"><h4>AI analysis</h4><dl class="kv">
          <dt>Category</dt><dd>${esc(d.category)} / ${esc(d.sub_category)}${d.ai.recategorised ? " (officer-corrected)" : ""}</dd>
          <dt>Routed to</dt><dd>${esc(d.department)}</dd><dt>Severity</dt><dd>${d.severity} / 5</dd>
          <dt>Confidence</dt><dd>${Math.round(d.ai.confidence * 100)}%${d.ai.needs_review ? " - flagged for officer review" : ""}</dd>
          <dt>Reasoning</dt><dd>${esc(d.ai.reason)}</dd><dt>Engine</dt><dd class="mono">${esc(d.ai.engine)}</dd></dl></div>
        <div class="box"><h4>Priority ${p.overridden ? "(officer override)" : "score"}</h4>
          <div style="display:flex;align-items:baseline;gap:14px;margin-bottom:14px"><span class="score">${p.score}</span><span class="muted">/ 100 · ${esc(p.label)}</span></div>
          ${p.breakdown.map((b) => `<div class="pbar"><span>${esc(b.label)}</span><div class="t"><i style="width:${Math.round(b.value * 100)}%"></i></div><b>+${b.points}</b></div>`).join("")}
          ${p.overridden ? `<p class="hint">Calculated score was ${p.computed}; an officer set it manually - see timeline for the reason.</p>` : ""}</div>
        ${isOff && d.reporters ? `<div class="box"><h4>Reporters (${d.reporters.length}) - visible to officials only</h4>${d.reporters.map((r) => `<p style="font-size:14px;margin-bottom:10px"><b>${esc(r.name)}</b> <span class="muted">· ${esc(r.contact)} · ${fmt(r.created_at)}</span><br>${esc(r.text) || "(photo only)"}</p>`).join("")}</div>` : ""}
      </section>
      <aside><div class="box"><h4>Timeline</h4>${timelineHTML(d)}</div>${citizenBox}${officerBox}</aside></div></div>`;

    bindIssueActions(d, id, tax);
  }

  function bindIssueActions(d, id, tax) {
    const run = async (fn, okMsg) => { try { await fn(); toast(okMsg); await viewIssue(id); } catch (e) { toast(e.message); } };
    const on = (sel, fn) => { const el = $(sel); if (el) el.onclick = fn; };
    on("#confirm", () => run(() => api(`/issues/${id}/confirm`, { method: "POST" }), "Thanks for confirming."));
    on("#reopen", () => run(() => api(`/issues/${id}/reopen`, { json: { reason: $("#reopen-reason").value } }), "Issue reopened."));
    on("#ack", () => run(() => api(`/issues/${id}/acknowledge`, { json: { target_date: $("#ack-date").value || null, note: $("#ack-note").value } }), "Issue acknowledged."));
    const pr = $("#pr"); if (pr) pr.oninput = () => ($("#pv").textContent = pr.value);
    const fileForm = (note, photo, extra = {}) => {
      const fd = new FormData(); fd.append("note", $(note).value);
      Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
      const f = $(photo).files[0]; if (f) fd.append("photo", f); return fd;
    };
    on("#prog", () => run(() => api(`/issues/${id}/progress`, { form: fileForm("#pr-note", "#pr-photo", { progress: $("#pr").value }) }), "Progress posted."));
    on("#comp", () => {
      if (!$("#cp-photo").files[0]) return toast("A photo of the finished work is required.");
      run(() => api(`/issues/${id}/complete`, { form: fileForm("#cp-note", "#cp-photo") }), "Marked as completed.");
    });
    const cat = $("#ov-cat");
    if (cat) cat.onchange = () => { const subs = cat.value ? tax.categories[cat.value].subs : []; $("#ov-sub").innerHTML = '<option value="">-</option>' + subs.map((s) => `<option>${esc(s)}</option>`).join(""); };
    on("#ov", () => {
      const body = { category: $("#ov-cat").value || null, sub_category: $("#ov-sub").value || null, clear_priority: $("#ov-clear").checked, reason: $("#ov-reason").value };
      const pv = $("#ov-pri").value; if (pv !== "") body.priority = parseInt(pv, 10);
      run(() => api(`/issues/${id}/override`, { json: body }), "Override applied.");
    });
  }

  /* ------------------------------------------------------------------ official: queue */
  async function viewQueue() {
    const f = { scope: "mine", stage: "open", q: "", sort: "priority" };
    app().innerHTML = `<div class="wrap">
      <div class="page-head"><h2 class="section">Priority queue</h2><p id="qsub">${esc(state.user.department)}</p></div>
      <div class="stats" id="qstats"></div>
      <div class="split"><aside class="side">
        <label class="search">${ICON.search}<input id="q" placeholder="Search queue" autocomplete="off"></label>
        <div class="filter" id="f-scope"><h4>Scope</h4><button data-v="mine" class="on">My department</button><button data-v="all">All departments</button></div>
        <div class="filter" id="f-stage"><h4>Status</h4>${[["open", "Open"], ["overdue", "Overdue"], ["received", "Received"], ["acknowledged", "Acknowledged"], ["in_progress", "In progress"], ["reopened", "Reopened"], ["completed", "Completed"], ["all", "All"]].map(([v, l]) => `<button data-v="${v}" class="${v === "open" ? "on" : ""}">${l}</button>`).join("")}</div>
        <label class="f"><span>Sort by</span><select class="in" id="sort"><option value="priority">Priority</option><option value="reports">Most reports</option><option value="oldest">Oldest first</option><option value="newest">Newest first</option></select></label>
      </aside><section><div class="tbl-wrap"><table><thead><tr><th>#</th><th>Priority</th><th>Issue</th><th>Reports</th><th>Status</th><th>Age</th></tr></thead><tbody id="rows"></tbody></table></div></section></div></div>`;
    const load = async () => {
      const data = await api("/official/queue?" + new URLSearchParams(f));
      const s = data.stats;
      $("#qstats").innerHTML = [["Open", s.open], ["Overdue", s.overdue], ["Avg. acknowledge", s.avg_ack_hours != null ? s.avg_ack_hours + "h" : "-"], ["Avg. resolve", s.avg_resolve_days != null ? s.avg_resolve_days + "d" : "-"], ["Reopen rate", s.reopen_rate + "%"]]
        .map(([l, v]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("");
      $("#rows").innerHTML = data.items.length ? data.items.map((c, i) => `<tr data-id="${c.id}">
        <td class="mono">${String(i + 1).padStart(2, "0")}</td>
        <td><span class="pill ${["critical", "high"].includes(c.priority.label) ? "fill" : ""}" title="${esc(c.priority.label)}">${c.priority.score}</span></td>
        <td><div class="tbl-title">${esc(c.title)}</div><div class="tbl-sub">${esc(c.category)} · ${esc(c.department)}${c.priority.overridden ? " · override" : ""}</div></td>
        <td>${c.reports}</td><td>${esc(c.stage_label)}${c.overdue ? ' <span class="chip fill">overdue</span>' : ""}</td><td>${ago(c.created_at)}</td></tr>`).join("")
        : '<tr><td colspan="6" class="muted" style="text-align:center;padding:48px">Nothing here. Nice work.</td></tr>';
    };
    const bind = (id, key) => $(id).addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; f[key] = b.dataset.v; $$("button", $(id)).forEach((x) => x.classList.toggle("on", x === b)); load(); });
    bind("#f-scope", "scope"); bind("#f-stage", "stage");
    $("#sort").onchange = (e) => { f.sort = e.target.value; load(); };
    $("#q").addEventListener("input", debounce((e) => { f.q = e.target.value; load(); }));
    $("#rows").addEventListener("click", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr) location.hash = "#/issue/" + tr.dataset.id; });
    await load();
  }

  /* ------------------------------------------------------------------ official: map */
  async function viewMap() {
    const cfg = await ensureConfig();
    let scope = "mine";
    app().innerHTML = `<div class="wrap"><div class="page-head"><h2 class="section">Issue map</h2><p>Circle size = number of merged reports. Dashed ring = overdue.</p></div>
      <div class="seg" id="s-scope" style="max-width:380px;margin:18px 0"><button data-v="mine" class="on">My department</button><button data-v="all">All departments</button></div>
      <div id="map"></div><p class="hint" id="mcount" style="margin:12px 0 90px"></p></div>`;
    if (!window.L) { $("#map").outerHTML = '<p class="err">The map library could not load. Check your internet connection.</p>'; return; }
    state.map = L.map("map").setView(cfg.map_center, 13);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" }).addTo(state.map);
    const layer = L.layerGroup().addTo(state.map);
    const draw = async () => {
      const data = await api("/official/queue?" + new URLSearchParams({ scope, stage: "open", sort: "priority" }));
      layer.clearLayers();
      const pts = [];
      data.items.forEach((c) => {
        const r = 8 + Math.min(c.reports, 20) * 1.3;
        const m = L.circleMarker([c.lat, c.lon], { radius: r, color: "#fff", weight: 2, fillColor: "#000", fillOpacity: c.priority.label === "low" ? 0.45 : 0.85 }).addTo(layer);
        if (c.overdue) L.circleMarker([c.lat, c.lon], { radius: r + 6, color: "#000", weight: 1.5, dashArray: "4 4", fill: false }).addTo(layer);
        m.bindPopup(`<b>${esc(c.title)}</b><br>${esc(c.sub_category)} · ${c.reports} report${c.reports > 1 ? "s" : ""}<br>Priority ${c.priority.score} (${esc(c.priority.label)})<br><a href="#/issue/${c.id}"><b>Open issue →</b></a>`);
        pts.push([c.lat, c.lon]);
      });
      if (pts.length) state.map.fitBounds(pts, { padding: [50, 50], maxZoom: 16 });
      $("#mcount").textContent = data.items.length + " open issue" + (data.items.length === 1 ? "" : "s") + " shown.";
    };
    $("#s-scope").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; scope = b.dataset.v; $$("button", $("#s-scope")).forEach((x) => x.classList.toggle("on", x === b)); draw(); });
    await draw();
  }

  /* ------------------------------------------------------------------ official: analytics */
  async function viewAnalytics() {
    app().innerHTML = loadingHTML();
    const a = await api("/official/analytics");
    const s = a.summary;
    const bars = (rows) => { const max = Math.max(1, ...rows.map((r) => r.count)); return rows.length ? rows.map((r) => `<div class="r"><span>${esc(r.label)}</span><div class="t"><i style="width:${(r.count / max) * 100}%"></i></div><b>${r.count}</b></div>`).join("") : '<p class="muted small">No data yet.</p>'; };
    const tmax = Math.max(1, ...a.trend.map((t) => t.count));
    app().innerHTML = `<div class="wrap"><div class="page-head"><h2 class="section">Analytics</h2><p>${esc(a.department)}</p></div>
      <div class="stats">${[["Issues", s.total], ["Open", s.open], ["Overdue", s.overdue], ["Avg. acknowledge", s.avg_ack_hours != null ? s.avg_ack_hours + "h" : "-"], ["Avg. resolve", s.avg_resolve_days != null ? s.avg_resolve_days + "d" : "-"], ["Reopen rate", s.reopen_rate + "%"]].map(([l, v]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("")}</div>
      <div class="two"><div class="box bars"><h4>By sub-category</h4>${bars(a.by_category)}</div><div class="box bars"><h4>By status</h4>${bars(a.by_stage)}</div></div>
      <div class="box"><h4>New citizen reports - last 14 days (all departments)</h4>
        <div class="cols">${a.trend.map((t) => `<div style="height:${Math.max(2, (t.count / tmax) * 100)}%" title="${t.day}: ${t.count}"><span>${t.count || ""}</span></div>`).join("")}</div>
        <div class="col-labels">${a.trend.map((t, i) => `<span>${i % 2 === 0 ? t.day.slice(0, 6) : ""}</span>`).join("")}</div></div>
      <div class="box" style="margin-bottom:90px"><h4>Department performance (public accountability)</h4><div class="tbl-wrap" style="border:0"><table><thead><tr><th>Department</th><th>Issues</th><th>Open</th><th>Overdue</th><th>Avg. acknowledge</th><th>Avg. resolve</th><th>Reopen</th></tr></thead><tbody>
        ${a.departments.map((d) => `<tr style="cursor:default"><td>${esc(d.department)}</td><td>${d.total}</td><td>${d.open}</td><td>${d.overdue}</td><td>${d.avg_ack_hours != null ? d.avg_ack_hours + "h" : "-"}</td><td>${d.avg_resolve_days != null ? d.avg_resolve_days + "d" : "-"}</td><td>${d.reopen_rate}%</td></tr>`).join("")}</tbody></table></div></div></div>`;
  }

  /* ------------------------------------------------------------------ router */
  const routes = [
    [/^#\/?$/, viewHome], [/^#\/how$/, viewHow], [/^#\/login$/, viewLogin],
    [/^#\/report$/, viewReport, "citizen"], [/^#\/my$/, viewMy, "citizen"], [/^#\/issue\/(\d+)$/, viewIssue],
    [/^#\/queue$/, viewQueue, "official"], [/^#\/map$/, viewMap, "official"], [/^#\/analytics$/, viewAnalytics, "official"],
  ];

  async function route() {
    if (state.map) { state.map.remove(); state.map = null; }
    if (state.pop) { state.pop.remove(); state.pop = null; }
    const hash = location.hash || "#/";
    for (const [re, fn, role] of routes) {
      const m = hash.match(re);
      if (!m) continue;
      if (role && (!state.user || state.user.role !== role)) { toast(state.user ? "That page is not available for your role." : "Please log in first."); location.hash = state.user ? "#/" : "#/login"; return; }
      renderTopbar();
      window.scrollTo(0, 0);
      try { await fn(...m.slice(1)); }
      catch (e) { app().innerHTML = `<div class="wrap"><p class="err">${esc(e.message)}</p></div>`; }
      return;
    }
    location.hash = "#/";
  }

  window.addEventListener("hashchange", route);
  (async function init() {
    if (state.token) {
      try { state.user = await api("/auth/me"); localStorage.setItem("cm_user", JSON.stringify(state.user)); }
      catch (_) { state.token = null; state.user = null; localStorage.removeItem("cm_token"); localStorage.removeItem("cm_user"); }
    }
    await route();
    setInterval(refreshBadge, 60000);
  })();
})();
