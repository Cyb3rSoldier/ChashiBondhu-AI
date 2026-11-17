/* ChashiBondhu service worker (served at /sw.js).
   - static files: cache-first (works offline)
   - selected farmer pages: network-first, saved per account, used only when offline
   - order/earnings/complaint pages are NEVER saved (they hold customer or private data)
   - everything else: normal network; offline navigation shows a small offline page */
"use strict";
const SHELL = "cb-shell-v1";
const META = "cb-meta";
const SHELL_URLS = ["/static/cb.css?v=5", "/static/cb.js?v=3", "/static/farmer.js?v=2", "/static/offline.js?v=1",
                    "/static/upazila.js?v=1"];
const PAGE_RE = [/^\/farmer$/, /^\/farmer\/listings$/, /^\/farmer\/listings\/new$/, /^\/farmer\/forecasts$/,
                 /^\/farmer\/forecasts\/new$/, /^\/farmer\/forecasts\/\d+$/, /^\/farmer\/forecasts\/\d+\/edit$/,
                 /^\/farmer\/drafts$/];

const isPage = (path) => PAGE_RE.some((re) => re.test(path));

async function currentUser() {
  const m = await (await caches.open(META)).match("/__cb_user");
  return m ? (await m.text()) : "";
}

async function pageCache() {
  const u = await currentUser();
  return u ? caches.open("cb-pages-" + u) : null;
}

async function clearPages() {
  for (const name of await caches.keys()) if (name.startsWith("cb-pages-")) await caches.delete(name);
  await caches.delete(META);
}

function offlinePage() {
  const html = `<!doctype html><html lang="bn"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ইন্টারনেট নেই</title><body style="font-family:system-ui,sans-serif;padding:24px;line-height:1.6;background:#EEF4E6;color:#1D2B1A">
<h1>ইন্টারনেট নেই / You are offline</h1>
<p>এই পাতাটি ফোনে রাখা নেই। ইন্টারনেট ফিরলে আবার চেষ্টা করুন।<br>This page is not saved on this phone. Please try again when internet returns.</p>
<p><a href="/farmer/drafts" style="color:#2E7A33;font-weight:700">ফোনে রাখা খসড়া / Saved on phone</a></p></body></html>`;
  return new Response(html, { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } });
}

async function savePage(path, response) {
  const ct = response.headers.get("content-type") || "";
  if (!response.ok || response.redirected || response.type !== "basic" || !ct.includes("text/html")) return;
  const cache = await pageCache();
  if (cache) await cache.put(path, response);
}

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_URLS)).catch(() => undefined));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const name of await caches.keys()) if (name.startsWith("cb-shell-") && name !== SHELL) await caches.delete(name);
    await self.clients.claim();
  })());
});

self.addEventListener("message", (e) => {
  const msg = e.data || {};
  if (msg.type === "user" && /^\d+$/.test(String(msg.user))) {
    e.waitUntil((async () => {
      const before = await currentUser();
      if (before && before !== String(msg.user)) await clearPages();      // another account on this phone
      await (await caches.open(META)).put("/__cb_user", new Response(String(msg.user)));
    })());
  } else if (msg.type === "warm" && Array.isArray(msg.urls)) {
    e.waitUntil(Promise.all(msg.urls.filter(isPage).map((p) =>
      fetch(p, { credentials: "same-origin", cache: "no-store" }).then((r) => savePage(p, r)).catch(() => undefined))));
  } else if (msg.type === "clear") {
    e.waitUntil(clearPages());
  }
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/static/")) {
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((r) => {
      if (r.ok) { const copy = r.clone(); caches.open(SHELL).then((c) => c.put(req, copy)); }
      return r;
    })));
    return;
  }
  if (isPage(url.pathname)) {
    e.respondWith(fetch(req).then((r) => { savePage(url.pathname, r.clone()); return r; }).catch(async () => {
      const cache = await pageCache();
      const hit = cache ? await cache.match(url.pathname) : null;
      return hit || offlinePage();
    }));
    return;
  }
  if (req.mode === "navigate") e.respondWith(fetch(req).catch(() => offlinePage()));
});
