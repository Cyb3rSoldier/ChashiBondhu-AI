/**
 * home.js — renders cards and filters on index.html.
 * Data source today: CB.DEMO (sample). Later: replace loadProducts()/loadTools() with fetch() to your API.
 */
(function () {
  const { t, esc, pick, fmtNum } = window.CB;

  const PRODUCE_CATS = ["all", "vegetables", "fruits", "grains", "dairy_eggs", "spices", "organic"];
  const TOOL_CATS = ["all", "hand", "harvest", "irrigation", "plow", "protect", "seeder", "spare", "sprayer", "tractor"];

  const state = {
    produce: { q: "", min: null, max: null, district: "", cat: "all" },
    tools: { q: "", min: null, max: null, brand: "", cat: "all" },
  };

  // ---------- data (swap these for API calls later) ----------
  async function loadProducts() { return window.CB.DEMO.PRODUCTS; }
  async function loadTools() { return window.CB.DEMO.TOOLS; }
  let PRODUCTS = [], TOOLS = [];

  // ---------- helpers ----------
  const taka = (n) => `৳${fmtNum(n)}`;
  const toNumber = (v) => {
    const s = String(v ?? "").trim().replace(/[০-৯]/g, (d) => "০১২৩৪৫৬৭৮৯".indexOf(d));
    if (s === "") return null;
    const n = Number(s);
    return Number.isFinite(n) && n >= 0 ? n : null;
  };
  const matchText = (item, q) => {
    if (!q) return true;
    const hay = `${item.name.bn} ${item.name.en} ${item.brand || ""}`.toLowerCase();
    return hay.includes(q.toLowerCase());
  };
  const inRange = (price, min, max) => (min == null || price >= min) && (max == null || price <= max);

  function placeholderTile(name, tone) {
    const first = Array.from(name.trim())[0] || "•";
    const bg = tone === "soil" ? "bg-soil-50 text-soil-500 dark:bg-soil-800/30 dark:text-soil-300" : "bg-leaf-50 text-leaf-500 dark:bg-leaf-900/60 dark:text-leaf-400";
    return `<div class="grid h-full w-full place-items-center ${bg}"><span class="font-brand text-6xl font-bold opacity-70" aria-hidden="true">${esc(first)}</span></div>`;
  }
  function imageBlock(item, tone) {
    const name = pick(item.name);
    if (!item.img) return placeholderTile(name, tone);
    return `<img src="${esc(item.img)}" alt="${esc(name)}" loading="lazy" class="h-full w-full object-cover"
      onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'h-full w-full bg-leaf-50'}))">`;
  }
  function emptyState() {
    return `<div class="col-span-full rounded-2xl border border-dashed border-line bg-surface p-10 text-center">
      <p class="text-lg font-semibold">${esc(t("empty_title"))}</p>
      <p class="mt-1 text-muted">${esc(t("empty_sub"))}</p></div>`;
  }

  // ---------- chips ----------
  function renderChips(el, cats, prefix, active, tone, onPick) {
    const on = tone === "soil" ? "bg-soil-500 text-white border-soil-500" : "bg-leaf-600 text-white border-leaf-600";
    const off = tone === "soil" ? "text-soil-600 dark:text-soil-300 hover:bg-soil-50 dark:hover:bg-soil-800/30" : "text-leaf-700 dark:text-leaf-300 hover:bg-leaf-50 dark:hover:bg-leaf-900/50";
    el.innerHTML = cats.map((c) => `
      <button type="button" class="cb-chip ${c === active ? on : off}" aria-pressed="${c === active}" data-cat="${c}">
        ${esc(t(prefix + c))}</button>`).join("");
    el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => onPick(b.dataset.cat)));
  }

  // ---------- produce ----------
  function productCard(p) {
    const name = pick(p.name);
    const save = p.oldPrice && p.oldPrice > p.price ? Math.round((1 - p.price / p.oldPrice) * 100) : 0;
    const leftBadge = save ? `<span class="rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-bold text-red-700">${esc(t("badge_sale"))}</span>`
      : p.isNew ? `<span class="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-bold text-blue-700">${esc(t("badge_new"))}</span>` : "";
    const organic = p.organic ? `<span title="${esc(t("organic_note"))}" class="rounded-full bg-leaf-100 px-2.5 py-0.5 text-xs font-bold text-leaf-700">${esc(t("badge_organic"))}</span>` : "";
    return `
<article class="flex flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-sm">
  <div class="relative aspect-[4/3]">${imageBlock(p, "leaf")}
    <div class="absolute inset-x-3 top-3 flex justify-between gap-2"><span>${leftBadge}</span><span>${organic}</span></div>
  </div>
  <div class="flex flex-1 flex-col p-4">
    <h3 class="text-lg font-semibold">${esc(name)}</h3>
    <p class="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <span class="text-xl font-bold text-leaf-600 dark:text-leaf-400">${taka(p.price)}</span>
      <span class="text-sm text-muted">/ ${esc(t("unit_" + p.unit))}</span>
      ${save ? `<s class="text-sm text-muted">${taka(p.oldPrice)}</s><span class="rounded bg-red-100 px-1.5 text-xs font-bold text-red-700">${esc(t("save_pct", { n: fmtNum(save) }))}</span>` : ""}
    </p>
    <p class="mt-3 text-sm text-muted">${esc(pick(p.farmer))}</p>
    <p class="text-sm text-muted">${esc(window.CB.districtName(p.district))}</p>
    <div class="mt-auto grid gap-2 pt-4">
      <a href="login.html?role=consumer" class="rounded-xl bg-leaf-500 py-2.5 text-center font-semibold text-white hover:bg-leaf-600">${esc(t("msg_farmer"))}</a>
      <a href="login.html?role=consumer" class="rounded-xl border border-leaf-500 py-2.5 text-center font-semibold text-leaf-700 hover:bg-leaf-50 dark:text-leaf-300 dark:hover:bg-leaf-900/50">${esc(t("login_to_buy"))}</a>
    </div>
  </div>
</article>`;
  }

  function renderProduce() {
    const s = state.produce;
    const list = PRODUCTS.filter((p) =>
      matchText(p, s.q) && inRange(p.price, s.min, s.max) &&
      (!s.district || p.district === s.district) &&
      (s.cat === "all" || (s.cat === "organic" ? p.organic : p.category === s.cat)));
    document.getElementById("produce-grid").innerHTML = list.length ? list.map(productCard).join("") : emptyState();
    document.getElementById("produce-count").textContent = t("results_count", { n: fmtNum(list.length) });
    renderChips(document.getElementById("produce-chips"), PRODUCE_CATS, "cat_", s.cat, "leaf", (c) => { s.cat = c; renderProduce(); });
  }

  // ---------- tools ----------
  function toolCard(x) {
    const name = pick(x.name);
    return `
<article class="flex flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-sm">
  <div class="relative aspect-[4/3]">${imageBlock(x, "soil")}
    ${x.isNew ? `<span class="absolute right-3 top-3 rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-bold text-blue-700">${esc(t("badge_new"))}</span>` : ""}
  </div>
  <div class="flex flex-1 flex-col p-4">
    <h3 class="text-lg font-semibold">${esc(name)}</h3>
    <p class="mt-1 text-sm text-muted">${esc(x.brand)}</p>
    <p class="mt-2 flex items-baseline gap-2"><span class="text-xl font-bold text-soil-600 dark:text-soil-300">${taka(x.price)}</span>
      <span class="text-sm text-muted">/ ${esc(t("unit_" + x.unit))}</span></p>
    <p class="mt-3 text-sm text-muted">${esc(pick(x.vendor))}</p>
    <p class="text-sm text-muted">${esc(window.CB.districtName(x.district))}</p>
    <div class="mt-auto pt-4">
      <a href="#" class="block rounded-xl border border-soil-500 py-2.5 text-center font-semibold text-soil-600 hover:bg-soil-50 dark:text-soil-300 dark:hover:bg-soil-800/30">${esc(t("view_details"))}</a>
    </div>
  </div>
</article>`;
  }

  function renderTools() {
    const s = state.tools;
    const list = TOOLS.filter((x) =>
      matchText(x, s.q) && inRange(x.price, s.min, s.max) &&
      (!s.brand || x.brand.toLowerCase().includes(s.brand.toLowerCase())) &&
      (s.cat === "all" || x.category === s.cat));
    document.getElementById("tools-grid").innerHTML = list.length ? list.map(toolCard).join("") : emptyState();
    document.getElementById("tools-count").textContent = t("results_count", { n: fmtNum(list.length) });
    renderChips(document.getElementById("tools-chips"), TOOL_CATS, "tcat_", s.cat, "soil", (c) => { s.cat = c; renderTools(); });
  }

  // ---------- videos + tips ----------
  function renderVideos() {
    document.getElementById("video-grid").innerHTML = window.CB.DEMO.VIDEOS.map((v) => {
      const title = esc(pick(v.title));
      const thumb = v.youtubeId
        ? `<img src="https://i.ytimg.com/vi/${encodeURIComponent(v.youtubeId)}/hqdefault.jpg" alt="" loading="lazy" class="h-full w-full object-cover">`
        : `<div class="grid h-full w-full place-items-center bg-gradient-to-br from-leaf-600 to-leaf-900 text-white">
             <div class="text-center"><svg viewBox="0 0 24 24" class="mx-auto h-12 w-12 opacity-90" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>
             <p class="mt-2 text-sm opacity-80">${esc(t("video_soon"))}</p></div></div>`;
      const href = v.youtubeId ? `https://www.youtube.com/watch?v=${encodeURIComponent(v.youtubeId)}` : "#videos";
      return `<a href="${href}" ${v.youtubeId ? 'target="_blank" rel="noopener"' : ""} class="overflow-hidden rounded-2xl border border-line bg-surface shadow-sm">
        <div class="aspect-video">${thumb}</div><p class="p-4 font-semibold">${title}</p></a>`;
    }).join("");
  }

  const TAG_TONE = {
    leaf: "bg-leaf-600", sky: "bg-sky-600", rose: "bg-rose-600", amber: "bg-amber-600",
  };
  function renderTips() {
    document.getElementById("tips-grid").innerHTML = window.CB.DEMO.TIPS.map((b) => `
      <article class="flex flex-col rounded-2xl border border-line bg-surface p-5 shadow-sm">
        <span class="self-start rounded-full px-3 py-1 text-xs font-bold text-white ${TAG_TONE[b.color] || TAG_TONE.leaf}">${esc(pick(b.tag))}</span>
        <h3 class="mt-4 text-lg font-bold">${esc(pick(b.title))}</h3>
        <p class="mt-2 text-muted">${esc(pick(b.body))}</p>
      </article>`).join("");
  }

  // ---------- wiring ----------
  function wireFilters() {
    const $ = (id) => document.getElementById(id);
    let timer;
    $("produce-search").addEventListener("input", (e) => { clearTimeout(timer); timer = setTimeout(() => { state.produce.q = e.target.value.trim(); renderProduce(); }, 200); });
    $("produce-apply").addEventListener("click", () => {
      state.produce.min = toNumber($("produce-min").value); state.produce.max = toNumber($("produce-max").value);
      state.produce.district = $("produce-district").value; renderProduce();
    });
    $("produce-reset").addEventListener("click", () => {
      ["produce-search", "produce-min", "produce-max", "produce-district"].forEach((id) => { $(id).value = ""; });
      state.produce = { q: "", min: null, max: null, district: "", cat: "all" }; renderProduce();
    });

    $("tools-search").addEventListener("input", (e) => { clearTimeout(timer); timer = setTimeout(() => { state.tools.q = e.target.value.trim(); renderTools(); }, 200); });
    $("tools-apply").addEventListener("click", () => {
      state.tools.min = toNumber($("tools-min").value); state.tools.max = toNumber($("tools-max").value);
      state.tools.brand = $("tools-brand").value.trim(); renderTools();
    });
    $("tools-reset").addEventListener("click", () => {
      ["tools-search", "tools-min", "tools-max", "tools-brand"].forEach((id) => { $(id).value = ""; });
      state.tools = { q: "", min: null, max: null, brand: "", cat: "all" }; renderTools();
    });
  }

  function renderAll() {
    window.CB.fillDistrictSelect(document.getElementById("produce-district"), "district_all");
    renderProduce(); renderTools(); renderVideos(); renderTips();
    document.getElementById("demo-notice").classList.toggle("hidden", !window.CB_CONFIG.showDemoNotice);
  }

  document.addEventListener("DOMContentLoaded", async () => {
    try {
      [PRODUCTS, TOOLS] = await Promise.all([loadProducts(), loadTools()]);
    } catch (err) {
      console.error("Could not load listings:", err);
      PRODUCTS = []; TOOLS = [];
    }
    wireFilters();
    renderAll();
  });
  document.addEventListener("cb:langchange", renderAll);
})();
