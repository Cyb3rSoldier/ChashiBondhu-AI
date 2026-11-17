/**
 * demo-data.js — SAMPLE data only, to show the design.
 * Every item has source: "demo". Replace with data from your FastAPI/Supabase API.
 * Prices here are NOT market prices.
 * img: put a real photo path (e.g. "assets/img/products/tomato.jpg") or leave "" for a clean placeholder tile.
 */
(function () {
  const SAMPLE_FARMER = { bn: "নমুনা কৃষক", en: "Sample farmer" };
  const SAMPLE_SHOP = { bn: "নমুনা দোকান", en: "Sample shop" };

  const PRODUCTS = [
    { id: "p1", name: { bn: "টমেটো", en: "Tomato" }, category: "vegetables", price: 60, oldPrice: 70, unit: "kg", district: "Rangpur", organic: false, isNew: false, img: "" },
    { id: "p2", name: { bn: "আলু", en: "Potato" }, category: "vegetables", price: 30, oldPrice: null, unit: "kg", district: "Munshiganj", organic: false, isNew: true, img: "" },
    { id: "p3", name: { bn: "ঢেঁড়স", en: "Ladies finger" }, category: "vegetables", price: 30, oldPrice: 35, unit: "kg", district: "Chattogram", organic: true, isNew: false, img: "" },
    { id: "p4", name: { bn: "দেশি মুরগির ডিম", en: "Local eggs" }, category: "dairy_eggs", price: 135, oldPrice: 145, unit: "dozen", district: "Chattogram", organic: true, isNew: false, img: "" },
    { id: "p5", name: { bn: "তরমুজ", en: "Watermelon" }, category: "fruits", price: 250, oldPrice: null, unit: "piece", district: "Patuakhali", organic: false, isNew: true, img: "" },
    { id: "p6", name: { bn: "মসুর ডাল", en: "Lentil" }, category: "grains", price: 110, oldPrice: null, unit: "kg", district: "Rajshahi", organic: false, isNew: false, img: "" },
    { id: "p7", name: { bn: "পেঁয়াজ", en: "Onion" }, category: "spices", price: 80, oldPrice: 90, unit: "kg", district: "Pabna", organic: false, isNew: false, img: "" },
    { id: "p8", name: { bn: "গরুর দুধ", en: "Cow milk" }, category: "dairy_eggs", price: 90, oldPrice: null, unit: "litre", district: "Sirajganj", organic: false, isNew: true, img: "" },
  ].map((p) => ({ ...p, farmer: SAMPLE_FARMER, source: "demo" }));

  const TOOLS = [
    { id: "t1", name: { bn: "হাত আঁচড়া (রেক)", en: "Rake" }, category: "hand", brand: "Brand A", price: 300, unit: "piece", district: "Rajshahi", isNew: true, img: "" },
    { id: "t2", name: { bn: "ঝোপ কাটার মেশিন", en: "Bush cutter" }, category: "harvest", brand: "Brand B", price: 10000, unit: "piece", district: "Rajshahi", isNew: true, img: "" },
    { id: "t3", name: { bn: "হাতে চালানো স্প্রেয়ার", en: "Knapsack sprayer" }, category: "sprayer", brand: "Brand A", price: 2500, unit: "piece", district: "Bogura", isNew: false, img: "" },
    { id: "t4", name: { bn: "সেচ পাম্প", en: "Irrigation pump" }, category: "irrigation", brand: "Brand C", price: 18000, unit: "piece", district: "Dinajpur", isNew: false, img: "" },
    { id: "t5", name: { bn: "পাওয়ার টিলার", en: "Power tiller" }, category: "tractor", brand: "Brand C", price: 150000, unit: "piece", district: "Jashore", isNew: false, img: "" },
    { id: "t6", name: { bn: "হাতের যন্ত্রের সেট", en: "Hand tool set" }, category: "hand", brand: "Brand B", price: 4000, unit: "set", district: "Rajshahi", isNew: true, img: "" },
    { id: "t7", name: { bn: "হাতের গ্লাভস ও মাস্ক", en: "Gloves and mask" }, category: "protect", brand: "Brand A", price: 450, unit: "set", district: "Dhaka", isNew: false, img: "" },
    { id: "t8", name: { bn: "বীজ বপন যন্ত্র", en: "Seed drill" }, category: "seeder", brand: "Brand C", price: 35000, unit: "piece", district: "Rangpur", isNew: false, img: "" },
  ].map((t) => ({ ...t, vendor: SAMPLE_SHOP, source: "demo" }));

  // youtubeId: "" = shows "coming soon". Admin adds real video IDs later.
  const VIDEOS = [
    { id: "v1", title: { bn: "ছোট খামারে জৈব চাষ", en: "Organic farming on small farms" }, youtubeId: "" },
    { id: "v2", title: { bn: "তরুণ কৃষকের সফলতার গল্প", en: "A young farmer's success story" }, youtubeId: "" },
    { id: "v3", title: { bn: "ফল বাগানের যত্ন", en: "Caring for a fruit orchard" }, youtubeId: "" },
    { id: "v4", title: { bn: "কম পানিতে সেচ", en: "Irrigation with less water" }, youtubeId: "" },
  ];

  // Short, general tips only (no doses, no numbers). Link later to your verified knowledge base.
  const TIPS = [
    { id: "b1", tag: { bn: "মাটি", en: "Soil" }, color: "leaf", title: { bn: "চাষের আগে মাটি তৈরি করুন", en: "Prepare soil before planting" }, body: { bn: "জৈব সার মেশান, মাটি ঝুরঝুরে রাখুন এবং সম্ভব হলে মাটি পরীক্ষা করান।", en: "Mix in organic matter, keep the soil loose, and get a soil test if you can." } },
    { id: "b2", tag: { bn: "সেচ", en: "Irrigation" }, color: "sky", title: { bn: "সঠিক সময়ে সেচ দিন", en: "Water at the right time" }, body: { bn: "সকাল বা বিকেলে সেচ দিলে পানি কম শুকায়। জমিতে পানি জমে থাকতে দেবেন না।", en: "Watering in the morning or evening loses less water. Do not let water stand in the field." } },
    { id: "b3", tag: { bn: "পোকা দমন", en: "Pest control" }, color: "rose", title: { bn: "আগে প্রাকৃতিক উপায়ে পোকা দমন", en: "Try natural pest control first" }, body: { bn: "নিয়মিত জমি দেখুন, আক্রান্ত পাতা সরান। কীটনাশক লাগলে কৃষি অফিসের পরামর্শ নিন।", en: "Check the field often and remove damaged leaves. Ask the agriculture office before using pesticide." } },
    { id: "b4", tag: { bn: "ফসল পরিবর্তন", en: "Crop rotation" }, color: "amber", title: { bn: "প্রতি মৌসুমে ফসল বদলান", en: "Rotate crops each season" }, body: { bn: "একই জমিতে বারবার একই ফসল না করলে মাটি ভালো থাকে এবং রোগ কম হয়।", en: "Not growing the same crop again and again keeps soil healthy and reduces disease." } },
  ];

  window.CB = Object.assign(window.CB || {}, { DEMO: { PRODUCTS, TOOLS, VIDEOS, TIPS } });
})();
