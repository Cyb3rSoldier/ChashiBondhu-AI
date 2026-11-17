/* ChashiBondhu farmer pages: weather card, area names, product preview, delete/cancel confirm.
   Uses only the browser + our own API, except the weather card, which calls Open-Meteo
   (free, no key, CORS allowed). The location is rounded and kept only on this phone. */
(function () {
  "use strict";
  var bn = function () { return window.cbLang() === "bn"; };
  var L = function (b, e) { return bn() ? b : e; };
  var num = function (n, d) { return window.cbNum(Number(n).toFixed(d || 0)); };

  /* ---------- confirm before delete / cancel ---------- */
  document.querySelectorAll("form[data-confirm-bn]").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (!window.confirm(L(f.getAttribute("data-confirm-bn"), f.getAttribute("data-confirm-en")))) e.preventDefault();
    });
  });

  /* ---------- area names: BD codes -> names via GET /areas/{code} ---------- */
  document.querySelectorAll("[data-area-name]").forEach(function (el) {
    var code = el.getAttribute("data-area-name");
    if (!/^BD\d{4}(\d{4})?$/.test(code)) return;
    fetch("/areas/" + encodeURIComponent(code))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (a) {
        if (!a) return;
        var area = a.area || a;
        el.dataset.bn = area.name_bn || area.name_en || code;
        el.dataset.en = area.name_en || area.name_bn || code;
        el.textContent = bn() ? el.dataset.bn : el.dataset.en;
      }).catch(function () { /* keep the code */ });
  });
  document.addEventListener("cb:lang", function () {
    document.querySelectorAll("[data-area-name][data-bn]").forEach(function (el) {
      el.textContent = bn() ? el.dataset.bn : el.dataset.en;
    });
  });

  /* ---------- product preview before publishing ---------- */
  var form = document.querySelector("[data-preview-form]");
  var modal = document.querySelector("[data-preview-modal]");
  if (form && modal && typeof modal.showModal === "function") {
    var confirmed = false;
    form.addEventListener("submit", function (e) {
      if (confirmed) return;                       // second time: really send
      if (!form.reportValidity()) { e.preventDefault(); return; }
      e.preventDefault();
      var list = modal.querySelector("[data-preview-list]");
      list.textContent = "";
      var sel = function (name) { var s = form.elements[name]; return s && s.options ? s.options[s.selectedIndex].text : ""; };
      var val = function (name) { var x = form.elements[name]; return x ? (x.value || "").trim() : ""; };
      var radio = function (name) {
        var c = form.querySelector("input[name=" + name + "]:checked");
        return c ? c.parentNode.textContent.trim() : "";
      };
      var rows = [
        [L("পণ্যের নাম", "Product"), val("title")],
        [L("বিক্রির ধরন", "Type of sale"), radio("listing_type")],
        [L("বিভাগ", "Category"), sel("category")],
        [L("দাম", "Price"), "৳" + window.cbNum(val("price_per_unit")) + " / " + sel("unit")],
        [L("ছাড়ের দাম", "Discount price"), val("discount_price") ? "৳" + window.cbNum(val("discount_price")) : ""],
        [L("মোট পরিমাণ", "Quantity"), window.cbNum(val("quantity"))],
        [L("সর্বনিম্ন অর্ডার", "Minimum order"), window.cbNum(val("min_order"))],
        [L("চাষের পদ্ধতি", "Farming method"), radio("farming_method")],
        [L("ফসল তোলার তারিখ", "Harvest date"), val("harvest_date")],
        [L("ফসল উঠবে", "Expected harvest"), val("available_from")],
        [L("ছবি", "Photo"), form.elements.image && form.elements.image.files.length ? L("দেওয়া হয়েছে", "Added") : ""]
      ];
      rows.forEach(function (r) {
        if (!r[1]) return;
        var dt = document.createElement("dt"), dd = document.createElement("dd");
        dt.textContent = r[0]; dd.textContent = r[1];
        list.appendChild(dt); list.appendChild(dd);
      });
      modal.showModal();
    });
    modal.querySelector("[data-preview-edit]").addEventListener("click", function () { modal.close(); });
    modal.querySelector("[data-preview-ok]").addEventListener("click", function () {
      confirmed = true; modal.close();
      form.dataset.previewOk = "1";               // offline.js may now save it on the phone if there is no internet
      if (typeof form.requestSubmit === "function") form.requestSubmit(); else form.submit();
    });
  }

  /* ---------- crop list fills an empty product name ---------- */
  document.querySelectorAll("select[data-fill-name]").forEach(function (sel) {
    sel.addEventListener("change", function () {
      var target = document.querySelector(sel.getAttribute("data-fill-name"));
      var opt = sel.options[sel.selectedIndex];
      if (target && !target.value.trim() && opt && opt.getAttribute("data-name")) target.value = opt.getAttribute("data-name");
    });
  });

  /* ---------- weather card ----------
     Default: the farmer's REGISTERED area (upazila / district point from our own data).
     "Use my current location" is optional; a location outside Bangladesh (wrong PC location, VPN) is refused,
     because that gave wrong weather before (for example 10 °C in Dhaka in November). */
  var card = document.querySelector("[data-weather]");
  if (!card) return;
  var body = card.querySelector("[data-w-body]"), placeEl = card.querySelector("[data-w-place]");
  var homeBtn = card.querySelector("[data-w-home]"), area = card.getAttribute("data-w-area") || "";
  var key = "cb_wloc_" + (card.getAttribute("data-user") || "0");
  var BD = { latMin: 20.3, latMax: 26.8, lonMin: 87.9, lonMax: 92.8 };
  function inBD(lat, lon) { return lat >= BD.latMin && lat <= BD.latMax && lon >= BD.lonMin && lon <= BD.lonMax; }
  var current = null;                       // {lat, lon, bn, en}
  var saved = null;
  try { saved = JSON.parse(localStorage.getItem(key) || "null"); } catch (e) { saved = null; }
  if (saved && !(saved.lat && inBD(+saved.lat, +saved.lon))) {
    saved = null; try { localStorage.removeItem(key); } catch (e) { /* ignore */ }
  }

  function msg(b, e) { body.innerHTML = ""; var p = document.createElement("p"); p.className = "cb-hint"; p.textContent = L(b, e); body.appendChild(p); }
  function setPlace() { if (placeEl) placeEl.textContent = current ? "· " + L(current.bn, current.en) : ""; }

  function show(d) {
    var c = d.current || {}, day = d.daily || {};
    body.innerHTML = "";
    var now = document.createElement("div"); now.className = "cb-w-now";
    now.innerHTML = "<b></b><span></span>";
    now.querySelector("b").textContent = num(c.temperature_2m, 0) + "°C";
    now.querySelector("span").textContent = L("আর্দ্রতা ", "Humidity ") + num(c.relative_humidity_2m, 0) + "% · " +
      L("এখন বৃষ্টি ", "Rain now ") + num(c.precipitation, 1) + " mm";
    body.appendChild(now);
    var ul = document.createElement("ul"); ul.className = "cb-w-days";
    (day.time || []).forEach(function (t, i) {
      var li = document.createElement("li");
      var d0 = new Date(t + "T00:00:00");
      var name = i === 0 ? L("আজ", "Today") : d0.toLocaleDateString(bn() ? "bn-BD" : "en-GB", { weekday: "short" });
      var prob = (day.precipitation_probability_max || [])[i];
      li.innerHTML = "<b></b><span></span><small></small>";
      li.querySelector("b").textContent = name;
      li.querySelector("span").textContent = num(day.temperature_2m_max[i], 0) + "° / " + num(day.temperature_2m_min[i], 0) + "°";
      li.querySelector("small").textContent = L("বৃষ্টি ", "Rain ") + num(day.precipitation_sum[i], 1) + " mm" +
        (prob != null ? " (" + num(prob, 0) + "%)" : "");
      ul.appendChild(li);
    });
    body.appendChild(ul);
    var when = document.createElement("p"); when.className = "cb-hint";
    when.textContent = L("আপডেট: ", "Updated: ") + new Date().toLocaleTimeString(bn() ? "bn-BD" : "en-GB", { hour: "2-digit", minute: "2-digit" });
    body.appendChild(when);
  }

  function load(p) {
    current = p; setPlace();
    msg("আবহাওয়া আনা হচ্ছে…", "Loading weather…");
    var url = "https://api.open-meteo.com/v1/forecast?latitude=" + (+p.lat).toFixed(4) + "&longitude=" + (+p.lon).toFixed(4) +
      "&current=temperature_2m,relative_humidity_2m,precipitation" +
      "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max" +
      "&timezone=Asia%2FDhaka&forecast_days=3";
    fetch(url).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(show)
      .catch(function () { msg("এখন আবহাওয়া আনা যাচ্ছে না (ইন্টারনেট নেই বা সার্ভার সমস্যা)। পরে আবার চেষ্টা করুন।", "Weather is not available right now (no internet or server problem). Please try again later."); });
  }

  var home = null;
  function loadHome(note) {
    if (!area) { msg("প্রোফাইলে এলাকা দিন, অথবা এখনকার অবস্থান ব্যবহার করুন।", "Add your area in your profile, or use your current location."); return; }
    var go = function (p) {
      load(p);
      if (note) { var n = document.createElement("p"); n.className = "cb-hint"; n.textContent = L(note[0], note[1]); body.prepend(n); }
    };
    if (home) { go(home); return; }
    fetch("/app/area-point/" + encodeURIComponent(area)).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (a) { home = { lat: a.lat, lon: a.lon, bn: a.name_bn, en: a.name_en }; go(home); })
      .catch(function () { msg("এলাকার অবস্থান পাওয়া যায়নি।", "Could not find your area's location."); });
  }

  card.querySelector("[data-w-locate]").addEventListener("click", function () {
    if (!navigator.geolocation) { msg("এই ডিভাইসে অবস্থান জানা যায় না।", "This device cannot share its location."); return; }
    msg("অবস্থান খোঁজা হচ্ছে…", "Finding your location…");
    navigator.geolocation.getCurrentPosition(function (pos) {
      var lat = +pos.coords.latitude.toFixed(2), lon = +pos.coords.longitude.toFixed(2);   // about 1 km, enough for weather
      if (!inBD(lat, lon)) {
        loadHome(["আপনার ডিভাইসের অবস্থান বাংলাদেশের বাইরে দেখাচ্ছে (ভুল লোকেশন বা VPN হতে পারে), তাই নিবন্ধিত এলাকার আবহাওয়া দেখানো হচ্ছে।",
                  "Your device location appears to be outside Bangladesh (wrong location or VPN), so your registered area is shown."]);
        return;
      }
      saved = { lat: lat, lon: lon };
      try { localStorage.setItem(key, JSON.stringify(saved)); } catch (e) { /* private mode */ }
      if (homeBtn) homeBtn.hidden = !area;
      load({ lat: lat, lon: lon, bn: "এখনকার অবস্থান", en: "current location" });
    }, function () {
      loadHome(["অবস্থানের অনুমতি পাওয়া যায়নি, তাই নিবন্ধিত এলাকার আবহাওয়া দেখানো হচ্ছে।", "Location permission was not given, so your registered area is shown."]);
    }, { timeout: 15000, maximumAge: 3600000 });
  });
  if (homeBtn) homeBtn.addEventListener("click", function () {
    saved = null; try { localStorage.removeItem(key); } catch (e) { /* ignore */ }
    homeBtn.hidden = true; loadHome(null);
  });

  if (saved) { if (homeBtn) homeBtn.hidden = !area; load({ lat: saved.lat, lon: saved.lon, bn: "এখনকার অবস্থান", en: "current location" }); }
  else loadHome(null);
  document.addEventListener("cb:lang", function () { if (current) { setPlace(); load(current); } });
})();
