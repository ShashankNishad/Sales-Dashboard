/* details.js - Page 2 logic */

let paymentsState = { page: 1, page_size: 25, sort: "date", dir: "desc", total: 0 };

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function achievementPct(target, collection) {
  return target ? Math.round((collection / target) * 1000) / 10 : 0;
}

async function loadKpis() {
  try {
    const params = new URLSearchParams();
    const door = document.getElementById("payments-door")?.value || "ALL";
    const brand = document.getElementById("payments-brand")?.value || "ALL";
    const status = document.getElementById("payments-status")?.value || "ALL";
    const dateFrom = document.getElementById("payments-date-from")?.value || "";
    const dateTo = document.getElementById("payments-date-to")?.value || "";
    if (door && door !== "ALL") params.set("door", door);
    if (brand && brand !== "ALL") params.set("brand", brand);
    if (status && status !== "ALL") params.set("status", status);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    const data = await apiGet(`/api/dashboard/kpis${params.toString() ? `?${params.toString()}` : ""}`);
    document.getElementById("kpi-target").textContent = formatMoney(data.total_target);
    document.getElementById("kpi-collection").textContent = formatMoney(data.total_collection);
    document.getElementById("kpi-os").textContent = formatMoney(data.total_os);
    document.getElementById("kpi-sixty").textContent = formatMoney(data.total_sixty_plus);
    document.getElementById("kpi-amount").textContent = formatMoney(data.total_commitment_amount ?? data.total_amount);
  } catch (err) { showToast(err.message, "error"); }
}

async function loadDoorSelect() {
  const select = document.getElementById("details-door-select");
  try {
    const data = await apiGet("/api/doors");
    select.innerHTML = '<option value="">-- Choose a door --</option>' +
      data.doors.map((d) => `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join("");
  } catch (err) { showToast(err.message, "error"); }
}

async function loadBrandFilter() {
  const select = document.getElementById("payments-brand");
  try {
    const data = await apiGet("/api/brands");
    select.innerHTML = '<option value="ALL">ALL</option>' +
      data.brands.map((b) => `<option value="${escapeHtml(b)}">${escapeHtml(b)}</option>`).join("");
  } catch (err) { /* non-fatal */ }
}

async function loadStatusFilter() {
  const select = document.getElementById("payments-status");
  try {
    const data = await apiGet("/api/statuses");
    select.innerHTML = '<option value="ALL">ALL</option>' +
      data.statuses.map((s) => `<option value="${s}">${s}</option>`).join("");
  } catch (err) { /* non-fatal */ }
}

async function loadDoorBrandSummary(door) {
  const tbody = document.getElementById("door-brand-body");
  const tfoot = document.getElementById("door-brand-foot");
  if (!door) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-state">Select a door above.</td></tr>';
    tfoot.innerHTML = "";
    return;
  }
  tbody.innerHTML = '<tr><td colspan="6" class="empty-state">Loading...</td></tr>';
  tfoot.innerHTML = "";
  try {
    const data = await apiGet(`/api/details/door-brand-summary?door=${encodeURIComponent(door)}`);
    if (!data.brands.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No records for this door.</td></tr>';
      return;
    }
    tbody.innerHTML = data.brands.map((b) => `
      <tr>
        <td>${escapeHtml(b.brand)}</td>
        <td>${formatMoney(b.target)}</td>
        <td>${formatMoney(b.collection)}</td>
        <td>${formatPct(b.achievement_pct)}</td>
        <td>${formatMoney(b.received)}</td>
        <td>${formatMoney(b.pending)}</td>
      </tr>
    `).join("");
    const totalTarget = data.brands.reduce((s, b) => s + Number(b.target || 0), 0);
    const totalCollection = data.brands.reduce((s, b) => s + Number(b.collection || 0), 0);
    const totalReceived = data.brands.reduce((s, b) => s + Number(b.received || 0), 0);
    const totalPending = data.brands.reduce((s, b) => s + Number(b.pending || 0), 0);
    tfoot.innerHTML = `
      <tr>
        <td>TOTAL</td>
        <td>${formatMoney(totalTarget)}</td>
        <td>${formatMoney(totalCollection)}</td>
        <td>${formatPct(achievementPct(totalTarget, totalCollection))}</td>
        <td>${formatMoney(totalReceived)}</td>
        <td>${formatMoney(totalPending)}</td>
      </tr>
    `;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Failed to load: ${escapeHtml(err.message)}</td></tr>`;
    tfoot.innerHTML = "";
  }
}

function statusBadge(status) {
  const cls = (status || "").toUpperCase() === "RECEIVED" ? "badge-received" : "badge-pending";
  return `<span class="badge ${cls}">${escapeHtml(status || "PENDING")}</span>`;
}

async function loadGroupedCollectionSummary() {
  const params = new URLSearchParams();
  const door = document.getElementById("payments-door").value;
  const brand = document.getElementById("payments-brand").value;
  const status = document.getElementById("payments-status").value;
  const search = document.getElementById("payments-search").value.trim();
  const dateFrom = document.getElementById("payments-date-from").value;
  const dateTo = document.getElementById("payments-date-to").value;
  if (door && door !== "ALL") params.set("door", door);
  if (brand && brand !== "ALL") params.set("brand", brand);
  if (status && status !== "ALL") params.set("status", status);
  if (search) params.set("search", search);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  try {
    const data = await apiGet(`/api/details/grouped-payments${params.toString() ? `?${params.toString()}` : ""}`);
    const totalEl = document.getElementById("grouped-total-collection");
    totalEl.textContent = formatMoney(data.total_collection ?? 0);
    return data;
  } catch (err) {
    const totalEl = document.getElementById("grouped-total-collection");
    totalEl.textContent = "₹ 0";
    return { rows: [] };
  }
}

async function loadPayments() {
  const tbody = document.getElementById("payments-body");
  const params = new URLSearchParams();
  const search = document.getElementById("payments-search").value.trim();
  const door = document.getElementById("payments-door").value;
  const brand = document.getElementById("payments-brand").value;
  const status = document.getElementById("payments-status").value;
  const dateFrom = document.getElementById("payments-date-from").value;
  const dateTo = document.getElementById("payments-date-to").value;
  if (search) params.set("search", search);
  if (door && door !== "ALL") params.set("door", door);
  if (brand && brand !== "ALL") params.set("brand", brand);
  if (status && status !== "ALL") params.set("status", status);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);

  tbody.innerHTML = '<tr><td colspan="6" class="empty-state">Loading...</td></tr>';
  try {
    const data = await apiGet(`/api/details/grouped-payments${params.toString() ? `?${params.toString()}` : ""}`);
    if (!data.rows.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No matching records.</td></tr>';
      document.getElementById("grouped-total-collection").textContent = "₹ 0";
    } else {
      tbody.innerHTML = data.rows.map((r) => {
        const dateRange = r.date_from && r.date_to ? `${r.date_from} to ${r.date_to}` : (r.date_from || r.date_to || "-");
        return `
          <tr data-group="${escapeHtml(r.brand)}|${escapeHtml(r.door)}|${escapeHtml(r.cluster || "Unassigned")}">
            <td>${escapeHtml(r.brand)}</td>
            <td>${escapeHtml(r.door)}</td>
            <td>${escapeHtml(r.cluster || "Unassigned")}</td>
            <td>${escapeHtml(dateRange)}</td>
            <td>${formatMoney(r.collection)}</td>
            <td><button class="btn-secondary btn-sm" onclick="showGroupedRecordDetails(${JSON.stringify(r).replace(/"/g, '&quot;')})">View Details</button></td>
          </tr>
        `;
      }).join("");
      document.getElementById("grouped-total-collection").textContent = formatMoney(data.total_collection ?? 0);
    }
    paymentsState.total = data.total || 0;
    const totalPages = Math.max(Math.ceil(paymentsState.total / paymentsState.page_size), 1);
    document.getElementById("payments-page-info").textContent =
      `Page ${paymentsState.page} of ${totalPages} — ${paymentsState.total} groups`;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Failed to load: ${escapeHtml(err.message)}</td></tr>`;
  }
  await loadKpis();
}

function showGroupedRecordDetails(group) {
  const rows = (group.records || []).slice().sort((a, b) => {
    const da = new Date(a.date || "2000-01-01");
    const db = new Date(b.date || "2000-01-01");
    return da - db;
  });
  const body = rows.map((r) => `
    <tr>
      <td>${escapeHtml(r.date || "")}</td>
      <td>${formatMoney(r.amount || 0)}</td>
      <td>${statusBadge(r.status)}</td>
      <td><button class="btn-secondary btn-sm" onclick="openReminderModal(${r.id}, ${JSON.stringify(r).replace(/"/g, '&quot;')})">Update</button></td>
    </tr>
  `).join("");
  openModal({
    title: `${group.brand} | ${group.door} | ${group.cluster || "Unassigned"}`,
    bodyHtml: `
      <div class="muted" style="margin-bottom:12px;">Grouped collection: ${formatMoney(group.collection || 0)}</div>
      <table>
        <thead>
          <tr><th>Date</th><th>Collection</th><th>Status</th><th>Action</th></tr>
        </thead>
        <tbody>${body || '<tr><td colspan="4" class="empty-state">No raw records.</td></tr>'}</tbody>
      </table>
    `,
    actions: [{ label: "Close", className: "btn-secondary", onClick: (close) => close() }],
  });
}

/**
 * Update Reminder / Commitment modal. Used from the Detailed Payment Records
 * table AND from the Commitment Date Report / Reminder Date Report tables.
 *
 * options.refresh   - function to call after a successful save, so the
 *                      screen the user was actually looking at (payments
 *                      table, commitment report, or reminder report)
 *                      re-loads and reflects the change immediately.
 * options.context   - "payments" | "report" - controls whether the
 *                      "mark as followed-up today" checkbox defaults on.
 */
function openReminderModal(id, record, options) {
  const opts = options || {};
  const refresh = opts.refresh || loadPayments;
  const defaultTouchToday = opts.context !== "report"; // reports default OFF, payments default ON

  const { close } = openModal({
    title: "Update Reminder / Commitment",
    bodyHtml: `
      <div class="field" style="margin-bottom:10px;">
        <label>Reminder Remark</label>
        <textarea id="modal-remark" rows="3" style="width:100%;">${escapeHtml(record.reminder_remark || "")}</textarea>
      </div>
      <div class="field" style="margin-bottom:10px;">
        <label>Commitment Date</label>
        <input type="date" id="modal-commit-date" value="${record.commitment_date || ""}" style="width:100%;">
      </div>
      <div class="field" style="margin-bottom:6px;">
        <label>Commitment Amount</label>
        <input type="number" id="modal-commit-amount" value="${record.commitment_amount ?? ""}" style="width:100%;">
      </div>
      <label style="display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--text-muted);margin-bottom:10px;">
        <input type="checkbox" id="modal-commit-add">
        Add this to the existing commitment (₹ ${Number(record.commitment_amount || 0).toLocaleString("en-IN")}) instead of replacing it
      </label>
      <div class="field" style="margin-bottom:10px;">
        <label>Status</label>
        <select id="modal-status" style="width:100%;">
          <option value="PENDING" ${(record.status || "PENDING") === "PENDING" ? "selected" : ""}>PENDING</option>
          <option value="RECEIVED" ${record.status === "RECEIVED" ? "selected" : ""}>RECEIVED</option>
        </select>
      </div>
      <label style="display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--text-muted);">
        <input type="checkbox" id="modal-touch-today" ${defaultTouchToday ? "checked" : ""}>
        Mark today as the Reminder Date (we followed up today)
      </label>
      <div class="muted" style="margin-top:10px;font-size:12px;">
        Unchecking this only moves the Commitment Date/Amount (e.g. "they pushed the date")
        without pretending we contacted them today — it will still show correctly the next
        time you run the Commitment/Reminder Date Report.
        A commitment is only a promise: it will NOT be counted in Collection totals until you
        set Status to RECEIVED here — at that point it moves into the actual collected amount
        and drops off the Commitment Report automatically.
      </div>
    `,
    actions: [
      { label: "Cancel", className: "btn-secondary", onClick: (close) => close() },
      {
        label: "Save",
        className: "btn-primary",
        onClick: async (close) => {
          const remark = document.getElementById("modal-remark").value;
          const commitDate = document.getElementById("modal-commit-date").value || null;
          const commitAmount = document.getElementById("modal-commit-amount").value || null;
          const commitAdd = document.getElementById("modal-commit-add").checked;
          const status = document.getElementById("modal-status").value;
          const touchToday = document.getElementById("modal-touch-today").checked;
          try {
            await apiPost("/api/reminder/update", {
              id,
              reminder_remark: remark,
              commitment_date: commitDate,
              commitment_amount: commitAmount,
              commitment_amount_mode: commitAdd ? "add" : "replace",
              status,
              keep_reminder_date: !touchToday,
            });
            showToast("Reminder updated.", "success");
            close();
            refresh();
          } catch (err) {
            showToast("Failed to update: " + err.message, "error");
          }
        },
      },
    ],
  });
}
window.openReminderModal = openReminderModal;

async function loadCommitmentReport() {
  const from = document.getElementById("commit-from").value;
  const to = document.getElementById("commit-to").value;
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  const tbody = document.getElementById("commit-body");
  tbody.innerHTML = '<tr><td colspan="7" class="empty-state">Loading...</td></tr>';
  try {
    const data = await apiGet(`/api/reports/commitment?${params.toString()}`);
    document.getElementById("commit-total").textContent = formatMoney(data.total_commitment_amount);
    const brandBody = document.getElementById("commit-brand-body");
    if (data.brand_totals && data.brand_totals.length) {
      brandBody.innerHTML = data.brand_totals
        .slice()
        .sort((a, b) => Number(b.total_commitment) - Number(a.total_commitment))
        .map((b) => `<tr><td>${escapeHtml(b.brand)}</td><td>${formatMoney(b.total_commitment)}</td></tr>`)
        .join("");
    } else {
      brandBody.innerHTML = '<tr><td colspan="2" class="empty-state">No commitments in this range.</td></tr>';
    }
    if (!data.rows.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No commitments in this range.</td></tr>';
      return;
    }
    tbody.innerHTML = data.rows.map((r) => `
      <tr>
        <td>${escapeHtml(r.brand)}</td>
        <td>${escapeHtml(r.door)}</td>
        <td>${formatMoney(r.pending_amount)}</td>
        <td>${r.commitment_amount != null ? formatMoney(r.commitment_amount) : ""}</td>
        <td>${escapeHtml(r.commitment_date || "")}</td>
        <td>${statusBadge(r.status)}</td>
        <td><button class="btn-secondary btn-sm" onclick="openReminderModal(${r.id}, ${JSON.stringify(r).replace(/"/g, '&quot;')}, { refresh: loadCommitmentReport, context: 'report' })">Update</button></td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-state">Failed: ${escapeHtml(err.message)}</td></tr>`;
  }
}
window.loadCommitmentReport = loadCommitmentReport;

async function loadReminderReport() {
  const from = document.getElementById("rem-from").value;
  const to = document.getElementById("rem-to").value;
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  const tbody = document.getElementById("rem-body");
  tbody.innerHTML = '<tr><td colspan="6" class="empty-state">Loading...</td></tr>';
  try {
    const data = await apiGet(`/api/reports/reminder-date?${params.toString()}`);
    if (!data.rows.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No reminders in this range.</td></tr>';
      return;
    }
    tbody.innerHTML = data.rows.map((r) => `
      <tr>
        <td>${escapeHtml(r.brand)}</td>
        <td>${escapeHtml(r.door)}</td>
        <td>${escapeHtml(r.reminder_remark || "")}</td>
        <td>${escapeHtml(r.reminder_date || "")}</td>
        <td>${escapeHtml(r.commitment_date || "")}</td>
        <td><button class="btn-secondary btn-sm" onclick="openReminderModal(${r.id}, ${JSON.stringify(r).replace(/"/g, '&quot;')}, { refresh: loadReminderReport, context: 'report' })">Update</button></td>
      </tr>
    `).join("");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty-state">Failed: ${escapeHtml(err.message)}</td></tr>`;
  }
}
window.loadReminderReport = loadReminderReport;

function bindSortableHeaders() {
  document.querySelectorAll("#payments-table thead th[data-col]").forEach((th) => {
    th.addEventListener("click", () => {
      const col = th.dataset.col;
      if (paymentsState.sort === col) {
        paymentsState.dir = paymentsState.dir === "asc" ? "desc" : "asc";
      } else {
        paymentsState.sort = col;
        paymentsState.dir = "desc";
      }
      paymentsState.page = 1;
      loadPayments();
    });
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  await Promise.all([loadKpis(), loadDoorSelect(), loadBrandFilter(), loadStatusFilter()]);
  await Promise.all([loadDoorBrandSummary(document.getElementById("details-door-select").value), loadPayments()]);
  bindSortableHeaders();

  document.getElementById("details-door-select").addEventListener("change", (e) => {
    loadDoorBrandSummary(e.target.value);
  });
  const filterControls = [
    document.getElementById("payments-door"),
    document.getElementById("payments-brand"),
    document.getElementById("payments-status"),
    document.getElementById("payments-search"),
    document.getElementById("payments-date-from"),
    document.getElementById("payments-date-to")
  ];
  filterControls.forEach((el) => {
    if (!el) return;
    const eventName = el.tagName === "INPUT" && el.type === "search" ? "input" : "change";
    el.addEventListener(eventName, () => {
      paymentsState.page = 1;
      loadPayments();
    });
  });
  document.getElementById("payments-apply").addEventListener("click", () => {
    paymentsState.page = 1;
    loadPayments();
  });
  document.getElementById("payments-prev").addEventListener("click", () => {
    if (paymentsState.page > 1) { paymentsState.page -= 1; loadPayments(); }
  });
  document.getElementById("payments-next").addEventListener("click", () => {
    const totalPages = Math.max(Math.ceil(paymentsState.total / paymentsState.page_size), 1);
    if (paymentsState.page < totalPages) { paymentsState.page += 1; loadPayments(); }
  });
  document.getElementById("commit-apply").addEventListener("click", loadCommitmentReport);
  document.getElementById("rem-apply").addEventListener("click", loadReminderReport);
});

window.onDataChanged = async () => {
  await Promise.all([loadKpis(), loadDoorSelect(), loadBrandFilter()]);
  await loadPayments();
};
