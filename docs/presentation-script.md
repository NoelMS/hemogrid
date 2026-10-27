# HemoGrid: presentation script (about 12 minutes)

Speak the quoted text in your own words. **Bold** lines are things to do on screen. Before you start: double-click **Start HemoGrid** and keep a PowerShell window open in the project folder.

---

## 1. The problem (45 s)

> "My project is HemoGrid, a database system for a blood bank. A blood bank is a good database problem because the data is small but the rules are strict. Blood has an expiry date that depends on the component. A donor can't give blood again for 90 or 120 days. A compatible unit must be found fast in an emergency. And two doctors must never be promised the same last bag. So most of the interesting work is in the database itself, not in the web page."

## 2. Architecture (1 min)

> "There are two databases. **PostgreSQL 16** holds everything that needs integrity: donors, donations, blood units, requests and allocations. **MongoDB** holds the lab screening reports, because each donor's health questionnaire has different fields. The web app is a thin Flask layer. It does not contain the business rules. It calls PostgreSQL functions and shows whatever the database says, including its error messages."

> "I installed PostgreSQL and MongoDB as portable copies on my N: drive, so there is no service installation. One launcher script starts both databases, seeds the data and opens the browser."

## 3. Design: ER model and normalization (1.5 min)

**Open `docs/er-diagram.md` (rendered) or show the diagram.**

> "`PERSON` is a superclass with three overlapping subclasses: donor, recipient and staff. That is the extended-ER specialization from Module 3. A donor's phones and the camps they attend are multivalued, so they became their own tables."

**Open `docs/normalization.md`, section 3.**

> "This is my 4NF example. If I stored phone and camp together in one table, adding one phone number would force one row per camp. That is a multivalued dependency. Splitting into `donor_phone` and `donor_camp` removes it. Every table is in BCNF, and I list the functional dependencies for each one in that document."

> "One deliberate redundancy: a unit's blood group is copied from the donor once, when the label is printed, and never changes. I did that on purpose. It is the label on the bag, and it keeps the main query fast."

## 4. Live application (3 min)

**Dashboard.**
> "This grid is a view over the stock table: blood group by component. Amber is below the reorder level, red is empty. Those alerts are created by a trigger, not by the app."

**Donors → search, open one donor → Record donation twice.**
> "I record a donation. Now I try again straight away. The database refuses with the reason and the date they can donate next. That message comes from a trigger, `trg_donation_eligibility`, which checks age, deferral, and the 90-day gap for men or 120-day gap for women."

**Screening → pick the donation → Save result with no reactive marker.**
> "Until the lab enters a result, nothing from this donation is in stock. When I save, the function `record_screening` creates three units: red cells, plasma and platelets. A trigger fills in the barcode, the blood group and the expiry date using each component's shelf life. The report itself is stored in MongoDB."

**Requests → Raise request → EMERGENCY, red cells.**
> "An emergency request reserves stock immediately. The function `allocate_units` picks the patient's own group first, then the soonest expiry, and avoids using universal O-negative unless nothing else fits. Then I click **Issue to hospital**, or **Cancel** to put the units back."

**Open any unit from Requests.**
> "Every status change of this bag is recorded by a trigger. I can also see its MongoDB screening document here."

## 5. Showing the database itself (3 min)

> "Now the database directly, without the web app."

**In PowerShell:**
```
N:\Tools\pg\pgsql\bin\psql.exe -p 54329 -U postgres -d hemogrid -f scripts\live_demo.sql
```
(Or paste the numbered steps from `scripts/live_demo.sql` one at a time.)

Talk through each output:

| Step | Say |
|---|---|
| 2 | "A blood group of Z+ is rejected by a domain CHECK constraint." |
| 3 | "A recent donor is blocked by the trigger, with a readable message." |
| 4 | "A passing screening creates three labelled units. The audit rows were written by a trigger. I wrap it in BEGIN and ROLLBACK, so the demo leaves no data behind." |
| 5 | "An expired unit cannot be made available again. The status changes follow a state machine enforced in the database." |
| 6 | "The emergency allocation. Both units are B-positive, the patient's own group, sorted by expiry." |
| 7 | "EXPLAIN shows the lookup uses `ix_unit_fefo`, a partial composite B+ tree index." |
| 8 | "A viewer role can read but gets *permission denied* on delete. That is GRANT-based authorization." |

## 6. Indexing, with numbers (1 min)

**Run:** `.venv\Scripts\python scripts\demo_indexing.py`

> "On 400,000 rows, the allocation lookup without an index scans the whole table in tens of milliseconds. With the partial composite B+ tree it takes a fraction of a millisecond, hundreds of times faster. The barcode lookup uses a hash index, because it is always an equality match. The last query is a range, expiring in 7 days: a hash index cannot help, the B+ tree can. The script prints these numbers live, and I saved a copy in `docs/indexing_demo.txt`."

## 7. Transactions and concurrency (2 min)

**Run:** `.venv\Scripts\python scripts\demo_transactions.py`

> "The scenario: exactly one O-negative unit in stock, and two emergency requests arrive at the same moment."

| Demo step | Say |
|---|---|
| 2 Naive | "Both transactions read the unit as free. Only my `UNIQUE` constraint on the allocation stops a double booking, and one request fails with an error." |
| 3 `allocate_units` | "With `SELECT … FOR UPDATE SKIP LOCKED`, one request gets the unit and the other sees it is taken and stays open. No error, no double allocation." |
| 4 Serializable | "At SERIALIZABLE isolation PostgreSQL aborts one transaction with a serialization failure and the application retries." |
| 5 Deadlock | "Two sessions lock the same two units in opposite order. PostgreSQL detects the deadlock and aborts one. The fix is to lock in a fixed order." |
| 1 and 6 | "Atomicity: a rollback undoes everything. Durability: a commit writes to the WAL." |

## 8. NoSQL (1 min)

**Screening page → "Report store" section, click a flag. Then Query lab → bottom half.**

> "The screening documents are in MongoDB. Optional fields such as pregnancy history or a medication list vary per donor, which is awkward in SQL and natural in a document. These are aggregation pipelines on that data: flag counts and average haemoglobin by result. In CAP terms, unit status and allocation are on the consistent side, because a double allocation is dangerous. The screening documents can tolerate delay, and the safety decision is already in PostgreSQL."

## 9. Close (30 s)

> "To summarise by module: relational design and algebra, SQL with triggers and procedures, normalization up to 4NF, indexing with measurements, concurrency control with a live demo, and a document store. Known limits: it is a single-user demo, only the document family of NoSQL is built, and the data is synthetic."

---

## Likely questions

**Why put logic in the database instead of the app?**
Because every client gets the same rules. A rule in a trigger cannot be bypassed by a forgotten check in some other screen. It also keeps the concurrency-sensitive part (allocation) inside one transaction.

**What is `SKIP LOCKED`?**
When a row is locked by another transaction, skip it instead of waiting. Two requests can then take different units at the same time.

**Why a partial index?**
`WHERE status = 'AVAILABLE'` indexes only the units that can be allocated. Expired and issued units are most rows and are never searched, so the index stays small: on the 400,000-row demo table it is 592 kB, against 2.9 MB for a plain index on the expiry column, which has to cover every row.

**B-tree or B+ tree?**
PostgreSQL's default `btree` is a B+ tree variant: data pointers are in the leaves and leaves are linked, so range scans are cheap.

**Why is `blood_unit.blood_group` stored twice?**
Deliberate, and explained in the normalization document: it is the immutable bag label, copied once by a trigger, so it cannot become inconsistent.

**Is it in BCNF?**
Yes. The table-by-table check is in section 2 of `docs/normalization.md`.

**What does ACID mean here?**
Atomic: allocating three units either all happens or none. Consistent: constraints and triggers hold after every commit. Isolated: concurrent allocations don't see each other's half-done work. Durable: committed data survives a crash through the write-ahead log.

**Why PostgreSQL and not MySQL?**
Partial indexes, `SKIP LOCKED`, domains, SERIALIZABLE snapshot isolation, and `EXPLAIN ANALYZE` that made the demos possible.

**How did you test it?**
`tests/test_db.py` has 13 database checks, `tests/ui_flows.py` drives the real forms, and `tests/ui_audit.py` checks the layout at three screen widths.
