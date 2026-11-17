/**
 * login.js — login + register for 4 roles: consumer, farmer, vendor, admin.
 * URL: login.html?role=farmer&mode=register
 * Rules: admin can only LOG IN (no public sign-up). Admin logs in with email; others with mobile number.
 * Sends to `${CB_CONFIG.apiBase}/auth/login` or `/auth/register` when apiBase is set.
 */
(function () {
  const { t, esc } = window.CB;
  const ROLES = ["consumer", "farmer", "vendor", "admin"];
  const ROLE_TONE = { consumer: "leaf", farmer: "leaf", vendor: "soil", admin: "slate" };

  const params = new URLSearchParams(location.search);
  const state = {
    role: ROLES.includes(params.get("role")) ? params.get("role") : "consumer",
    mode: params.get("mode") === "register" ? "register" : "login",
    busy: false,
  };
  if (state.role === "admin") state.mode = "login";

  // ---------- helpers ----------
  const bnToEn = (s) => String(s ?? "").replace(/[০-৯]/g, (d) => "০১২৩৪৫৬৭৮৯".indexOf(d));
  function normalizePhone(raw) {
    let s = bnToEn(raw).replace(/[\s\-()]/g, "");
    if (s.startsWith("+880")) s = "0" + s.slice(4);
    else if (s.startsWith("880")) s = "0" + s.slice(3);
    return s;
  }
  const isPhone = (s) => /^01[3-9]\d{8}$/.test(s);
  const isEmail = (s) => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(s);

  function syncUrl() {
    const p = new URLSearchParams({ role: state.role });
    if (state.mode === "register") p.set("mode", "register");
    try { history.replaceState(null, "", `${location.pathname}?${p}`); } catch (e) { /* file:// pages can block this; safe to skip */ }
  }

  // ---------- field templates ----------
  function field(id, labelKey, type = "text", extra = "") {
    return `<div>
      <label for="${id}" class="mb-1 block font-semibold">${esc(t(labelKey))}</label>
      <input id="${id}" name="${id}" type="${type}" class="cb-field" ${extra} aria-describedby="${id}-err">
      <p id="${id}-err" class="mt-1 hidden text-sm text-red-600 dark:text-red-400"></p>
    </div>`;
  }
  function passwordField(id, labelKey, autocomplete) {
    return `<div>
      <label for="${id}" class="mb-1 block font-semibold">${esc(t(labelKey))}</label>
      <div class="relative">
        <input id="${id}" name="${id}" type="password" class="cb-field !pr-20" autocomplete="${autocomplete}" aria-describedby="${id}-err">
        <button type="button" data-toggle-pw="${id}" class="absolute right-2 top-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold text-muted hover:text-ink">${esc(t("show_pw"))}</button>
      </div>
      <p id="${id}-err" class="mt-1 hidden text-sm text-red-600 dark:text-red-400"></p>
    </div>`;
  }
  function districtField() {
    return `<div>
      <label for="district" class="mb-1 block font-semibold">${esc(t("f_district"))}</label>
      <select id="district" name="district" class="cb-field" aria-describedby="district-err"></select>
      <p id="district-err" class="mt-1 hidden text-sm text-red-600 dark:text-red-400"></p>
    </div>`;
  }

  // ---------- render ----------
  function renderRolePicker() {
    const el = document.getElementById("role-picker");
    el.innerHTML = ROLES.map((r) => {
      const on = r === state.role;
      const tone = ROLE_TONE[r];
      const onCls = tone === "soil" ? "bg-soil-500 border-soil-500 text-white"
        : tone === "slate" ? "bg-slate-700 border-slate-700 text-white" : "bg-leaf-600 border-leaf-600 text-white";
      return `<button type="button" role="radio" aria-checked="${on}" data-role="${r}"
        class="rounded-xl border px-3 py-2.5 font-semibold ${on ? onCls : "border-line hover:bg-page"}">${esc(t("role_" + r))}</button>`;
    }).join("");
    el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      state.role = b.dataset.role;
      if (state.role === "admin") state.mode = "login";
      syncUrl(); render();
    }));
  }

  function renderTabs() {
    const el = document.getElementById("mode-tabs");
    const adminLock = state.role === "admin";
    el.innerHTML = ["login", "register"].map((m) => {
      const on = m === state.mode;
      const disabled = adminLock && m === "register";
      return `<button type="button" role="tab" aria-selected="${on}" data-mode="${m}" ${disabled ? "disabled" : ""}
        class="rounded-lg py-2 font-semibold ${on ? "bg-surface shadow-sm" : "text-muted"} ${disabled ? "cursor-not-allowed opacity-40" : ""}">
        ${esc(t(m === "login" ? "tab_login" : "tab_register"))}</button>`;
    }).join("");
    el.querySelectorAll("button:not([disabled])").forEach((b) => b.addEventListener("click", () => {
      state.mode = b.dataset.mode; syncUrl(); render();
    }));
  }

  function renderForm() {
    const form = document.getElementById("auth-form");
    const { role, mode } = state;
    let html = "";
    if (mode === "login") {
      html += role === "admin"
        ? field("email", "f_email", "email", 'autocomplete="email"')
        : field("phone", "f_phone", "tel", 'autocomplete="tel" inputmode="tel" placeholder="01XXXXXXXXX"');
      html += passwordField("password", "f_password", "current-password");
    } else {
      html += field("name", "f_name", "text", 'autocomplete="name"');
      if (role === "vendor") html += field("shop", "f_shop", "text", 'autocomplete="organization"');
      html += field("phone", "f_phone", "tel", 'autocomplete="tel" inputmode="tel" placeholder="01XXXXXXXXX"');
      html += districtField();
      html += passwordField("password", "f_password", "new-password");
      html += passwordField("confirm", "f_confirm", "new-password");
    }
    const tone = ROLE_TONE[role] === "soil" ? "bg-soil-500 hover:bg-soil-600" : ROLE_TONE[role] === "slate" ? "bg-slate-700 hover:bg-slate-800" : "bg-leaf-600 hover:bg-leaf-700";
    html += `<button id="submit-btn" type="submit" class="mt-2 h-12 rounded-xl font-bold text-white ${tone} disabled:opacity-60">
      ${esc(t(mode === "login" ? "btn_login" : "btn_register"))}</button>`;
    form.innerHTML = html;

    const sel = form.querySelector("#district");
    if (sel) window.CB.fillDistrictSelect(sel, "choose_district");

    form.querySelectorAll("[data-toggle-pw]").forEach((b) => b.addEventListener("click", () => {
      const input = document.getElementById(b.dataset.togglePw);
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      b.textContent = t(show ? "hide_pw" : "show_pw");
    }));
  }

  function render() {
    const roleName = t("role_" + state.role);
    document.getElementById("side-text").textContent = t("side_" + state.role);
    document.getElementById("form-title").textContent =
      t(state.mode === "login" ? "auth_title_login" : "auth_title_register", { role: roleName });
    document.getElementById("admin-note").classList.toggle("hidden", state.role !== "admin");
    const sw = document.getElementById("mode-switch");
    sw.classList.toggle("hidden", state.role === "admin");
    sw.textContent = t(state.mode === "login" ? "switch_to_register" : "switch_to_login");
    renderRolePicker(); renderTabs(); renderForm();
    setStatus(null);
  }

  // ---------- validation ----------
  function setError(id, key) {
    const input = document.getElementById(id);
    const err = document.getElementById(`${id}-err`);
    if (!input || !err) return;
    input.setAttribute("aria-invalid", key ? "true" : "false");
    err.textContent = key ? t(key) : "";
    err.classList.toggle("hidden", !key);
  }

  function collectAndValidate() {
    const get = (id) => (document.getElementById(id)?.value ?? "").trim();
    const data = { role: state.role };
    const errors = {};

    if (state.mode === "login" && state.role === "admin") {
      data.email = get("email").toLowerCase();
      if (!data.email) errors.email = "err_required"; else if (!isEmail(data.email)) errors.email = "err_email";
    } else {
      data.phone = normalizePhone(get("phone"));
      if (!data.phone) errors.phone = "err_required"; else if (!isPhone(data.phone)) errors.phone = "err_phone";
    }

    const pw = document.getElementById("password")?.value ?? "";
    if (!pw) errors.password = "err_required"; else if (state.mode === "register" && pw.length < 8) errors.password = "err_pw_len";
    data.password = pw;

    if (state.mode === "register") {
      data.name = get("name"); if (!data.name) errors.name = "err_required";
      if (state.role === "vendor") { data.shop = get("shop"); if (!data.shop) errors.shop = "err_required"; }
      data.district = get("district");
      if (!data.district || !window.CB.DISTRICTS[data.district]) errors.district = "err_district";
      const confirm = document.getElementById("confirm")?.value ?? "";
      if (!confirm) errors.confirm = "err_required"; else if (confirm !== pw) errors.confirm = "err_pw_match";
    }

    ["email", "phone", "password", "name", "shop", "district", "confirm"].forEach((id) => setError(id, errors[id]));
    const firstBad = Object.keys(errors)[0];
    if (firstBad) document.getElementById(firstBad)?.focus();
    return firstBad ? null : data;
  }

  function setStatus(kind, key) {
    const el = document.getElementById("form-status");
    if (!kind) { el.classList.add("hidden"); return; }
    const cls = {
      ok: "bg-leaf-50 text-leaf-800 dark:bg-leaf-900/50 dark:text-leaf-200",
      info: "bg-amber-50 text-amber-800 dark:bg-amber-900/30 dark:text-amber-200",
      error: "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-200",
    }[kind];
    el.className = `mt-4 rounded-xl px-4 py-3 text-sm ${cls}`;
    el.textContent = t(key);
  }

  // ---------- submit ----------
  async function onSubmit(e) {
    e.preventDefault();
    if (state.busy) return;
    const data = collectAndValidate();
    if (!data) return;

    const base = (window.CB_CONFIG && window.CB_CONFIG.apiBase) || "";
    if (!base) { setStatus("info", "srv_not_connected"); return; }

    state.busy = true;
    const btn = document.getElementById("submit-btn");
    btn.disabled = true;
    try {
      const res = await fetch(`${base}/auth/${state.mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStatus("ok", "srv_ok");
      // TODO: redirect to the right dashboard, e.g. location.href = `${state.role}/dashboard.html`;
    } catch (err) {
      console.error("Auth request failed:", err);
      setStatus("error", "srv_error");
    } finally {
      state.busy = false;
      btn.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    syncUrl();
    render();
    document.getElementById("auth-form").addEventListener("submit", onSubmit);
    document.getElementById("mode-switch").addEventListener("click", () => {
      state.mode = state.mode === "login" ? "register" : "login"; syncUrl(); render();
    });
  });
  document.addEventListener("cb:langchange", render);
})();
