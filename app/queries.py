"""Named queries for the Query Lab page: each shows the SQL idea, its relational-algebra form and live results."""

QUERIES = [
    {"title": "Yield per donation camp", "topic": "Join + GROUP BY + LEFT JOIN",
     "algebra": "camp ⟕ donation ⟕ blood_unit, then γ camp_id; COUNT(unit_id)",
     "sql": """SELECT c.name AS camp, count(DISTINCT d.donation_id) AS donations, count(u.unit_id) AS units
FROM camp c LEFT JOIN donation d USING (camp_id) LEFT JOIN blood_unit u USING (donation_id)
GROUP BY c.name ORDER BY units DESC"""},
    {"title": "Groups with open demand but no compatible stock", "topic": "Set operation (EXCEPT) + user function",
     "algebra": "π group(σ status∈{OPEN,PARTIAL}(request ⋈ recipient)) − π group(σ compatible(...)(blood_unit))",
     "sql": """SELECT DISTINCT rc.blood_group, r.component
FROM request r JOIN recipient rc ON rc.person_id = r.patient_id
WHERE r.status IN ('OPEN','PARTIAL')
EXCEPT
SELECT rc.blood_group, r.component
FROM request r JOIN recipient rc ON rc.person_id = r.patient_id
JOIN blood_unit u ON u.status = 'AVAILABLE' AND u.component = r.component AND compatible(u.blood_group, rc.blood_group, r.component)
WHERE r.status IN ('OPEN','PARTIAL')
ORDER BY 1, 2"""},
    {"title": "Hospitals that ordered both red cells and plasma", "topic": "Relational division via double NOT EXISTS",
     "algebra": "π hospital,component(request) ÷ {PRBC, PLASMA}",
     "sql": """SELECT h.name FROM hospital h
WHERE NOT EXISTS (
  SELECT 1 FROM component_type ct WHERE ct.component IN ('PRBC','PLASMA')
  AND NOT EXISTS (SELECT 1 FROM request r WHERE r.hospital_id = h.hospital_id AND r.component = ct.component))
ORDER BY h.name"""},
    {"title": "Hospital ranking by units issued", "topic": "Window function RANK()",
     "algebra": "γ hospital; COUNT(unit) then rank (extension beyond core algebra)",
     "sql": """SELECT rank() OVER (ORDER BY count(a.unit_id) DESC) AS rank, h.name AS hospital, count(a.unit_id) AS units_issued
FROM hospital h LEFT JOIN request r USING (hospital_id)
LEFT JOIN allocation a ON a.request_id = r.request_id AND a.issued_at IS NOT NULL
GROUP BY h.name ORDER BY rank, hospital"""},
    {"title": "Wastage by component", "topic": "Aggregation with FILTER and a computed ratio",
     "algebra": "γ component; COUNT(*), COUNT(σ status=EXPIRED)",
     "sql": """SELECT component, count(*) AS total_units, count(*) FILTER (WHERE status = 'EXPIRED') AS expired,
       round(100.0 * count(*) FILTER (WHERE status = 'EXPIRED') / count(*), 1) AS wastage_pct
FROM blood_unit GROUP BY component ORDER BY wastage_pct DESC"""},
    {"title": "Registered donors who have never donated", "topic": "NULL handling: anti-join",
     "algebra": "donor − π donor_id(donation)  (equivalently σ donation_id IS NULL on a left join)",
     "sql": """SELECT p.city, count(*) AS donors FROM donor d JOIN person p ON p.person_id = d.person_id
LEFT JOIN donation x ON x.donor_id = d.person_id WHERE x.donation_id IS NULL
GROUP BY p.city ORDER BY donors DESC"""},
    {"title": "Donors due back in the next 45 days", "topic": "View + date arithmetic",
     "algebra": "σ eligible_from ≤ today+45 (v_eligible_donors ∪ deferred soon)",
     "sql": """SELECT p.full_name, d.blood_group, d.last_donation_date,
       d.last_donation_date + CASE p.sex WHEN 'F' THEN 120 ELSE 90 END AS eligible_from
FROM donor d JOIN person p ON p.person_id = d.person_id
WHERE d.last_donation_date IS NOT NULL
  AND d.last_donation_date + CASE p.sex WHEN 'F' THEN 120 ELSE 90 END BETWEEN current_date AND current_date + 45
ORDER BY eligible_from, p.full_name LIMIT 12"""},
    {"title": "Donors above the average donation count", "topic": "Nested (scalar) subquery in HAVING",
     "algebra": "γ donor; COUNT(*) → σ count > AVG(count)",
     "sql": """SELECT p.full_name, count(*) AS donations FROM donation d JOIN person p ON p.person_id = d.donor_id
GROUP BY p.full_name HAVING count(*) > (SELECT avg(c) FROM (SELECT count(*) AS c FROM donation GROUP BY donor_id) t)
ORDER BY donations DESC, p.full_name LIMIT 10"""},
]
