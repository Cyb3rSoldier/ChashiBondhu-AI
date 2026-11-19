/* UI v7 helpers: show / hide password, gentle fade between sign-in pages. No data is sent anywhere. */
(function () {
  "use strict";
  document.querySelectorAll("[data-cb-eye]").forEach(function (b) {
    var input = document.getElementById(b.getAttribute("data-cb-eye"));
    if (!input) return;
    b.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      b.setAttribute("aria-pressed", show ? "true" : "false");
      var i = b.querySelector("i"); if (i) i.className = "fa-solid " + (show ? "fa-eye-slash" : "fa-eye");
      input.focus();
    });
  });
  /* password-again check while typing (the server checks again) */
  document.querySelectorAll("[data-cb-same]").forEach(function (p2) {
    var p1 = document.getElementById(p2.getAttribute("data-cb-same"));
    function check() {
      var en = document.documentElement.getAttribute("data-lang") === "en";
      p2.setCustomValidity(p2.value && p1 && p2.value !== p1.value ? (en ? "Passwords do not match." : "দুটি পাসওয়ার্ড মেলেনি।") : "");
    }
    p2.addEventListener("input", check); if (p1) p1.addEventListener("input", check);
  });
  /* role tabs / sign-in <-> sign-up links: short fade-out before the next page */
  document.querySelectorAll("[data-cb-fade]").forEach(function (a) {
    a.addEventListener("click", function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      var card = document.querySelector(".cb-auth2"); if (!card) return;
      e.preventDefault(); card.style.transition = "opacity .15s, transform .15s"; card.style.opacity = "0"; card.style.transform = "translateY(6px)";
      setTimeout(function () { location.href = a.href; }, 140);
    });
  });
})();
