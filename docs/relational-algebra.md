# Relational algebra for the key queries

Notation: σ select, π project, ⋈ natural/theta join, ⟕ left outer join, ∪ ∩ − set operations, ρ rename, γ grouping/aggregation, ÷ division.
Each expression has a live SQL version in the app's **Query lab** page (`app/queries.py`).

| # | Question | Relational algebra | SQL feature |
|---|---|---|---|
| 1 | Which donors are O− and have donated? | π name(σ blood_group='O−'(donor ⋈ person) ⋈ donation) | join, selection |
| 2 | Donors who have **never** donated | π donor_id(donor) − π donor_id(donation) | difference / anti-join |
| 3 | Units available now of group G, component C | σ status='AVAILABLE' ∧ blood_group=G ∧ component=C(blood_unit) | selection (served by the partial B+ tree) |
| 4 | Units issued to Kovai Medical Centre | π barcode(σ name='Kovai…'(hospital) ⋈ request ⋈ allocation ⋈ blood_unit) | 4-way join |
| 5 | Groups with open demand but no compatible stock | π group(σ status∈{OPEN,PARTIAL}(request ⋈ recipient)) − π group(…⋈ σ compatible(…)(blood_unit)) | EXCEPT |
| 6 | Hospitals that ordered **both** red cells and plasma | π hospital,component(request) ÷ {PRBC, PLASMA} | division, via double NOT EXISTS |
| 7 | Units collected per camp | γ camp_id; COUNT(unit_id)(camp ⟕ donation ⟕ blood_unit) | outer join + aggregation |
| 8 | Donors donating more than the average | γ donor; COUNT → σ count > AVG(count) | nested subquery in HAVING |

## Additional algebra

- **Rename** for self-comparison: ρ d2(donation); donations of the same donor less than 90 days apart = σ d1.donor_id = d2.donor_id ∧ 0 < d2.donated_on − d1.donated_on < 90 (donation × d2). Rejecting this set is exactly what `trg_donation_eligibility` does at insert time.
- **Outer join** keeps camps with zero donations in query 7; an inner join would silently drop them.
- **Duplicates**: algebra is set-based, SQL is bag-based, hence `DISTINCT` in query 5.
