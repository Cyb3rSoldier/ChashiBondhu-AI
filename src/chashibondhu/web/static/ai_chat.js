/* ChashiBondhu AI chat — Fosholi (ফসলি) and Dr. Krishi (ড. কৃষি) share this file.
 * - Sidebar: the user's real chats from the server (grouped Today / Yesterday / 7 days / Older), search, rename, delete.
 * - Real streaming: the server sends one JSON per line (sentences that already passed the safety checks).
 * - Dr. Krishi photo answers come as ONE checked JSON diagnosis and are drawn as cards (never parsed from text).
 * - Voice in: Web Speech API (bn-BD) fills the box for review. Voice out: Bangla speechSynthesis, per message.
 * No technical status text is shown to farmers. */
(function () {
  "use strict";
  var app = document.getElementById("aiApp");
  if (!app) return;
  var A = app.dataset.assistant, ASK = app.dataset.ask, NEW = app.dataset.new, IMAGES = app.dataset.images === "1";
  var CONV = app.dataset.conv ? Number(app.dataset.conv) : null;
  var PAGE = "/assistant/" + A;
  var csrfMeta = document.querySelector('meta[name="csrf-token"]'), CSRF = csrfMeta ? csrfMeta.content : "";
  var log = document.getElementById("aiLog"), form = document.getElementById("aiForm"), box = document.getElementById("aiQ");
  var scroller = app.querySelector("[data-ai-scroll]"), welcome = app.querySelector("[data-ai-welcome]");
  var statusEl = app.querySelector("[data-ai-status]"), sendBtn = form.querySelector(".aic-send");
  var busy = false;

  /* ============================================================ helpers */
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function icon(name) { var i = el("i", "fa-solid " + name); i.setAttribute("aria-hidden", "true"); return i; }
  function tt(bn, en) {
    var f = document.createDocumentFragment();
    f.appendChild(el("span", "lang-bn", bn)); f.appendChild(el("span", "lang-en", en == null ? bn : en)); return f;
  }
  function isEn() { return document.documentElement.getAttribute("data-lang") === "en"; }
  function bnDigits(s) { return String(s).replace(/\d/g, function (d) { return "০১২৩৪৫৬৭৮৯"[d]; }); }
  function clock(d) {
    var h = d.getHours(), m = ("0" + d.getMinutes()).slice(-2), h12 = h % 12 || 12;
    return { bn: bnDigits(h12 + ":" + m), en: h12 + ":" + m + (h < 12 ? " AM" : " PM") };
  }
  function timeEl(iso) {
    var d = iso ? new Date(iso) : new Date(); if (isNaN(d)) return el("span");
    var c = clock(d), p = el("p", "aic-time"); p.appendChild(tt(c.bn, c.en)); return p;
  }
  function toBottom() { scroller.scrollTop = scroller.scrollHeight; }
  function say(bn, en, isErr) { statusEl.textContent = ""; if (bn) statusEl.appendChild(tt(bn, en)); statusEl.classList.toggle("err", !!isErr); }
  function api(url, opts) {
    opts = opts || {}; opts.credentials = "same-origin"; opts.headers = opts.headers || {};
    if (opts.method && opts.method !== "GET") opts.headers["X-CSRF-Token"] = CSRF;
    return fetch(url, opts).then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { if (!r.ok) throw j; return j; }); });
  }
  function showWelcome(on) { if (welcome) { welcome.hidden = !on; if (on) scroller.scrollTop = 0; } }

  var ERR = {
    too_many: ["এক ঘণ্টায় অনেক প্রশ্ন হয়েছে। একটু পরে আবার চেষ্টা করুন।", "Too many questions this hour. Please try again later."],
    ai_busy: ["এখন অনেক প্রশ্ন আসছে। এক মিনিট পরে আবার চেষ্টা করুন।", "Many questions right now. Try again in a minute."],
    ai_down: ["সহায়ক এখন চালু নেই। একটু পরে চেষ্টা করুন।", "The assistant is not available now. Please try later."],
    ai_error: ["দুঃখিত, উত্তর তৈরি করা যায়নি। আবার চেষ্টা করুন।", "Sorry, the answer could not be made. Please try again."],
    net: ["ইন্টারনেট সংযোগ পাওয়া যাচ্ছে না।", "No internet connection."],
    question_length: ["২ থেকে ৫০০ অক্ষরে প্রশ্ন লিখুন।", "Write 2 to 500 characters."],
    not_allowed: ["এই সহায়ক শুধু কৃষক ও অ্যাডমিনের জন্য।", "This assistant is for farmers and admins only."],
    not_image: ["ছবিটা খোলা যাচ্ছে না। JPG বা PNG ছবি দিন।", "The photo could not be read. Use a JPG or PNG photo."]
  };
  var NOTES = {
    need_area: ["আবহাওয়া দেখতে উপরে এলাকা/জেলা বেছে নিন।", "Choose your area or district above to see the weather."],
    weather_down: ["এখন আবহাওয়ার তথ্য আনা যাচ্ছে না। একটু পরে চেষ্টা করুন।", "Weather data is not available right now. Try again later."],
    climate_missing: ["এই এলাকার জলবায়ু-ইতিহাস এখনো যুক্ত নেই।", "Climate history for this area is not loaded yet."]
  };

  /* ============================================================ sidebar (real history) */
  var list = app.querySelector("[data-ai-list]"), search = app.querySelector("[data-ai-search]");
  var mq = window.matchMedia("(max-width: 900px)"), collapseKey = "cb_ai_side_collapsed";
  try { if (!mq.matches && localStorage.getItem(collapseKey) === "1") app.classList.add("is-collapsed"); } catch (e) { /* ignore */ }
  function setDrawer(open) {
    app.classList.toggle("is-open", open);
    app.querySelector("[data-ai-scrim]").hidden = !open;
    if (open) { var f = search || app.querySelector("[data-ai-new]"); if (f) f.focus(); }
  }
  app.querySelector("[data-ai-side-toggle]").addEventListener("click", function () {
    if (mq.matches) { setDrawer(!app.classList.contains("is-open")); return; }
    var c = app.classList.toggle("is-collapsed");
    try { localStorage.setItem(collapseKey, c ? "1" : "0"); } catch (e) { /* ignore */ }
  });
  app.querySelector("[data-ai-side-close]").addEventListener("click", function () { setDrawer(false); });
  app.querySelector("[data-ai-scrim]").addEventListener("click", function () { setDrawer(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && app.classList.contains("is-open")) setDrawer(false); });

  function group(iso) {
    var d = new Date(iso), now = new Date(), day = 864e5;
    var start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    if (d.getTime() >= start) return 0;
    if (d.getTime() >= start - day) return 1;
    if (d.getTime() >= start - 7 * day) return 2;
    return 3;
  }
  var GROUPS = [["আজ", "Today"], ["গতকাল", "Yesterday"], ["গত ৭ দিন", "Previous 7 days"], ["আরও আগে", "Older"]];
  var openMenu = null;
  function closeMenu() { if (openMenu) { openMenu.menu.remove(); openMenu.btn.setAttribute("aria-expanded", "false"); openMenu = null; } }
  document.addEventListener("click", function (e) { if (openMenu && !openMenu.menu.contains(e.target) && e.target !== openMenu.btn && !openMenu.btn.contains(e.target)) closeMenu(); });

  function loadList() {
    var q = search ? search.value.trim() : "";
    return api("/app/" + A + "/conversations" + (q ? "?q=" + encodeURIComponent(q) : "")).then(function (j) {
      list.textContent = "";
      if (!j.items.length) {
        var p = el("p", "aic-muted");
        p.appendChild(q ? tt("কিছু পাওয়া যায়নি।", "Nothing found.") : tt("এখনো কোনো চ্যাট নেই।", "No chats yet."));
        list.appendChild(p); return;
      }
      var last = -1;
      j.items.forEach(function (c) {
        var g = group(c.at);
        if (g !== last) { var h = el("h4"); h.appendChild(tt(GROUPS[g][0], GROUPS[g][1])); list.appendChild(h); last = g; }
        list.appendChild(item(c));
      });
    }).catch(function () {
      list.textContent = ""; var p = el("p", "aic-muted"); p.appendChild(tt("তালিকা আনা যায়নি।", "Could not load the list.")); list.appendChild(p);
    });
  }
  function item(c) {
    var row = el("div", "aic-item" + (c.id === CONV ? " is-active" : ""));
    var a = el("a", null, c.title); a.href = PAGE + "?c=" + c.id; a.title = c.title;
    if (c.id === CONV) a.setAttribute("aria-current", "page");
    var more = el("button", "aic-ico"); more.type = "button"; more.appendChild(icon("fa-ellipsis"));
    more.setAttribute("aria-label", "আরও / More options"); more.setAttribute("aria-haspopup", "true"); more.setAttribute("aria-expanded", "false");
    more.addEventListener("click", function (e) {
      e.stopPropagation();
      if (openMenu && openMenu.btn === more) { closeMenu(); return; }
      closeMenu();
      var menu = el("div", "aic-menu"); menu.setAttribute("role", "menu");
      var rn = el("button"); rn.type = "button"; rn.setAttribute("role", "menuitem"); rn.appendChild(icon("fa-pen")); rn.appendChild(tt("নাম বদলান", "Rename"));
      var del = el("button", "is-bad"); del.type = "button"; del.setAttribute("role", "menuitem"); del.appendChild(icon("fa-trash")); del.appendChild(tt("মুছুন", "Delete"));
      rn.addEventListener("click", function () { closeMenu(); rename(row, a, c); });
      del.addEventListener("click", function () {
        if (!del.dataset.sure) { del.dataset.sure = "1"; del.textContent = ""; del.appendChild(icon("fa-trash")); del.appendChild(tt("নিশ্চিত? আবার চাপুন", "Sure? Press again")); return; }
        closeMenu();
        api("/app/" + A + "/conversations/" + c.id + "/delete", { method: "POST" }).then(function () {
          if (c.id === CONV) { location.href = PAGE; return; }
          loadList();
        }).catch(function () { say("মুছতে সমস্যা হয়েছে।", "Could not delete.", true); });
      });
      menu.appendChild(rn); menu.appendChild(del); row.appendChild(menu);
      more.setAttribute("aria-expanded", "true"); openMenu = { menu: menu, btn: more }; rn.focus();
    });
    row.appendChild(a); row.appendChild(more);
    return row;
  }
  function rename(row, a, c) {
    var input = el("input", "aic-rename"); input.value = c.title; input.maxLength = 80; input.setAttribute("aria-label", "নতুন নাম / New name");
    row.replaceChild(input, a); input.focus(); input.select();
    var done = false;
    function finish(save) {
      if (done) return; done = true;
      var v = input.value.replace(/\s+/g, " ").trim();
      if (!save || !v || v === c.title) { row.replaceChild(a, input); return; }
      api("/app/" + A + "/conversations/" + c.id + "/rename", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: v }) })
        .then(function () { c.title = v; a.textContent = v; a.title = v; row.replaceChild(a, input); })
        .catch(function () { row.replaceChild(a, input); say("নাম বদলানো যায়নি।", "Could not rename.", true); });
    }
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); finish(true); } if (e.key === "Escape") finish(false); });
    input.addEventListener("blur", function () { finish(true); });
  }
  var searchT = null;
  if (search) search.addEventListener("input", function () { clearTimeout(searchT); searchT = setTimeout(loadList, 250); });
  app.querySelector("[data-ai-new]").addEventListener("click", function () {
    stopSpeaking();
    api(NEW, { method: "POST" }).catch(function () {}).then(function () { location.href = PAGE; });
  });

  /* ============================================================ rows */
  function userRow(text, opts) {
    opts = opts || {};
    var row = el("div", "aic-row me"), wrap = el("div"), b = el("div", "aic-bubble");
    if (opts.file) { var im = el("img"); im.alt = "পাঠানো ছবি"; im.src = URL.createObjectURL(opts.file); b.appendChild(im); }
    else if (opts.photo) { var g = el("span", "aic-photo-gone"); g.appendChild(icon("fa-image")); g.appendChild(tt("ছবি (সংরক্ষণ করা হয় না)", "Photo (not stored)")); b.appendChild(g); }
    if (text) b.appendChild(document.createTextNode((opts.photo || opts.file) ? "\n" + text : text));
    wrap.appendChild(b); wrap.appendChild(timeEl(opts.at)); row.appendChild(wrap); log.appendChild(row);
    return row;
  }
  var AV_ICON = (app.querySelector(".aic-av i") || {}).className || "fa-solid fa-seedling";

  function Bot(at) {
    this.row = el("div", "aic-row bot");
    var av = el("span", "aic-av"); av.setAttribute("aria-hidden", "true"); av.appendChild(el("i", AV_ICON));
    this.body = el("div", "aic-body"); this.bubble = el("div", "aic-bubble");
    this.main = el("div"); this.bubble.appendChild(this.main);
    this.body.appendChild(this.bubble);
    this.row.appendChild(av); this.row.appendChild(this.body); log.appendChild(this.row);
    this.sentences = []; this.adv = null; this.at = at;
  }
  Bot.prototype.waiting = function (file) {
    if (file) {
      var w = el("div", "aic-analyze"), im = el("img"); im.alt = ""; im.src = URL.createObjectURL(file);
      var right = el("div"); right.style.flex = "1";
      var t = el("p"); t.appendChild(tt("আপনার ছবিটি বিশ্লেষণ করা হচ্ছে...", "Analysing your photo...")); right.appendChild(t);
      var sk = el("div", "aic-sk"); sk.appendChild(el("i")); sk.appendChild(el("i")); sk.appendChild(el("i")); right.appendChild(sk);
      w.appendChild(im); w.appendChild(right); this.wait = w;
    } else {
      var d = el("span", "aic-dots"); d.setAttribute("aria-label", "উত্তর আসছে / Answer coming");
      d.appendChild(el("i")); d.appendChild(el("i")); d.appendChild(el("i")); this.wait = d;
    }
    this.bubble.insertBefore(this.wait, this.main);
  };
  Bot.prototype.unwait = function () { if (this.wait) { this.wait.remove(); this.wait = null; } };
  Bot.prototype.sentence = function (ev) {
    this.unwait(); this.sentences.push(ev.text);
    if (ev.part === "advice" && !/[?？]\s*$/.test(ev.text)) {
      if (!this.adv) {
        this.adv = el("div", "aic-adv"); var h = el("h4"); h.appendChild(icon("fa-lightbulb")); h.appendChild(document.createTextNode(" "));
        h.appendChild(tt("পরামর্শ", "Advice")); this.adv.appendChild(h); this.advList = el("ul"); this.adv.appendChild(this.advList);
        this.bubble.appendChild(this.adv);
      }
      this.advList.appendChild(el("li", null, ev.text));
    } else if (/[?？]\s*$/.test(ev.text) && !ev.label) {
      var q = el("p", "aic-ask"); q.appendChild(icon("fa-circle-question")); q.appendChild(el("span", null, ev.text)); this.bubble.appendChild(q);
    } else {
      var p = el("p"); if (ev.label) p.appendChild(el("b", null, ev.label + ": "));
      p.appendChild(document.createTextNode(ev.text)); this.main.appendChild(p);
    }
    toBottom();
  };
  Bot.prototype.card = function (ev) {
    this.unwait();
    var c = el("div", "aic-data");
    if (ev.kind === "weather") weatherCard(c, ev, this.sentences);
    else if (ev.kind === "climate") climateCard(c, ev.data);
    else {
      var n = ev.text ? [ev.text, ev.text] : (NOTES[ev.code] || ["", ""]);
      c = el("p", "aic-note"); c.appendChild(icon("fa-circle-info")); var s = el("span"); s.appendChild(tt(n[0], n[1])); c.appendChild(s);
      this.sentences.push(n[0]);
    }
    this.bubble.insertBefore(c, this.main); toBottom();
  };
  Bot.prototype.diagnosis = function (p, file) {
    this.unwait();
    this.bubble.classList.add("aic-bare");
    this.main.appendChild(drawDiagnosis(p, file)); toBottom();
  };
  Bot.prototype.done = function (ev) {
    this.unwait();
    if (ev.answer && (ev.payload || !this.sentences.length)) this.sentences = ev.answer.split("\n");
    if (ev.fallback) { this.main.appendChild(el("p", null, ev.fallback)); this.sentences.push(ev.fallback); }
    if (ev.note) { var n = el("p", "aic-note"); n.appendChild(icon("fa-circle-info")); n.appendChild(el("span", null, ev.note)); this.bubble.appendChild(n); }
    if (ev.safety) { var s = el("p", "aic-safe"); s.appendChild(icon("fa-triangle-exclamation")); s.appendChild(el("span", null, ev.safety)); this.body.appendChild(s); }
    if (ev.sources && ev.sources.length) sourcesTo(this.bubble, ev.sources);
    this.actions(ev.message_id); this.body.appendChild(timeEl(this.at));
  };
  Bot.prototype.fail = function (code, retry) {
    this.unwait();
    var m = ERR[code] || ERR.ai_error, p = el("p", "aic-err"); p.appendChild(icon("fa-circle-exclamation")); p.appendChild(document.createTextNode(" "));
    p.appendChild(tt(m[0], m[1])); this.main.appendChild(p);
    if (retry && ["too_many", "not_allowed", "not_image", "question_length"].indexOf(code) < 0) {
      var b = el("button", "aic-retry"); b.type = "button"; b.appendChild(icon("fa-rotate-right")); b.appendChild(document.createTextNode(" "));
      b.appendChild(tt("আবার চেষ্টা করুন", "Try again")); var self = this;
      b.addEventListener("click", function () { self.row.remove(); retry(); });
      this.main.appendChild(b);
    }
    toBottom();
  };
  Bot.prototype.actions = function (mid) {
    var bar = el("div", "aic-acts"), sentences = this.sentences;
    bar.appendChild(speakerButton(function () { return sentences; }));
    var cp = el("button"); cp.type = "button"; cp.setAttribute("aria-label", "কপি / Copy"); cp.title = "কপি / Copy"; cp.appendChild(icon("fa-copy"));
    cp.addEventListener("click", function () {
      if (navigator.clipboard) navigator.clipboard.writeText(sentences.join("\n")).then(function () { cp.classList.add("on"); }).catch(function () {});
    });
    bar.appendChild(cp);
    if (mid) {
      [[true, "fa-thumbs-up", "কাজে লেগেছে / Helpful"], [false, "fa-thumbs-down", "কাজে লাগেনি / Not helpful"]].forEach(function (f) {
        var b = el("button"); b.type = "button"; b.setAttribute("aria-label", f[2]); b.title = f[2]; b.appendChild(icon(f[1]));
        b.addEventListener("click", function () {
          api("/app/ai/feedback", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message_id: mid, helpful: f[0] }) }).catch(function () {});
          bar.querySelectorAll("button[data-fb]").forEach(function (x) { x.disabled = true; }); b.classList.add("on");
        });
        b.dataset.fb = "1"; bar.appendChild(b);
      });
    }
    this.body.appendChild(bar);
  };
  function sourcesTo(node, sources) {
    var src = el("div", "aic-src");
    sources.forEach(function (x) {
      var pg = x.printed_page || x.pdf_page, chip = el("span"); chip.title = x.excerpt || "";
      chip.appendChild(icon("fa-book")); chip.appendChild(document.createTextNode(" "));
      chip.appendChild(tt("হাতবই · পৃ. " + bnDigits(pg), "Handbook · p. " + pg)); src.appendChild(chip);
    });
    node.appendChild(src);
  }

  /* ============================================================ weather / climate cards (real numbers only) */
  function weatherCard(c, ev, sentences) {
    var d = ev.data, h = el("h5"); h.appendChild(icon("fa-cloud-sun")); h.appendChild(tt("আবহাওয়া · " + ev.area.bn, "Weather · " + ev.area.en)); c.appendChild(h);
    var big = el("p", "aic-big", Math.round(d.now.temp) + "°C"), sm = el("small");
    sm.appendChild(tt("  আর্দ্রতা " + Math.round(d.now.rh) + "% · এখন বৃষ্টি " + d.now.rain_mm + " mm", "  Humidity " + Math.round(d.now.rh) + "% · Rain now " + d.now.rain_mm + " mm"));
    big.appendChild(sm); c.appendChild(big);
    var days = el("div", "aic-days"), names = [["আজ", "Today"], ["আগামীকাল", "Tomorrow"], ["পরশু", "Day after"]];
    d.days.forEach(function (x, i) {
      var b = el("div", "aic-day"), n = el("b"); n.appendChild(tt(names[i] ? names[i][0] : x.date, names[i] ? names[i][1] : x.date)); b.appendChild(n);
      b.appendChild(el("span", "t", Math.round(x.t_max) + "° / " + Math.round(x.t_min) + "°")); b.appendChild(el("br"));
      var r = el("span"); var pr = x.rain_prob != null ? " (" + x.rain_prob + "%)" : "";
      r.appendChild(tt("বৃষ্টি " + x.rain_mm + " mm" + pr, "Rain " + x.rain_mm + " mm" + pr)); b.appendChild(r);
      if (x.gust_max != null) { b.appendChild(el("br")); var g = el("span"); g.appendChild(tt("দমকা হাওয়া " + Math.round(x.gust_max) + " km/h", "Gusts " + Math.round(x.gust_max) + " km/h")); b.appendChild(g); }
      days.appendChild(b);
    });
    c.appendChild(days);
    if (ev.tips && ev.tips.length) {
      var ul = el("ul"); ev.tips.forEach(function (x) { var li = el("li"); li.appendChild(tt(x.bn, x.en)); ul.appendChild(li); sentences.push(x.bn); }); c.appendChild(ul);
    }
    c.appendChild(el("p", "aic-tiny", "Open-Meteo"));
  }
  var MON = [["জানুয়ারি", "January"], ["ফেব্রুয়ারি", "February"], ["মার্চ", "March"], ["এপ্রিল", "April"], ["মে", "May"], ["জুন", "June"],
    ["জুলাই", "July"], ["আগস্ট", "August"], ["সেপ্টেম্বর", "September"], ["অক্টোবর", "October"], ["নভেম্বর", "November"], ["ডিসেম্বর", "December"]];
  function climateCard(c, d) {
    var m = MON[d.month - 1], h = el("h5"); h.appendChild(icon("fa-clock-rotate-left"));
    h.appendChild(tt("জলবায়ু-ইতিহাস · " + d.area.bn + " · " + m[0] + " (পূর্বাভাস নয়)", "Climate history · " + d.area.en + " · " + m[1] + " (not a forecast)")); c.appendChild(h);
    var ul = el("ul");
    function li(bn, en) { var x = el("li"); x.appendChild(tt(bn, en)); ul.appendChild(x); }
    if (d.normal) li("৩০ বছরের গড় (" + d.normal.baseline + "): বৃষ্টি " + Math.round(d.normal.rain_mm) + " mm, গড় তাপমাত্রা " + d.normal.t_mean + "°C",
      "30-year normal (" + d.normal.baseline + "): rain " + Math.round(d.normal.rain_mm) + " mm, mean temp " + d.normal.t_mean + "°C");
    if (d.recent) {
      var r = d.recent;
      li(r.years + " গড় বৃষ্টি " + r.rain_mm_avg + " mm; গত বছর (" + r.last.year + ") " + r.last.rain_mm + " mm",
        r.years + " average rain " + r.rain_mm_avg + " mm; last year (" + r.last.year + ") " + r.last.rain_mm + " mm");
      li("সবচেয়ে ভেজা " + r.wettest.year + " (" + r.wettest.rain_mm + " mm), সবচেয়ে শুকনো " + r.driest.year + " (" + r.driest.rain_mm + " mm)",
        "Wettest " + r.wettest.year + " (" + r.wettest.rain_mm + " mm), driest " + r.driest.year + " (" + r.driest.rain_mm + " mm)");
      li("এই মাসের রেকর্ড: সর্বোচ্চ " + r.hottest + "°C, সর্বনিম্ন " + r.coldest + "°C", "Records this month: highest " + r.hottest + "°C, lowest " + r.coldest + "°C");
    }
    c.appendChild(ul); c.appendChild(el("p", "aic-tiny", "NASA POWER"));
  }

  /* ============================================================ diagnosis cards (from the checked JSON) */
  var LVL = { low: ["কম", "Low"], medium: ["মাঝারি", "Medium"], high: ["বেশি", "High"] };
  var RISK = { low: ["কম ঝুঁকি", "Low risk"], moderate: ["মাঝারি ঝুঁকি", "Moderate risk"], high: ["বেশি ঝুঁকি", "High risk"] };
  function dcard(cls, ic, bn, en, tone) {
    var c = el("section", "aic-dc " + (cls || "")); if (tone) c.style.setProperty("--tone", tone);
    var h = el("h5"), i = el("span", "ic"); i.appendChild(icon(ic)); h.appendChild(i); h.appendChild(tt(bn, en)); c.appendChild(h); return c;
  }
  function bullets(c, items, ic) { var ul = el("ul"); items.forEach(function (t) { var li = el("li"); li.appendChild(icon(ic)); li.appendChild(el("span", null, t)); ul.appendChild(li); }); c.appendChild(ul); }
  function drawDiagnosis(p, file) {
    var wrap = el("div", "aic-dx");
    // 1. overview
    var top = el("section", "aic-dc aic-dx-top"), pic;
    if (file) { pic = el("img", "aic-dx-img"); pic.alt = "আপনার পাঠানো ছবি"; pic.src = URL.createObjectURL(file); }
    else { pic = el("div", "aic-dx-img"); pic.appendChild(icon("fa-image")); pic.appendChild(el("br")); pic.appendChild(tt("ছবি সংরক্ষণ করা হয় না", "Photos are not stored")); }
    top.appendChild(pic);
    var info = el("div"), k = el("p", "aic-kicker"); k.appendChild(tt("ছবি দেখে ফলাফল", "Photo check result")); info.appendChild(k);
    if (p.status === "not_plant" || p.status === "poor_image") {
      var h0 = el("h4"); h0.appendChild(tt(p.status === "not_plant" ? "ছবিটি কৃষি-সমস্যা দেখার উপযোগী নয়" : "আরও পরিষ্কার ছবি দরকার",
        p.status === "not_plant" ? "This photo is not suitable for a crop check" : "A clearer photo is needed")); info.appendChild(h0);
      info.appendChild(el("p", null, p.message));
      if (p.crop && p.crop.key) { var cf = el("div", "aic-facts"), f0 = el("span", "aic-fact"); f0.appendChild(icon("fa-seedling")); f0.appendChild(document.createTextNode(" " + p.crop.bn)); cf.appendChild(f0); info.appendChild(cf); }
      top.appendChild(info); wrap.appendChild(top);
      if (p.observed_symptoms && p.observed_symptoms.length) { var o0 = dcard("", "fa-eye", "ছবিতে যা দেখা যাচ্ছে", "Seen in the photo", "#1e6fb8"); bullets(o0, p.observed_symptoms, "fa-circle"); wrap.appendChild(o0); }
      var nx = dcard("", "fa-camera", "পরবর্তী পদক্ষেপ", "Next step", "#b8860b"); nx.appendChild(el("p", null, p.next_step)); wrap.appendChild(nx);
      return wrap;
    }
    var crop = el("div", "aic-facts"), fc = el("span", "aic-fact"); fc.appendChild(icon("fa-seedling"));
    fc.appendChild(tt(" ফসল: " + p.crop.bn + (p.crop.key && p.crop.en ? " (" + p.crop.en + ")" : ""), " Crop: " + (p.crop.key ? (p.crop.en || p.crop.bn) : p.crop.en)));
    crop.appendChild(fc);
    if (p.diagnosis) {
      var h1 = el("h4"); h1.appendChild(tt("সম্ভাব্য সমস্যা: " + p.diagnosis.bn, "Possible problem: " + (p.diagnosis.en || p.diagnosis.bn))); info.appendChild(h1);
      if (p.diagnosis.en) info.appendChild(el("span", "en lang-bn", p.diagnosis.en));
      var lv = p.diagnosis.confidence, fl = el("span", "aic-fact lvl-" + lv); fl.appendChild(icon("fa-gauge-simple"));
      fl.appendChild(tt(" এআই-এর অনুমান: " + LVL[lv][0], " AI's own guess: " + LVL[lv][1])); fl.title = "এটি শতাংশ নয়, শুধু এআই-এর নিজের অনুমান / Not a percentage, only the AI's own guess";
      crop.appendChild(fl);
      info.appendChild(crop);
      if (p.diagnosis.scientific_name) { var sc = el("p", "aic-sci"); sc.appendChild(tt("জীবাণু/কারণ (বৈজ্ঞানিক নাম): ", "Cause (scientific name): ")); sc.appendChild(el("i", null, p.diagnosis.scientific_name)); info.appendChild(sc); }
    } else {
      var h2 = el("h4"); h2.appendChild(tt("রোগ নিশ্চিতভাবে বলা যাচ্ছে না", "The problem is not clear")); info.appendChild(h2); info.appendChild(crop);
      if (p.message) info.appendChild(el("p", null, p.message));
      if (p.other_possibilities && p.other_possibilities.length) {
        var po = el("div", "aic-facts"); p.other_possibilities.forEach(function (o) { var f = el("span", "aic-fact"); f.appendChild(tt(o.bn, o.en || o.bn)); po.appendChild(f); }); info.appendChild(po);
      }
    }
    if (p.summary) info.appendChild(el("p", null, p.summary));
    top.appendChild(info); wrap.appendChild(top);
    // 2. symptoms (seen vs usual kept apart)
    if ((p.observed_symptoms || []).length || (p.typical_symptoms || []).length) {
      var s = dcard("", "fa-magnifying-glass", "কী কী লক্ষণ দেখা যাচ্ছে?", "What signs are there?", "#1e6fb8");
      if (p.observed_symptoms.length) { var s1 = el("p", "sub"); s1.appendChild(tt("এই ছবিতে দেখা যাচ্ছে", "Seen in this photo")); s.appendChild(s1); bullets(s, p.observed_symptoms, "fa-eye"); }
      if (p.typical_symptoms.length) { var s2 = el("p", "sub"); s2.appendChild(tt("এই সমস্যায় সাধারণত যা হয় (ছবিতে দেখা যায়নি)", "Usually seen with this problem (not seen in the photo)")); s.appendChild(s2); bullets(s, p.typical_symptoms, "fa-circle"); }
      wrap.appendChild(s);
    }
    // 3. causes
    if ((p.possible_causes || []).length) { var c3 = dcard("", "fa-circle-question", "কেন এই সমস্যা হতে পারে?", "Why may this happen?", "#b8860b"); bullets(c3, p.possible_causes, "fa-circle"); wrap.appendChild(c3); }
    // 4. what to do now (most visible)
    if ((p.immediate_actions || []).length) {
      var d4 = dcard("aic-do", "fa-list-check", "এখন আপনার করণীয়", "What to do now"), ol = el("ol");
      p.immediate_actions.forEach(function (t) { ol.appendChild(el("li", null, t)); }); d4.appendChild(ol); wrap.appendChild(d4);
    }
    // 5. prevention
    if ((p.prevention || []).length) { var c5 = dcard("", "fa-shield-halved", "ভবিষ্যতে রোগ প্রতিরোধের উপায়", "How to prevent it", "#2e7d32"); bullets(c5, p.prevention, "fa-check"); wrap.appendChild(c5); }
    // 6. risk + next step (risk only when the server allowed it)
    if (p.risk_level || p.next_step) {
      var c6 = dcard("", "fa-route", p.risk_level ? "ঝুঁকি ও পরবর্তী পদক্ষেপ" : "পরবর্তী পদক্ষেপ", p.risk_level ? "Risk and next step" : "Next step", "#d0661c");
      if (p.risk_level) {
        var rk = el("div", "aic-risk"), mt = el("span", "aic-meter " + p.risk_level); mt.appendChild(el("i")); mt.appendChild(el("i")); mt.appendChild(el("i"));
        rk.appendChild(mt); var rb = el("b"); rb.appendChild(tt(RISK[p.risk_level][0], RISK[p.risk_level][1])); rk.appendChild(rb);
        var rn = el("small", "aic-muted"); rn.appendChild(tt(" (এআই-এর অনুমান)", " (AI's estimate)")); rk.appendChild(rn); c6.appendChild(rk);
      }
      if (p.next_step) c6.appendChild(el("p", null, p.next_step));
      wrap.appendChild(c6);
    }
    (p.limitations || []).forEach(function (l) { var n = el("p", "aic-note"); n.appendChild(icon("fa-circle-info")); n.appendChild(el("span", null, l)); wrap.appendChild(n); });
    // 7. follow-up questions made from THIS diagnosis
    if ((p.follow_up_questions || []).length) {
      var c7 = dcard("", "fa-comments", "আরও জানতে চাইলে", "Ask more", "#6a4fb3"), fu = el("div", "aic-fu");
      p.follow_up_questions.forEach(function (q) {
        var b = el("button", "aic-chip", q); b.type = "button"; b.addEventListener("click", function () { if (!busy) send(q, null); }); fu.appendChild(b);
      });
      c7.appendChild(fu); wrap.appendChild(c7);
    }
    return wrap;
  }

  /* ============================================================ ask (real stream) */
  var areaSel = app.querySelector("[data-ai-area]"), areaKey = "cb_ai_area_" + A;
  if (areaSel) {
    try { var sv = localStorage.getItem(areaKey); if (sv && areaSel.querySelector('option[value="' + sv + '"]')) areaSel.value = sv; } catch (e) { /* ignore */ }
    areaSel.addEventListener("change", function () { try { localStorage.setItem(areaKey, areaSel.value); } catch (e) { /* ignore */ } });
  }
  function send(q, file) {
    if (busy) return;
    showWelcome(false); stopSpeaking(); say("");
    userRow(q, { file: file });
    run(q, file);
  }
  function run(q, file) {
    busy = true; sendBtn.disabled = true;
    var bot = new Bot(); bot.waiting(file); toBottom();
    var req, got = false, retry = function () { run(q, file); };
    if (IMAGES) {
      var fd = new FormData(); fd.append("question", q);
      if (areaSel && areaSel.value) fd.append("area", areaSel.value);
      if (file) fd.append("image", file, file.name || "photo.jpg");
      req = { method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": CSRF, "Accept": "application/x-ndjson" }, body: fd };
    } else {
      req = { method: "POST", credentials: "same-origin", body: JSON.stringify({ question: q }),
        headers: { "Content-Type": "application/json", "X-CSRF-Token": CSRF, "Accept": "application/x-ndjson" } };
    }
    fetch(ASK, req).then(function (res) {
      if (!res.ok) return res.json().catch(function () { return {}; }).then(function (j) { bot.fail(j.detail || "ai_error", retry); });
      var reader = res.body.getReader(), dec = new TextDecoder(), buf = "", failed = false;
      function handle(line) {
        if (!line.trim()) return;
        var ev; try { ev = JSON.parse(line); } catch (e) { return; }
        if (ev.t === "s") { got = true; bot.sentence(ev); }
        else if (ev.t === "card") { got = true; bot.card(ev); }
        else if (ev.t === "diagnosis") { got = true; bot.diagnosis(ev.data, file); }
        else if (ev.t === "done") {
          got = true; bot.done(ev);
          if (ev.conv_id && ev.conv_id !== CONV) { CONV = ev.conv_id; app.dataset.conv = CONV; }
          loadList();
        }
        else if (ev.t === "error") { failed = true; bot.fail(ev.code, retry); }
      }
      function pump() {
        return reader.read().then(function (r) {
          if (r.done) { handle(buf); if (!got && !failed) bot.fail("ai_error", retry); return; }
          buf += dec.decode(r.value, { stream: true });
          var parts = buf.split("\n"); buf = parts.pop(); parts.forEach(handle);
          return pump();
        });
      }
      return pump();
    }).catch(function () { bot.fail("net", retry); })
      .then(function () { busy = false; sendBtn.disabled = false; });
  }

  /* ============================================================ composer */
  var fileIn = app.querySelector("[data-ai-file]"), preview = app.querySelector("[data-ai-preview]");
  function pickedFile() { return fileIn && fileIn.files && fileIn.files[0] ? fileIn.files[0] : null; }
  function clearFile() { if (fileIn) fileIn.value = ""; if (preview) { preview.textContent = ""; preview.hidden = true; } }
  if (fileIn) fileIn.addEventListener("change", function () {
    var f = pickedFile(); preview.textContent = "";
    if (!f) { preview.hidden = true; return; }
    if (!/^image\//.test(f.type) || f.size > 10 * 1024 * 1024) { clearFile(); say("শুধু ছবি দিন (১০ MB-এর ছোট)।", "Please choose a photo under 10 MB.", true); return; }
    say("");
    var img = el("img"); img.alt = ""; img.src = URL.createObjectURL(f);
    var name = el("span"); name.appendChild(tt("ছবি তৈরি। চাইলে প্রশ্ন লিখে পাঠান।", "Photo ready. Add a question if you like, then send."));
    var x = el("button", "aic-ico"); x.type = "button"; x.setAttribute("aria-label", "ছবি সরান / Remove photo"); x.title = "ছবি সরান / Remove photo"; x.appendChild(icon("fa-xmark"));
    x.addEventListener("click", function () { clearFile(); box.focus(); });
    preview.appendChild(img); preview.appendChild(name); preview.appendChild(x); preview.hidden = false; box.focus();
  });
  function grow() { box.style.height = "auto"; box.style.height = Math.min(box.scrollHeight, 180) + "px"; }
  box.addEventListener("input", grow);
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var q = box.value.replace(/\s+/g, " ").trim(), file = IMAGES ? pickedFile() : null;
    if (busy) return;
    if (q.length < 2 && !file) { say("প্রশ্ন লিখুন বা ছবি দিন।", "Type a question or add a photo.", true); return; }
    box.value = ""; grow(); clearFile(); send(q, file);
  });
  box.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event("submit")); }
  });
  /* welcome cards + common questions do real things */
  if (welcome) {
    welcome.querySelectorAll(".aic-card").forEach(function (c) {
      c.addEventListener("click", function () {
        var act = c.dataset.act;
        if (act === "send" && c.dataset.q) { send(c.dataset.q, null); return; }
        if (c.dataset.fill) { box.value = c.dataset.fill; grow(); }
        if (act === "photo" && fileIn) { fileIn.click(); say("আক্রান্ত অংশের কাছ থেকে আলোতে তোলা পরিষ্কার ছবি দিন।", "Take a clear, close photo of the affected part in good light."); }
        box.focus(); if (c.dataset.fill) box.select();
      });
    });
    welcome.querySelectorAll(".aic-chip").forEach(function (c) { c.addEventListener("click", function () { send(c.dataset.q, null); }); });
  }

  /* ============================================================ voice in */
  var SR = window.SpeechRecognition || window.webkitSpeechRecognition, rec = null, listening = false;
  var mic = app.querySelector("[data-ai-mic]");
  mic.addEventListener("click", function () {
    if (!SR) { say("এই ব্রাউজারে কথা বলে লেখা যায় না। Chrome ব্যবহার করুন।", "Voice typing is not available in this browser. Use Chrome.", true); return; }
    if (listening) { rec.stop(); return; }
    stopSpeaking();
    rec = new SR(); rec.lang = "bn-BD"; rec.interimResults = true; rec.maxAlternatives = 1;
    var base = box.value ? box.value + " " : "";
    rec.onresult = function (e) { var t = ""; for (var i = 0; i < e.results.length; i++) t += e.results[i][0].transcript; box.value = (base + t).slice(0, 500); grow(); };
    rec.onerror = function (e) {
      var denied = e.error === "not-allowed" || e.error === "service-not-allowed";
      say(denied ? "মাইক্রোফোন ব্যবহারের অনুমতি দিন।" : "কথা বোঝা যায়নি, আবার বলুন।", denied ? "Please allow the microphone." : "Could not hear clearly, please try again.", true);
    };
    rec.onend = function () {
      listening = false; mic.classList.remove("listening"); mic.setAttribute("aria-pressed", "false");
      if (box.value.trim()) say("লেখাটা দেখে ঠিক থাকলে পাঠান চাপুন।", "Check the text, then press Send.");
    };
    listening = true; mic.classList.add("listening"); mic.setAttribute("aria-pressed", "true");
    say("বলুন… শেষ হলে আবার মাইক চাপুন।", "Speak… press the mic again when done.");
    try { rec.start(); } catch (e) { listening = false; mic.classList.remove("listening"); }
  });

  /* ============================================================ voice out */
  var synth = window.speechSynthesis, speaking = null;
  function bnVoice() { if (!synth) return null; return synth.getVoices().find(function (x) { return /^bn([-_]|$)/i.test(x.lang); }) || null; }
  if (synth && synth.onvoiceschanged !== undefined) synth.onvoiceschanged = function () {};
  function stopSpeaking() { if (synth) synth.cancel(); if (speaking) { speaking.reset(); speaking = null; } }
  window.addEventListener("pagehide", stopSpeaking);
  function speakerButton(getSentences) {
    var wrap = el("span"), play = el("button"), stop = el("button");
    play.type = stop.type = "button";
    var ic = icon("fa-volume-high"), label = el("span"); label.appendChild(tt("শুনুন", "Listen"));
    play.appendChild(ic); play.appendChild(label); play.setAttribute("aria-label", "শুনুন / Listen");
    stop.appendChild(icon("fa-stop")); stop.setAttribute("aria-label", "থামান / Stop"); stop.title = "থামান / Stop"; stop.hidden = true;
    var st = { idle: true, paused: false, i: 0 };
    function setLabel(bn, en, cls) { ic.className = "fa-solid " + cls; label.textContent = ""; label.appendChild(tt(bn, en)); }
    var ctl = { reset: function () { st.idle = true; st.paused = false; st.i = 0; setLabel("শুনুন", "Listen", "fa-volume-high"); stop.hidden = true; play.classList.remove("on"); } };
    function next(list, voice) {
      if (st.idle || st.i >= list.length) { ctl.reset(); speaking = null; return; }
      var u = new SpeechSynthesisUtterance(list[st.i]); u.lang = voice.lang || "bn-BD"; u.rate = 0.95;
      try { u.voice = voice; } catch (e) { /* lang alone still picks the Bangla voice */ }
      u.onend = function () { if (!st.idle && !st.paused) { st.i++; next(list, voice); } };
      u.onerror = function () { ctl.reset(); speaking = null; };
      synth.speak(u);
    }
    play.addEventListener("click", function () {
      if (!synth) { say("এই ব্রাউজারে পড়ে শোনানো যায় না।", "This browser cannot read aloud.", true); return; }
      var voice = bnVoice();
      if (!voice) { say("এই ডিভাইসে বাংলা কণ্ঠ নেই। Android-এ Chrome বা বাংলা ভয়েস চালু করা কম্পিউটারে চেষ্টা করুন।", "No Bangla voice on this device. Try Chrome on Android or install a Bangla voice.", true); return; }
      if (!st.idle && !st.paused) { synth.pause(); st.paused = true; setLabel("চালিয়ে যান", "Resume", "fa-play"); return; }
      if (st.paused) { synth.resume(); st.paused = false; setLabel("বিরতি", "Pause", "fa-pause"); return; }
      stopSpeaking();
      st.idle = false; st.i = 0; speaking = ctl; setLabel("বিরতি", "Pause", "fa-pause"); stop.hidden = false; play.classList.add("on");
      next(getSentences().filter(function (s) { return s && s.trim(); }), voice);
    });
    stop.addEventListener("click", stopSpeaking);
    wrap.appendChild(play); wrap.appendChild(stop); return wrap;
  }

  /* ============================================================ start: history of the open chat */
  var hist = [];
  try { hist = JSON.parse(document.getElementById("aiHistory").textContent || "[]"); } catch (e) { hist = []; }
  hist.forEach(function (m) {
    if (m.role === "user") { userRow(m.content === "ছবি পাঠানো হয়েছে" ? "" : m.content, { photo: m.kind === "photo", at: m.at }); return; }
    var b = new Bot(m.at);
    if (m.payload) { b.diagnosis(m.payload, null); b.sentences = (m.content || "").split("\n"); }
    else { (m.content || "").split("\n").forEach(function (line) { if (line.trim()) b.sentence({ part: "main", text: line.trim() }); }); }
    if (m.sources && m.sources.length) sourcesTo(b.bubble, m.sources);
    b.actions(m.id); b.body.appendChild(timeEl(m.at));
  });
  loadList();
  if (hist.length) toBottom();
  showWelcome(!hist.length);
  if (app.dataset.start) { send(app.dataset.start, null); history.replaceState(null, "", location.pathname); }
  else if (!mq.matches) box.focus();
})();
