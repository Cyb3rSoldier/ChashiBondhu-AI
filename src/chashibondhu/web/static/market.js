/* Marketplace: search autocomplete (debounced, keyboard), quantity stepper, one-click-only checkout. */
(function () {
  "use strict";
  var bn = function () { return window.cbLang() === "bn"; };

  /* ---------- autocomplete ---------- */
  var box = document.querySelector("[data-autocomplete]");
  if (box) {
    var input = box.querySelector("input"), list = box.querySelector("ul"), form = input.form;
    var timer = null, items = [], cur = -1, last = "", seq = 0;
    var close = function () { list.hidden = true; input.setAttribute("aria-expanded", "false"); cur = -1; };
    var mark = function () {
      list.querySelectorAll("li").forEach(function (li, i) {
        li.setAttribute("aria-selected", i === cur ? "true" : "false");
        if (i === cur) input.setAttribute("aria-activedescendant", li.id);
      });
    };
    var pick = function (i) { if (!items[i]) return; input.value = items[i].q; close(); form.submit(); };
    var draw = function () {
      list.textContent = "";
      if (!items.length) { close(); return; }
      items.forEach(function (it, i) {
        var li = document.createElement("li");
        li.id = "ac" + i; li.setAttribute("role", "option");
        var name = document.createElement("span"); name.textContent = bn() ? it.bn : it.en;
        var n = document.createElement("small");
        n.textContent = window.cbNum(it.count) + (bn() ? " টি পণ্য" : (it.count === 1 ? " product" : " products"));
        li.appendChild(name); li.appendChild(n);
        li.addEventListener("mousedown", function (e) { e.preventDefault(); pick(i); });
        list.appendChild(li);
      });
      list.hidden = false; input.setAttribute("aria-expanded", "true"); cur = -1;
    };
    input.addEventListener("input", function () {
      clearTimeout(timer);
      var q = input.value.trim();
      if (!q) { items = []; close(); return; }
      timer = setTimeout(function () {
        if (q === last) { draw(); return; }
        last = q; var mine = ++seq;
        fetch("/market/suggest?q=" + encodeURIComponent(q)).then(function (r) { return r.ok ? r.json() : { items: [] }; })
          .then(function (d) { if (mine === seq) { items = d.items || []; draw(); } })
          .catch(function () { items = []; close(); });
      }, 220);
    });
    input.addEventListener("keydown", function (e) {
      if (list.hidden) return;
      if (e.key === "ArrowDown") { cur = Math.min(cur + 1, items.length - 1); mark(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { cur = Math.max(cur - 1, -1); mark(); e.preventDefault(); }
      else if (e.key === "Enter" && cur >= 0) { e.preventDefault(); pick(cur); }
      else if (e.key === "Escape") { close(); }
    });
    input.addEventListener("blur", function () { setTimeout(close, 150); });
  }

  /* ---------- quantity stepper + live total ---------- */
  var qty = document.querySelector("#qty[data-min]");
  if (qty) {
    var min = parseFloat(qty.dataset.min), max = parseFloat(qty.dataset.max);
    var total = document.querySelector("[data-qty-total]"), price = total ? parseFloat(total.dataset.price) : 0;
    var toNum = function (v) { return parseFloat(String(v).replace(/[০-৯]/g, function (d) { return "০১২৩৪৫৬৭৮৯".indexOf(d); })); };
    var show = function () {
      var v = toNum(qty.value);
      if (!total) return;
      if (isNaN(v) || v < min || v > max) {
        total.textContent = bn() ? ("পরিমাণ " + window.cbNum(min) + " থেকে " + window.cbNum(max) + " এর মধ্যে দিন") : ("Choose between " + min + " and " + max);
      } else {
        total.textContent = (bn() ? "মোট: ৳" : "Total: ৳") + window.cbNum((v * price).toFixed(2));
      }
    };
    document.querySelectorAll("[data-step]").forEach(function (b) {
      b.addEventListener("click", function () {
        var v = toNum(qty.value); if (isNaN(v)) v = min;
        v = Math.round((v + parseFloat(b.dataset.step)) * 100) / 100;
        qty.value = Math.min(Math.max(v, min), max); show();
      });
    });
    qty.addEventListener("input", show); document.addEventListener("cb:lang", show); show();
  }

  /* ---------- checkout: send once ---------- */
  document.querySelectorAll("form[data-once]").forEach(function (f) {
    f.addEventListener("submit", function () {
      var b = f.querySelector("button[type=submit]");
      setTimeout(function () { if (b) b.disabled = true; }, 0);
    });
  });
})();
