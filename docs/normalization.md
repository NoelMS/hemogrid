# Functional dependencies and normalization

## 1. Starting point: one wide intake sheet

The paper register a blood bank starts from:

```
INTAKE(donor_id, donor_name, sex, dob, city, blood_group, phone, camp_id, camp_name, camp_date,
       donation_id, donated_on, volume_ml, unit_id, component, shelf_days, expiry_date)
```

Dependencies that hold in the domain:

| FD | Meaning |
|---|---|
| donor_id → donor_name, sex, dob, city, blood_group | a donor is one person with one group |
| camp_id → camp_name, camp_date | |
| donation_id → donor_id, camp_id, donated_on, volume_ml | one donation = one donor, one day |
| unit_id → donation_id, component, expiry_date | |
| component → shelf_days | shelf life depends on the component only |
| (donation_id, component) → unit_id | one unit per component per donation |
| donor_id ↠ phone  and  donor_id ↠ camp_id | phones and camps are independent multivalued facts |

Candidate key of the wide sheet: `(unit_id, phone, camp_id)`.

## 2. Normal forms step by step

**1NF.** Atomic values only: phone numbers are one per row, not a comma list; the component list of a donation is split into one unit per row.

**2NF.** Remove partial dependencies on part of the key. `donor_name, sex, dob, city, blood_group` depend only on `donor_id`; `camp_name, camp_date` only on `camp_id`; `donated_on, volume_ml` only on `donation_id`. They move to `person/donor`, `camp`, `donation`.

**3NF.** Remove transitive dependencies. In `blood_unit`, `unit_id → component → shelf_days`, so `shelf_days` is moved into `component_type(component → shelf_days, storage)`. Without this, changing the platelet shelf life would mean updating every platelet row.

**BCNF.** Every determinant must be a candidate key. Checked for each table:

| Table | Non-trivial FDs | Determinant is a key? |
|---|---|---|
| person | person_id → all | yes |
| donor | person_id → blood_group, last_donation_date, deferred_until | yes |
| camp | camp_id → name, venue, camp_date, coordinator_id | yes |
| donation | donation_id → …; (donor_id, donated_on) → donation_id | both are candidate keys |
| blood_unit | unit_id → …; barcode → unit_id; (donation_id, component) → unit_id | all candidate keys |
| component_type | component → shelf_days, storage, label | yes |
| stock_policy | (blood_group, component) → reorder_level | yes |
| allocation | allocation_id → …; unit_id → allocation_id | both candidate keys |

All tables are in BCNF, and the decomposition is dependency-preserving: every FD above is contained in a single table, so no join is needed to enforce any of them.

**Deliberate redundancy.** `blood_unit.blood_group` repeats `donor.blood_group` (through `donation`). It is the *label printed on the bag*; it is copied once by `trg_unit_label` and never updated, so it cannot become inconsistent, and the hot allocation query avoids a three-table join.

## 3. Fourth normal form (multivalued dependencies)

If phones and camps were kept in one table:

```
DONOR_CONTACT_CAMP(donor_id, phone, camp_id)      -- key = all three columns
```

| donor_id | phone | camp_id |
|---|---|---|
| 17 | +919840011122 | 3 |
| 17 | +919840011122 | 6 |
| 17 | +919840077788 | 3 |
| 17 | +919840077788 | 6 |

`donor_id ↠ phone` and `donor_id ↠ camp_id` are independent multivalued dependencies. The table is in BCNF (it is all-key) but not 4NF: adding one phone forces a row per camp, and forgetting one produces a false fact ("number X was used at camp Y"). Decomposing into `donor_phone(donor_id, phone)` and `donor_camp(donor_id, camp_id)` removes the redundancy and is lossless: `donor_phone ⋈ donor_camp = original`.

## 4. Fifth normal form (join dependency)

Suppose a three-way relation `SUPPLY(hospital, camp, component)` were stored under the cyclic rule *"if a hospital buys from a camp, the camp supplies a component, and the hospital buys that component, then the hospital buys that component from that camp"*. That is the join dependency ⋈ {(hospital, camp), (camp, component), (hospital, component)}: the relation is in 4NF yet redundant, and 5NF requires splitting it into its three binary projections.

HemoGrid never stores such a fact. Demand is `request(hospital, component)`, supply is `blood_unit(donation → camp, component)`, and the two meet only at allocation time (`allocation`), so no relation in the schema satisfies a non-trivial join dependency not implied by its keys. The schema is therefore in 5NF.

## 5. Armstrong's axioms in use

Closure of `{donation_id}⁺` under the FDs above: `donation_id → donor_id` (given), `donor_id → blood_group` (given) so by *transitivity* `donation_id → blood_group`. This is exactly why `blood_group` is not stored in `donation`, and why `trg_unit_label` can derive it. *Augmentation* gives `(donation_id, component) → expiry_date`, and *union* combines it with `(donation_id, component) → unit_id` into one key lookup.
