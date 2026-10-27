# HemoGrid: talk-through script (about 12 minutes)

Say the quoted parts in your own words. **Bold** lines are things to do on screen. Before you start: double-click **Start HemoGrid**, and keep a PowerShell window open in the project folder.

The theme of the whole talk: **the database does the work, the web page only shows it.**

---

## 1. What I built, in one breath (30 s)

> "HemoGrid is a database system for a blood bank. The interesting part is not the web page. It is how I used PostgreSQL to hold the rules, so the data can never get into a wrong state, and how I used MongoDB for the one kind of data that doesn't fit a fixed table."

## 2. Architecture and setup (1 min)

> "Two databases. **PostgreSQL 16** is the system of record: donors, donations, blood units, requests and allocations. **MongoDB** stores the lab screening reports. The Flask app has almost no business logic. It calls PostgreSQL functions and displays whatever comes back, including the database's own error messages."

> "I run both as portable installs on my N: drive, so nothing is installed as a service. One launcher script starts both databases, creates and seeds the schema the first time, starts the app and opens the browser. The seed script creates about 420 donors, 850 units and 34 requests."

**Open the app → Design → SQL objects.**
> "Everything is in three SQL files: tables and indexes, then triggers and functions, then views and roles. This page shows them straight from the repository."

## 3. How the schema is designed (2 min)

**Design → ER diagram. Click "Enlarge diagram".**

> "`PERSON` is a superclass. `DONOR`, `RECIPIENT` and `STAFF` are subclasses that share its key, because one person can be more than one of them. A donor's phone numbers and the camps they attended are multivalued, so each has its own table."

> "Domains such as `blood_group` and `component_code` are defined once with a CHECK constraint and reused by every table, so a blood group of 'Z+' is rejected anywhere it could appear."

**Design → Normalization, scroll to the 4NF section.**

> "I checked every table against its functional dependencies and every one is in BCNF. The 4NF example: if phones and camps shared a table, adding one phone number would force one row per camp. Splitting them removes that. There is one deliberate redundancy: a unit's blood group is copied from the donor once, when the label is printed, and never changes, because it is the label on the bag. It also keeps the main query fast."

## 4. Using PostgreSQL: rules inside the database (3 min)

> "I'll show the database directly, without the web app. Each of these rules is enforced by PostgreSQL itself."

**In PowerShell:**
```
N:\Tools\pg\pgsql\bin\psql.exe -p 54329 -U postgres -d hemogrid -f scripts\live_demo.sql
```
(Or paste one numbered step at a time from `scripts/live_demo.sql`.)

| Step | What it demonstrates | Say |
|---|---|---|
| 2 | Domain CHECK constraint | "Invalid data never gets in, whichever client sends it." |
| 3 | Trigger `trg_donation_eligibility` | "A BEFORE INSERT trigger checks age, deferral and the minimum gap since the last donation, and raises a readable message. The app just shows it." |
| 4 | Function `record_screening` + trigger `trg_unit_label` | "One function call creates three units. A BEFORE INSERT trigger fills in the blood group, collection date, expiry date and barcode, so nobody types those. An AFTER trigger writes the audit rows. I wrapped it in BEGIN and ROLLBACK, so the demo leaves nothing behind." |
| 5 | Status trigger | "A unit's status follows a small state machine. EXPIRED can never go back to AVAILABLE. The rule is a trigger, so no screen can bypass it." |
| 6 | Function `allocate_units` | "A PL/pgSQL function picks units for a request: the patient's own group first, then soonest expiry, and it avoids spending universal O-negative if it can. The whole thing is one transaction." |
| 7 | `EXPLAIN` | "The planner uses `ix_unit_fefo`, a partial composite index. More on that next." |
| 8 | Roles and GRANT | "A viewer role can read but gets 'permission denied' on delete. Routines are SECURITY DEFINER, so a role only needs EXECUTE permission, not direct write access to the audit tables." |
| 9 | Views | "The dashboard's stock grid is a view, `v_stock`. The app doesn't compute it." |

**Open the app → Query lab.**
> "These eight queries run live: joins, EXCEPT, relational division with double NOT EXISTS, a window function, and nested subqueries. Each shows its SQL and its relational-algebra form."

## 5. Using PostgreSQL: indexes (1 min)

**Run:** `.venv\Scripts\python scripts\demo_indexing.py`

> "I built a 400,000-row table and measured with `EXPLAIN ANALYZE`. The allocation lookup, without an index, scans the whole table in tens of milliseconds. With a partial composite B+ tree index on group, component and expiry, where only AVAILABLE units are indexed, it reads five index entries and takes a fraction of a millisecond. The barcode lookup uses a hash index because it is always an equality match. The last query is a range, and a hash index can't serve it, the B+ tree can. The same results are saved on the Design page under Indexing."

## 6. Using PostgreSQL: transactions and concurrency (2 min)

**Run:** `.venv\Scripts\python scripts\demo_transactions.py`

> "Exactly one O-negative unit is in stock, and two emergency requests arrive at the same moment."

| Demo step | Say |
|---|---|
| 2 Naive read-then-write | "Both transactions read the unit as free. Only my UNIQUE constraint on `allocation.unit_id` prevents a double booking, and one request fails with an error." |
| 3 `allocate_units` | "With `SELECT … FOR UPDATE SKIP LOCKED`, one request locks the unit, the other skips it, sees none left and stays open. No error, no double allocation." |
| 4 SERIALIZABLE | "At SERIALIZABLE isolation PostgreSQL aborts one transaction with a serialization failure and the application retries it." |
| 5 Deadlock | "Two sessions lock the same two rows in opposite order. PostgreSQL detects the deadlock and aborts one. The fix is to lock in a fixed order." |
| 1 and 6 | "Atomicity: a rollback undoes everything. Durability: a commit is flushed to the write-ahead log." |

## 7. Using MongoDB (1 min)

**Screening page → Report store → click a flag. Then Query lab → bottom half.**

> "Each donation has a screening report stored as a document in MongoDB. The questionnaire differs per donor: pregnancy history only appears for some, a medication list has any length, and new lab markers get added over time. In SQL that means a sparse table. In a document it is just fields. PostgreSQL still decides pass or fail and creates the units. The app writes the report afterwards, so if PostgreSQL refuses, no orphan document exists. And if MongoDB is down, screening still works and the page says so."

> "The aggregation pipelines on the Query lab page count flags and average haemoglobin by result."

## 8. The application on top (1 min)

**Donors → open one → Record donation twice. Screening → save a result. Requests → raise an EMERGENCY request.**

> "The web app is deliberately thin. When I record a second donation straight away, the message on screen is the trigger's own message. Saving a screening result calls `record_screening`. An emergency request calls `allocate_units`. Cancel and Issue call their own functions. If I switched the front end to something else, every rule would still hold."

## 9. Close (30 s)

> "To summarise: PostgreSQL enforces integrity with constraints, triggers and functions, uses indexes and locking for speed and concurrency, and separates access with roles. MongoDB holds the flexible reports. The tests cover the database rules, the real forms and the layout at three screen sizes. Limits: it is a single-user demo, only the document family of NoSQL is built, and the data is synthetic."

---

## Likely questions

**Why put logic in the database instead of the app?**
Every client gets the same rules, and a rule in a trigger cannot be bypassed by a forgotten check in another screen. It also keeps the concurrency-sensitive part, allocation, inside one transaction.

**What is `SKIP LOCKED`?**
If a row is locked by another transaction, skip it instead of waiting. Two requests can then take different units at the same time.

**Why a partial index?**
`WHERE status = 'AVAILABLE'` indexes only the units that can be allocated. Expired and issued units are most rows and are never searched, so the index stays small: on the 400,000-row demo table it is 592 kB, against 2.9 MB for a plain index on the expiry column, which has to cover every row.

**B-tree or B+ tree?**
PostgreSQL's default `btree` is a B+ tree variant: data pointers are in the leaves and the leaves are linked, so range scans are cheap.

**Why is `blood_unit.blood_group` stored twice?**
Deliberate, and explained under Design → Normalization: it is the immutable bag label, copied once by a trigger, so it cannot become inconsistent.

**Is it in BCNF?**
Yes. The table-by-table check is in the Normalization page.

**What does ACID mean here?**
Atomic: allocating three units either all happens or none. Consistent: constraints and triggers hold after every commit. Isolated: concurrent allocations don't see each other's half-done work. Durable: committed data survives a crash through the write-ahead log.

**Why PostgreSQL and not MySQL?**
Partial indexes, `SKIP LOCKED`, domains, SERIALIZABLE snapshot isolation and `EXPLAIN ANALYZE` made the design and the demos possible.

**Why MongoDB for reports and not a JSON column in PostgreSQL?**
A JSON column would also work. I wanted a separate document store to show where each model fits: strict relations and transactions in PostgreSQL, schema-free documents in MongoDB. The cost is two systems to run and no cross-store transaction, so I ordered the writes to avoid orphans.

**How did you test it?**
`tests/test_db.py` has 13 database checks, `tests/ui_flows.py` drives the real forms, and `tests/ui_audit.py` checks every page at three screen widths.
