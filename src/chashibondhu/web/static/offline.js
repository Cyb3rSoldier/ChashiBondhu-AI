/* ChashiBondhu offline mode for farmers (loaded only on farmer sessions).
   Drafts live in IndexedDB on this phone, tagged with the farmer's account id. They are sent when the
   internet returns. Each draft has a client id (UUID) so a retry never creates a duplicate on the server.
   "Synced" is shown only after the server answered OK. Conflicts are never overwritten silently. */
(function () {
  "use strict";
  var meta = document.querySelector('meta[name="cb-user"]');
  if (!meta || !window.indexedDB) return;
  var USER = String(meta.getAttribute("content"));
  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var CSRF = csrfMeta ? csrfMeta.getAttribute("content") : "";
  var MAX_IMAGE = 8 * 1024 * 1024;
  var KEEP_SYNCED_DAYS = 7;
  var WARM = ["/farmer", "/farmer/listings", "/farmer/listings/new", "/farmer/forecasts", "/farmer/forecasts/new",
              "/farmer/drafts"];
  var bn = function () { return window.cbLang() === "bn"; };
  var L = function (b, e) { return bn() ? b : e; };
  var STATUS = {
    saved: ["ফোনে রাখা আছে", "Saved on device"], waiting: ["ইন্টারনেটের অপেক্ষা", "Waiting for internet"],
    syncing: ["পাঠানো হচ্ছে…", "Syncing…"], synced: ["পাঠানো হয়েছে", "Synced successfully"],
    failed: ["পাঠানো যায়নি — আবার চেষ্টা হবে", "Sync failed — will retry"], action: ["আপনার কাজ দরকার", "Action required"]
  };
  var ERR = {
    login_required: ["আবার লগইন করুন, তারপর \"এখনই পাঠান\" চাপুন।", "Log in again, then press \"Sync now\"."],
    csrf: ["আবার লগইন করুন, তারপর \"এখনই পাঠান\" চাপুন।", "Log in again, then press \"Sync now\"."],
    wrong_account: ["এই খসড়া অন্য অ্যাকাউন্টের।", "This draft belongs to another account."],
    not_allowed: ["এই অ্যাকাউন্ট দিয়ে পাঠানো যায় না।", "This account cannot send it."],
    closed: ["আগাম ফসলটি আর খোলা নেই, বদলানো যাবে না।", "The forecast is no longer open, so it cannot change."],
    not_found: ["সার্ভারে জিনিসটি পাওয়া যায়নি।", "Not found on the server."]
  };

  /* ---------- service worker ---------- */
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () { /* offline pages unavailable */ });
    navigator.serviceWorker.ready.then(function (reg) {
      if (!reg.active) return;
      reg.active.postMessage({ type: "user", user: USER });
      if (navigator.onLine) setTimeout(function () { reg.active.postMessage({ type: "warm", urls: WARM }); }, 1500);
    });
  }
  document.querySelectorAll("form.cb-logout").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (f.dataset.cbOut) return;
      e.preventDefault();
      f.dataset.cbOut = "1";
      var jobs = [];
      if (window.caches) jobs.push(caches.keys().then(function (k) {
        return Promise.all(k.filter(function (n) { return n.indexOf("cb-pages-") === 0 || n === "cb-meta"; })
          .map(function (n) { return caches.delete(n); }));
      }));
      Promise.all(jobs).catch(function () {}).then(function () { HTMLFormElement.prototype.submit.call(f); });
    });
  });

  /* ---------- IndexedDB ---------- */
  var dbp = null;
  function db() {
    if (dbp) return dbp;
    dbp = new Promise(function (ok, bad) {
      var r = indexedDB.open("chashibondhu-offline", 1);
      r.onupgradeneeded = function () {
        var s = r.result.createObjectStore("drafts", { keyPath: "client_id" });
        s.createIndex("user_id", "user_id");
      };
      r.onsuccess = function () { ok(r.result); };
      r.onerror = function () { bad(r.error); };
    });
    return dbp;
  }
  function tx(mode, fn) {
    return db().then(function (d) {
      return new Promise(function (ok, bad) {
        var t = d.transaction("drafts", mode), s = t.objectStore("drafts"), out = fn(s);
        t.oncomplete = function () { ok(out && out.result !== undefined ? out.result : undefined); };
        t.onerror = function () { bad(t.error); };
        t.onabort = function () { bad(t.error); };
      });
    });
  }
  function mine() {
    return tx("readonly", function (s) { return s.index("user_id").getAll(USER); });
  }
  function getDraft(id) { return tx("readonly", function (s) { return s.get(id); }); }
  function putDraft(rec) { return tx("readwrite", function (s) { s.put(rec); }); }
  function delDraft(id) { return tx("readwrite", function (s) { s.delete(id); }); }

  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    var b = crypto.getRandomValues(new Uint8Array(16));
    b[6] = (b[6] & 15) | 64; b[8] = (b[8] & 63) | 128;
    var h = Array.prototype.map.call(b, function (x) { return (x + 256).toString(16).slice(1); }).join("");
    return h.slice(0, 8) + "-" + h.slice(8, 12) + "-" + h.slice(12, 16) + "-" + h.slice(16, 20) + "-" + h.slice(20);
  }

  /* ---------- forms ---------- */
  function fields(form) {
    var out = {};
    new FormData(form).forEach(function (v, k) {
      if (k === "csrf" || k === "version" || typeof v !== "string") return;
      out[k] = v;
    });
    return out;
  }
  function fill(form, data) {
    Object.keys(data || {}).forEach(function (k) {
      var els = form.querySelectorAll('[name="' + k + '"]');
      els.forEach(function (el) {
        if (el.type === "radio" || el.type === "checkbox") el.checked = (el.value === data[k]);
        else if (el.type !== "file") el.value = data[k];
      });
    });
    var chosen = form.querySelector("[data-chosen]");
    if (chosen && data.upazila_label) { chosen.textContent = data.upazila_label; chosen.parentNode.hidden = false; }
  }

  function saveDraft(form, queued) {
    var kind = form.getAttribute("data-offline");
    var file = form.elements.image && form.elements.image.files && form.elements.image.files[0];
    if (file && (file.size > MAX_IMAGE || !/^image\//.test(file.type))) {
      window.cbToast(L("ছবিটা ৮ MB-এর ছোট হতে হবে।", "The photo must be under 8 MB."), true);
      return Promise.reject(new Error("image"));
    }
    var id = form.dataset.draftId;
    return (id ? getDraft(id) : Promise.resolve(null)).then(function (old) {
      var now = new Date().toISOString();
      var data = fields(form);
      var rec = old || { client_id: uuid(), user_id: USER, kind: kind, created_at: now };
      rec.data = data;
      rec.title = data.title || data.product_name || "";
      rec.server_id = form.getAttribute("data-server-id") || rec.server_id || null;
      rec.base_version = form.getAttribute("data-version") || rec.base_version || null;
      if (file) { rec.image = file; rec.image_name = file.name || "photo.jpg"; }
      rec.status = queued ? "waiting" : "saved";
      rec.updated_at = now;
      rec.error = null; rec.errors = null; rec.conflict = null; rec.force = false;
      return putDraft(rec).then(function () { return rec; });
    });
  }

  function reachable() {
    if (!navigator.onLine) return Promise.resolve(false);
    var ctrl = window.AbortController ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 4000);
    return fetch("/health", { cache: "no-store", signal: ctrl ? ctrl.signal : undefined })
      .then(function (r) { clearTimeout(timer); return r.ok; })
      .catch(function () { clearTimeout(timer); return false; });
  }

  var params = new URLSearchParams(location.search);
  document.querySelectorAll("form[data-offline]").forEach(function (form) {
    var draftId = params.get("draft");
    if (draftId) {
      getDraft(draftId).then(function (rec) {
        if (!rec || rec.user_id !== USER) return;
        form.dataset.draftId = rec.client_id;
        fill(form, rec.data);
        var note = document.createElement("p");
        note.className = "cb-flash ok";
        note.textContent = L("ফোনে রাখা খসড়া খোলা হয়েছে", "Editing a draft saved on this phone") +
          (rec.image ? L(" (ছবি রাখা আছে)", " (photo kept)") : "");
        form.parentNode.insertBefore(note, form);
      });
    }
    form.addEventListener("submit", function (e) {
      if (form.dataset.cbSending) return;
      if (form.hasAttribute("data-preview-form") && form.dataset.previewOk !== "1") return;   // preview first
      e.preventDefault();
      if (!form.reportValidity()) return;
      reachable().then(function (online) {
        if (online && !form.dataset.draftId) {               // normal online save
          form.dataset.cbSending = "1";
          HTMLFormElement.prototype.submit.call(form);
          return;
        }
        return saveDraft(form, true).then(function () {
          window.cbToast(online ? L("পাঠানো হচ্ছে…", "Sending…") : L("ফোনে রাখা হলো। ইন্টারনেট ফিরলে পাঠানো হবে।", "Saved on phone. It will be sent when internet returns."));
          return (online ? syncAll() : Promise.resolve()).then(function () { location.href = "/farmer/drafts"; });
        });
      }).catch(function () { form.dataset.previewOk = ""; });
    });
    var keep = form.querySelector("[data-save-draft]");
    if (keep) keep.addEventListener("click", function () {
      if (!form.reportValidity()) return;
      saveDraft(form, false).then(function () { location.href = "/farmer/drafts"; }).catch(function () {});
    });
  });

  /* ---------- sync ---------- */
  function freshCsrf() {
    return fetch("/farmer/drafts", { cache: "no-store", credentials: "same-origin" }).then(function (r) {
      if (!r.ok || r.redirected) return null;
      return r.text().then(function (h) {
        var m = h.match(/name="csrf-token" content="([^"]+)"/);
        return m ? m[1] : null;
      });
    }).catch(function () { return null; });
  }

  function send(rec) {
    if (rec.kind === "forecast") {
      return fetch("/farmer/sync/forecast", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": CSRF },
        body: JSON.stringify({ client_id: rec.client_id, owner: USER, server_id: rec.server_id,
                               base_version: rec.base_version, force: rec.force === true, data: rec.data })
      });
    }
    var fd = new FormData();
    Object.keys(rec.data || {}).forEach(function (k) { fd.append(k, rec.data[k]); });
    fd.append("client_id", rec.client_id);
    fd.append("owner", USER);
    if (rec.image) fd.append("image", rec.image, rec.image_name || "photo.jpg");
    return fetch("/farmer/sync/listing", { method: "POST", credentials: "same-origin",
                                           headers: { "X-CSRF-Token": CSRF }, body: fd });
  }

  function syncOne(rec, retried) {
    rec.status = "syncing";
    return putDraft(rec).then(render).then(function () { return send(rec); }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (body) {
        if (res.ok && body.ok) {
          rec.status = "synced"; rec.server_url = body.url || null; rec.synced_at = new Date().toISOString();
          rec.image = null; rec.error = null; rec.errors = null; rec.conflict = null;
          return;
        }
        if (res.status === 401 && body.detail === "csrf" && !retried) {
          return freshCsrf().then(function (tok) {
            if (!tok) { rec.status = "action"; rec.error = "login_required"; return; }
            CSRF = tok;
            return syncOne(rec, true).then(function () { throw "done"; });
          });
        }
        if (res.status === 409 && body.detail === "conflict") {
          rec.status = "action"; rec.conflict = { server: body.server, server_version: body.server_version };
        } else if ([401, 403, 404, 409, 422].indexOf(res.status) >= 0) {
          rec.status = "action"; rec.error = body.detail || "invalid"; rec.errors = body.errors || null;
        } else {
          rec.status = "failed"; rec.error = "server"; rec.tries = (rec.tries || 0) + 1;
        }
      });
    }).catch(function (err) {
      if (err === "done") return "done";
      rec.status = "failed"; rec.error = "network"; rec.tries = (rec.tries || 0) + 1;
    }).then(function (r) { return r === "done" ? undefined : putDraft(rec); });
  }

  var running = false;
  function syncAll() {
    if (running) return Promise.resolve();
    running = true;
    return reachable().then(function (online) {
      if (!online) return;
      return mine().then(function (list) {
        var todo = (list || []).filter(function (r) { return ["waiting", "failed", "syncing"].indexOf(r.status) >= 0; })
          .sort(function (a, b) { return a.created_at < b.created_at ? -1 : 1; });
        return todo.reduce(function (p, r) { return p.then(function () { return syncOne(r); }); }, Promise.resolve());
      });
    }).catch(function () {}).then(function () { running = false; render(); });
  }
  window.cbOffline = { syncAll: syncAll };

  /* ---------- connectivity indicator ---------- */
  var net = document.querySelector("[data-cb-net]");
  function indicator(list) {
    if (!net) return;
    var pending = (list || []).filter(function (r) { return ["saved", "waiting", "failed", "syncing", "action"].indexOf(r.status) >= 0; }).length;
    var text, cls;
    if (!navigator.onLine) { text = L("অফলাইন", "Offline"); cls = "off"; }
    else if (pending) { text = L("পাঠানো বাকি ", "Pending sync ") + window.cbNum(pending); cls = "wait"; }
    else { text = L("অনলাইন", "Online"); cls = "on"; }
    net.hidden = false;
    net.className = "cb-chip-btn cb-net " + cls;
    net.querySelector("[data-cb-net-text]").textContent = text;
  }

  /* ---------- drafts page ---------- */
  var box = document.querySelector("[data-drafts-list]");
  function editUrl(r) {
    if (r.kind === "listing") return "/farmer/listings/new?draft=" + r.client_id;
    if (r.server_id) return "/farmer/forecasts/" + r.server_id + "/edit?draft=" + r.client_id;
    return "/farmer/forecasts/new?draft=" + r.client_id;
  }
  function el(tag, cls, text) { var x = document.createElement(tag); if (cls) x.className = cls; if (text != null) x.textContent = text; return x; }
  function btn(label, cls, fn) { var b = el("button", "cb-mini " + (cls || ""), label); b.type = "button"; b.addEventListener("click", fn); return b; }

  function draw(list) {
    if (!box) return;
    var empty = box.querySelector("[data-drafts-empty]");
    box.querySelectorAll(".cb-item").forEach(function (n) { n.remove(); });
    var shown = (list || []).sort(function (a, b) { return a.updated_at < b.updated_at ? 1 : -1; });
    if (empty) empty.hidden = shown.length > 0;
    shown.forEach(function (r) {
      var item = el("div", "cb-item"), top = el("div", "cb-item-top"), txt = el("div");
      var ic = el("span", "cb-thumb"); ic.innerHTML = r.kind === "listing" ? '<i class="fa-solid fa-store"></i>' : '<i class="fa-solid fa-seedling"></i>';
      txt.appendChild(el("b", null, (r.title || "—")));
      txt.appendChild(el("small", null, (r.kind === "listing" ? L("পণ্য", "Product") : (r.server_id ? L("আগাম ফসল (বদল)", "Harvest forecast (edit)") : L("আগাম ফসল", "Harvest forecast"))) +
        " · " + new Date(r.updated_at).toLocaleString(bn() ? "bn-BD" : "en-GB")));
      var st = STATUS[r.status] || STATUS.saved;
      var badge = el("span", "cb-badge " + (r.status === "synced" ? "" : r.status === "action" || r.status === "failed" ? "bad" : "soil"), L(st[0], st[1]));
      top.appendChild(ic); top.appendChild(txt); top.appendChild(badge); item.appendChild(top);

      if (r.status === "action" && r.conflict) {
        var c = el("div", "cb-tip"), cd = el("div");
        cd.appendChild(el("b", null, L("এটি অন্য কোথাও থেকে আগেই বদলানো হয়েছে।", "This was changed somewhere else first.")));
        var s = r.conflict.server || {}, mineD = r.data || {};
        ["product_name", "expected_qty", "unit", "harvest_from", "harvest_to"].forEach(function (k) {
          cd.appendChild(el("span", null, k + ": " + L("সার্ভারে ", "server ") + (s[k] || "—") + " | " + L("আপনার ", "yours ") + (mineD[k] || "—")));
          cd.appendChild(document.createElement("br"));
        });
        c.appendChild(el("i", "fa-solid fa-triangle-exclamation")); c.appendChild(cd); item.appendChild(c);
      } else if (r.status === "action" || r.status === "failed") {
        var msg = r.errors ? r.errors.map(function (x) { return L(x[0], x[1]); }).join(" ")
          : (ERR[r.error] ? L(ERR[r.error][0], ERR[r.error][1]) : (r.error === "network" ? L("ইন্টারনেট নেই।", "No internet.") : L("সার্ভারে সমস্যা।", "Server problem.")));
        item.appendChild(el("p", "cb-hint", msg));
      }

      var acts = el("div", "cb-item-actions");
      if (r.status === "synced") {
        if (r.server_url) { var a = el("a", "cb-mini main", L("দেখুন", "Open")); a.href = r.server_url; acts.appendChild(a); }
        acts.appendChild(btn(L("তালিকা থেকে সরান", "Remove from list"), "", function () { delDraft(r.client_id).then(render); }));
      } else if (r.status !== "syncing") {
        if (r.conflict) {
          acts.appendChild(btn(L("আমারটা রাখুন (সার্ভারেরটা বদলে দিন)", "Keep mine (replace server)"), "main", function () {
            r.force = true; r.conflict = null; r.status = "waiting"; putDraft(r).then(syncAll);
          }));
          acts.appendChild(btn(L("সার্ভারেরটা রাখুন (আমার বদল মুছুন)", "Keep server version (delete mine)"), "", function () {
            delDraft(r.client_id).then(render);
          }));
        } else {
          var ed = el("a", "cb-mini", L("বদলান", "Edit")); ed.href = editUrl(r); acts.appendChild(ed);
          if (r.status === "saved") acts.appendChild(btn(L("পাঠানোর জন্য রাখুন", "Send when online"), "main", function () {
            r.status = "waiting"; putDraft(r).then(syncAll);
          }));
          if (r.status === "failed" || r.status === "waiting") acts.appendChild(btn(L("আবার চেষ্টা", "Retry"), "main", syncAll));
        }
        acts.appendChild(btn(L("মুছুন", "Delete"), "danger", function () {
          if (window.confirm(L("এই খসড়া মুছবেন?", "Delete this draft?"))) delDraft(r.client_id).then(render);
        }));
      }
      item.appendChild(acts);
      box.appendChild(item);
    });
  }

  function render() {
    return mine().then(function (list) {
      var cutoff = Date.now() - KEEP_SYNCED_DAYS * 864e5;
      var old = (list || []).filter(function (r) { return r.status === "synced" && Date.parse(r.synced_at) < cutoff; });
      return Promise.all(old.map(function (r) { return delDraft(r.client_id); })).then(function () {
        var keep = (list || []).filter(function (r) { return old.indexOf(r) < 0; });
        indicator(keep); draw(keep);
      });
    }).catch(function () { indicator([]); });
  }

  var syncBtn = document.querySelector("[data-sync-now]");
  if (syncBtn) syncBtn.addEventListener("click", syncAll);
  window.addEventListener("online", syncAll);
  window.addEventListener("offline", render);
  document.addEventListener("cb:lang", render);
  setInterval(function () { if (navigator.onLine) syncAll(); }, 60000);
  render().then(function () { if (navigator.onLine) syncAll(); });
})();
