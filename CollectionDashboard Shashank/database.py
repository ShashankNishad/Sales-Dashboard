"""
database.py
-----------
Handles SQLite connection, schema creation, and the CENTRALIZED
aggregation logic for the Collection Management Dashboard.

IMPORTANT BUSINESS RULE
========================
The same DOOR + BRAND can appear on multiple rows because a new row is
added for every DATE (transaction / follow-up date) that occurs. Fields
like TARGET, O/S and 60+ are "master" values that describe the Door+Brand
as a whole and are REPEATED on every one of those rows. If we blindly
SUM these columns across all rows, the totals get artificially inflated
by the number of duplicate date-rows.

To keep this correct and easy to change later, the classification of
every numeric column is centralized in AGGREGATION_STRATEGY below.

  "master"        -> value is repeated per DOOR+BRAND. When aggregating,
                      we take ONE representative value per DOOR+BRAND
                      (the latest by rowid) and then sum those
                      representative values across doors/brands.
  "transactional" -> value is per-row/per-date and should be SUMMED
                      across every row normally (e.g. AMOUNT collected
                      on each date).

If your business logic changes (e.g. COLLECTION becomes transactional
instead of a repeated master value), just edit the dict below - no
other code needs to change.
"""

import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "database")
DB_PATH = os.path.join(DB_DIR, "collection.db")

# ---------------------------------------------------------------------
# CENTRALIZED AGGREGATION STRATEGY - edit this to change business logic
# ---------------------------------------------------------------------
AGGREGATION_STRATEGY = {
    "target": "master",          # repeated per Door+Brand -> dedupe then sum
    "os": "master",              # O/S - repeated per Door+Brand -> dedupe then sum
    "sixty_plus": "master",      # 60+ - repeated per Door+Brand -> dedupe then sum
    "collection": "master",      # repeated per Door+Brand (as-of value) -> dedupe then sum
    "amount": "transactional",   # actual money received on a DATE -> sum every row
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    door TEXT NOT NULL,
    door_type TEXT,
    cluster TEXT,
    os REAL DEFAULT 0,
    sixty_plus REAL DEFAULT 0,
    target REAL DEFAULT 0,
    collection REAL DEFAULT 0,
    ach TEXT,
    date TEXT,
    amount REAL DEFAULT 0,
    status TEXT,
    brand TEXT,
    reminder_remark TEXT,
    reminder_date TEXT,
    commitment_date TEXT,
    commitment_amount REAL,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_door ON records(door);
CREATE INDEX IF NOT EXISTS idx_brand ON records(brand);
CREATE INDEX IF NOT EXISTS idx_date ON records(date);
CREATE INDEX IF NOT EXISTS idx_reminder_date ON records(reminder_date);
CREATE INDEX IF NOT EXISTS idx_commitment_date ON records(commitment_date);
CREATE INDEX IF NOT EXISTS idx_status ON records(status);
CREATE INDEX IF NOT EXISTS idx_door_type ON records(door_type);
CREATE INDEX IF NOT EXISTS idx_cluster ON records(cluster);
CREATE INDEX IF NOT EXISTS idx_door_brand ON records(door, brand);

CREATE TABLE IF NOT EXISTS upload_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT,
    rows_inserted INTEGER,
    rows_skipped INTEGER,
    upload_time TEXT DEFAULT (datetime('now')),
    notes TEXT
);
"""

# ---------------------------------------------------------------------
# Lightweight migration: adds any columns that don't exist yet on an
# already-created database file (so existing installs / existing
# collection.db files pick up new fields like `cluster` automatically,
# without losing any data).
# ---------------------------------------------------------------------
MIGRATION_COLUMNS = {
    "cluster": "TEXT",
}


def _migrate(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(records)").fetchall()}
    for col_name, col_type in MIGRATION_COLUMNS.items():
        if col_name not in existing:
            conn.execute(f"ALTER TABLE records ADD COLUMN {col_name} {col_type}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cluster ON records(cluster)")
    conn.commit()


def get_connection():
    """Return a new SQLite connection with row factory set to dict-like access."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create the database and tables if they do not already exist."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _migrate(conn)
    finally:
        conn.close()


def master_dedupe_subquery():
    """
    Returns a SQL fragment (as a string) that selects ONE representative
    row per DOOR+BRAND (the most recently inserted one, i.e. MAX(id)).
    Used whenever we need to sum "master" fields (target, os, sixty_plus,
    collection) without double counting duplicate date-rows.
    """
    return """
        SELECT r.*
        FROM records r
        INNER JOIN (
            SELECT door, brand, MAX(id) AS max_id
            FROM records
            GROUP BY door, brand
        ) latest ON r.door = latest.door
                AND r.brand = latest.brand
                AND r.id = latest.max_id
    """


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
