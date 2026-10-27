-- Views and authorization (Module 2).
SET search_path = hemo;

-- Live stock by group x component, with the policy threshold for the dashboard heat grid.
CREATE VIEW v_stock AS
SELECT p.blood_group, p.component, p.reorder_level,
       count(u.unit_id) FILTER (WHERE u.status = 'AVAILABLE')  AS available,
       count(u.unit_id) FILTER (WHERE u.status = 'RESERVED')   AS reserved,
       min(u.expiry_date) FILTER (WHERE u.status = 'AVAILABLE') AS next_expiry
FROM stock_policy p
LEFT JOIN blood_unit u ON u.blood_group = p.blood_group AND u.component = p.component
GROUP BY p.blood_group, p.component, p.reorder_level;

CREATE VIEW v_expiring AS
SELECT u.unit_id, u.barcode, u.blood_group, u.component, u.status, u.expiry_date,
       u.expiry_date - current_date AS days_left, ct.shelf_days
FROM blood_unit u JOIN component_type ct USING (component)
WHERE u.status IN ('AVAILABLE','RESERVED') AND u.expiry_date <= current_date + 7;

-- Eligible donors today: no active deferral and past the sex-specific gap.
CREATE VIEW v_eligible_donors AS
SELECT d.person_id AS donor_id, p.full_name, p.city, d.blood_group, d.last_donation_date,
       coalesce(d.last_donation_date + CASE p.sex WHEN 'F' THEN 120 ELSE 90 END, current_date) AS eligible_from
FROM donor d JOIN person p ON p.person_id = d.person_id
WHERE (d.deferred_until IS NULL OR d.deferred_until <= current_date)
  AND extract(year FROM age(p.dob)) BETWEEN 18 AND 65
  AND (d.last_donation_date IS NULL
       OR current_date - d.last_donation_date >= CASE p.sex WHEN 'F' THEN 120 ELSE 90 END);

CREATE VIEW v_request_board AS
SELECT r.request_id, h.name AS hospital, pe.full_name AS patient, rc.blood_group AS patient_group,
       r.component, r.units_needed, r.urgency, r.status, r.created_at,
       (SELECT count(*) FROM allocation a WHERE a.request_id = r.request_id) AS allocated
FROM request r
JOIN hospital h ON h.hospital_id = r.hospital_id
JOIN recipient rc ON rc.person_id = r.patient_id
JOIN person pe ON pe.person_id = rc.person_id;

-- ---- Roles: least privilege. The app connects as hemo_app (member of the working roles).
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hemo_lab')      THEN CREATE ROLE hemo_lab; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hemo_clinical') THEN CREATE ROLE hemo_clinical; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'hemo_viewer')   THEN CREATE ROLE hemo_viewer; END IF;
END $$;

GRANT USAGE ON SCHEMA hemo TO hemo_lab, hemo_clinical, hemo_viewer;
GRANT SELECT ON ALL TABLES IN SCHEMA hemo TO hemo_viewer, hemo_lab, hemo_clinical;
-- Lab: registers donors/donations, records screening, changes unit status.
GRANT INSERT, UPDATE ON person, donor, donor_phone, donor_camp, donation, blood_unit TO hemo_lab;
GRANT EXECUTE ON FUNCTION record_screening, expire_units TO hemo_lab;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA hemo TO hemo_lab, hemo_clinical;
-- Clinical: raises and fulfils requests; cannot touch donors or screening.
GRANT INSERT, UPDATE ON request, allocation, recipient, person TO hemo_clinical;
GRANT UPDATE (status) ON blood_unit TO hemo_clinical;
GRANT EXECUTE ON FUNCTION allocate_units, issue_request, cancel_request TO hemo_clinical;

-- Routines run with the owner's rights so a role needs EXECUTE only, not write access to audit/alert tables.
ALTER FUNCTION trg_unit_after()   SECURITY DEFINER SET search_path = hemo, pg_catalog;
ALTER FUNCTION trg_unit_label()   SECURITY DEFINER SET search_path = hemo, pg_catalog;
ALTER FUNCTION trg_donation_after() SECURITY DEFINER SET search_path = hemo, pg_catalog;
ALTER FUNCTION check_stock(blood_group, component_code)           SECURITY DEFINER SET search_path = hemo, pg_catalog;
ALTER FUNCTION record_screening(int, text, boolean)               SECURITY DEFINER SET search_path = hemo, pg_catalog;
ALTER FUNCTION allocate_units(int)  SECURITY DEFINER SET search_path = hemo, pg_catalog;
ALTER FUNCTION issue_request(int)   SECURITY DEFINER SET search_path = hemo, pg_catalog;
ALTER FUNCTION cancel_request(int)  SECURITY DEFINER SET search_path = hemo, pg_catalog;
ALTER FUNCTION expire_units()       SECURITY DEFINER SET search_path = hemo, pg_catalog;
