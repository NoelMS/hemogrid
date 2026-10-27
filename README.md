# HemoGrid: Blood Bank, Donor & Emergency Allocation Database System

Tracks donors, donation camps, lab screening, labelled blood units with expiry dates, hospital requests and emergency allocation. PostgreSQL holds the transactional data; MongoDB holds screening reports. The business rules live in the database (triggers and functions), and the web app is a thin layer over them.

## Run it

**One click:** double-click `Start HemoGrid.bat`. It starts PostgreSQL and MongoDB, seeds the database on the first run, starts the app and opens http://127.0.0.1:5057 in your browser. `Stop HemoGrid.bat` shuts everything down.

PostgreSQL and MongoDB are portable binaries in `N:\Tools`. Manual steps:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dbs.ps1 start       # PostgreSQL :54329, MongoDB :27018
.venv\Scripts\python scripts\seed.py                                   # schema + logic + ~420 donors, ~850 units, 34 requests
.venv\Scripts\python app\app.py                                        # http://127.0.0.1:5057
```

Fresh machine: `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`, and unpack PostgreSQL 16 / MongoDB 7 zips to the paths in `scripts\dbs.ps1`.

## What is where

| Area | Where |
|---|---|
| Tables, constraints, domains, indexes | `db/01_schema.sql` |
| Triggers and routines (`allocate_units`, `record_screening`, `issue_request`, ...) | `db/02_logic.sql` |
| Views and roles with GRANTs | `db/03_views_roles.sql` |
| Eight reference queries with their relational-algebra form | **Query lab** page, `app/queries.py` |
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
