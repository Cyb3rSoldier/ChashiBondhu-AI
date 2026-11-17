/**
 * i18n.js — Bangla (default) + English text.
 * In HTML:  data-i18n="key"  (text), data-i18n-ph="key" (placeholder), data-i18n-aria="key" (aria-label)
 * In JS:    CB.t("key", {n: 5}),  CB.fmtNum(1200),  CB.setLang("en")
 * Fires a "cb:langchange" event on document so pages can re-render cards.
 */
(function () {
  const DICT = {
    bn: {
      brand: "চাষীবন্ধু",
      nav_home: "হোম", nav_market: "বাজার", nav_produce: "টাটকা পণ্য", nav_tools: "কৃষি যন্ত্রপাতি",
      nav_about: "আমাদের কথা", nav_contact: "যোগাযোগ", nav_login: "লগইন",
      login_consumer: "ক্রেতা হিসেবে লগইন", login_farmer: "কৃষক হিসেবে লগইন",
      login_vendor: "বিক্রেতা হিসেবে লগইন", login_admin: "অ্যাডমিন লগইন",
      no_account: "অ্যাকাউন্ট নেই?",
      role_consumer: "ক্রেতা", role_farmer: "কৃষক", role_vendor: "বিক্রেতা", role_admin: "অ্যাডমিন",
      toggle_lang: "English", toggle_lang_aria: "ভাষা বদলান", toggle_theme_aria: "আলো/অন্ধকার মোড", menu_aria: "মেনু",

      hero_pill: "বাংলাদেশের কৃষকের প্ল্যাটফর্ম",
      hero_title_a: "কৃষকের হাত থেকে", hero_title_b: "সরাসরি আপনার কাছে!",
      hero_sub: "চাষীবন্ধু কৃষককে সরাসরি ক্রেতার সাথে যুক্ত করে।",
      hero_sub2: "টাটকা পণ্য, ন্যায্য দাম, মাঝে কোনো দালাল নেই।",
      cta_shop: "ক্রেতা হিসেবে কিনুন", cta_join: "কৃষক হিসেবে যোগ দিন",
      trust_1_t: "৬৪ জেলা", trust_1_s: "যেকোনো জেলা থেকে বিক্রি",
      trust_2_t: "ক্যাশ অন ডেলিভারি", trust_2_s: "পণ্য হাতে পেয়ে টাকা দিন",
      trust_3_t: "বাংলা ও English", trust_3_s: "নিজের ভাষায় সহজে ব্যবহার",
      scroll: "নিচে দেখুন",

      produce_pill: "টাটকা পণ্য", produce_title: "কৃষকের মাঠ থেকে",
      produce_sub: "সারা বাংলাদেশের কৃষকের কাছ থেকে সরাসরি কিনুন — টাটকা ও ন্যায্য দামে",
      search_produce_ph: "সবজি, ফল, শস্য খুঁজুন...",
      min_ph: "সর্বনিম্ন ৳", max_ph: "সর্বোচ্চ ৳", district_all: "সব জেলা", choose_district: "জেলা বেছে নিন",
      apply: "প্রয়োগ করুন", reset: "মুছুন",
      cat_all: "সব", cat_vegetables: "সবজি", cat_fruits: "ফল", cat_grains: "শস্য ও ডাল",
      cat_dairy_eggs: "দুধ ও ডিম", cat_spices: "মসলা", cat_organic: "জৈব",
      badge_new: "নতুন", badge_sale: "ছাড়", badge_organic: "জৈব",
      organic_note: "কৃষকের দেওয়া তথ্য, সনদ যাচাই করা নয়",
      save_pct: "{n}% সাশ্রয়",
      unit_kg: "কেজি", unit_dozen: "ডজন", unit_piece: "পিস", unit_set: "সেট", unit_litre: "লিটার",
      msg_farmer: "কৃষককে মেসেজ", login_to_buy: "কিনতে লগইন করুন",
      demo_notice: "এখানে নমুনা তালিকা দেখানো হচ্ছে। ডাটাবেস যুক্ত হলে আসল পণ্য দেখা যাবে।",
      empty_title: "কোনো কিছু পাওয়া যায়নি", empty_sub: "ফিল্টার বদলে দেখুন অথবা \"মুছুন\" চাপুন।",
      results_count: "{n}টি ফলাফল",

      tools_pill: "যন্ত্রপাতি", tools_title: "কৃষি যন্ত্রপাতির বাজার",
      tools_sub: "নিবন্ধিত বিক্রেতাদের কাছ থেকে ট্রাক্টর, লাঙল, বীজ, সার ও কৃষি যন্ত্রপাতি খুঁজুন",
      search_tools_ph: "যন্ত্র, মেশিন, বীজ খুঁজুন...", brand_ph: "ব্র্যান্ড",
      tcat_all: "সব যন্ত্র", tcat_hand: "হাতের যন্ত্র", tcat_harvest: "হারভেস্টার ও মাড়াই যন্ত্র",
      tcat_irrigation: "সেচ যন্ত্র", tcat_plow: "লাঙল ও মই", tcat_protect: "সুরক্ষা সরঞ্জাম",
      tcat_seeder: "বীজ বপন যন্ত্র", tcat_spare: "খুচরা যন্ত্রাংশ", tcat_sprayer: "স্প্রেয়ার",
      tcat_tractor: "ট্রাক্টর ও পাওয়ার টিলার",
      view_details: "বিস্তারিত দেখুন",

      vendor_title: "আপনি কি কৃষি যন্ত্রপাতি বিক্রি করেন?",
      vendor_sub: "আপনার যন্ত্রপাতি, মেশিন, বীজ ও সরঞ্জাম তালিকাভুক্ত করুন এবং সারা দেশের কৃষকের কাছে পৌঁছান।",
      vendor_cta: "বিক্রেতা হিসেবে নিবন্ধন করুন",

      video_pill: "ভিডিও", video_title: "ভিডিও দেখে চাষ শিখুন", video_sub: "ছোট ও সহজ কৃষি ভিডিও",
      video_all: "সব ভিডিও", video_soon: "ভিডিও শীঘ্রই যোগ হবে",

      blog_pill: "জ্ঞানভান্ডার", blog_title: "চাষের সহজ পরামর্শ",
      blog_sub: "সারা বাংলাদেশের কৃষকের জন্য ছোট ও সহজ পরামর্শ", blog_all: "সব লেখা", read_more: "পড়ুন",
      load_more: "আরও দেখুন",
      blog_tip_office: "নিজের জমির জন্য নির্দিষ্ট পরামর্শ লাগলে উপজেলা কৃষি অফিসে যোগাযোগ করুন।",

      footer_about: "কৃষক ও ক্রেতার মাঝে সরাসরি সেতু। টাটকা পণ্য, ন্যায্য দাম, কোনো দালাল নেই।",
      tagline: "কৃষককে স্মার্টভাবে চাষ, ভালো দামে বিক্রি ও বেশি আয়ে সাহায্য করা",
      footer_quick: "দ্রুত লিংক", footer_users: "ব্যবহারকারী", footer_contact: "যোগাযোগ",
      privacy: "গোপনীয়তা নীতি", browse: "পণ্য দেখুন", support: "সহায়তা কেন্দ্র",
      address: "ঢাকা, বাংলাদেশ", rights: "© ২০২৬ চাষীবন্ধু। সর্বস্বত্ব সংরক্ষিত।",
      made_with: "বাংলাদেশের কৃষকের জন্য ভালোবাসা দিয়ে তৈরি",

      welcome: "চাষীবন্ধুতে স্বাগতম",
      side_consumer: "কৃষকের কাছ থেকে সরাসরি টাটকা পণ্য কিনুন।",
      side_farmer: "আপনার ফসল সরাসরি ক্রেতার কাছে বিক্রি করুন — মাঠ থেকেই।",
      side_vendor: "আপনার যন্ত্রপাতি সারা দেশের কৃষকের কাছে পৌঁছে দিন।",
      side_admin: "প্ল্যাটফর্ম দেখভাল ও পরিচালনা করুন।",
      choose_role: "আপনি কে?",
      tab_login: "লগইন", tab_register: "নিবন্ধন",
      auth_title_login: "{role} হিসেবে লগইন", auth_title_register: "{role} হিসেবে নতুন অ্যাকাউন্ট",
      f_phone: "মোবাইল নম্বর", f_email: "ইমেইল", f_password: "পাসওয়ার্ড", f_confirm: "আবার পাসওয়ার্ড দিন",
      f_name: "আপনার নাম", f_district: "জেলা", f_shop: "দোকান বা প্রতিষ্ঠানের নাম",
      show_pw: "দেখান", hide_pw: "লুকান",
      btn_login: "লগইন করুন", btn_register: "অ্যাকাউন্ট খুলুন",
      switch_to_register: "অ্যাকাউন্ট নেই? নিবন্ধন করুন", switch_to_login: "অ্যাকাউন্ট আছে? লগইন করুন",
      admin_note: "অ্যাডমিন অ্যাকাউন্ট শুধু প্রধান অ্যাডমিন তৈরি করেন। এখানে নিবন্ধন করা যায় না।",
      err_required: "এই ঘরটি পূরণ করুন",
      err_phone: "সঠিক মোবাইল নম্বর দিন (যেমন ০১৭১২৩৪৫৬৭৮)",
      err_email: "সঠিক ইমেইল দিন", err_pw_len: "পাসওয়ার্ড কমপক্ষে ৮ অক্ষরের হতে হবে",
      err_pw_match: "দুটি পাসওয়ার্ড মিলছে না", err_district: "আপনার জেলা বেছে নিন",
      srv_not_connected: "ফর্ম ঠিক আছে। সার্ভার এখনো যুক্ত হয়নি (প্রোটোটাইপ)।",
      srv_error: "সার্ভারে সমস্যা হয়েছে। একটু পরে আবার চেষ্টা করুন।",
      srv_ok: "সফল হয়েছে!",
      back_home: "হোমে ফিরুন",
    },
    en: {
      brand: "ChashiBondhu",
      nav_home: "Home", nav_market: "Marketplaces", nav_produce: "Fresh produce", nav_tools: "Farming tools",
      nav_about: "About us", nav_contact: "Contact", nav_login: "Login",
      login_consumer: "Login as consumer", login_farmer: "Login as farmer",
      login_vendor: "Login as vendor", login_admin: "Admin login",
      no_account: "Don't have an account?",
      role_consumer: "Consumer", role_farmer: "Farmer", role_vendor: "Vendor", role_admin: "Admin",
      toggle_lang: "বাংলা", toggle_lang_aria: "Change language", toggle_theme_aria: "Light/dark mode", menu_aria: "Menu",

      hero_pill: "Bangladeshi farmers' platform",
      hero_title_a: "From the farmer", hero_title_b: "straight to you!",
      hero_sub: "ChashiBondhu connects farmers directly with consumers.",
      hero_sub2: "Fresh products, fair prices, and no middlemen.",
      cta_shop: "Shop as consumer", cta_join: "Join as farmer",
      trust_1_t: "64 districts", trust_1_s: "Sell from any district",
      trust_2_t: "Cash on delivery", trust_2_s: "Pay when you receive",
      trust_3_t: "বাংলা & English", trust_3_s: "Easy to use in your language",
      scroll: "Scroll",

      produce_pill: "Fresh produce", produce_title: "From farmers' fields",
      produce_sub: "Buy directly from farmers across Bangladesh — fresh and fairly priced",
      search_produce_ph: "Search vegetables, fruits, grains...",
      min_ph: "Min ৳", max_ph: "Max ৳", district_all: "All districts", choose_district: "Choose district",
      apply: "Apply", reset: "Reset",
      cat_all: "All", cat_vegetables: "Vegetables", cat_fruits: "Fruits", cat_grains: "Grains & pulses",
      cat_dairy_eggs: "Dairy & eggs", cat_spices: "Spices", cat_organic: "Organic",
      badge_new: "New", badge_sale: "Sale", badge_organic: "Organic",
      organic_note: "Stated by the farmer, not a verified certificate",
      save_pct: "Save {n}%",
      unit_kg: "kg", unit_dozen: "dozen", unit_piece: "piece", unit_set: "set", unit_litre: "litre",
      msg_farmer: "Message farmer", login_to_buy: "Login to buy",
      demo_notice: "Showing sample listings. Real products appear once the database is connected.",
      empty_title: "Nothing found", empty_sub: "Change the filters or press \"Reset\".",
      results_count: "{n} results",

      tools_pill: "Tools & equipment", tools_title: "Farming tools marketplace",
      tools_sub: "Find tractors, plows, seeds, fertilizers and farming equipment from registered vendors",
      search_tools_ph: "Search tools, machines, seeds...", brand_ph: "Brand",
      tcat_all: "All tools", tcat_hand: "Hand tools", tcat_harvest: "Harvesters & threshers",
      tcat_irrigation: "Irrigation equipment", tcat_plow: "Plows & harrows", tcat_protect: "Protective gear",
      tcat_seeder: "Seeders & planters", tcat_spare: "Spare parts", tcat_sprayer: "Sprayers & spreaders",
      tcat_tractor: "Tractors & power tillers",
      view_details: "View details",

      vendor_title: "Do you sell farming tools?",
      vendor_sub: "List your tools, machines, seeds and equipment and reach farmers across Bangladesh.",
      vendor_cta: "Register as vendor",

      video_pill: "Video hub", video_title: "Learn farming from videos", video_sub: "Short, simple farming guides",
      video_all: "View all videos", video_soon: "Video coming soon",

      blog_pill: "Knowledge hub", blog_title: "Simple farming tips",
      blog_sub: "Short, easy tips for farmers across Bangladesh", blog_all: "View all articles", read_more: "Read",
      load_more: "Load more",
      blog_tip_office: "For advice about your own field, contact your Upazila Agriculture Office.",

      footer_about: "A direct bridge between farmers and consumers. Fresh produce, fair prices, no middlemen.",
      tagline: "Helping farmers grow smarter, sell better and earn more",
      footer_quick: "Quick links", footer_users: "For users", footer_contact: "Contact us",
      privacy: "Privacy policy", browse: "Browse products", support: "Support centre",
      address: "Dhaka, Bangladesh", rights: "© 2026 ChashiBondhu. All rights reserved.",
      made_with: "Made with love for Bangladesh's farmers",

      welcome: "Welcome to ChashiBondhu",
      side_consumer: "Buy fresh produce directly from farmers.",
      side_farmer: "Sell your harvest directly to buyers — even from the field.",
      side_vendor: "Bring your tools to farmers across the country.",
      side_admin: "Monitor and manage the platform.",
      choose_role: "Who are you?",
      tab_login: "Log in", tab_register: "Register",
      auth_title_login: "Log in as {role}", auth_title_register: "New {role} account",
      f_phone: "Mobile number", f_email: "Email", f_password: "Password", f_confirm: "Confirm password",
      f_name: "Your name", f_district: "District", f_shop: "Shop or business name",
      show_pw: "Show", hide_pw: "Hide",
      btn_login: "Log in", btn_register: "Create account",
      switch_to_register: "No account? Register", switch_to_login: "Have an account? Log in",
      admin_note: "Admin accounts are created by the main admin only. They cannot be registered here.",
      err_required: "Please fill in this field",
      err_phone: "Enter a valid mobile number (e.g. 01712345678)",
      err_email: "Enter a valid email", err_pw_len: "Password must be at least 8 characters",
      err_pw_match: "Passwords do not match", err_district: "Choose your district",
      srv_not_connected: "Form looks good. The server is not connected yet (prototype).",
      srv_error: "Server problem. Please try again in a moment.",
      srv_ok: "Done!",
      back_home: "Back to home",
    },
  };

  const KEY = "cb_lang";
  let current = "bn";
  try { current = localStorage.getItem(KEY) === "en" ? "en" : "bn"; } catch (e) { /* default bn */ }

  function t(key, vars) {
    let s = (DICT[current] && DICT[current][key]) ?? DICT.bn[key] ?? key;
    if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v);
    return s;
  }

  function fmtNum(n) {
    const num = Number(n);
    if (!Number.isFinite(num)) return "";
    return num.toLocaleString(current === "bn" ? "bn-BD" : "en-IN");
  }

  function applyI18n(root = document) {
    root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    root.querySelectorAll("[data-i18n-ph]").forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
    root.querySelectorAll("[data-i18n-aria]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.i18nAria)); });
  }

  function setLang(lang) {
    current = lang === "en" ? "en" : "bn";
    try { localStorage.setItem(KEY, current); } catch (e) { /* ignore */ }
    document.documentElement.lang = current;
    applyI18n();
    document.dispatchEvent(new CustomEvent("cb:langchange", { detail: { lang: current } }));
  }

  /** Pick bn/en from an object like {bn:"টমেটো", en:"Tomato"} */
  function pick(obj) {
    if (obj == null) return "";
    if (typeof obj === "string") return obj;
    return obj[current] ?? obj.bn ?? obj.en ?? "";
  }

  /** Escape text before putting it in innerHTML */
  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  window.CB = Object.assign(window.CB || {}, {
    DICT, t, fmtNum, applyI18n, setLang, pick, esc, getLang: () => current,
  });
})();
