"""
excel_processor.py
-------------------
Reads an uploaded Excel file with Pandas, validates/cleans it, and
inserts valid rows into SQLite. One bad row never crashes the whole
upload - it is skipped and reported back to the user.
"""

import pandas as pd
import numpy as np
from datetime import datetime
import logging
import re

from database import get_connection

logger = logging.getLogger("excel_processor")

REQUIRED_COLUMNS = [
    "DOOR", "DOOR TYPE", "O/S", "60+", "TARGET", "COLLECTION",
    "ACH", "DATE", "AMOUNT", "STATUS", "BRAND",
]
OPTIONAL_COLUMNS = [
    "Reminder Remark", "Reminder Date", "Commitment Date", "Commitment Amount",
]
# A few different header spellings are accepted for the cluster column so an
# existing Excel workbook can add whichever label is most natural.
CLUSTER_COLUMN_ALIASES = ["CLUSTER", "CLUSTER NAME", "CLUSTER-NAME"]

COLUMN_MAP = {
    "DOOR": "door",
    "DOOR TYPE": "door_type",
    "O/S": "os",
    "60+": "sixty_plus",
    "TARGET": "target",
    "COLLECTION": "collection",
    "ACH": "ach",
    "DATE": "date",
    "AMOUNT": "amount",
    "STATUS": "status",
    "BRAND": "brand",
    "Reminder Remark": "reminder_remark",
    "Reminder Date": "reminder_date",
    "Commitment Date": "commitment_date",
    "Commitment Amount": "commitment_amount",
}

# Full column layout used for both the upload template and the backup /
# export workbook, so a backup file can always be re-uploaded as-is.
BACKUP_COLUMNS = [
    "DOOR", "DOOR TYPE", "CLUSTER", "O/S", "60+", "TARGET", "COLLECTION",
    "ACH", "DATE", "AMOUNT", "STATUS", "BRAND",
    "Reminder Remark", "Reminder Date", "Commitment Date", "Commitment Amount",
]


def _clean_text(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text if text else None


def _clean_numeric(value):
    """Parse numeric values, tolerating commas, currency symbols, % signs, blanks."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        if isinstance(value, float) and np.isnan(value):
            return 0.0
        return float(value)
    text = str(value).strip()
    if text == "" or text.lower() in ("nan", "none", "-", "na"):
        return 0.0
    text = text.replace(",", "").replace("₹", "").replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return 0.0


def _clean_date(value):
    """Normalize many date formats to YYYY-MM-DD. Returns None if blank/invalid."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if text == "" or text.lower() in ("nan", "none", "-"):
        return None
    formats = [
        "%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d",
        "%m/%d/%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Last resort - let pandas try to guess
    try:
        parsed = pd.to_datetime(text, errors="raise", dayfirst=True)
        return parsed.strftime("%Y-%m-%d")
    except Exception:
        return None


def validate_columns(df):
    """Return list of missing required columns (case/space tolerant)."""
    normalized = {str(c).strip().upper(): c for c in df.columns}
    missing = []
    for req in REQUIRED_COLUMNS:
        if req.upper() not in normalized:
            missing.append(req)
    return missing


def process_excel_file(filepath, original_filename):
    """
    Reads, validates, cleans and inserts an Excel file's rows into SQLite.
    Returns a dict summary: {success, inserted, skipped, errors, missing_columns}
    """
    try:
        df = pd.read_excel(filepath, dtype=object)
    except Exception as e:
        logger.exception("Failed to read excel file")
        return {"success": False, "error": f"Could not read Excel file: {e}"}

    df.columns = [str(c).strip() for c in df.columns]

    missing = validate_columns(df)
    if missing:
        return {
            "success": False,
            "error": "Missing required column(s).",
            "missing_columns": missing,
        }

    # Build a lookup from normalized header -> actual header found in file
    normalized = {str(c).strip().upper(): c for c in df.columns}

    def col(name):
        return normalized.get(name.upper())

    def col_any(*names):
        for name in names:
            found = normalized.get(name.upper())
            if found:
                return found
        return None

    cluster_col = col_any(*CLUSTER_COLUMN_ALIASES)

    inserted = 0
    skipped = 0
    row_errors = []

    conn = get_connection()
    cur = conn.cursor()

    for idx, row in df.iterrows():
        try:
            door = _clean_text(row.get(col("DOOR")))
            brand = _clean_text(row.get(col("BRAND")))
            if not door or not brand:
                skipped += 1
                row_errors.append(f"Row {idx + 2}: missing DOOR or BRAND, skipped.")
                continue

            door_type = _clean_text(row.get(col("DOOR TYPE")))
            cluster = _clean_text(row.get(cluster_col)) if cluster_col else None
            os_val = _clean_numeric(row.get(col("O/S")))
            sixty_plus = _clean_numeric(row.get(col("60+")))
            target = _clean_numeric(row.get(col("TARGET")))
            collection = _clean_numeric(row.get(col("COLLECTION")))
            ach = _clean_text(row.get(col("ACH")))
            date_val = _clean_date(row.get(col("DATE")))
            amount = _clean_numeric(row.get(col("AMOUNT")))
            status = _clean_text(row.get(col("STATUS"))) or "PENDING"

            reminder_remark = None
            reminder_date = None
            commitment_date = None
            commitment_amount = None

            if col("Reminder Remark"):
                reminder_remark = _clean_text(row.get(col("Reminder Remark")))
            if col("Reminder Date"):
                reminder_date = _clean_date(row.get(col("Reminder Date")))
            if col("Commitment Date"):
                commitment_date = _clean_date(row.get(col("Commitment Date")))
            if col("Commitment Amount"):
                commitment_amount = _clean_numeric(row.get(col("Commitment Amount")))

            cur.execute(
                """
                INSERT INTO records
                (door, door_type, cluster, os, sixty_plus, target, collection, ach, date,
                 amount, status, brand, reminder_remark, reminder_date,
                 commitment_date, commitment_amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    door, door_type, cluster, os_val, sixty_plus, target, collection,
                    ach, date_val, amount, status, brand, reminder_remark,
                    reminder_date, commitment_date, commitment_amount,
                ),
            )
            inserted += 1
        except Exception as e:
            skipped += 1
            row_errors.append(f"Row {idx + 2}: {e}")
            logger.warning("Skipped row %s due to error: %s", idx + 2, e)

    cur.execute(
        "INSERT INTO upload_log (filename, rows_inserted, rows_skipped, notes) "
        "VALUES (?, ?, ?, ?)",
        (original_filename, inserted, skipped, "; ".join(row_errors[:20])),
    )
    conn.commit()
    conn.close()

    return {
        "success": True,
        "inserted": inserted,
        "skipped": skipped,
        "errors": row_errors[:20],  # cap for UI readability
        "total_errors": len(row_errors),
    }


# =======================================================================
# BACKUP / EXPORT
# =======================================================================
def export_backup_workbook(filepath):
    """
    Dumps EVERY record currently in the database into an .xlsx file using
    the exact same column layout the app accepts on upload (see
    BACKUP_COLUMNS). This means the resulting file is both a safe backup
    AND can be re-uploaded through "Upload Excel" to restore/recover the
    data if the live database ever gets corrupted.

    Returns the number of rows written.
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            SELECT door, door_type, cluster, os, sixty_plus, target, collection,
                   ach, date, amount, status, brand, reminder_remark,
                   reminder_date, commitment_date, commitment_amount
            FROM records
            ORDER BY id ASC
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    records = []
    for r in rows:
        records.append({
            "DOOR": r["door"],
            "DOOR TYPE": r["door_type"],
            "CLUSTER": r["cluster"],
            "O/S": r["os"],
            "60+": r["sixty_plus"],
            "TARGET": r["target"],
            "COLLECTION": r["collection"],
            "ACH": r["ach"],
            "DATE": r["date"],
            "AMOUNT": r["amount"],
            "STATUS": r["status"],
            "BRAND": r["brand"],
            "Reminder Remark": r["reminder_remark"],
            "Reminder Date": r["reminder_date"],
            "Commitment Date": r["commitment_date"],
            "Commitment Amount": r["commitment_amount"],
        })

    df = pd.DataFrame(records, columns=BACKUP_COLUMNS)
    df.to_excel(filepath, index=False)
    return len(records)
