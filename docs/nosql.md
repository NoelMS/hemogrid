# Module 6: NoSQL in HemoGrid

## What is implemented: document store (MongoDB 7)

`screening_reports` holds one document per donation:

```json
{ "donation_id": 214, "donor_id": 88, "tested_on": "2026-10-20T15:00:00", "hb_gdl": 13.4,
  "markers": { "hiv": "NEGATIVE", "hbsag": "NEGATIVE", "hcv": "NEGATIVE", "syphilis": "NEGATIVE", "malaria": "NEGATIVE" },
  "result": "PASS", "flags": [],
  "questionnaire": { "weight_kg": 71, "recent_travel": false, "on_medication": ["metformin"], "pregnancy_history": "none" } }
```

**Why a document store here.** The questionnaire is different for every donor (pregnancy history only for women, free-text notes sometimes, a medication list of any length) and the lab adds new test markers over time. In SQL that is a sparse table or an EAV anti-pattern; in a document it is just fields. The facts that need integrity, joins and transactions (donors, units, allocations) stay in PostgreSQL.

**How the two stores cooperate.** `donation_id` is the shared key. `record_screening()` in PostgreSQL decides the outcome and creates units; the app then writes the report document. The order is deliberate: if PostgreSQL refuses (donation already screened), no orphan document is written. If MongoDB is down, screening still succeeds and the UI says the report store is unreachable (availability over consistency for this non-critical side data).

Indexes: unique on `donation_id`, multikey on `flags`. Aggregations are on the **Query lab** page (flag frequency, mean Hb by result, medication unwind).

## CAP theorem applied

| Data | Store | Choice |
|---|---|---|
| Unit status, allocation | PostgreSQL | **CP**: a double allocation is a patient-safety failure, so reject writes rather than diverge |
| Screening report documents | MongoDB | **AP-leaning**: a delayed or retried report is harmless; the unit's safety decision is already in PostgreSQL |

## The other three NoSQL families (design notes, not built)

| Family | Where it would fit in a bigger HemoGrid | Sketch |
|---|---|---|
| Key-value (Redis) | live stock counters for a wall display; barcode → unit-id cache | `HINCRBY stock:O- PRBC -1` on allocation, rebuilt from SQL if lost |
| Column-family (Cassandra) | cold-chain temperature readings, millions of sensor rows per fridge | partition by `(fridge_id, day)`, cluster by time |
| Graph (Neo4j) | donor → camp → recipient look-back when a donation is later found infected | `(Donor)-[:GAVE]->(Donation)-[:SPLIT_INTO]->(Unit)-[:ISSUED_TO]->(Patient)` traversal |

These are described only; the project implements and tests the document store.
