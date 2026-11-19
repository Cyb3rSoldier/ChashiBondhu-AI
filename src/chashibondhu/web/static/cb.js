/* ChashiBondhu shared page script: language + theme switches, mobile menu, toast. */
(function () {
  "use strict";
  var root = document.documentElement;
  function save(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }

  function syncPlaceholders() {
    var lang = root.getAttribute("data-lang") || "bn";
    document.querySelectorAll("[data-ph-bn]").forEach(function (el) {
      el.setAttribute("placeholder", lang === "en" ? el.getAttribute("data-ph-en") : el.getAttribute("data-ph-bn"));
    });
  }
  function syncThemeIcon() {
    var dark = root.getAttribute("data-theme") === "dark";
    document.querySelectorAll("[data-cb-theme-icon]").forEach(function (i) {
      i.className = dark ? "fa-solid fa-sun" : "fa-solid fa-moon";
    });
  }

  window.cbLang = function () { return root.getAttribute("data-lang") === "en" ? "en" : "bn"; };
  window.cbNum = function (n) {
    var s = String(n);
    return window.cbLang() === "bn" ? s.replace(/[0-9]/g, function (d) { return "০১২৩৪৫৬৭৮৯"[d]; }) : s;
  };
  window.cbToast = function (msg, bad) {
    var t = document.createElement("div");
    t.className = "cb-toast" + (bad ? " bad" : "");
    t.setAttribute("role", "status");
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 2600);
  };

  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-cb-lang]");
    if (b) {
      var next = window.cbLang() === "bn" ? "en" : "bn";
      root.setAttribute("data-lang", next); root.setAttribute("lang", next); save("cb_lang", next);
      syncPlaceholders();
      document.dispatchEvent(new CustomEvent("cb:lang", { detail: next }));
      return;
    }
    if (e.target.closest("[data-cb-theme]")) {
      var t = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", t); save("cb_theme", t); syncThemeIcon();
      return;
    }
    var burger = e.target.closest("[data-cb-burger]");
    if (burger) {
      var d = document.getElementById("cbDrawer");
      var open = d.classList.toggle("open");
      burger.setAttribute("aria-expanded", String(open));
      burger.querySelector("i").className = open ? "fa-solid fa-xmark" : "fa-solid fa-bars";
      return;
    }
    // close open dropdown menus when clicking elsewhere
    document.querySelectorAll("details.cb-menu[open]").forEach(function (m) {
      if (!m.contains(e.target)) m.removeAttribute("open");
    });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    document.querySelectorAll("details.cb-menu[open]").forEach(function (m) { m.removeAttribute("open"); });
    var d = document.getElementById("cbDrawer");
    if (d && d.classList.contains("open")) document.querySelector("[data-cb-burger]").click();
  });

  // home page: header is see-through over the photo, solid after scrolling or when the menu is open
  var nav = document.querySelector("[data-cb-nav]");
  if (nav && document.body.classList.contains("cb-home")) {
    var drawer = document.getElementById("cbDrawer");
    var syncNav = function () {
      var top = window.scrollY < 40 && !(drawer && drawer.classList.contains("open"));
      nav.classList.toggle("is-top", top);
    };
    window.addEventListener("scroll", syncNav, { passive: true });
    document.addEventListener("click", function () { setTimeout(syncNav, 0); });
    syncNav();
  }

  syncPlaceholders();
  syncThemeIcon();
})();


/* ---------- v4 extras: scroll reveal, counters, progress bar, back-to-top, footer year ---------- */
(function () {
  "use strict";
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  // reveal on scroll
  var items = document.querySelectorAll(".cb-reveal");
  if (items.length) {
    if ("IntersectionObserver" in window && !reduce) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add("is-in"); io.unobserve(en.target); } });
      }, { threshold: 0.12, rootMargin: "0px 0px -6% 0px" });
      items.forEach(function (el) { io.observe(el); });
    } else { items.forEach(function (el) { el.classList.add("is-in"); }); }
  }

  // count-up numbers: <b data-count="123">১২৩</b>; the original text is put back at the end
  document.querySelectorAll("[data-count]").forEach(function (el) {
    var target = parseInt(el.getAttribute("data-count"), 10), original = el.textContent;
    if (isNaN(target) || target < 1 || reduce || !("IntersectionObserver" in window)) return;
    var done = false;
    var obs = new IntersectionObserver(function (en) {
      if (!en[0].isIntersecting || done) return;
      done = true; obs.disconnect();
      var t0 = null, dur = 900;
      function tick(ts) {
        if (t0 === null) t0 = ts;
        var k = Math.min((ts - t0) / dur, 1), eased = 1 - Math.pow(1 - k, 3);
        el.textContent = window.cbNum(Math.round(target * eased));
        if (k < 1) requestAnimationFrame(tick); else el.textContent = original;
      }
      requestAnimationFrame(tick);
    }, { threshold: 0.4 });
    obs.observe(el);
  });

  // progress bar + back-to-top
  var bar = document.querySelector("[data-cb-progress]"), top = document.querySelector("[data-cb-top]"), ticking = false;
  function onScroll() {
    var h = document.documentElement, max = h.scrollHeight - h.clientHeight, y = window.scrollY || h.scrollTop;
    if (bar) bar.style.width = (max > 0 ? Math.min(100, (y / max) * 100) : 0) + "%";
    if (top) top.hidden = y < 600;
    ticking = false;
  }
  window.addEventListener("scroll", function () { if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } }, { passive: true });
  if (top) top.addEventListener("click", function () { window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" }); });
  onScroll();

  // footer year (follows the language digits)
  function year() { document.querySelectorAll("[data-year]").forEach(function (el) { el.textContent = window.cbNum(new Date().getFullYear()); }); }
  year(); document.addEventListener("cb:lang", year);
})();
