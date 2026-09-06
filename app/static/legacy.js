"use strict";
const key = "nbtc_brief_v1";
const button = document.getElementById("legacyDownload");
const status = document.getElementById("legacyStatus");
let legacy = null;
try {
  legacy = JSON.parse(localStorage.getItem(key) || "null");
} catch (_) {
  status.textContent = "The legacy browser data is not valid JSON.";
}
if (legacy && typeof legacy === "object") {
  const counts = ["interests", "watchlist", "archive", "assessments"]
    .map(name => `${name}: ${Array.isArray(legacy[name]) ? legacy[name].length : 0}`).join(", ");
  status.textContent = `Legacy data found (${counts}).`;
  button.disabled = false;
} else if (!status.textContent.includes("valid JSON")) {
  status.textContent = "No legacy data was found for this browser and origin.";
}
button.addEventListener("click", () => {
  const state = {};
  for (const name of ["interests", "watchlist", "archive", "assessments"]) {
    state[name] = Array.isArray(legacy[name]) ? legacy[name] : [];
  }
  const payload = {format:"nbtc-brief-legacy", version:1, exportedAt:new Date().toISOString(), state};
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {type:"application/json"}));
  link.download = `nbtc-brief-legacy-${new Date().toISOString().slice(0,10)}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
});
