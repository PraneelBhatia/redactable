// Popup logic — reuses the deterministic engine (no model, fully offline).
// redactable.js is copied into this folder so the unpacked extension is self-contained;
// it is generated from web/redactable.js (keep them in sync, or symlink during dev).
import { scrub } from "./redactable.js";

const $ = (id) => document.getElementById(id);

function run() {
  const r = scrub($("in").value, { numbered: true });
  $("out").value = r.text;
  const total = r.spans.length;
  $("stats").textContent = total
    ? `${total} identifier${total === 1 ? "" : "s"} struck · ` +
      Object.entries(r.counts).map(([t, n]) => `${t} ${n}`).join(" · ")
    : "nothing detected";
}

$("scrub").onclick = run;
$("in").addEventListener("input", run);
$("copy").onclick = async () => {
  await navigator.clipboard.writeText($("out").value);
  $("copy").textContent = "Copied ✓";
  setTimeout(() => ($("copy").textContent = "Copy safe text"), 1200);
};
