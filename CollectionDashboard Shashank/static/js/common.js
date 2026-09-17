/* common.js - shared helpers used across all pages */

function showToast(message, type = "success") {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3800);
}

function formatMoney(value) {
  const num = Number(value) || 0;
  return "\u20B9 " + num.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function formatPct(value) {
  return `${Number(value || 0).toFixed(1)}%`;
}

async function apiGet(url) {
  const res = await fetch(url);
  const data = await res.json().catch(() => ({ success: false, error: "Invalid server response." }));
  if (!res.ok || data.success === false) {
    throw new Error(data.error || "Request failed.");
  }
  return data;
}

async function apiPost(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await res.json().catch(() => ({ success: false, error: "Invalid server response." }));
  if (!res.ok || data.success === false) {
    throw new Error(data.error || "Request failed.");
  }
  return data;
}

function openModal({ title, bodyHtml, actions }) {
  const root = document.getElementById("modal-root");
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  const box = document.createElement("div");
  box.className = "modal-box";
  box.innerHTML = `
    <div class="modal-title">${title}</div>
    <div class="modal-body">${bodyHtml}</div>
    <div class="modal-actions" id="modal-actions"></div>
  `;
  overlay.appendChild(box);
  root.appendChild(overlay);

  const actionsEl = box.querySelector("#modal-actions");
  const close = () => overlay.remove();
  (actions || []).forEach((a) => {
    const btn = document.createElement("button");
    btn.textContent = a.label;
    btn.className = a.className || "btn-secondary";
    btn.onclick = () => a.onClick(close);
    actionsEl.appendChild(btn);
  });
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  return { close, box };
}

/* ---------------- Backup (available on every page) ---------------- */
async function downloadBackupNow(silent) {
  try {
    if (!silent) showToast("Preparing backup file...", "success");
    window.location.assign("/api/backup/download");
    dataBackedUpThisSession = true;
  } catch (err) {
    showToast("Backup failed: " + err.message, "error");
  }
}
window.downloadBackupNow = downloadBackupNow;

let dataBackedUpThisSession = false;

document.addEventListener("DOMContentLoaded", () => {
  const backupBtn = document.getElementById("global-backup-btn");
  if (backupBtn) {
    backupBtn.addEventListener("click", () => downloadBackupNow(false));
  }

  const exportBtn = document.getElementById("create-html-data-btn");
  if (exportBtn) {
    exportBtn.addEventListener("click", () => {
      const modal = openModal({
        title: "Create HTML with Data",
        bodyHtml: `
          <div class="field" style="margin-bottom:12px;">
            <label>Date From</label>
            <input type="date" id="export-date-from">
          </div>
          <div class="field">
            <label>Date To</label>
            <input type="date" id="export-date-to">
          </div>
        `,
        actions: [
          { label: "Cancel", className: "btn-secondary", onClick: (close) => close() },
          {
            label: "Create HTML",
            className: "btn-primary",
            onClick: async (close) => {
              const from = document.getElementById("export-date-from").value;
              const to = document.getElementById("export-date-to").value;
              if (!from || !to) {
                showToast("Please select both dates before generating the HTML export.", "error");
                return;
              }
              try {
                const url = `/api/export/html-snapshot?date_from=${encodeURIComponent(from)}&date_to=${encodeURIComponent(to)}`;
                const response = await fetch(url);
                const blob = await response.blob();
                const disposition = response.headers.get("Content-Disposition") || "attachment";
                const match = disposition.match(/filename\s*=\s*"?([^";]+)"?/i) || [];
                const filename = match[1] || `Collection_Dashboard_${from}_to_${to}.html`;
                const link = document.createElement("a");
                link.href = URL.createObjectURL(blob);
                link.download = filename;
                document.body.appendChild(link);
                link.click();
                link.remove();
                URL.revokeObjectURL(link.href);
                showToast("HTML snapshot downloaded.", "success");
                close();
              } catch (err) {
                showToast("Failed to create HTML snapshot: " + err.message, "error");
              }
            },
          },
        ],
      });
      if (modal && modal.box) {
        const box = modal.box;
        const form = box.querySelector("#export-date-from");
        if (form) form.focus();
      }
    });
  }
});

/* Gentle reminder when leaving/closing the tab: browsers only allow a
   generic native prompt here (no custom Yes/No + auto-download is possible
   for security reasons), so this just nudges the user to click
   "Backup Data" before they close, if they haven't already this session. */
window.addEventListener("beforeunload", (e) => {
  if (!dataBackedUpThisSession) {
    e.preventDefault();
    e.returnValue = "Have you backed up your data? Click 'Backup Data' in the sidebar before closing.";
    return e.returnValue;
  }
});

/* ---------------- Global Excel upload (available on every page) ---------------- */
document.addEventListener("DOMContentLoaded", () => {
  const uploadInput = document.getElementById("global-upload");
  const statusEl = document.getElementById("upload-status");
  if (!uploadInput) return;

  uploadInput.addEventListener("change", async () => {
    const file = uploadInput.files[0];
    if (!file) return;
    statusEl.textContent = "Uploading...";

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/upload", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok || !data.success) {
        if (data.missing_columns) {
          showToast(`Upload failed. Missing column: ${data.missing_columns.join(", ")}`, "error");
          statusEl.textContent = `Missing: ${data.missing_columns.join(", ")}`;
        } else {
          showToast(data.error || "Upload failed.", "error");
          statusEl.textContent = "Upload failed.";
        }
        return;
      }
      showToast(`\u2713 ${data.inserted.toLocaleString()} records uploaded successfully.`, "success");
      statusEl.textContent = `${data.inserted} inserted, ${data.skipped} skipped.`;
      if (typeof window.onDataChanged === "function") {
        window.onDataChanged();
      }
    } catch (err) {
      showToast("Upload failed: " + err.message, "error");
      statusEl.textContent = "Upload failed.";
    } finally {
      uploadInput.value = "";
    }
  });
});
