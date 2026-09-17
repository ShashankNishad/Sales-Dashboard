/* dashboard.js - Page 1 logic */

async function loadDoors() {
  const select = document.getElementById("door-filter");
  try {
    const data = await apiGet("/api/doors");
    const current = select.value;
    select.innerHTML = '<option value="ALL">ALL</option>' +
      data.doors.map((d) => `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join("");
    if (data.doors.includes(current)) select.value = current;
  } catch (err) {
    showToast("Could not load doors: " + err.message, "error");
  }
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function loadKpis(filters = {}) {
  try {
    const params = new URLSearchParams();
    const door = filters.door || document.getElementById("door-filter").value;
    const dateFrom = filters.date_from || document.getElementById("date-from-filter").value;
    const dateTo = filters.date_to || document.getElementById("date-to-filter").value;
    if (door && door !== "ALL") params.set("door", door);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    const data = await apiGet(`/api/dashboard/kpis${params.toString() ? `?${params.toString()}` : ""}`);
    document.getElementById("kpi-target").textContent = formatMoney(data.total_target);
    document.getElementById("kpi-collection").textContent = formatMoney(data.total_collection);
    document.getElementById("kpi-os").textContent = formatMoney(data.total_os);
    document.getElementById("kpi-sixty").textContent = formatMoney(data.total_sixty_plus);
    document.getElementById("kpi-amount").textContent = formatMoney(data.total_commitment_amount ?? data.total_amount);
  } catch (err) {
    showToast("Could not load KPIs: " + err.message, "error");
  }
}

function achievementPct(target, collection) {
  return target ? Math.round((collection / target) * 1000) / 10 : 0;
}

async function loadBrandSummary(filters = {}) {
  const tbody = document.getElementById("brand-summary-body");
  const tfoot = document.getElementById("brand-summary-foot");
  try {
    const params = new URLSearchParams();
    const door = filters.door || document.getElementById("door-filter").value;
    const dateFrom = filters.date_from || document.getElementById("date-from-filter").value;
    const dateTo = filters.date_to || document.getElementById("date-to-filter").value;
    if (door && door !== "ALL") params.set("door", door);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    const data = await apiGet(`/api/dashboard/brand-summary${params.toString() ? `?${params.toString()}` : ""}`);
    if (!data.brands.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No data yet. Upload an Excel file to get started.</td></tr>';
      tfoot.innerHTML = "";
      return;
    }
    tbody.innerHTML = data.brands.map((b) => `
      <tr>
        <td>${escapeHtml(b.brand)}</td>
        <td>${formatMoney(b.target)}</td>
        <td>${formatMoney(b.collection)}</td>
        <td>${formatPct(b.achievement_pct)}</td>
      </tr>
    `).join("");
    const totalTarget = data.brands.reduce((s, b) => s + Number(b.target || 0), 0);
    const totalCollection = data.brands.reduce((s, b) => s + Number(b.collection || 0), 0);
    tfoot.innerHTML = `
      <tr>
        <td>TOTAL</td>
        <td>${formatMoney(totalTarget)}</td>
        <td>${formatMoney(totalCollection)}</td>
        <td>${formatPct(achievementPct(totalTarget, totalCollection))}</td>
      </tr>
    `;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty-state">Failed to load brand summary.</td></tr>`;
    tfoot.innerHTML = "";
  }
}

async function loadClusterSummary(filters = {}) {
  const tbody = document.getElementById("cluster-summary-body");
  const tfoot = document.getElementById("cluster-summary-foot");
  try {
    const params = new URLSearchParams();
    const door = filters.door || document.getElementById("door-filter").value;
    const dateFrom = filters.date_from || document.getElementById("date-from-filter").value;
    const dateTo = filters.date_to || document.getElementById("date-to-filter").value;
    if (door && door !== "ALL") params.set("door", door);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    const data = await apiGet(`/api/dashboard/cluster-summary${params.toString() ? `?${params.toString()}` : ""}`);
    if (!data.clusters.length) {
      tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No cluster data yet. Add a "Cluster" column to your Excel file and re-upload.</td></tr>';
      tfoot.innerHTML = "";
      return;
    }
    tbody.innerHTML = data.clusters.map((c) => `
      <tr>
        <td>${escapeHtml(c.cluster)}</td>
        <td>${formatMoney(c.target)}</td>
        <td>${formatMoney(c.collection)}</td>
        <td>${formatPct(c.achievement_pct)}</td>
      </tr>
    `).join("");
    const totalTarget = data.clusters.reduce((s, c) => s + Number(c.target || 0), 0);
    const totalCollection = data.clusters.reduce((s, c) => s + Number(c.collection || 0), 0);
    tfoot.innerHTML = `
      <tr>
        <td>TOTAL</td>
        <td>${formatMoney(totalTarget)}</td>
        <td>${formatMoney(totalCollection)}</td>
        <td>${formatPct(achievementPct(totalTarget, totalCollection))}</td>
      </tr>
    `;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty-state">Could not load cluster summary: ${escapeHtml(err.message)}</td></tr>`;
    tfoot.innerHTML = "";
  }
}

async function refreshDashboard() {
  const filters = {
    door: document.getElementById("door-filter").value,
    date_from: document.getElementById("date-from-filter").value,
    date_to: document.getElementById("date-to-filter").value,
  };
  await Promise.all([loadKpis(filters), loadBrandSummary(filters), loadClusterSummary(filters)]);
}

document.addEventListener("DOMContentLoaded", async () => {
  await loadDoors();
  await refreshDashboard();

  document.getElementById("door-filter").addEventListener("change", refreshDashboard);
  document.getElementById("date-from-filter").addEventListener("change", refreshDashboard);
  document.getElementById("date-to-filter").addEventListener("change", refreshDashboard);
  document.getElementById("dashboard-apply").addEventListener("click", refreshDashboard);
});

// called by common.js after a successful Excel upload
window.onDataChanged = async () => {
  await loadDoors();
  await refreshDashboard();
};
