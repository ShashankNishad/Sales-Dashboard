/* data_management.js - Page 3 logic */

let dmRows = [];
let dmSelected = new Set();

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function loadFilterOptions() {
  try {
    const [brands, doors, statuses, clusters] = await Promise.all([
      apiGet("/api/brands"), apiGet("/api/doors"), apiGet("/api/statuses"), apiGet("/api/clusters"),
    ]);
    document.getElementById("dm-brand").innerHTML = '<option value="ALL">ALL</option>' +
      brands.brands.map((b) => `<option value="${escapeHtml(b)}">${escapeHtml(b)}</option>`).join("");
    document.getElementById("dm-door").innerHTML = '<option value="ALL">ALL</option>' +
      doors.doors.map((d) => `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join("");
    document.getElementById("dm-status").innerHTML = '<option value="ALL">ALL</option>' +
      statuses.statuses.map((s) => `<option value="${s}">${s}</option>`).join("");
    document.getElementById("dm-cluster").innerHTML = '<option value="ALL">ALL</option>' +
      clusters.clusters.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
  } catch (err) { /* non-fatal */ }
}

function statusBadge(status) {
  const cls = (status || "").toUpperCase() === "RECEIVED" ? "badge-received" : "badge-pending";
  return `<span class="badge ${cls}">${escapeHtml(status || "PENDING")}</span>`;
}

function renderRows() {
  const tbody = document.getElementById("dm-body");
  if (!dmRows.length) {
    tbody.innerHTML = '<tr><td colspan="14" class="empty-state">No matching records.</td></tr>';
    updateDeleteButton();
    return;
  }
  tbody.innerHTML = dmRows.map((r) => `
    <tr data-id="${r.id}">
      <td class="checkbox-cell"><input type="checkbox" class="dm-row-checkbox" data-id="${r.id}" ${dmSelected.has(r.id) ? "checked" : ""}></td>
      <td>${escapeHtml(r.door)}</td>
      <td>${escapeHtml(r.brand)}</td>
      <td>${escapeHtml(r.cluster || "")}</td>
      <td>${escapeHtml(r.door_type || "")}</td>
      <td>${escapeHtml(r.date || "")}</td>
      <td>${formatMoney(r.amount)}</td>
      <td>${statusBadge(r.status)}</td>
      <td>${formatMoney(r.os)}</td>
      <td>${formatMoney(r.sixty_plus)}</td>
      <td>${formatMoney(r.target)}</td>
      <td>${escapeHtml(r.reminder_remark || "")}</td>
      <td>${escapeHtml(r.commitment_date || "")}</td>
      <td>${r.commitment_amount != null ? formatMoney(r.commitment_amount) : ""}</td>
      <td><button class="btn-secondary btn-sm" onclick='openEditModal(${r.id})'>EDIT</button></td>
    </tr>
  `).join("");

  document.querySelectorAll(".dm-row-checkbox").forEach((cb) => {
    cb.addEventListener("change", () => {
      const id = Number(cb.dataset.id);
      if (cb.checked) dmSelected.add(id); else dmSelected.delete(id);
      updateDeleteButton();
    });
  });
  updateDeleteButton();
}

function updateDeleteButton() {
  const btn = document.getElementById("dm-delete-btn");
  btn.disabled = dmSelected.size === 0;
  btn.textContent = dmSelected.size ? `DELETE SELECTED (${dmSelected.size})` : "DELETE SELECTED";
}

async function runSearch() {
  const params = new URLSearchParams();
  const dateFrom = document.getElementById("dm-date-from").value;
  const dateTo = document.getElementById("dm-date-to").value;
  const brand = document.getElementById("dm-brand").value;
  const door = document.getElementById("dm-door").value;
  const cluster = document.getElementById("dm-cluster").value;
  const status = document.getElementById("dm-status").value;
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  if (brand) params.set("brand", brand);
  if (door) params.set("door", door);
  if (cluster) params.set("cluster", cluster);
  if (status) params.set("status", status);

  const tbody = document.getElementById("dm-body");
  tbody.innerHTML = '<tr><td colspan="14" class="empty-state">Searching...</td></tr>';
  try {
    const data = await apiGet(`/api/data/search?${params.toString()}`);
    dmRows = data.rows;
    dmSelected.clear();
    document.getElementById("dm-result-count").textContent = `${data.count} record(s) found.`;
    renderRows();
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="14" class="empty-state">Search failed: ${escapeHtml(err.message)}</td></tr>`;
  }
}

function openEditModal(id) {
  const record = dmRows.find((r) => r.id === id);
  if (!record) return;
  const { close } = openModal({
    title: `Edit Record — ${escapeHtml(record.door)}`,
    bodyHtml: `
      <div class="field" style="margin-bottom:10px;">
        <label>Amount</label>
        <input type="number" id="edit-amount" value="${record.amount ?? 0}" style="width:100%;">
      </div>
      <div class="field" style="margin-bottom:10px;">
        <label>Status</label>
        <select id="edit-status" style="width:100%;">
          <option value="RECEIVED" ${record.status === "RECEIVED" ? "selected" : ""}>RECEIVED</option>
          <option value="PENDING" ${record.status === "PENDING" ? "selected" : ""}>PENDING</option>
        </select>
      </div>
      <div class="field" style="margin-bottom:10px;">
        <label>Cluster</label>
        <input type="text" id="edit-cluster" value="${escapeHtml(record.cluster || "")}" placeholder="e.g. Shashank" style="width:100%;">
      </div>
      <div class="field" style="margin-bottom:10px;">
        <label>Reminder Remark</label>
        <textarea id="edit-remark" rows="2" style="width:100%;">${escapeHtml(record.reminder_remark || "")}</textarea>
      </div>
      <div class="field" style="margin-bottom:10px;">
        <label>Commitment Date</label>
        <input type="date" id="edit-commit-date" value="${record.commitment_date || ""}" style="width:100%;">
      </div>
      <div class="field">
        <label>Commitment Amount</label>
        <input type="number" id="edit-commit-amount" value="${record.commitment_amount ?? ""}" style="width:100%;">
      </div>
      <div class="muted" style="margin-top:10px;font-size:12px;">Changing the remark auto-updates Reminder Date to today.</div>
    `,
    actions: [
      { label: "Cancel", className: "btn-secondary", onClick: (close) => close() },
      {
        label: "Save Changes",
        className: "btn-primary",
        onClick: async (close) => {
          try {
            await apiPost(`/api/data/update/${id}`, {
              amount: Number(document.getElementById("edit-amount").value),
              status: document.getElementById("edit-status").value,
              cluster: document.getElementById("edit-cluster").value || null,
              reminder_remark: document.getElementById("edit-remark").value,
              commitment_date: document.getElementById("edit-commit-date").value || null,
              commitment_amount: document.getElementById("edit-commit-amount").value || null,
            });
            showToast("Record updated.", "success");
            close();
            runSearch();
          } catch (err) {
            showToast("Update failed: " + err.message, "error");
          }
        },
      },
    ],
  });
}
window.openEditModal = openEditModal;

function confirmDelete() {
  const count = dmSelected.size;
  if (!count) return;
  const { close } = openModal({
    title: "WARNING",
    bodyHtml: `This action will permanently delete <b>${count}</b> selected record(s).<br><br>Are you sure you want to continue?`,
    actions: [
      { label: "CANCEL", className: "btn-secondary", onClick: (close) => close() },
      { label: "DELETE", className: "btn-danger", onClick: (close) => { close(); askPasswordAndDelete(); } },
    ],
  });
}

function askPasswordAndDelete() {
  const { close, box } = openModal({
    title: "Confirm Password",
    bodyHtml: `
      <div class="field">
        <label>Enter password to confirm deletion</label>
        <input type="password" id="delete-password" style="width:100%;" placeholder="Password">
      </div>
      <div id="delete-password-error" style="color:#e0393f;font-size:12px;margin-top:8px;"></div>
    `,
    actions: [
      { label: "Cancel", className: "btn-secondary", onClick: (close) => close() },
      {
        label: "Delete",
        className: "btn-danger",
        onClick: async (close) => {
          const password = document.getElementById("delete-password").value;
          try {
            const data = await apiPost("/api/data/delete", { ids: Array.from(dmSelected), password });
            showToast("Data deleted successfully.", "success");
            close();
            dmSelected.clear();
            runSearch();
          } catch (err) {
            document.getElementById("delete-password-error").textContent = err.message || "Incorrect password.";
          }
        },
      },
    ],
  });
  setTimeout(() => box.querySelector("#delete-password")?.focus(), 50);
}

/* ---------------- Backups panel ---------------- */
async function loadBackupsList() {
  const tbody = document.getElementById("dm-backups-body");
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="4" class="empty-state">Loading...</td></tr>';
  try {
    const data = await apiGet("/api/backup/list");
    if (!data.backups.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No backups yet. Click "Backup Data" in the sidebar to create one.</td></tr>';
      return;
    }
    tbody.innerHTML = data.backups.map((b) => `
      <tr>
        <td>${escapeHtml(b.filename)}</td>
        <td>${escapeHtml(b.created_at)}</td>
        <td>${b.size_kb} KB</td>
        <td><a class="btn-secondary btn-sm" href="/api/backup/file/${encodeURIComponent(b.filename)}">Download</a></td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty-state">Failed to load backups: ${escapeHtml(err.message)}</td></tr>`;
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  await loadFilterOptions();
  await loadBackupsList();

  document.getElementById("dm-search-btn").addEventListener("click", runSearch);
  document.getElementById("dm-delete-btn").addEventListener("click", confirmDelete);
  document.getElementById("dm-refresh-backups")?.addEventListener("click", loadBackupsList);
  document.getElementById("dm-select-all").addEventListener("click", () => {
    const allSelected = dmSelected.size === dmRows.length && dmRows.length > 0;
    dmSelected.clear();
    if (!allSelected) dmRows.forEach((r) => dmSelected.add(r.id));
    renderRows();
  });
  document.getElementById("dm-header-checkbox").addEventListener("change", (e) => {
    dmSelected.clear();
    if (e.target.checked) dmRows.forEach((r) => dmSelected.add(r.id));
    renderRows();
  });
});

window.onDataChanged = async () => {
  await loadFilterOptions();
  await loadBackupsList();
  runSearch();
};
