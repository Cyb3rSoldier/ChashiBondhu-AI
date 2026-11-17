/**
 * layout.js — injects the shared header and footer.
 * Page needs: <div id="site-header"></div> and <div id="site-footer"></div>
 * <body data-header="overlay"> = transparent header over a hero (turns solid on scroll).
 */
(function () {
  const ICON = {
    logo: `<svg viewBox="0 0 32 32" class="h-6 w-6" aria-hidden="true"><path fill="#15803d" d="M16 29c-1-6-4-9-9-11 1-6 5-10 9-11v22z"/><path fill="#4ade80" d="M16 29c1-6 4-9 9-11-1-6-5-10-9-11v22z"/><path fill="#14532d" d="M15 7h2v22h-2z"/></svg>`,
    chevron: `<svg viewBox="0 0 20 20" class="h-4 w-4" fill="currentColor" aria-hidden="true"><path d="M5.2 7.2a.75.75 0 0 1 1.06 0L10 10.94l3.74-3.74a.75.75 0 1 1 1.06 1.06l-4.27 4.27a.75.75 0 0 1-1.06 0L5.2 8.26a.75.75 0 0 1 0-1.06z"/></svg>`,
    user: `<svg viewBox="0 0 24 24" class="h-5 w-5" fill="currentColor" aria-hidden="true"><path d="M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zm0 2c-4.4 0-8 2.2-8 5v2h16v-2c0-2.8-3.6-5-8-5z"/></svg>`,
    sprout: `<svg viewBox="0 0 24 24" class="h-5 w-5" fill="currentColor" aria-hidden="true"><path d="M12 22v-8c0-3-2-6-7-6 0 4 2 6 6 6M12 14c0-3 2-6 7-6 0 4-2 6-6 6" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round"/></svg>`,
    wrench: `<svg viewBox="0 0 24 24" class="h-5 w-5" fill="currentColor" aria-hidden="true"><path d="M21.7 6.3a5.5 5.5 0 0 1-7.2 6.8L6 21.6a2 2 0 1 1-2.8-2.8l8.5-8.5a5.5 5.5 0 0 1 6.8-7.2l-3.3 3.3.6 2.8 2.8.6 3.1-3.5z"/></svg>`,
    shield: `<svg viewBox="0 0 24 24" class="h-5 w-5" fill="currentColor" aria-hidden="true"><path d="M12 2 4 5v6c0 5 3.4 9.6 8 11 4.6-1.4 8-6 8-11V5l-8-3zm-1 14-4-4 1.4-1.4L11 13.2l4.6-4.6L17 10l-6 6z"/></svg>`,
    sun: `<svg viewBox="0 0 24 24" class="h-5 w-5 hidden dark:block" fill="currentColor" aria-hidden="true"><path d="M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0-5 1 3h-2l1-3zm0 20-1-3h2l-1 3zM2 12l3-1v2l-3-1zm20 0-3 1v-2l3 1zM4.9 4.9l2.8 1.4-1.4 1.4-1.4-2.8zm14.2 14.2-2.8-1.4 1.4-1.4 1.4 2.8zM4.9 19.1l1.4-2.8 1.4 1.4-2.8 1.4zM19.1 4.9l-1.4 2.8-1.4-1.4 2.8-1.4z"/></svg>`,
    moon: `<svg viewBox="0 0 24 24" class="h-5 w-5 dark:hidden" fill="currentColor" aria-hidden="true"><path d="M20 15.5A8.5 8.5 0 0 1 8.5 4a8.5 8.5 0 1 0 11.5 11.5z"/></svg>`,
    menu: `<svg viewBox="0 0 24 24" class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" stroke-linecap="round"/></svg>`,
  };

  const loginItems = () => `
    <a class="cb-item" role="menuitem" href="login.html?role=consumer"><span class="text-leaf-600">${ICON.user}</span><span data-i18n="login_consumer"></span></a>
    <a class="cb-item" role="menuitem" href="login.html?role=farmer"><span class="text-leaf-600">${ICON.sprout}</span><span data-i18n="login_farmer"></span></a>
    <a class="cb-item" role="menuitem" href="login.html?role=vendor"><span class="text-soil-500">${ICON.wrench}</span><span data-i18n="login_vendor"></span></a>
    <a class="cb-item" role="menuitem" href="login.html?role=admin"><span class="text-slate-500 dark:text-slate-300">${ICON.shield}</span><span data-i18n="login_admin"></span></a>
    <div class="mx-2 my-2 border-t border-line"></div>
    <p class="px-3 pb-2 text-sm text-muted" data-i18n="no_account"></p>
    <div class="grid grid-cols-3 gap-2 px-2 pb-1">
      <a href="login.html?role=consumer&mode=register" class="rounded-lg bg-leaf-500 px-2 py-2 text-center text-sm font-semibold text-white hover:bg-leaf-600" data-i18n="role_consumer"></a>
      <a href="login.html?role=farmer&mode=register" class="rounded-lg bg-leaf-500 px-2 py-2 text-center text-sm font-semibold text-white hover:bg-leaf-600" data-i18n="role_farmer"></a>
      <a href="login.html?role=vendor&mode=register" class="rounded-lg bg-soil-500 px-2 py-2 text-center text-sm font-semibold text-white hover:bg-soil-600" data-i18n="role_vendor"></a>
    </div>`;

  function headerHTML() {
    return `
<header id="cb-header" class="fixed inset-x-0 top-0 z-50">
  <div class="mx-auto flex h-16 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6 lg:h-20">
    <a href="index.html" class="flex shrink-0 items-center gap-3">
      <span class="grid h-10 w-10 place-items-center rounded-xl bg-white shadow">${ICON.logo}</span>
      <span class="font-brand text-xl font-bold text-white sm:text-2xl" data-i18n="brand"></span>
    </a>

    <nav class="hidden items-center gap-1 lg:flex" aria-label="Main">
      <a href="index.html#top" class="cb-navlink" data-i18n="nav_home"></a>
      <div class="relative" data-dropdown>
        <button type="button" class="cb-navlink inline-flex items-center gap-1" aria-expanded="false" aria-haspopup="true">
          <span data-i18n="nav_market"></span>${ICON.chevron}
        </button>
        <div class="cb-menu cb-menu-left hidden" role="menu">
          <a class="cb-item" role="menuitem" href="index.html#produce"><span class="text-leaf-600">${ICON.sprout}</span><span data-i18n="nav_produce"></span></a>
          <a class="cb-item" role="menuitem" href="index.html#tools"><span class="text-soil-500">${ICON.wrench}</span><span data-i18n="nav_tools"></span></a>
        </div>
      </div>
      <a href="index.html#about" class="cb-navlink" data-i18n="nav_about"></a>
      <a href="index.html#contact" class="cb-navlink" data-i18n="nav_contact"></a>
      <div class="relative" data-dropdown>
        <button type="button" class="cb-navlink inline-flex items-center gap-1" aria-expanded="false" aria-haspopup="true">
          <span data-i18n="nav_login"></span>${ICON.chevron}
        </button>
        <div class="cb-menu hidden" role="menu">${loginItems()}</div>
      </div>
    </nav>

    <div class="flex items-center gap-2">
      <button type="button" class="cb-iconbtn text-sm" data-action="lang" data-i18n-aria="toggle_lang_aria"><span data-i18n="toggle_lang"></span></button>
      <button type="button" class="cb-iconbtn" data-action="theme" data-i18n-aria="toggle_theme_aria">${ICON.moon}${ICON.sun}</button>
      <button type="button" class="cb-iconbtn lg:hidden" data-action="menu" aria-expanded="false" aria-controls="cb-mobile" data-i18n-aria="menu_aria">${ICON.menu}</button>
    </div>
  </div>

  <div id="cb-mobile" class="hidden border-t border-white/10 bg-leaf-800 px-4 pb-5 pt-2 lg:hidden dark:bg-leaf-900">
    <nav class="grid gap-1" aria-label="Mobile">
      <a href="index.html#top" class="cb-navlink" data-i18n="nav_home"></a>
      <a href="index.html#produce" class="cb-navlink" data-i18n="nav_produce"></a>
      <a href="index.html#tools" class="cb-navlink" data-i18n="nav_tools"></a>
      <a href="index.html#about" class="cb-navlink" data-i18n="nav_about"></a>
      <a href="index.html#contact" class="cb-navlink" data-i18n="nav_contact"></a>
    </nav>
    <div class="cb-menu !static mt-3 !min-w-0 !shadow-none">${loginItems()}</div>
  </div>
</header>`;
  }

  function footerHTML() {
    const link = (href, key) => `<li><a href="${href}" class="hover:text-white" data-i18n="${key}"></a></li>`;
    return `
<footer class="bg-leaf-900 text-leaf-100/80 dark:bg-[#08140d]">
  <div class="mx-auto grid max-w-7xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-2 lg:grid-cols-4">
    <div id="about">
      <a href="index.html" class="flex items-center gap-3">
        <span class="grid h-10 w-10 place-items-center rounded-xl bg-white">${ICON.logo}</span>
        <span class="font-brand text-xl font-bold text-white" data-i18n="brand"></span>
      </a>
      <p class="mt-4 max-w-xs" data-i18n="footer_about"></p>
      <p class="mt-3 max-w-xs text-sm text-leaf-300" data-i18n="tagline"></p>
    </div>
    <div>
      <h2 class="font-bold text-white" data-i18n="footer_quick"></h2>
      <ul class="mt-4 grid gap-2">
        ${link("index.html#top", "nav_home")}${link("index.html#produce", "nav_produce")}
        ${link("index.html#tools", "nav_tools")}${link("#", "privacy")}
      </ul>
    </div>
    <div>
      <h2 class="font-bold text-white" data-i18n="footer_users"></h2>
      <ul class="mt-4 grid gap-2">
        ${link("login.html?role=consumer", "login_consumer")}${link("login.html?role=farmer", "login_farmer")}
        ${link("login.html?role=vendor", "login_vendor")}${link("#", "support")}
      </ul>
    </div>
    <div id="contact">
      <h2 class="font-bold text-white" data-i18n="footer_contact"></h2>
      <ul class="mt-4 grid gap-2">
        <li data-i18n="address"></li>
        <li><a href="tel:+8801835314263" class="hover:text-white">+880 1835-314263</a></li>
        <li><a href="mailto:hello@chashibondhu.com" class="hover:text-white">hello@chashibondhu.com</a></li>
      </ul>
    </div>
  </div>
  <div class="border-t border-white/10">
    <div class="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-5 text-sm sm:flex-row sm:justify-between sm:px-6">
      <p data-i18n="rights"></p><p data-i18n="made_with"></p>
    </div>
  </div>
</footer>`;
  }

  function closeAllDropdowns(except) {
    document.querySelectorAll("[data-dropdown]").forEach((dd) => {
      if (dd === except) return;
      dd.querySelector(".cb-menu").classList.add("hidden");
      dd.querySelector("button").setAttribute("aria-expanded", "false");
    });
  }

  function wire() {
    const header = document.getElementById("cb-header");
    const overlay = document.body.dataset.header === "overlay";
    const mobile = document.getElementById("cb-mobile");

    const updateHeader = () => {
      const solid = !overlay || window.scrollY > 40 || !mobile.classList.contains("hidden");
      header.classList.toggle("cb-solid", solid);
      header.classList.toggle("cb-overlay", !solid);
    };
    updateHeader();
    window.addEventListener("scroll", updateHeader, { passive: true });

    document.querySelectorAll("[data-dropdown]").forEach((dd) => {
      const btn = dd.querySelector("button");
      const menu = dd.querySelector(".cb-menu");
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const open = menu.classList.contains("hidden");
        closeAllDropdowns(dd);
        menu.classList.toggle("hidden", !open);
        btn.setAttribute("aria-expanded", String(open));
      });
    });
    document.addEventListener("click", () => closeAllDropdowns());
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAllDropdowns(); });

    header.querySelector('[data-action="lang"]').addEventListener("click", () => {
      window.CB.setLang(window.CB.getLang() === "bn" ? "en" : "bn");
    });
    header.querySelector('[data-action="theme"]').addEventListener("click", () => {
      const dark = !document.documentElement.classList.contains("dark");
      document.documentElement.classList.toggle("dark", dark);
      try { localStorage.setItem("cb_theme", dark ? "dark" : "light"); } catch (e) { /* ignore */ }
    });
    const menuBtn = header.querySelector('[data-action="menu"]');
    menuBtn.addEventListener("click", () => {
      const open = mobile.classList.contains("hidden");
      mobile.classList.toggle("hidden", !open);
      menuBtn.setAttribute("aria-expanded", String(open));
      updateHeader();
    });
    mobile.querySelectorAll("a").forEach((a) => a.addEventListener("click", () => {
      mobile.classList.add("hidden"); menuBtn.setAttribute("aria-expanded", "false"); updateHeader();
    }));
  }

  document.addEventListener("DOMContentLoaded", () => {
    const h = document.getElementById("site-header");
    const f = document.getElementById("site-footer");
    if (h) h.outerHTML = headerHTML();
    if (f) f.outerHTML = footerHTML();
    if (document.getElementById("cb-header")) wire();
    window.CB.applyI18n();
  });
})();
