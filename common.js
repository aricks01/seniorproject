// Shared frontend logic for StegApp. Talks to the Kali-utility API.
// API contract (unchanged from the original prototype):
//   POST /api/embed    (multipart) -> file blob
//   POST /api/extract  (multipart) -> file blob
//   POST /api/detect   (multipart) -> { job_id }        then poll
//   POST /api/crack    (multipart) -> { job_id }        then poll
//   GET  /api/wordlists            -> ["rockyou.txt", ...]
//   GET  /api/jobs/{id}            -> { state, percent?, result?, passphrase?, download? }
//   POST /api/jobs/{id}/cancel

const sleep = ms => new Promise(r => setTimeout(r, ms));
const esc = s => String(s).replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---- API key: shared across pages via localStorage + topbar field ----
const API_KEY = "stegapp_api_key";
function wireApiKey() {
  const field = document.getElementById("apikey");
  if (!field) return;
  field.value = localStorage.getItem(API_KEY) || "";
  field.addEventListener("input", () => localStorage.setItem(API_KEY, field.value));
}
const keyHdr = () => {
  const k = localStorage.getItem(API_KEY) || "";
  return k ? { "X-API-Key": k } : {};
};

// ---- Nav highlight ----
function wireNav() {
  const here = (location.pathname.split("/").pop() || "index.html");
  document.querySelectorAll("nav.ops a").forEach(a => {
    if (a.getAttribute("href") === here) a.classList.add("active");
  });
}

// ---- Output helpers ----
function setOut(out, msg, cls) {
  out.className = "out" + (cls ? " " + cls : "");
  out.textContent = msg;
}

function saveBlob(blob, name) {
  const a = Object.assign(document.createElement("a"),
    { href: URL.createObjectURL(blob), download: name });
  a.click();
  URL.revokeObjectURL(a.href);
}

async function fail(res) {
  const j = await res.json().catch(() => ({}));
  throw new Error(j.detail || res.statusText || "Request failed");
}

// ---- Populate wordlist <select> if present on this page ----
async function loadWordlists() {
  const sel = document.querySelector("select[name=wordlist_name]");
  if (!sel) return;
  try {
    const r = await fetch("/api/wordlists", { headers: keyHdr() });
    if (!r.ok) throw new Error();
    const list = await r.json();
    sel.innerHTML = list.map(n => `<option>${esc(n)}</option>`).join("")
      || `<option value="">(none available)</option>`;
  } catch {
    sel.innerHTML = `<option value="">(could not load server wordlists)</option>`;
  }
}

// ---- Wire every operation form on the page ----
function wireForms() {
  document.querySelectorAll("form[data-endpoint]").forEach(form => {
    const out = form.querySelector(".out");
    const bar = form.querySelector(".bar > i");
    form.addEventListener("submit", async e => {
      e.preventDefault();
      const btn = form.querySelector("button:not([type=button])");
      btn.disabled = true;
      setOut(out, "Working…", "busy");
      if (bar) bar.style.width = "0";
      try {
        const fd = new FormData(form);
        // drop empty optional file inputs so the server sees "no upload"
        for (const [k, v] of [...fd]) if (v instanceof File && !v.name) fd.delete(k);
        const res = await fetch(form.dataset.endpoint,
          { method: "POST", body: fd, headers: keyHdr() });
        if (!res.ok) await fail(res);
        if (form.dataset.mode === "file") {
          saveBlob(await res.blob(), form.dataset.name || "output.bin");
          setOut(out, "Done — file downloaded.", "ok");
        } else {
          const { job_id } = await res.json();
          if (!job_id) throw new Error("server did not return a job id");
          await pollJob(job_id, form, out, bar);
        }
      } catch (err) {
        setOut(out, "Error: " + err.message, "err");
      } finally {
        btn.disabled = false;
      }
    });
  });
}

async function pollJob(id, form, out, bar) {
  const cancel = form.querySelector("[data-cancel]");
  if (cancel) {
    cancel.hidden = false;
    cancel.onclick = () =>
      fetch(`/api/jobs/${id}/cancel`, { method: "POST", headers: keyHdr() });
  }
  try {
    while (true) {
      const res = await fetch(`/api/jobs/${id}`, { headers: keyHdr() });
      if (!res.ok) await fail(res);
      const j = await res.json();
      if (j.state === "queued" || j.state === "running") {
        setOut(out, j.state + (j.percent != null ? ` — ${j.percent}%` : "…"), "busy");
        if (bar && j.percent != null) bar.style.width = j.percent + "%";
        await sleep(1500);
        continue;
      }
      if (bar) bar.style.width = "100%";
      if (j.state === "cancelled") { setOut(out, "Job cancelled.", null); return; }
      if (j.state === "failed")    { setOut(out, "Job failed.", "err"); return; }
      if (j.result === "found") {
        if (j.passphrase) {
          setOut(out, `Passphrase found: ${j.passphrase}  `, "ok");
          if (j.download) {
            out.appendChild(Object.assign(document.createElement("a"),
              { href: j.download, textContent: "Download extracted file" }));
          }
        } else {
          setOut(out, "Hidden data likely present.", "ok");
        }
      } else {
        setOut(out, "Result: " + String(j.result).replace(/_/g, " "), null);
      }
      return;
    }
  } finally {
    if (cancel) cancel.hidden = true;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  wireApiKey();
  wireNav();
  loadWordlists();
  wireForms();
});
