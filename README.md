# HemoGrid: Blood Bank, Donor & Emergency Allocation Database System

Tracks donors, donation camps, lab screening, labelled blood units with expiry dates, hospital requests and emergency allocation. PostgreSQL holds the transactional data; MongoDB holds screening reports. The business rules live in the database (triggers and functions), and the web app is a thin layer over them.

## Run it

**One click:** double-click the HemoGrid shortcut on the Desktop or in the Start menu (both are created the first time), or open `HemoGrid.pyw`. A small launcher window checks the setup and installs whatever is missing:

| Step | What it checks | If missing |
|---|---|---|
| Python environment | private virtual environment in `.venv` | creates it |
| Application packages | Flask, Markdown, psycopg, pymongo | installs `requirements-app.txt` |
| PostgreSQL 16 | portable server in the tools folder | downloads and unpacks it (about 320 MB) |
| MongoDB 7 | portable server in the tools folder | downloads and unpacks it (about 590 MB) |
| Database servers | data directories and running servers | initialises and starts both |
| Sample data | schema and demo data | builds and seeds the database |
| Web application | the app on port 5057 | starts it |

It then opens HemoGrid in its own window, with no browser tabs or address bar. No console windows are opened at any point. When that window is closed, the launcher stops the application and both databases. Starting it a second time while it is running just opens another window.

The tools folder is `N:\Tools` when an N: drive exists, otherwise `%LOCALAPPDATA%\HemoGrid\tools`. Set `HEMO_TOOLS` to choose another place. Logs are in its `logs` subfolder. To stop everything by hand, run `pythonw HemoGrid.pyw --stop`.

Needs Windows 10 or 11 with Python 3.12 or newer (with tkinter) and Microsoft Edge or Chrome.

Manual setup without the launcher:

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements-app.txt
.venv\Scripts\python scripts\seed.py
.venv\Scripts\python app\app.py
```

## What is where

| Area | Where |
|---|---|
| Tables, constraints, domains, indexes | `db/01_schema.sql` |
| Triggers and routines (`allocate_units`, `record_screening`, `issue_request`, ...) | `db/02_logic.sql` |
| Views and roles with GRANTs | `db/03_views_roles.sql` |
| Eight reference queries with their relational-algebra form | **Query lab** page, `app/queries.py` |
| Narrated walkthrough video (3 min 35 s, captions) | top of the **Design** page; rebuild with `video/narration.py` then `video/build.py` (see below) |
| ER diagram, normalization, algebra, indexing, transactions, NoSQL | **Design** page in the app (sources in `docs/`) |
| MongoDB screening reports | `docs/nosql.md`, Screening and Query lab pages |
| Walk-through of the database in psql | `scripts/live_demo.sql` |
| Talk-through script | `docs/presentation-script.md` |

## Tests (all headless)

| Command | What it checks |
|---|---|
| `python tests\test_db.py` | 13 database checks: compatibility matrix, triggers, routines, status rules, roles; each rolls back |
| `python tests\ui_flows.py` | 13 flows through the real forms (re-seed afterwards: it writes data) |
| `python tests\ui_audit.py` | every page (incl. Design) at 1280, 1024 and 390 px: console errors, overflow, scrollbars, tap targets, contrast, hover, focus |
| `python scripts\demo_transactions.py` | concurrency demo on a scratch clone; output in `docs\transactions_demo.txt` |
| `python scripts\demo_indexing.py` | index comparison on 400k rows; output in `docs\indexing_demo.txt` |

## Rebuilding the walkthrough video

The video is rendered headlessly from the app's own data, so it stays truthful: the ER diagram is the live Mermaid output, the SQL errors are real `psql` output, and the indexing numbers are read from `docs/indexing_demo.txt`.

```powershell
.venv\Scripts\python video\narration.py        # narration (offline Windows voice) + timeline
.venv\Scripts\python video\build.py scene      # needs the app running; embeds the live ER diagram
.venv\Scripts\python video\build.py frames     # 30 fps frames via headless Edge
.venv\Scripts\python video\build.py audio      # narration + soft music bed
.venv\Scripts\python video\build.py mux        # writes app/static/explainer.mp4, .jpg and .vtt (needs ffmpeg)
```

## Design decisions worth knowing

- **Allocation logic lives in the database** (`allocate_units`): exact group first, then soonest expiry, universal O− kept back. `SELECT … FOR UPDATE SKIP LOCKED` lets concurrent requests take different units. `UNIQUE(allocation.unit_id)` is the backstop.
- **A unit label is derived, not typed** (`trg_unit_label`): group from the donor, expiry from the component's shelf life, barcode from the id.
- **Illegal state changes are rejected** by a trigger (`EXPIRED → AVAILABLE` and so on); every change is audited and low-stock alerts open and clear automatically.
- **Roles** (`hemo_viewer`, `hemo_lab`, `hemo_clinical`) have table-level GRANTs; routines are `SECURITY DEFINER` so a role needs only EXECUTE.
- Interface design direction: `docs/design-direction.md`. Screenshots from the audit: `docs/screens/`.

## Known limits

- Single local user; the app connects as the database owner (the roles are exercised in `tests/test_db.py`, not wired to logins) and the Flask secret key is a demo constant.
- No CSRF tokens on the forms.
- Only the document-store family of NoSQL is implemented; key-value, column and graph are design notes in `docs/nosql.md`.
- Seed data is synthetic. Platelets show ~90% expired because the seed spans 55 days and platelets last 5.
