/**
 * districts.js — all 64 districts of Bangladesh, grouped by the 8 divisions.
 * TEMPORARY: later load this from your admin reference table via the API,
 * so spellings and IDs match the backend exactly.
 */
(function () {
  const DIVISIONS = [
    { key: "Barishal", bn: "বরিশাল", districts: [
      ["Barguna", "বরগুনা"], ["Barishal", "বরিশাল"], ["Bhola", "ভোলা"], ["Jhalokathi", "ঝালকাঠি"],
      ["Patuakhali", "পটুয়াখালী"], ["Pirojpur", "পিরোজপুর"]] },
    { key: "Chattogram", bn: "চট্টগ্রাম", districts: [
      ["Bandarban", "বান্দরবান"], ["Brahmanbaria", "ব্রাহ্মণবাড়িয়া"], ["Chandpur", "চাঁদপুর"],
      ["Chattogram", "চট্টগ্রাম"], ["Cumilla", "কুমিল্লা"], ["Cox's Bazar", "কক্সবাজার"], ["Feni", "ফেনী"],
      ["Khagrachhari", "খাগড়াছড়ি"], ["Lakshmipur", "লক্ষ্মীপুর"], ["Noakhali", "নোয়াখালী"], ["Rangamati", "রাঙ্গামাটি"]] },
    { key: "Dhaka", bn: "ঢাকা", districts: [
      ["Dhaka", "ঢাকা"], ["Faridpur", "ফরিদপুর"], ["Gazipur", "গাজীপুর"], ["Gopalganj", "গোপালগঞ্জ"],
      ["Kishoreganj", "কিশোরগঞ্জ"], ["Madaripur", "মাদারীপুর"], ["Manikganj", "মানিকগঞ্জ"], ["Munshiganj", "মুন্সীগঞ্জ"],
      ["Narayanganj", "নারায়ণগঞ্জ"], ["Narsingdi", "নরসিংদী"], ["Rajbari", "রাজবাড়ী"], ["Shariatpur", "শরীয়তপুর"],
      ["Tangail", "টাঙ্গাইল"]] },
    { key: "Khulna", bn: "খুলনা", districts: [
      ["Bagerhat", "বাগেরহাট"], ["Chuadanga", "চুয়াডাঙ্গা"], ["Jashore", "যশোর"], ["Jhenaidah", "ঝিনাইদহ"],
      ["Khulna", "খুলনা"], ["Kushtia", "কুষ্টিয়া"], ["Magura", "মাগুরা"], ["Meherpur", "মেহেরপুর"],
      ["Narail", "নড়াইল"], ["Satkhira", "সাতক্ষীরা"]] },
    { key: "Mymensingh", bn: "ময়মনসিংহ", districts: [
      ["Jamalpur", "জামালপুর"], ["Mymensingh", "ময়মনসিংহ"], ["Netrokona", "নেত্রকোনা"], ["Sherpur", "শেরপুর"]] },
    { key: "Rajshahi", bn: "রাজশাহী", districts: [
      ["Bogura", "বগুড়া"], ["Chapainawabganj", "চাঁপাইনবাবগঞ্জ"], ["Joypurhat", "জয়পুরহাট"], ["Naogaon", "নওগাঁ"],
      ["Natore", "নাটোর"], ["Pabna", "পাবনা"], ["Rajshahi", "রাজশাহী"], ["Sirajganj", "সিরাজগঞ্জ"]] },
    { key: "Rangpur", bn: "রংপুর", districts: [
      ["Dinajpur", "দিনাজপুর"], ["Gaibandha", "গাইবান্ধা"], ["Kurigram", "কুড়িগ্রাম"], ["Lalmonirhat", "লালমনিরহাট"],
      ["Nilphamari", "নীলফামারী"], ["Panchagarh", "পঞ্চগড়"], ["Rangpur", "রংপুর"], ["Thakurgaon", "ঠাকুরগাঁও"]] },
    { key: "Sylhet", bn: "সিলেট", districts: [
      ["Habiganj", "হবিগঞ্জ"], ["Moulvibazar", "মৌলভীবাজার"], ["Sunamganj", "সুনামগঞ্জ"], ["Sylhet", "সিলেট"]] },
  ];

  const BY_KEY = {};
  DIVISIONS.forEach((d) => d.districts.forEach(([en, bn]) => { BY_KEY[en] = { en, bn, division: d.key }; }));

  /** Fill a <select> with optgroups by division. firstLabelKey = i18n key for the empty option. */
  function fillDistrictSelect(select, firstLabelKey) {
    const keep = select.value;
    const lang = window.CB.getLang();
    select.innerHTML = "";
    const first = document.createElement("option");
    first.value = ""; first.textContent = window.CB.t(firstLabelKey);
    select.appendChild(first);
    DIVISIONS.forEach((d) => {
      const g = document.createElement("optgroup");
      g.label = lang === "bn" ? `${d.bn} বিভাগ` : `${d.key} Division`;
      d.districts.forEach(([en, bn]) => {
        const o = document.createElement("option");
        o.value = en; o.textContent = lang === "bn" ? bn : en;
        g.appendChild(o);
      });
      select.appendChild(g);
    });
    select.value = keep;
  }

  function districtName(key) {
    const d = BY_KEY[key];
    if (!d) return key || "";
    return window.CB.getLang() === "bn" ? d.bn : d.en;
  }

  window.CB = Object.assign(window.CB || {}, { DIVISIONS, DISTRICTS: BY_KEY, fillDistrictSelect, districtName });
})();
