# HemoGrid: Blood Bank, Donor & Emergency Allocation Database System

DBMS (23CS2013) course project. Tracks donors, camps, donations, lab screening, labelled blood units with expiry, hospital requests and emergency allocation. PostgreSQL holds the transactional data; MongoDB holds screening reports.

## Run it

**One click:** double-click `Start HemoGrid.bat` (or the HemoGrid shortcut on the Desktop). It starts PostgreSQL and MongoDB, seeds the database on the first run, starts the app and opens http://127.0.0.1:5057 in your browser. `Stop HemoGrid.bat` shuts everything down.

Everything lives on N: (PostgreSQL and MongoDB are portable binaries in `N:\Tools`). Manual steps:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dbs.ps1 start       # PostgreSQL :54329, MongoDB :27018
.venv\Scripts\python scripts\seed.py                                   # schema + logic + ~420 donors, ~850 units, 34 requests
.venv\Scripts\python app\app.py                                        # http://127.0.0.1:5057
```

Fresh machine: `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`, and unpack PostgreSQL 16 / MongoDB 7 zips to the paths in `scripts\dbs.ps1`.

## Tests (all headless)

| Command | What it proves |
|---|---|
| `python tests\test_db.py` | 13 database checks: compatibility matrix, triggers, procedures, status machine, roles; each rolls back |
| `python tests\ui_flows.py` | 13 end-to-end flows through the real forms (re-seed afterwards: it writes data) |
| `python tests\ui_audit.py` | 12 pages × 3 widths (1280, 1024, 390): console errors, overflow, scrollbars, tap targets, contrast, hover, focus |
| `python scripts\demo_transactions.py` | Module 5 demo on a scratch clone; output in `docs\transactions_demo.txt` |
| `python scripts\demo_indexing.py` | Module 4 demo on 400k rows; output in `docs\indexing_demo.txt` |

## Syllabus map

| Module | Where |
|---|---|
| 1 Architecture, relational model, algebra | `db/01_schema.sql`, `docs/relational-algebra.md`, role separation in `db/03_views_roles.sql` |
| 2 SQL, views, procedures, triggers, authorization | `db/02_logic.sql` (5 triggers, 7 routines), `db/03_views_roles.sql` (4 views, 3 roles with GRANTs), **Query lab** page (8 queries: join, set op, division, window, nested, NULL handling) |
| 3 Design | `docs/er-diagram.md` (specialization, multivalued attributes), `docs/normalization.md` (FDs, Armstrong, 1NF to 5NF, 4NF example) |
| 4 Indexing | partial composite B+ tree + hash index in `db/01_schema.sql`; measured in `docs/indexing_demo.txt` |
| 5 Transactions | `docs/transactions_demo.txt`: atomicity, lost update / double booking, `FOR UPDATE SKIP LOCKED`, SERIALIZABLE with retry, deadlock, WAL |
| 6 NoSQL | `docs/nosql.md`, MongoDB `screening_reports`, aggregations on the Query lab page |

## Design decisions worth knowing

- **Allocation logic lives in the database** (`allocate_units`): exact group first, then soonest expiry, universal O− kept back. `SELECT … FOR UPDATE SKIP LOCKED` lets concurrent requests take different units. `UNIQUE(allocation.unit_id)` is the backstop.
- **A unit label is derived, not typed** (`trg_unit_label`): group from the donor, expiry from the component's shelf life, barcode from the id.
- **Illegal state changes are rejected** by a trigger (`EXPIRED → AVAILABLE` and so on); every change is audited and low-stock alerts open and clear automatically.
- **Roles** (`hemo_viewer`, `hemo_lab`, `hemo_clinical`) have table-level GRANTs; routines are `SECURITY DEFINER` so a role needs only EXECUTE.
- Interface design direction: `docs/design-direction.md`. Screenshots from the audit: `docs/screens/`.

## Known limits

- Single local user; the app connects as the database owner (the roles are demonstrated in `tests/test_db.py`, not wired to logins) and the Flask secret key is a demo constant.
- No CSRF tokens on the forms (local demo).
- Only the document-store family of NoSQL is implemented; key-value, column and graph are design notes in `docs/nosql.md`.
- Seed data is synthetic. Platelets show ~90% expired because the seed spans 55 days and platelets last 5.

