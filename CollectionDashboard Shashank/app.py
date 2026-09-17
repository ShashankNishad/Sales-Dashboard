"""
app.py - Collection Management Dashboard
==========================================
Flask backend. Serves 3 pages (dashboard, details, data management)
and a set of JSON APIs consumed by the frontend via fetch()/AJAX.

Run:
    python app.py
Then open http://127.0.0.1:5000/ in a browser.
"""

import os
import sys
import glob
import logging
import traceback
import re
from datetime import datetime, date

from flask import Flask, render_template, request, jsonify, g, send_file
from werkzeug.utils import secure_filename

from database import init_db, get_connection, master_dedupe_subquery, AGGREGATION_STRATEGY
import excel_processor

# ---------------------------------------------------------------------
# App / path setup (PyInstaller-friendly: resolves correctly whether
# running as a normal script or from inside a frozen .exe bundle)
# ---------------------------------------------------------------------
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    TEMPLATE_DIR = os.path.join(sys._MEIPASS, "templates")
    STATIC_DIR = os.path.join(sys._MEIPASS, "static")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
    STATIC_DIR = os.path.join(BASE_DIR, "static")

UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
LOG_DIR = os.path.join(BASE_DIR, "logs")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB upload cap
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR

# ---------------------------------------------------------------------
# Logging - detailed errors go to file, users only ever see friendly text
# ---------------------------------------------------------------------
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "app.log"),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app")

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
DELETE_PASSWORD = os.environ.get("COLLECTION_DASHBOARD_DELETE_PASSWORD", "Shashank")
ALLOWED_EXTENSIONS = {"xlsx", "xls"}
STATUS_VALUES = ("RECEIVED", "PENDING")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.errorhandler(Exception)
def handle_uncaught(e):
    logger.error("Unhandled error: %s\n%s", e, traceback.format_exc())
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Something went wrong while processing your request."}), 500
    return "Something went wrong while loading the data.", 500


# =======================================================================
# PAGE ROUTES
# =======================================================================
@app.route("/")
@app.route("/dashboard")
def dashboard_page():
    return render_template("dashboard.html")


@app.route("/details")
def details_page():
    return render_template("details.html")


@app.route("/data-management")
def data_management_page():
    return render_template("data_management.html")


# =======================================================================
# HELPERS
# =======================================================================
def money(x):
    return round(x or 0, 2)


def fetch_all(query, params=()):
    conn = get_connection()
    try:
        cur = conn.execute(query, params)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def fetch_one(query, params=()):
    conn = get_connection()
    try:
        cur = conn.execute(query, params)
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def normalize_date_value(value):
    """Normalize many date strings to a Python date object; accept ISO, d-Mon-Y, d/m/Y, etc."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date") and callable(value.date):
        try:
            return value.date()
        except Exception:
            pass
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none", "null", "-"}:
        return None
    text = text.replace("/", "-")
    # Handle Excel / SQLite style dates like 2026-04-13 and 13-Apr-2026
    formats = [
        "%Y-%m-%d",
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d %b %Y",
        "%d %B %Y",
        "%m-%d-%Y",
        "%Y/%m/%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    # Last resort: coerce with the date parser when used in uploads / exports.
    try:
        import pandas as pd
        parsed = pd.to_datetime(text, errors="raise", dayfirst=True)
        return parsed.date()
    except Exception:
        return None


def build_filter_clause(args, allow=("door", "brand", "status", "door_type", "cluster")):
    """Build a WHERE clause + params list from query args for simple equality filters,
    plus optional date-range filters (date_from/date_to on the `date` column)."""
    clauses = []
    params = []
    for key in allow:
        val = args.get(key)
        if val and str(val).upper() != "ALL":
            clauses.append(f"{key} = ?")
            params.append(val)
    date_from = normalize_date_value(args.get("date_from"))
    date_to = normalize_date_value(args.get("date_to"))
    if date_from:
        clauses.append("date >= ?")
        params.append(date_from.strftime("%Y-%m-%d"))
    if date_to:
        clauses.append("date <= ?")
        params.append(date_to.strftime("%Y-%m-%d"))
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def filter_records(rows, args, *, allow_search_fields=None):
    """Apply equality/search/date filters in memory so mixed date formats are handled consistently."""
    door = args.get("door")
    brand = args.get("brand")
    status = args.get("status")
    search = (args.get("search") or "").strip()
    date_from = normalize_date_value(args.get("date_from"))
    date_to = normalize_date_value(args.get("date_to"))
    allow_search_fields = allow_search_fields or ["door", "brand", "status", "cluster", "reminder_remark"]

    filtered = []
    for row in rows:
        if door and str(door).upper() != "ALL" and (row.get("door") or "") != door:
            continue
        if brand and str(brand).upper() != "ALL" and (row.get("brand") or "") != brand:
            continue
        if status and str(status).upper() != "ALL" and (row.get("status") or "") != status:
            continue

        row_date = normalize_date_value(row.get("date"))
        if date_from and (row_date is None or row_date < date_from):
            continue
        if date_to and (row_date is None or row_date > date_to):
            continue

        if search:
            haystack = " ".join(str(row.get(field) or "") for field in allow_search_fields)
            if search.lower() not in haystack.lower():
                continue

        filtered.append(row)
    return filtered


def dedupe_master_rows(rows):
    """Take the latest row per (door, brand) for master-value fields like target/os/collection."""
    latest = {}
    for row in rows:
        key = (row.get("door") or "", row.get("brand") or "")
        current = latest.get(key)
        if current is None or int(row.get("id") or 0) > int(current.get("id") or 0):
            latest[key] = row
    return list(latest.values())


def group_payment_records(rows):
    """Group raw records by door + brand + cluster for display/summarized collection view."""
    groups = {}
    for row in rows:
        key = (
            (row.get("door") or "").strip(),
            (row.get("brand") or "").strip(),
            (row.get("cluster") or "Unassigned").strip() or "Unassigned",
        )
        if key not in groups:
            groups[key] = {
                "door": key[0],
                "brand": key[1],
                "cluster": key[2],
                "records": [],
                "collection": 0.0,
                "date_from": None,
                "date_to": None,
            }
        entry = groups[key]
        amount = float(row.get("amount") or 0)
        entry["collection"] += amount
        entry["records"].append(row)
        row_date = normalize_date_value(row.get("date"))
        if row_date:
            if entry["date_from"] is None or row_date < entry["date_from"]:
                entry["date_from"] = row_date
            if entry["date_to"] is None or row_date > entry["date_to"]:
                entry["date_to"] = row_date
    rows_out = []
    for group in groups.values():
        group["collection"] = round(group["collection"], 2)
        group["date_from"] = group["date_from"].strftime("%d-%b-%Y") if group["date_from"] else ""
        group["date_to"] = group["date_to"].strftime("%d-%b-%Y") if group["date_to"] else ""
        group["records"] = sorted(group["records"], key=lambda r: (normalize_date_value(r.get("date")) or date.min, r.get("id") or 0))
        rows_out.append(group)
    return sorted(rows_out, key=lambda g: (-float(g["collection"]), g["door"], g["brand"], g["cluster"]))


# =======================================================================
# API: DASHBOARD (Page 1)
# =======================================================================
@app.route("/api/dashboard/kpis")
def api_dashboard_kpis():
    """
    KPI totals. master fields are deduped per Door+Brand before summing, while
    commitment amount is summed across filtered raw records. The dashboard label
    uses the commitment field, but the raw amount total remains available for
    compatibility with older screens.
    """
    raw_rows = fetch_all("SELECT * FROM records ORDER BY id")
    filtered_rows = filter_records(raw_rows, request.args)
    master_rows = dedupe_master_rows(filtered_rows)

    total_target = sum(float(r.get("target") or 0) for r in master_rows)
    total_os = sum(float(r.get("os") or 0) for r in master_rows)
    total_sixty_plus = sum(float(r.get("sixty_plus") or 0) for r in master_rows)
    total_collection = sum(float(r.get("collection") or 0) for r in master_rows)
    total_commitment = sum(float(r.get("commitment_amount") or 0) for r in filtered_rows)
    total_amount = sum(float(r.get("amount") or 0) for r in filtered_rows)

    return jsonify({
        "success": True,
        "total_target": money(total_target),
        "total_collection": money(total_collection),
        "total_os": money(total_os),
        "total_sixty_plus": money(total_sixty_plus),
        "total_amount": money(total_amount),
        "total_commitment_amount": money(total_commitment),
    })


@app.route("/api/dashboard/brand-summary")
def api_brand_summary():
    filtered_rows = filter_records(fetch_all("SELECT * FROM records ORDER BY id"), request.args)
    master_rows = dedupe_master_rows(filtered_rows)
    grouped = {}
    for row in master_rows:
        brand = row.get("brand") or "Unassigned"
        grouped.setdefault(brand, {"brand": brand, "target": 0.0, "collection": 0.0})
        grouped[brand]["target"] += float(row.get("target") or 0)
        grouped[brand]["collection"] += float(row.get("collection") or 0)

    rows = sorted(grouped.values(), key=lambda r: r["brand"].lower())
    for r in rows:
        r["target"] = money(r["target"])
        r["collection"] = money(r["collection"])
        r["achievement_pct"] = round((r["collection"] / r["target"]) * 100, 1) if r["target"] else 0.0
    return jsonify({"success": True, "brands": rows})


@app.route("/api/dashboard/cluster-summary")
def api_cluster_summary():
    """Cluster Name analysis using the filtered master rows only."""
    filtered_rows = filter_records(fetch_all("SELECT * FROM records ORDER BY id"), request.args)
    master_rows = dedupe_master_rows(filtered_rows)
    grouped = {}
    for row in master_rows:
        cluster = (row.get("cluster") or "Unassigned").strip() or "Unassigned"
        grouped.setdefault(cluster, {"cluster": cluster, "target": 0.0, "collection": 0.0})
        grouped[cluster]["target"] += float(row.get("target") or 0)
        grouped[cluster]["collection"] += float(row.get("collection") or 0)

    rows = sorted(grouped.values(), key=lambda r: r["cluster"].lower())
    for r in rows:
        r["target"] = money(r["target"])
        r["collection"] = money(r["collection"])
        r["achievement_pct"] = round((r["collection"] / r["target"]) * 100, 1) if r["target"] else 0.0
    return jsonify({"success": True, "clusters": rows})


@app.route("/api/doors")
def api_doors():
    rows = fetch_all("SELECT DISTINCT door FROM records ORDER BY door")
    return jsonify({"success": True, "doors": [r["door"] for r in rows]})


@app.route("/api/brands")
def api_brands():
    rows = fetch_all("SELECT DISTINCT brand FROM records ORDER BY brand")
    return jsonify({"success": True, "brands": [r["brand"] for r in rows]})


@app.route("/api/clusters")
def api_clusters():
    rows = fetch_all(
        "SELECT DISTINCT cluster FROM records WHERE cluster IS NOT NULL AND TRIM(cluster) != '' ORDER BY cluster"
    )
    return jsonify({"success": True, "clusters": [r["cluster"] for r in rows]})


@app.route("/api/statuses")
def api_statuses():
    return jsonify({"success": True, "statuses": list(STATUS_VALUES)})


# =======================================================================
# API: DETAILS PAGE (Page 2)
# =======================================================================
@app.route("/api/details/door-brand-summary")
def api_door_brand_summary():
    door = request.args.get("door")
    if not door or door.upper() == "ALL":
        return jsonify({"success": False, "error": "A specific door must be selected."}), 400

    dedupe_sql = master_dedupe_subquery()
    master_rows = fetch_all(
        f"""
        SELECT brand, COALESCE(SUM(target),0) AS target, COALESCE(SUM(collection),0) AS collection
        FROM ({dedupe_sql}) dedup
        WHERE door = ?
        GROUP BY brand
        """,
        (door,),
    )
    amount_rows = fetch_all(
        "SELECT brand, COALESCE(SUM(amount),0) AS received FROM records WHERE door = ? GROUP BY brand",
        (door,),
    )
    amount_map = {r["brand"]: r["received"] for r in amount_rows}

    result = []
    for r in master_rows:
        received = amount_map.get(r["brand"], 0)
        result.append({
            "brand": r["brand"],
            "target": money(r["target"]),
            "collection": money(r["collection"]),
            "achievement_pct": round((r["collection"] / r["target"]) * 100, 1) if r["target"] else 0.0,
            "received": money(received),
            "pending": money(r["target"] - received),
        })
    return jsonify({"success": True, "door": door, "brands": result})


@app.route("/api/details/payments")
def api_details_payments():
    """Detailed, filterable, paginated payment table for the details page."""
    args = request.args
    filtered_rows = filter_records(fetch_all("SELECT * FROM records ORDER BY id"), args)
    sort_col = args.get("sort", "date")
    sort_dir = "DESC" if args.get("dir", "desc").lower() == "desc" else "ASC"
    valid_sorts = {"date", "amount", "brand", "door", "status", "reminder_date", "commitment_date"}
    if sort_col not in valid_sorts:
        sort_col = "date"

    def sort_key(row):
        value = row.get(sort_col) or ""
        if sort_col in {"date", "reminder_date", "commitment_date"}:
            norm = normalize_date_value(value)
            return (norm is None, norm or date.min)
        if sort_col == "amount":
            return (False, float(value or 0))
        return (False, str(value).lower())

    filtered_rows = sorted(filtered_rows, key=sort_key, reverse=(sort_dir == "DESC"))

    page = max(int(args.get("page", 1)), 1)
    page_size = min(max(int(args.get("page_size", 25)), 1), 500)
    offset = (page - 1) * page_size
    page_rows = filtered_rows[offset:offset + page_size]
    return jsonify({
        "success": True,
        "rows": page_rows,
        "total": len(filtered_rows),
        "page": page,
        "page_size": page_size,
    })


@app.route("/api/details/grouped-payments")
def api_grouped_payments():
    """Grouped summary for the details page. It keeps raw rows intact, but aggregates them for display."""
    raw_rows = fetch_all("SELECT * FROM records ORDER BY id")
    filtered_rows = filter_records(raw_rows, request.args)
    groups = group_payment_records(filtered_rows)
    total_collection = sum(float(r["collection"]) for r in groups)
    return jsonify({
        "success": True,
        "rows": groups,
        "total": len(groups),
        "total_collection": money(total_collection),
    })


@app.route("/api/reminder/update", methods=["POST"])
def api_reminder_update():
    data = request.get_json(force=True)
    record_id = data.get("id")
    if not record_id:
        return jsonify({"success": False, "error": "Record id required."}), 400

    remark = data.get("reminder_remark")
    commitment_date = data.get("commitment_date")
    commitment_amount_input = data.get("commitment_amount")
    commitment_amount_mode = (data.get("commitment_amount_mode") or "replace").lower()
    status = data.get("status")
    # Reminder Date auto-stamps to today UNLESS the caller is only pushing
    # the commitment date further out from the Commitment/Reminder Date
    # Report screens (keep_reminder_date=true) - in that case we leave the
    # existing reminder date alone and just move the commitment date, so a
    # "they'll pay later" edit is reflected without pretending we phoned
    # them again today.
    keep_reminder_date = bool(data.get("keep_reminder_date"))
    today = datetime.now().strftime("%Y-%m-%d")

    def to_float(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    conn = get_connection()
    try:
        current = conn.execute(
            "SELECT amount, commitment_amount FROM records WHERE id = ?", (record_id,)
        ).fetchone()
        if current is None:
            return jsonify({"success": False, "error": "Record not found."}), 404
        existing_amount = current["amount"] or 0
        existing_commitment = current["commitment_amount"] or 0

        requested = to_float(commitment_amount_input)
        # "Add" mode: the entered value is a NEW commitment on top of whatever
        # was already pledged, so it accumulates instead of overwriting it -
        # e.g. they promise another 5,000 next week on top of an existing
        # 10,000 pledge, without losing the first one.
        if commitment_amount_mode == "add":
            effective_commitment = existing_commitment + (requested or 0)
        else:
            effective_commitment = requested  # None => field was cleared on purpose

        # A commitment is a PROMISE, not money in hand - it must not show up
        # anywhere collection totals are summed until the door is actually
        # marked RECEIVED. Once RECEIVED, that pledged amount graduates into
        # the real, received AMOUNT and stops being counted as "committed but
        # not yet collected" (so Total Commitment Amount correctly shrinks).
        if status == "RECEIVED":
            new_amount = existing_amount + (effective_commitment or 0)
            new_commitment_amount = None
            new_commitment_date = None
        else:
            new_amount = existing_amount
            new_commitment_amount = effective_commitment
            new_commitment_date = commitment_date

        if keep_reminder_date:
            conn.execute(
                """
                UPDATE records
                SET reminder_remark = ?, commitment_date = ?, commitment_amount = ?,
                    amount = ?, status = COALESCE(?, status),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (remark, new_commitment_date, new_commitment_amount, new_amount, status, record_id),
            )
        else:
            conn.execute(
                """
                UPDATE records
                SET reminder_remark = ?, reminder_date = ?, commitment_date = ?,
                    commitment_amount = ?, amount = ?, status = COALESCE(?, status),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (remark, today, new_commitment_date, new_commitment_amount, new_amount, status, record_id),
            )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"success": True, "reminder_date": today})


@app.route("/api/reports/commitment")
def api_commitment_report():
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    clauses = ["commitment_date IS NOT NULL", "commitment_date != ''"]
    params = []
    if date_from:
        clauses.append("commitment_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("commitment_date <= ?")
        params.append(date_to)
    where = " WHERE " + " AND ".join(clauses)

    rows = fetch_all(
        f"""
        SELECT id, brand, door, (target - amount) AS pending_amount, commitment_amount,
               commitment_date, status, reminder_remark, reminder_date
        FROM records
        {where}
        ORDER BY commitment_date ASC
        """,
        params,
    )
    total_commitment = sum((r["commitment_amount"] or 0) for r in rows)

    brand_totals = {}
    for r in rows:
        brand_totals.setdefault(r["brand"], 0)
        brand_totals[r["brand"]] += r["commitment_amount"] or 0
    brand_totals_list = [{"brand": b, "total_commitment": money(v)} for b, v in brand_totals.items()]

    return jsonify({
        "success": True,
        "rows": rows,
        "total_commitment_amount": money(total_commitment),
        "brand_totals": brand_totals_list,
    })


@app.route("/api/reports/reminder-date")
def api_reminder_date_report():
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    clauses = ["reminder_date IS NOT NULL", "reminder_date != ''"]
    params = []
    if date_from:
        clauses.append("reminder_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("reminder_date <= ?")
        params.append(date_to)
    where = " WHERE " + " AND ".join(clauses)

    rows = fetch_all(
        f"""
        SELECT id, brand, door, reminder_remark, reminder_date, commitment_date,
               commitment_amount, status
        FROM records
        {where}
        ORDER BY reminder_date DESC
        """,
        params,
    )
    return jsonify({"success": True, "rows": rows})


# =======================================================================
# API: HTML EXPORT / SNAPSHOT
# =======================================================================

@app.route("/api/export/html-snapshot")
def api_export_html_snapshot():
    """Generate a self-contained HTML snapshot for a selected date range."""
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    if not date_from or not date_to:
        return jsonify({"success": False, "error": "Both date range values are required."}), 400

    rows = fetch_all("SELECT * FROM records ORDER BY id")
    filtered_rows = filter_records(rows, {"date_from": date_from, "date_to": date_to})
    groups = group_payment_records(filtered_rows)
    dashboard_kpis = {
        "total_target": 0.0,
        "total_collection": 0.0,
        "total_os": 0.0,
        "total_sixty_plus": 0.0,
        "total_commitment_amount": 0.0,
    }
    master_rows = dedupe_master_rows(filtered_rows)
    for r in master_rows:
        dashboard_kpis["total_target"] += float(r.get("target") or 0)
        dashboard_kpis["total_collection"] += float(r.get("collection") or 0)
        dashboard_kpis["total_os"] += float(r.get("os") or 0)
        dashboard_kpis["total_sixty_plus"] += float(r.get("sixty_plus") or 0)
    dashboard_kpis["total_commitment_amount"] = sum(float(r.get("commitment_amount") or 0) for r in filtered_rows)

    brand_summary = {}
    for r in master_rows:
        brand = (r.get("brand") or "Unassigned").strip() or "Unassigned"
        brand_summary.setdefault(brand, {"brand": brand, "target": 0.0, "collection": 0.0})
        brand_summary[brand]["target"] += float(r.get("target") or 0)
        brand_summary[brand]["collection"] += float(r.get("collection") or 0)
    brand_summary = sorted(brand_summary.values(), key=lambda r: r["brand"].lower())
    for row in brand_summary:
        row["achievement_pct"] = round((row["collection"] / row["target"]) * 100, 1) if row["target"] else 0.0

    cluster_summary = {}
    for r in master_rows:
        cluster = (r.get("cluster") or "Unassigned").strip() or "Unassigned"
        cluster_summary.setdefault(cluster, {"cluster": cluster, "target": 0.0, "collection": 0.0})
        cluster_summary[cluster]["target"] += float(r.get("target") or 0)
        cluster_summary[cluster]["collection"] += float(r.get("collection") or 0)
    cluster_summary = sorted(cluster_summary.values(), key=lambda r: r["cluster"].lower())
    for row in cluster_summary:
        row["achievement_pct"] = round((row["collection"] / row["target"]) * 100, 1) if row["target"] else 0.0

    export_data = {
        "date_from": date_from,
        "date_to": date_to,
        "records": filtered_rows,
        "grouped_records": groups,
        "dashboard": dashboard_kpis,
        "brand_summary": brand_summary,
        "cluster_summary": cluster_summary,
    }

    js_blob = "window.snapshotData = " + __import__("json").dumps(export_data, ensure_ascii=False, default=str) + ";"
    html = r'''
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Collection Dashboard Snapshot</title>
<style>
:root {
  --bg:#f2faf5; --surface:#fff; --surface-alt:#eef8f1; --border:#dcefe2; --text:#12160f; --text-muted:#5b6b60;
  --primary:#16a34a; --primary-dark:#0f172a; --primary-soft:#e3f8ec; --success:#16a34a; --success-soft:#e3f8ec;
  --danger:#dc2626; --warning:#c2760f; --warning-soft:#fdf0e0; --radius:14px; --radius-sm:9px;
  --shadow:0 1px 2px rgba(10,20,15,.05), 0 8px 24px rgba(10,20,15,.06); --font:'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, Helvetica, Arial, sans-serif;
}
* { box-sizing:border-box; }
body { margin:0; font-family:var(--font); background:var(--bg); color:var(--text); -webkit-font-smoothing:antialiased; }
.app-shell { display:block; min-height:100vh; }
.brand-mark { display:flex; align-items:center; gap:9px; }
.brand-dot { width:10px; height:10px; border-radius:50%; background:linear-gradient(135deg,#4ade80,#16a34a); box-shadow:0 0 0 5px rgba(74,222,128,.18); }
.brand-title { font-weight:700; font-size:14px; color:#fff; }
.brand-subtitle { font-size:10.5px; color:#8ba692; margin-top:1px; }
.main-content { width:100%; max-width:1320px; margin:0 auto; display:flex; flex-direction:column; min-width:0; }
.topbar { padding:18px 30px 20px; background:linear-gradient(160deg,#0a0d0a,#111511 60%,#122016); color:#fff; box-shadow:0 4px 18px rgba(10,20,15,.3); border-bottom:3px solid #16a34a; }
.topbar-brand-row { display:flex; justify-content:center; margin-bottom:14px; }
.topbar-title-row { text-align:center; margin-bottom:18px; }
.page-heading { margin:0; font-size:26px; font-weight:800; letter-spacing:.3px; color:#4ade80; text-shadow:0 1px 0 rgba(0,0,0,.3); }
.page-heading .range { font-weight:500; font-size:12.5px; opacity:.8; display:block; margin-top:5px; color:#cfe8d8; letter-spacing:.2px; }
.topbar-top { display:flex; align-items:center; justify-content:center; flex-wrap:wrap; gap:14px; margin-bottom:16px; }
.readonly-pill { background:rgba(74,222,128,.14); border:1px solid rgba(74,222,128,.4); color:#4ade80; padding:6px 12px; border-radius:999px; font-size:11.5px; font-weight:700; white-space:nowrap; }
.filter-bar { display:flex; flex-wrap:wrap; gap:12px; align-items:flex-end; justify-content:center; }
.field { display:flex; flex-direction:column; gap:5px; min-width:150px; }
.field label { font-size:11px; font-weight:700; letter-spacing:.3px; text-transform:uppercase; }
.topbar label { color:rgba(255,255,255,.75); }
select, input, textarea { padding:9px 11px; border:1px solid var(--border); border-radius:var(--radius-sm); font-size:13px; width:100%; font-family:var(--font); background:#fff; color:var(--text); }
.topbar select, .topbar input { border:1px solid rgba(255,255,255,.2); background:#fff; }
button { border:none; border-radius:var(--radius-sm); padding:9px 17px; font-size:13px; font-weight:700; cursor:pointer; transition:filter .12s ease, transform .05s ease; }
button:active { transform:translateY(1px); }
.btn-primary { background:#4ade80; color:#0a0d0a; }
.btn-primary:hover { filter:brightness(0.95); }
.content-body .btn-primary { background:var(--primary); color:#fff; }
.content-body .btn-primary:hover { background:#12833c; }
.btn-secondary { background:var(--surface-alt); color:var(--text); border:1px solid var(--border); }
.btn-secondary:hover { background:#e2f3e8; }
.btn-sm { padding:6px 11px; font-size:12px; }
.content-body { padding:26px 30px 70px; }
.kpi-grid { display:grid; grid-template-columns:repeat(5,1fr); gap:16px; margin-bottom:24px; }
.kpi-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); padding:17px 19px; box-shadow:var(--shadow); position:relative; overflow:hidden; }
.kpi-label { font-size:11.5px; font-weight:700; color:var(--text-muted); text-transform:uppercase; letter-spacing:.4px; }
.kpi-value { font-size:23px; font-weight:800; margin-top:9px; letter-spacing:-.2px; color:#0a0d0a; }
.accent-target { border-top:3px solid #0a0d0a; }
.accent-collection { border-top:3px solid #16a34a; }
.accent-os { border-top:3px solid #0a0d0a; }
.accent-sixty { border-top:3px solid #dc2626; }
.accent-amount { border-top:3px solid #16a34a; }
.panel { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius); box-shadow:var(--shadow); padding:20px 22px; margin-bottom:22px; }
.panel-header { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; margin-bottom:16px; }
.panel-title { margin:0; font-size:15px; font-weight:700; color:#0a0d0a; }
.panel-title::before { content:''; display:inline-block; width:8px; height:8px; border-radius:2px; background:#16a34a; margin-right:8px; }
.panel-subtitle { font-size:12px; color:var(--text-muted); margin-top:3px; }
.grid-2 { display:grid; grid-template-columns:1.4fr 1fr; gap:20px; }
.table-scroll { overflow-x:auto; border-radius:var(--radius-sm); border:1px solid var(--border); }
table { width:100%; border-collapse:collapse; font-size:13px; }
thead th { position:sticky; top:0; text-align:left; background:#0f1512; font-size:11px; text-transform:uppercase; letter-spacing:.3px; color:#8ba692; padding:11px 13px; border-bottom:1px solid var(--border); white-space:nowrap; }
tbody td { padding:10px 13px; border-bottom:1px solid var(--border); white-space:nowrap; }
tbody tr:last-child td { border-bottom:none; }
tbody tr:hover { background:var(--surface-alt); }
tfoot td { padding:11px 13px; font-weight:700; background:var(--surface-alt); border-top:2px solid #16a34a; white-space:nowrap; }
.filter-bar-panel { margin-bottom:16px; }
.summary-strip { display:flex; align-items:center; justify-content:space-between; padding:13px 16px; background:#0f1512; border:1px solid #0f1512; border-radius:var(--radius-sm); margin-bottom:16px; font-weight:700; color:#4ade80; }
.summary-strip span:last-child { font-size:16px; }
.badge { display:inline-block; padding:3px 10px; border-radius:999px; font-size:11px; font-weight:700; }
.badge-received { background:var(--success-soft); color:var(--success); }
.badge-pending { background:var(--warning-soft); color:var(--warning); }
.empty-state { padding:34px 20px; text-align:center; color:var(--text-muted); }
.muted { color:var(--text-muted); }
.modal-overlay { position:fixed; inset:0; background:rgba(10,15,10,0.6); display:flex; align-items:center; justify-content:center; z-index:1000; }
.modal-box { background:#fff; border-radius:var(--radius); width:480px; max-width:92vw; padding:24px; box-shadow:0 20px 60px rgba(10,20,15,.35); }
.modal-title { font-size:16px; font-weight:700; margin-bottom:12px; }
.modal-actions { display:flex; justify-content:flex-end; gap:10px; margin-top:18px; }
.footer-note { text-align:center; font-size:11.5px; color:var(--text-muted); margin-top:8px; }
@media (max-width:1100px) { .grid-2 { grid-template-columns:1fr; } .kpi-grid { grid-template-columns:repeat(3,1fr); } }
@media (max-width:760px) { .kpi-grid { grid-template-columns:repeat(2,1fr); } .content-body { padding:18px 16px 50px; } .topbar { padding:16px 18px; } .page-heading { font-size:20px; } }
</style>
</head>
<body>
<div class="app-shell">
  <main class="main-content">
    <header class="topbar">
      <div class="topbar-brand-row">
        <div class="brand-mark"><span class="brand-dot"></span><div><div class="brand-title">Collection</div><div class="brand-subtitle">Management System</div></div></div>
      </div>
      <div class="topbar-title-row">
        <h1 class="page-heading">ACTIVE CLOTHING DASHBOARD <span class="range">''' + date_from + ''' &rarr; ''' + date_to + '''</span></h1>
      </div>
      <div class="topbar-top">
        <span class="readonly-pill">&#128196; View &amp; filter only</span>
      </div>
      <div class="filter-bar">
        <div class="field"><label>Select Door</label><select id="door-filter"><option value="ALL">ALL</option></select></div>
        <div class="field"><label>Date From</label><input id="date-from-filter" type="date" value="''' + date_from + '''"></div>
        <div class="field"><label>Date To</label><input id="date-to-filter" type="date" value="''' + date_to + '''"></div>
        <button class="btn-primary" id="apply-filters">Apply / Filter</button>
      </div>
    </header>
    <div class="content-body">
      <div class="kpi-grid">
        <div class="kpi-card accent-target"><div class="kpi-label">Total Target</div><div class="kpi-value" id="kpi-target">Rs 0</div></div>
        <div class="kpi-card accent-collection"><div class="kpi-label">Total Collection</div><div class="kpi-value" id="kpi-collection">Rs 0</div></div>
        <div class="kpi-card accent-os"><div class="kpi-label">Total O/S</div><div class="kpi-value" id="kpi-os">Rs 0</div></div>
        <div class="kpi-card accent-sixty"><div class="kpi-label">Total 60+</div><div class="kpi-value" id="kpi-sixty">Rs 0</div></div>
        <div class="kpi-card accent-amount"><div class="kpi-label">Total Commitment Amount</div><div class="kpi-value" id="kpi-amount">Rs 0</div></div>
      </div>
      <div class="grid-2">
        <div class="panel"><div class="panel-header"><div><h3 class="panel-title">Brand Summary</h3><div class="panel-subtitle">Target vs. Collection achievement</div></div></div><div class="table-scroll"><table><thead><tr><th>Brand</th><th>Target</th><th>Collection</th><th>Achievement</th></tr></thead><tbody id="brand-summary-body"><tr><td colspan="4" class="empty-state">No data</td></tr></tbody><tfoot id="brand-summary-foot"></tfoot></table></div></div>
        <div class="panel"><div class="panel-header"><div><h3 class="panel-title">Cluster Summary</h3><div class="panel-subtitle">Total by Cluster</div></div></div><div class="table-scroll"><table><thead><tr><th>Cluster</th><th>Target</th><th>Collection</th><th>Achievement</th></tr></thead><tbody id="cluster-summary-body"><tr><td colspan="4" class="empty-state">No data</td></tr></tbody><tfoot id="cluster-summary-foot"></tfoot></table></div></div>
      </div>

      <div class="panel">
        <div class="panel-header">
          <div>
            <h3 class="panel-title">Commitment Report &mdash; By Brand</h3>
            <div class="panel-subtitle">Kis party (brand) ne kitna commitment kiya hai, commitment date ke hisaab se</div>
          </div>
        </div>
        <div class="filter-bar filter-bar-panel">
          <div class="field"><label>Commitment From</label><input type="date" id="commit-from"></div>
          <div class="field"><label>Commitment To</label><input type="date" id="commit-to"></div>
          <button class="btn-primary" id="commit-apply">Show Report</button>
        </div>
        <div class="summary-strip"><span>Total Commitment Amount</span><span id="commit-total">Rs 0</span></div>
        <div class="grid-2">
          <div class="table-scroll">
            <table>
              <thead><tr><th>Brand</th><th>Total Commitment</th></tr></thead>
              <tbody id="commit-brand-body"><tr><td colspan="2" class="empty-state">Showing all commitments in the snapshot.</td></tr></tbody>
            </table>
          </div>
          <div class="table-scroll">
            <table>
              <thead><tr><th>Brand</th><th>Door</th><th>Commit Amt</th><th>Commit Date</th><th>Status</th></tr></thead>
              <tbody id="commit-body"><tr><td colspan="5" class="empty-state">Loading...</td></tr></tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-header"><div><h3 class="panel-title">Detailed Payment Records</h3><div class="panel-subtitle">Grouped by Door + Brand + Cluster</div></div></div>
        <div class="filter-bar">
          <div class="field"><label>Search</label><input type="search" id="payments-search" placeholder="Door, brand, status..."></div>
          <div class="field"><label>Door</label><select id="payments-door"><option value="ALL">ALL</option></select></div>
          <div class="field"><label>Brand</label><select id="payments-brand"><option value="ALL">ALL</option></select></div>
          <div class="field"><label>Status</label><select id="payments-status"><option value="ALL">ALL</option></select></div>
          <div class="field"><label>Date From</label><input type="date" id="payments-date-from"></div>
          <div class="field"><label>Date To</label><input type="date" id="payments-date-to"></div>
          <button class="btn-primary" id="payments-apply">Apply</button>
        </div>
        <div class="summary-strip"><span>Total Collection</span><span id="total-collection-summary">Rs 0</span></div>
        <div class="table-scroll"><table><thead><tr><th>Brand</th><th>Door</th><th>Cluster</th><th>Date Range</th><th>Collection</th><th>View Details</th></tr></thead><tbody id="payments-body"><tr><td colspan="6" class="empty-state">Loading...</td></tr></tbody></table></div>
      </div>
      <div class="footer-note">Generated by Collection Dashboard &middot; this is a static, read-only copy &mdash; re-export for the latest data.</div>
    </div>
  </main>
</div>
<div id="modal-root"></div>
<script>
''' + js_blob + '''
const fmtMoney = (value) => { const num = Number(value) || 0; return 'Rs ' + num.toLocaleString('en-IN', { maximumFractionDigits: 0 }); };
const fmtPct = (value) => `${Number(value || 0).toFixed(1)}%`;
function escapeHtml(str) { return String(str ?? '').replace(/[&<>"']/g, (c) => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' })[c]); }
function openModal({ title, bodyHtml, actions }) { const root = document.getElementById('modal-root'); const overlay = document.createElement('div'); overlay.className = 'modal-overlay'; const box = document.createElement('div'); box.className = 'modal-box'; box.innerHTML = `<div class='modal-title'>${title}</div><div>${bodyHtml}</div><div class='modal-actions' id='modal-actions'></div>`; overlay.appendChild(box); root.appendChild(overlay); const close = () => overlay.remove(); const actionsEl = box.querySelector('#modal-actions'); (actions || []).forEach((a) => { const btn = document.createElement('button'); btn.textContent = a.label; btn.className = a.className || 'btn-secondary'; btn.onclick = () => a.onClick(close); actionsEl.appendChild(btn); }); overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); }); return { close, box }; }
function loadFilters() { const doors = [...new Set(snapshotData.records.map(r => r.door).filter(Boolean))].sort(); const brands = [...new Set(snapshotData.records.map(r => r.brand).filter(Boolean))].sort(); const statuses = [...new Set(snapshotData.records.map(r => r.status).filter(Boolean))].sort(); const select = id => document.getElementById(id); select('door-filter').innerHTML = '<option value="ALL">ALL</option>' + doors.map(d => `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join(''); select('payments-door').innerHTML = '<option value="ALL">ALL</option>' + doors.map(d => `<option value="${escapeHtml(d)}">${escapeHtml(d)}</option>`).join(''); select('payments-brand').innerHTML = '<option value="ALL">ALL</option>' + brands.map(b => `<option value="${escapeHtml(b)}">${escapeHtml(b)}</option>`).join(''); select('payments-status').innerHTML = '<option value="ALL">ALL</option>' + statuses.map(s => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join(''); }
function getFilteredRecords() {
  const args = {
    door: document.getElementById('door-filter').value,
    date_from: document.getElementById('date-from-filter').value,
    date_to: document.getElementById('date-to-filter').value,
    brand: document.getElementById('payments-brand').value,
    status: document.getElementById('payments-status').value,
    search: document.getElementById('payments-search').value.trim(),
    door_filter_details: document.getElementById('payments-door').value,
    payments_date_from: document.getElementById('payments-date-from').value,
    payments_date_to: document.getElementById('payments-date-to').value,
  };
  const rows = snapshotData.records.filter((row) => {
    if (args.door && args.door !== 'ALL' && row.door !== args.door) return false;
    if (args.door_filter_details && args.door_filter_details !== 'ALL' && row.door !== args.door_filter_details) return false;
    if (args.brand && args.brand !== 'ALL' && row.brand !== args.brand) return false;
    if (args.status && args.status !== 'ALL' && row.status !== args.status) return false;
    if (args.date_from && row.date && row.date < args.date_from) return false;
    if (args.date_to && row.date && row.date > args.date_to) return false;
    // The Detailed Payment Records section has its own Date From/To - this is
    // what previously had no effect, since it never reached this filter.
    if (args.payments_date_from && row.date && row.date < args.payments_date_from) return false;
    if (args.payments_date_to && row.date && row.date > args.payments_date_to) return false;
    if (args.search) { const haystack = `${row.door || ''} ${row.brand || ''} ${row.cluster || ''} ${row.status || ''} ${row.reminder_remark || ''}` .toLowerCase(); if (!haystack.includes(args.search.toLowerCase())) return false; }
    return true;
  });
  return rows;
}
function renderKpis(rows) { const master = {}; rows.forEach(r => { const key = `${r.door || ''}|${r.brand || ''}`; if (!master[key] || Number(r.id) > Number(master[key].id)) master[key] = r; }); const totalTarget = Object.values(master).reduce((s, r) => s + Number(r.target || 0), 0); const totalCollection = Object.values(master).reduce((s, r) => s + Number(r.collection || 0), 0); const totalOs = Object.values(master).reduce((s, r) => s + Number(r.os || 0), 0); const totalSixty = Object.values(master).reduce((s, r) => s + Number(r.sixty_plus || 0), 0); const totalCommitment = rows.reduce((s, r) => s + Number(r.commitment_amount || 0), 0); document.getElementById('kpi-target').textContent = fmtMoney(totalTarget); document.getElementById('kpi-collection').textContent = fmtMoney(totalCollection); document.getElementById('kpi-os').textContent = fmtMoney(totalOs); document.getElementById('kpi-sixty').textContent = fmtMoney(totalSixty); document.getElementById('kpi-amount').textContent = fmtMoney(totalCommitment); }
function renderSummaries(rows) { const master = {}; rows.forEach(r => { const key = `${r.door || ''}|${r.brand || ''}`; if (!master[key] || Number(r.id) > Number(master[key].id)) master[key] = r; }); const brands = {}; Object.values(master).forEach(r => { const brand = r.brand || 'Unassigned'; brands[brand] = brands[brand] || { brand, target:0, collection:0 }; brands[brand].target += Number(r.target || 0); brands[brand].collection += Number(r.collection || 0); }); const brandRows = Object.values(brands).sort((a,b) => a.brand.localeCompare(b.brand)); const brandBody = document.getElementById('brand-summary-body'); brandBody.innerHTML = brandRows.length ? brandRows.map((b) => `<tr><td>${escapeHtml(b.brand)}</td><td>${fmtMoney(b.target)}</td><td>${fmtMoney(b.collection)}</td><td>${fmtPct(b.collection && b.target ? (b.collection / b.target) * 100 : 0)}</td></tr>`).join('') : '<tr><td colspan="4" class="empty-state">No data.</td></tr>'; const totalTarget = brandRows.reduce((s,b)=>s+Number(b.target||0),0); const totalCollection = brandRows.reduce((s,b)=>s+Number(b.collection||0),0); document.getElementById('brand-summary-foot').innerHTML = `<tr><td>TOTAL</td><td>${fmtMoney(totalTarget)}</td><td>${fmtMoney(totalCollection)}</td><td>${fmtPct(totalTarget ? (totalCollection / totalTarget) * 100 : 0)}</td></tr>`; const clusters = {}; Object.values(master).forEach(r => { const cluster = r.cluster || 'Unassigned'; clusters[cluster] = clusters[cluster] || { cluster, target:0, collection:0 }; clusters[cluster].target += Number(r.target || 0); clusters[cluster].collection += Number(r.collection || 0); }); const clusterRows = Object.values(clusters).sort((a,b) => a.cluster.localeCompare(b.cluster)); const clusterBody = document.getElementById('cluster-summary-body'); clusterBody.innerHTML = clusterRows.length ? clusterRows.map((c) => `<tr><td>${escapeHtml(c.cluster)}</td><td>${fmtMoney(c.target)}</td><td>${fmtMoney(c.collection)}</td><td>${fmtPct(c.collection && c.target ? (c.collection / c.target) * 100 : 0)}</td></tr>`).join('') : '<tr><td colspan="4" class="empty-state">No data.</td></tr>'; const totalClusterTarget = clusterRows.reduce((s,c)=>s+Number(c.target||0),0); const totalClusterCollection = clusterRows.reduce((s,c)=>s+Number(c.collection||0),0); document.getElementById('cluster-summary-foot').innerHTML = `<tr><td>TOTAL</td><td>${fmtMoney(totalClusterTarget)}</td><td>${fmtMoney(totalClusterCollection)}</td><td>${fmtPct(totalClusterTarget ? (totalClusterCollection / totalClusterTarget) * 100 : 0)}</td></tr>`; }
function renderGroupedPayments(rows) { const groups = {}; rows.forEach((r) => { const key = `${r.door || ''}|${r.brand || ''}|${r.cluster || 'Unassigned'}`; if (!groups[key]) groups[key] = { door:r.door, brand:r.brand, cluster:r.cluster || 'Unassigned', records:[], collection:0, date_from:null, date_to:null }; const g = groups[key]; g.records.push(r); const amount = Number(r.amount || 0); g.collection += amount; const d = r.date ? new Date(r.date) : null; if (d && (!g.date_from || d < new Date(g.date_from))) g.date_from = d; if (d && (!g.date_to || d > new Date(g.date_to))) g.date_to = d; }); const out = Object.values(groups).map((g) => ({ ...g, date_from: g.date_from ? g.date_from.toISOString().slice(0,10) : '', date_to: g.date_to ? g.date_to.toISOString().slice(0,10) : '', collection: g.collection })); const total = out.reduce((s, g) => s + Number(g.collection || 0), 0); document.getElementById('total-collection-summary').textContent = fmtMoney(total); const tbody = document.getElementById('payments-body'); if (!out.length) { tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No matching records.</td></tr>'; return; } tbody.innerHTML = out.map((g) => `<tr><td>${escapeHtml(g.brand || '')}</td><td>${escapeHtml(g.door || '')}</td><td>${escapeHtml(g.cluster || 'Unassigned')}</td><td>${escapeHtml(g.date_from ? g.date_from : '')}${g.date_from && g.date_to ? ' to ' : ''}${escapeHtml(g.date_to ? g.date_to : '')}</td><td>${fmtMoney(g.collection)}</td><td><button class='btn-secondary btn-sm' onclick='showGroupDetails(${JSON.stringify(g).replace(/"/g, '&quot;')})'>View Details</button></td></tr>`).join(''); }
function showGroupDetails(group) { const rows = group.records.slice().sort((a,b) => new Date(a.date) - new Date(b.date)); const body = rows.map((r) => `<tr><td>${escapeHtml(r.date || '')}</td><td>${fmtMoney(r.amount || 0)}</td><td>${escapeHtml(r.status || '')}</td></tr>`).join(''); openModal({ title: `${group.brand} | ${group.door} | ${group.cluster}`, bodyHtml: `<table><thead><tr><th>Date</th><th>Amount</th><th>Status</th></tr></thead><tbody>${body}</tbody></table><div class="muted" style="margin-top:10px;font-size:12px;">This is a read-only snapshot - open the live app to update reminders or commitments.</div>`, actions: [{ label: 'Close', className: 'btn-secondary', onClick: (close) => close() }] }); }
window.showGroupDetails = showGroupDetails;
function renderCommitmentReport() {
  const from = document.getElementById('commit-from').value;
  const to = document.getElementById('commit-to').value;
  const rows = snapshotData.records.filter(r => {
    if (!r.commitment_date) return false;
    if (from && r.commitment_date < from) return false;
    if (to && r.commitment_date > to) return false;
    return true;
  });
  const total = rows.reduce((s, r) => s + Number(r.commitment_amount || 0), 0);
  document.getElementById('commit-total').textContent = fmtMoney(total);
  const brandTotals = {};
  rows.forEach(r => { const b = r.brand || 'Unassigned'; brandTotals[b] = (brandTotals[b] || 0) + Number(r.commitment_amount || 0); });
  const brandRows = Object.entries(brandTotals).map(([brand, total]) => ({ brand, total })).sort((a, b) => b.total - a.total);
  const brandBody = document.getElementById('commit-brand-body');
  brandBody.innerHTML = brandRows.length ? brandRows.map(b => `<tr><td>${escapeHtml(b.brand)}</td><td>${fmtMoney(b.total)}</td></tr>`).join('') : '<tr><td colspan="2" class="empty-state">No commitments in this range.</td></tr>';
  const detailBody = document.getElementById('commit-body');
  detailBody.innerHTML = rows.length ? rows.slice().sort((a,b) => (a.commitment_date || '').localeCompare(b.commitment_date || '')).map(r => `<tr><td>${escapeHtml(r.brand || '')}</td><td>${escapeHtml(r.door || '')}</td><td>${r.commitment_amount != null ? fmtMoney(r.commitment_amount) : ''}</td><td>${escapeHtml(r.commitment_date || '')}</td><td>${r.status === 'RECEIVED' ? '<span class="badge badge-received">RECEIVED</span>' : '<span class="badge badge-pending">PENDING</span>'}</td></tr>`).join('') : '<tr><td colspan="5" class="empty-state">No commitments in this range.</td></tr>';
}
function refreshSnapshotView() { const rows = getFilteredRecords(); renderKpis(rows); renderSummaries(rows); renderGroupedPayments(rows); }
loadFilters();
refreshSnapshotView();
renderCommitmentReport();
document.getElementById('apply-filters').addEventListener('click', refreshSnapshotView);
document.getElementById('payments-apply').addEventListener('click', refreshSnapshotView);
document.getElementById('door-filter').addEventListener('change', refreshSnapshotView);
document.getElementById('payments-door').addEventListener('change', refreshSnapshotView);
document.getElementById('payments-brand').addEventListener('change', refreshSnapshotView);
document.getElementById('payments-status').addEventListener('change', refreshSnapshotView);
document.getElementById('payments-search').addEventListener('input', refreshSnapshotView);
document.getElementById('date-from-filter').addEventListener('change', refreshSnapshotView);
document.getElementById('date-to-filter').addEventListener('change', refreshSnapshotView);
document.getElementById('payments-date-from').addEventListener('change', refreshSnapshotView);
document.getElementById('payments-date-to').addEventListener('change', refreshSnapshotView);
document.getElementById('commit-apply').addEventListener('click', renderCommitmentReport);
</script>
</body></html>
'''
    filename = f"Collection_Dashboard_{date_from}_to_{date_to}.html"
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", filename)
    export_dir = os.path.join(BASE_DIR, "exports")
    os.makedirs(export_dir, exist_ok=True)
    export_path = os.path.join(export_dir, safe_name)
    with open(export_path, "w", encoding="utf-8") as fp:
        fp.write(html)
    return send_file(export_path, as_attachment=True, download_name=safe_name)


# =======================================================================
# API: DATA MANAGEMENT (Page 3)
# =======================================================================
@app.route("/api/data/search")
def api_data_search():
    where, params = build_filter_clause(request.args)
    rows = fetch_all(
        f"""
        SELECT id, door, door_type, cluster, os, sixty_plus, target, collection, ach,
               date, amount, status, brand, reminder_remark, reminder_date,
               commitment_date, commitment_amount
        FROM records
        {where}
        ORDER BY date DESC
        LIMIT 1000
        """,
        params,
    )
    return jsonify({"success": True, "rows": rows, "count": len(rows)})


@app.route("/api/data/update/<int:record_id>", methods=["POST"])
def api_data_update(record_id):
    data = request.get_json(force=True)

    allowed_fields = {
        "amount": "amount",
        "status": "status",
        "cluster": "cluster",
        "reminder_remark": "reminder_remark",
        "commitment_date": "commitment_date",
        "commitment_amount": "commitment_amount",
    }
    updates = []
    params = []
    for field_in, column in allowed_fields.items():
        if field_in in data:
            updates.append(f"{column} = ?")
            params.append(data[field_in])

    # Business rule: updating the reminder remark auto-stamps today's reminder date
    if "reminder_remark" in data:
        updates.append("reminder_date = ?")
        params.append(datetime.now().strftime("%Y-%m-%d"))

    if not updates:
        return jsonify({"success": False, "error": "No valid fields to update."}), 400

    updates.append("updated_at = datetime('now')")
    params.append(record_id)

    conn = get_connection()
    try:
        conn.execute(f"UPDATE records SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    finally:
        conn.close()
    return jsonify({"success": True})


@app.route("/api/data/delete", methods=["POST"])
def api_data_delete():
    data = request.get_json(force=True)
    ids = data.get("ids", [])
    password = data.get("password", "")

    if not ids:
        return jsonify({"success": False, "error": "No records selected."}), 400

    if password != DELETE_PASSWORD:
        return jsonify({"success": False, "error": "Incorrect password."}), 403

    placeholders = ",".join("?" for _ in ids)
    conn = get_connection()
    try:
        conn.execute(f"DELETE FROM records WHERE id IN ({placeholders})", ids)
        conn.commit()
    finally:
        conn.close()
    return jsonify({"success": True, "deleted": len(ids)})


# =======================================================================
# API: BACKUP / RECOVERY
# =======================================================================
def _make_backup_file(prefix="backup"):
    """Writes a fresh backup workbook into BACKUP_DIR and returns (path, row_count)."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{prefix}_{stamp}.xlsx"
    path = os.path.join(BACKUP_DIR, filename)
    row_count = excel_processor.export_backup_workbook(path)
    return path, row_count


def _prune_old_backups(prefix="auto_backup", keep=15):
    """Keeps only the most recent N auto-backups so the folder doesn't grow forever."""
    files = sorted(
        glob.glob(os.path.join(BACKUP_DIR, f"{prefix}_*.xlsx")),
        key=os.path.getmtime,
        reverse=True,
    )
    for old_file in files[keep:]:
        try:
            os.remove(old_file)
        except OSError:
            pass


@app.route("/api/backup/download")
def api_backup_download():
    """
    On-demand full backup. Generates an .xlsx snapshot of every record right
    now and sends it straight to the browser as a download - the same file
    layout Upload Excel accepts, so it doubles as a restore/recovery file.
    """
    path, row_count = _make_backup_file(prefix="backup")
    download_name = os.path.basename(path)
    return send_file(path, as_attachment=True, download_name=download_name)


@app.route("/api/backup/list")
def api_backup_list():
    files = sorted(
        glob.glob(os.path.join(BACKUP_DIR, "*.xlsx")),
        key=os.path.getmtime,
        reverse=True,
    )
    result = []
    for f in files[:50]:
        stat = os.stat(f)
        result.append({
            "filename": os.path.basename(f),
            "size_kb": round(stat.st_size / 1024, 1),
            "created_at": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return jsonify({"success": True, "backups": result})


@app.route("/api/backup/file/<path:filename>")
def api_backup_file(filename):
    safe_name = secure_filename(filename)
    path = os.path.join(BACKUP_DIR, safe_name)
    if not os.path.isfile(path):
        return jsonify({"success": False, "error": "Backup file not found."}), 404
    return send_file(path, as_attachment=True, download_name=safe_name)


# =======================================================================
# API: EXCEL UPLOAD
# =======================================================================
@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file uploaded."}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected."}), 400
    if not allowed_file(file.filename):
        return jsonify({"success": False, "error": "Only .xlsx and .xls files are supported."}), 400

    filename = secure_filename(file.filename)
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(save_path)

    # Safety net: automatically snapshot whatever is currently in the
    # database BEFORE this new file is processed. If the new upload turns
    # out to be bad/corrupt, this auto-backup can be downloaded from
    # Data Management -> Backups and re-uploaded to recover.
    try:
        existing = fetch_one("SELECT COUNT(*) AS c FROM records")["c"]
        if existing:
            _make_backup_file(prefix="auto_backup")
            _prune_old_backups(prefix="auto_backup", keep=15)
    except Exception:
        logger.exception("Auto-backup before upload failed (continuing with upload anyway)")

    result = excel_processor.process_excel_file(save_path, filename)
    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


# =======================================================================
# MAIN
# =======================================================================
if __name__ == "__main__":
    init_db()
    # webbrowser auto-open, useful for the packaged .exe experience
    import webbrowser
    import threading

    port = 5000
    url = f"http://127.0.0.1:{port}/"

    def open_browser():
        webbrowser.open(url)

    if os.environ.get("CD_NO_BROWSER") != "1":
        threading.Timer(1.0, open_browser).start()

    app.run(host="0.0.0.0", port=port, debug=False)
