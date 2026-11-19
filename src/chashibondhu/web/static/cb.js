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
