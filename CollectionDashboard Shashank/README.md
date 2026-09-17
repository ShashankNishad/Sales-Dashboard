# Collection Management Dashboard

A complete Collection Management System: Excel upload → SQLite storage →
professional dashboard, door/brand analytics, reminder & commitment
tracking, and password-protected data management. Packaged to run as a
Windows `.exe`.

## Stack
- Frontend: HTML / CSS / vanilla JavaScript
- Backend: Python + Flask (REST-style JSON APIs)
- Database: SQLite3 (auto-created on first run)
- Excel processing: Pandas + OpenPyXL

## 1. Run it locally (development)

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
python app.py
```

Your browser opens automatically at `http://127.0.0.1:5000/`.
The SQLite database is created automatically at `database/collection.db`
the first time you run it — nothing to set up manually.

To generate a sample Excel file for testing uploads:
```bash
python make_sample_excel.py
```
Then use the **Upload Excel** button in the left sidebar (works from any page)
and pick `sample_data.xlsx`.

## 2. Required Excel columns

```
DOOR, DOOR TYPE, O/S, 60+, TARGET, COLLECTION, ACH, DATE, AMOUNT, STATUS, BRAND
```
Optional: `Cluster` (or `Cluster Name`), `Reminder Remark`, `Reminder Date`, `Commitment Date`, `Commitment Amount`

`Cluster` is a person/team assigned to a Brand (e.g. Levis → Shashank,
Rare Rabbit → Lalit). It drives the **Cluster Summary** table on the
Dashboard (Target / Total Collection / Achievement % per cluster).

Dates, numbers with commas/₹/%, and blank cells are all handled gracefully.
A row missing DOOR or BRAND is skipped (not the whole file); the upload
result tells you how many rows were inserted vs. skipped.

## 3. The 3 pages

1. **Dashboard** (`/`) — KPI cards (Target/Collection/O-S/60+/Amount),
   Brand Summary table (with a Total row), Cluster Summary table (Target /
   Collection / Achievement % by Cluster Name), Door filter (all update
   live, no page refresh).
2. **Collection Details** (`/details`) — Door-wise brand breakdown with a
   Total row, searchable/sortable/paginated payment table with an inline
   "Update" button per row to record a Reminder Remark + Commitment
   Date/Amount, plus Commitment-Date and Reminder-Date range reports —
   each row in these two reports also has an **Update** button, so if a
   commitment slips (e.g. the party pushes the date further) you can edit
   it right there and it updates the same underlying record. A checkbox
   in the update dialog lets you choose whether to also stamp today as the
   Reminder Date, or only move the Commitment Date/Amount.
3. **Data Management** (`/data-management`) — Search by date range /
   brand / door / cluster / status, EDIT a record inline (including its
   Cluster), or select rows and DELETE — which requires a confirmation
   dialog **and** a password (development password: `Shashank`, checked
   server-side only — it is never present in any JavaScript file). This
   page also lists all data **Backups** with one-click download.

## 4. Backup & recovery

- **Automatic backup**: right before every Excel upload is processed, the
  app snapshots everything currently in the database into a timestamped
  `.xlsx` file under `backups/` (kept: last 15 auto-backups).
- **Manual backup**: click **"Backup Data"** in the sidebar (any page,
  any time) to instantly download a full `.xlsx` snapshot of every record.
- **Recovery**: any backup file uses the exact same column layout as a
  normal upload, so if data ever looks wrong/corrupted, just re-upload
  the backup file via **Upload Excel** to restore it.
- All available backups (auto + manual) are listed with download links on
  the **Data Management** page.
- Note: browsers can't run a custom "Yes/No, download this file" dialog
  when a tab is being closed (a security restriction), so instead the app
  shows a native "leave site?" reminder if you haven't clicked Backup Data
  yet this session — click **Backup Data** before closing to be safe.

## 5. Important business rule — duplicate Door+Brand rows

The same Door+Brand can repeat across many DATE rows. `TARGET`, `O/S`,
`60+` and `COLLECTION` are treated as **master** values (repeated per
Door+Brand) — the backend dedupes to one row per Door+Brand (the most
recently inserted) before summing them, so totals are never inflated.
`AMOUNT` is treated as **transactional** and is summed across every row.

This logic lives in ONE place — `AGGREGATION_STRATEGY` at the top of
`database.py` — so you can change it (e.g. if COLLECTION should actually
be summed per transaction) without touching any route code.

## 6. Package as a Windows `.exe`

Do this step **on a Windows machine** with the venv from step 1 active:

```bash
python build_exe.py
```

This runs PyInstaller with the right `--add-data` flags to bundle
`templates/` and `static/` inside the executable. Output:

```
dist/CollectionDashboard/CollectionDashboard.exe
```

Hand the whole `dist/CollectionDashboard/` folder to the end user. They
double-click `CollectionDashboard.exe` — no Python, no VS Code, no
manual browser opening required. The app creates its own
`database/`, `uploads/` and `logs/` folders right next to the `.exe`.

## 7. Project structure

```
CollectionDashboard/
├── app.py                  Flask app + all API routes
├── database.py             Schema + centralized aggregation logic
├── excel_processor.py      Excel validation/cleaning/import
├── build_exe.py            PyInstaller packaging script
├── make_sample_excel.py    Generates test data
├── requirements.txt
├── database/collection.db  (auto-created)
├── templates/
│   ├── base.html
│   ├── dashboard.html
│   ├── details.html
│   └── data_management.html
├── static/
│   ├── css/style.css
│   └── js/{common,dashboard,details,data_management}.js
├── uploads/                 (uploaded Excel files land here)
├── backups/                 (auto + manual backup snapshots)
└── logs/app.log             (detailed errors; users never see raw tracebacks)
```

## 8. Security notes

- All SQL uses parameterized queries — no string concatenation of user input.
- The delete password is checked only in `app.py` (server-side); it is
  never sent to or stored in the browser/JS.
- For production, move `DELETE_PASSWORD` in `app.py` to an environment
  variable or a hashed value in a config file instead of the hardcoded
  development default.
