/**
 * boot.js — load right AFTER the Tailwind CDN script, in <head>.
 * 1) Tailwind theme (brand colours + fonts)
 * 2) Sets dark/light + language on <html> early (no flash)
 * 3) App config (API base URL — empty = server not connected yet)
 */
/* global tailwind */
tailwind.config = {
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        leaf: {
          50: "#ecfdf3", 100: "#d1fadf", 300: "#86efac", 400: "#4ade80",
          500: "#16a34a", 600: "#15803d", 700: "#166534", 800: "#14532d", 900: "#0f3d22",
        },
        soil: { 50: "#fff7ed", 100: "#ffedd5", 300: "#fdba74", 500: "#ea7a0c", 600: "#c2600a", 700: "#9a4a08", 800: "#7c3a06" },
        page: "rgb(var(--page) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        ink: "rgb(var(--ink) / <alpha-value>)",
        muted: "rgb(var(--muted) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
      },
      fontFamily: {
        sans: ['"Hind Siliguri"', "Roboto", "system-ui", "sans-serif"],
        brand: ['"Noto Serif Bengali"', '"Noto Serif"', "Georgia", "serif"],
      },
    },
  },
};

window.CB_CONFIG = {
  // Set this when the FastAPI backend is ready, e.g. "http://127.0.0.1:8000/api"
  apiBase: "",
  // Show the "sample listings" notice until real data comes from the database
  showDemoNotice: true,
};

(function earlyPrefs() {
  let theme = null, lang = null;
  try { theme = localStorage.getItem("cb_theme"); lang = localStorage.getItem("cb_lang"); } catch (e) { /* storage blocked */ }
  if (!theme) theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.documentElement.lang = lang === "en" ? "en" : "bn";
})();
