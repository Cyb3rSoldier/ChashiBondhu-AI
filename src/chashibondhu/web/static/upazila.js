/* Upazila search box: uses GET /areas/search?q=... (existing API) and keeps only upazila codes (BD + 8 digits). */
(function () {
  "use strict";
  var box = document.querySelector("[data-upazila-picker]");
  if (!box) return;
  var input = box.querySelector("input[type=search]"), list = box.querySelector(".cb-suggest");
  var code = box.querySelector("input[name=upazila_code]"), label = box.querySelector("input[name=upazila_label]");
  var chosen = box.querySelector(".cb-chosen"), chosenText = box.querySelector("[data-chosen]");
  var timer = null, lastQ = "";
  function pick(c, text) {
    code.value = c; label.value = text; chosenText.textContent = text; chosen.hidden = false;
    list.hidden = true; list.textContent = ""; input.value = "";
  }
  function areaOf(hit) { return (hit && (hit.area || hit)) || {}; }
  function show(results) {
    list.textContent = "";
    var n = 0;
    results.forEach(function (hit) {
      var a = areaOf(hit), c = a.code || a.area_code || a.pcode || "";
      if (!/^BD\d{8}$/.test(c) || n >= 8) return;
      n += 1;
      var bn = a.name_bn || "", en = a.name_en || a.name || "";
      var parent = a.district_name_bn || a.district_name_en || a.parent_name || "";
      var text = (bn && en ? bn + " (" + en + ")" : bn || en || c) + (parent ? ", " + parent : "");
      var li = document.createElement("li"), b = document.createElement("button");
      b.type = "button"; b.textContent = text;
      b.addEventListener("click", function () { pick(c, text); });
      li.appendChild(b); list.appendChild(li);
    });
    if (!n) {
      var li2 = document.createElement("li"); li2.style.padding = "10px 12px";
      li2.textContent = window.cbLang() === "en" ? "No upazila found. Try another spelling." : "উপজেলা পাওয়া যায়নি। অন্যভাবে লিখে দেখুন।";
      list.appendChild(li2);
    }
    list.hidden = false;
  }
  input.addEventListener("input", function () {
    var q = input.value.trim();
    clearTimeout(timer);
    if (q.length < 2) { list.hidden = true; return; }
    timer = setTimeout(function () {
      lastQ = q;
      fetch("/areas/search?limit=20&q=" + encodeURIComponent(q))
        .then(function (r) { return r.ok ? r.json() : { results: [] }; })
        .then(function (d) { if (q === lastQ) show(d.results || []); })
        .catch(function () { list.hidden = true; });
    }, 250);
  });
})();
