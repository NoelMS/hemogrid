-- Live walkthrough of the HemoGrid database in psql. Every step that changes data is rolled back.
-- Run it all:   psql -p 54329 -U postgres -d hemogrid -f scripts/live_demo.sql
-- Or paste one numbered step at a time while presenting.
SET search_path = hemo;
\pset pager off
\set ON_ERROR_STOP off

\echo
\echo '== 1. What is in the database =='
SELECT relname AS table, n_live_tup AS approx_rows FROM pg_stat_user_tables WHERE schemaname = 'hemo' ORDER BY relname;

\echo
\echo '== 2. Constraints reject bad data (domain CHECK on blood group) =='
INSERT INTO recipient (person_id, blood_group) VALUES (1, 'Z+');

\echo
\echo '== 3. Trigger: a donor who gave blood recently cannot donate again =='
SELECT person_id AS recent_donor, last_donation_date FROM donor WHERE last_donation_date >= current_date - 30 ORDER BY person_id LIMIT 1 \gset
INSERT INTO donation (donor_id, staff_id, volume_ml) VALUES (:recent_donor, (SELECT min(person_id) FROM staff), 450);

\echo
\echo '== 4. Screening PASS creates labelled units (trigger fills group, dates, barcode); then ROLLBACK =='
SELECT donor_id AS fresh_donor FROM v_eligible_donors WHERE blood_group = 'O-' ORDER BY donor_id LIMIT 1 \gset
BEGIN;
INSERT INTO donation (donor_id, staff_id, volume_ml) VALUES (:fresh_donor, (SELECT min(person_id) FROM staff), 450) RETURNING donation_id \gset
SELECT record_screening(:donation_id, 'PASS', true) AS units_created;
SELECT barcode, blood_group, component, collected_on, expiry_date, status FROM blood_unit WHERE donation_id = :donation_id ORDER BY component;
SELECT unit_id, old_status, new_status FROM unit_audit WHERE unit_id IN (SELECT unit_id FROM blood_unit WHERE donation_id = :donation_id) ORDER BY audit_id;
ROLLBACK;

\echo
\echo '== 5. Trigger: an expired unit can never become available again =='
UPDATE blood_unit SET status = 'AVAILABLE' WHERE unit_id = (SELECT unit_id FROM blood_unit WHERE status = 'EXPIRED' LIMIT 1);

\echo
\echo '== 6. Emergency allocation: exact group first, soonest expiry next, O- kept back; then ROLLBACK =='
BEGIN;
INSERT INTO request (hospital_id, patient_id, component, units_needed, urgency)
  SELECT 1, person_id, 'PRBC', 2, 'EMERGENCY' FROM recipient WHERE blood_group = 'B+' LIMIT 1 RETURNING request_id \gset
SELECT allocate_units(:request_id) AS units_reserved;
SELECT a.request_id, u.barcode, u.blood_group, u.expiry_date, u.status FROM allocation a JOIN blood_unit u USING (unit_id) WHERE a.request_id = :request_id;
SELECT request_id, status FROM request WHERE request_id = :request_id;
ROLLBACK;

\echo
\echo '== 7. Index: the allocation lookup uses the partial composite B+ tree (look for ix_unit_fefo) =='
EXPLAIN (ANALYZE, COSTS OFF, TIMING OFF)
SELECT unit_id FROM blood_unit WHERE blood_group = 'O+' AND component = 'PRBC' AND status = 'AVAILABLE' ORDER BY expiry_date LIMIT 5;

\echo
\echo '== 8. Authorization: a viewer can read but not delete =='
SET ROLE hemo_viewer;
SELECT count(*) AS donors_visible FROM donor;
DELETE FROM donor;
RESET ROLE;

\echo
\echo '== 9. Views: stock heat-grid source and low-stock alerts =='
SELECT blood_group, component, available, reorder_level FROM v_stock WHERE available < reorder_level ORDER BY blood_group, component;
SELECT blood_group, component, available, raised_at::date FROM stock_alert WHERE cleared_at IS NULL ORDER BY available, blood_group LIMIT 5;
