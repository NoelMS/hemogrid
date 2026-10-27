-- HemoGrid business logic: functions, procedures, triggers.
SET search_path = hemo;

-- ---------------------------------------------------------------- compatibility
-- Red cells / whole blood follow donor->recipient rules; plasma and platelets are ABO-reversed.
CREATE FUNCTION compatible(unit_grp blood_group, patient_grp blood_group, comp component_code)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
  WITH g AS (
    SELECT regexp_replace(unit_grp,    '[+-]', '') AS ua, right(unit_grp, 1)    AS ur,
           regexp_replace(patient_grp, '[+-]', '') AS pa, right(patient_grp, 1) AS pr
  )
  SELECT CASE WHEN comp IN ('WB','PRBC') THEN
           (ur = '-' OR pr = '+')
           AND (ua = 'O' OR pa = 'AB' OR ua = pa)
         ELSE
           (ua = 'AB' OR pa = 'O' OR ua = pa)
         END
  FROM g
$$;

-- ---------------------------------------------------------------- triggers
-- 1. Donor eligibility: age 18-65, not deferred, minimum gap 90 days (men) / 120 days (women).
CREATE FUNCTION trg_donation_eligibility() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE d donor%ROWTYPE; p person%ROWTYPE; gap int;
BEGIN
  SELECT * INTO d FROM donor  WHERE person_id = NEW.donor_id FOR UPDATE;
  SELECT * INTO p FROM person WHERE person_id = NEW.donor_id;
  IF extract(year FROM age(NEW.donated_on, p.dob)) NOT BETWEEN 18 AND 65 THEN
    RAISE EXCEPTION 'Donor % is outside the 18-65 age window', p.full_name USING ERRCODE = 'P0001';
  END IF;
  IF d.deferred_until IS NOT NULL AND NEW.donated_on < d.deferred_until THEN
    RAISE EXCEPTION 'Donor % is deferred until %', p.full_name, d.deferred_until USING ERRCODE = 'P0001';
  END IF;
  gap := CASE p.sex WHEN 'F' THEN 120 ELSE 90 END;
  IF d.last_donation_date IS NOT NULL AND NEW.donated_on - d.last_donation_date < gap THEN
    RAISE EXCEPTION 'Donor % gave blood on %; next eligible on %', p.full_name, d.last_donation_date,
      d.last_donation_date + gap USING ERRCODE = 'P0001';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER donation_eligibility BEFORE INSERT ON donation
  FOR EACH ROW EXECUTE FUNCTION trg_donation_eligibility();

CREATE FUNCTION trg_donation_after() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  UPDATE donor SET last_donation_date = GREATEST(coalesce(last_donation_date, NEW.donated_on), NEW.donated_on)
   WHERE person_id = NEW.donor_id;
  RETURN NEW;
END $$;
CREATE TRIGGER donation_after AFTER INSERT ON donation
  FOR EACH ROW EXECUTE FUNCTION trg_donation_after();

-- 2. A unit label is derived, never typed: group from the donor, dates from donation + shelf life, barcode from the id.
CREATE FUNCTION trg_unit_label() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE dn donation%ROWTYPE;
BEGIN
  SELECT * INTO dn FROM donation WHERE donation_id = NEW.donation_id;
  NEW.blood_group  := (SELECT blood_group FROM donor WHERE person_id = dn.donor_id);
  NEW.collected_on := dn.donated_on;
  NEW.expiry_date  := dn.donated_on + (SELECT shelf_days FROM component_type WHERE component = NEW.component);
  NEW.barcode      := 'HG' || to_char(dn.donated_on, 'YYMMDD') || '-' || lpad(NEW.unit_id::text, 7, '0');
  RETURN NEW;
END $$;
CREATE TRIGGER unit_label BEFORE INSERT ON blood_unit
  FOR EACH ROW EXECUTE FUNCTION trg_unit_label();

-- 3. Status machine: illegal jumps (e.g. EXPIRED -> AVAILABLE) are rejected.
CREATE FUNCTION trg_unit_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status = OLD.status THEN RETURN NEW; END IF;
  IF NOT ((OLD.status, NEW.status) IN (
      ('QUARANTINE','AVAILABLE'), ('QUARANTINE','DISCARDED'),
      ('AVAILABLE','RESERVED'),   ('AVAILABLE','EXPIRED'),   ('AVAILABLE','DISCARDED'),
      ('RESERVED','AVAILABLE'),   ('RESERVED','ISSUED'),     ('RESERVED','DISCARDED'))) THEN
    RAISE EXCEPTION 'Illegal unit transition % -> % (unit %)', OLD.status, NEW.status, OLD.unit_id USING ERRCODE = 'P0001';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER unit_transition BEFORE UPDATE OF status ON blood_unit
  FOR EACH ROW EXECUTE FUNCTION trg_unit_transition();

-- 4. Audit + low-stock alert after every unit change.
CREATE FUNCTION check_stock(g blood_group, c component_code) RETURNS void LANGUAGE plpgsql AS $$
DECLARE n int; lvl int;
BEGIN
  SELECT count(*) INTO n FROM blood_unit WHERE blood_group = g AND component = c AND status = 'AVAILABLE';
  SELECT reorder_level INTO lvl FROM stock_policy WHERE blood_group = g AND component = c;
  IF lvl IS NULL THEN RETURN; END IF;
  IF n < lvl THEN
    INSERT INTO stock_alert (blood_group, component, available)
    SELECT g, c, n WHERE NOT EXISTS
      (SELECT 1 FROM stock_alert WHERE blood_group = g AND component = c AND cleared_at IS NULL);
    UPDATE stock_alert SET available = n WHERE blood_group = g AND component = c AND cleared_at IS NULL;
  ELSE
    UPDATE stock_alert SET cleared_at = now() WHERE blood_group = g AND component = c AND cleared_at IS NULL;
  END IF;
END $$;

CREATE FUNCTION trg_unit_after() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' OR NEW.status <> OLD.status THEN
    INSERT INTO unit_audit (unit_id, old_status, new_status)
    VALUES (NEW.unit_id, CASE WHEN TG_OP = 'UPDATE' THEN OLD.status END, NEW.status);
    PERFORM check_stock(NEW.blood_group, NEW.component);
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER unit_after AFTER INSERT OR UPDATE ON blood_unit
  FOR EACH ROW EXECUTE FUNCTION trg_unit_after();

-- ---------------------------------------------------------------- routines
-- record_screening: PASS creates labelled units (split = red cells + plasma + platelets, else whole blood);
-- FAIL defers the donor for a year.
CREATE FUNCTION record_screening(p_donation int, p_result text, p_split boolean DEFAULT true)
RETURNS int LANGUAGE plpgsql AS $$
DECLARE dn donation%ROWTYPE; made int := 0; c component_code;
BEGIN
  SELECT * INTO dn FROM donation WHERE donation_id = p_donation FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'No such donation %', p_donation; END IF;
  IF dn.screening <> 'PENDING' THEN RAISE EXCEPTION 'Donation % already screened (%)', p_donation, dn.screening; END IF;
  IF p_result NOT IN ('PASS','FAIL') THEN RAISE EXCEPTION 'Result must be PASS or FAIL'; END IF;
  UPDATE donation SET screening = p_result WHERE donation_id = p_donation;
  IF p_result = 'FAIL' THEN
    UPDATE donor SET deferred_until = dn.donated_on + 365 WHERE person_id = dn.donor_id;
    RETURN 0;
  END IF;
  FOREACH c IN ARRAY (CASE WHEN p_split THEN ARRAY['PRBC','PLASMA','PLT'] ELSE ARRAY['WB'] END)::component_code[] LOOP
    INSERT INTO blood_unit (donation_id, component, status, barcode, blood_group, collected_on, expiry_date)
    VALUES (p_donation, c, 'AVAILABLE', '', 'O+', current_date, current_date + 1);  -- label columns overwritten by trg_unit_label
    made := made + 1;
  END LOOP;
  RETURN made;
END $$;

-- allocate_units: reserve compatible stock for a request, exact group first, then soonest expiry (FEFO).
-- SKIP LOCKED lets concurrent requests take *different* units instead of queueing behind each other.
CREATE FUNCTION allocate_units(p_request int) RETURNS int LANGUAGE plpgsql AS $$
DECLARE r request%ROWTYPE; pg blood_group; have int; got int := 0; u record;
BEGIN
  SELECT * INTO r FROM request WHERE request_id = p_request FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'No such request %', p_request; END IF;
  IF r.status NOT IN ('OPEN','PARTIAL') THEN RAISE EXCEPTION 'Request % is %, cannot allocate', p_request, r.status; END IF;
  SELECT blood_group INTO pg FROM recipient WHERE person_id = r.patient_id;
  SELECT count(*) INTO have FROM allocation WHERE request_id = p_request;

  FOR u IN
    SELECT unit_id FROM blood_unit
     WHERE status = 'AVAILABLE' AND component = r.component AND expiry_date > current_date
       AND compatible(blood_group, pg, r.component)
     ORDER BY (blood_group = pg) DESC, expiry_date, unit_id
     LIMIT GREATEST(r.units_needed - have, 0)
       FOR UPDATE SKIP LOCKED
  LOOP
    UPDATE blood_unit SET status = 'RESERVED' WHERE unit_id = u.unit_id;
    INSERT INTO allocation (request_id, unit_id) VALUES (p_request, u.unit_id);
    got := got + 1;
  END LOOP;

  UPDATE request SET status = CASE WHEN have + got >= units_needed THEN 'FULFILLED'
                                   WHEN have + got > 0 THEN 'PARTIAL' ELSE 'OPEN' END
   WHERE request_id = p_request;
  RETURN got;
END $$;

CREATE FUNCTION issue_request(p_request int) RETURNS int LANGUAGE plpgsql AS $$
BEGIN
  PERFORM 1 FROM request WHERE request_id = p_request AND status = 'FULFILLED' FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Request % is not fully allocated', p_request; END IF;
  UPDATE blood_unit SET status = 'ISSUED' WHERE unit_id IN (SELECT unit_id FROM allocation WHERE request_id = p_request);
  UPDATE allocation SET issued_at = now() WHERE request_id = p_request;
  UPDATE request SET status = 'ISSUED' WHERE request_id = p_request;
  RETURN (SELECT count(*) FROM allocation WHERE request_id = p_request);
END $$;

-- cancel_request releases reserved units back to stock.
CREATE FUNCTION cancel_request(p_request int) RETURNS int LANGUAGE plpgsql AS $$
DECLARE n int;
BEGIN
  PERFORM 1 FROM request WHERE request_id = p_request AND status IN ('OPEN','PARTIAL','FULFILLED') FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'Request % cannot be cancelled', p_request; END IF;
  UPDATE blood_unit SET status = 'AVAILABLE' WHERE unit_id IN (SELECT unit_id FROM allocation WHERE request_id = p_request);
  GET DIAGNOSTICS n = ROW_COUNT;
  DELETE FROM allocation WHERE request_id = p_request;
  UPDATE request SET status = 'CANCELLED' WHERE request_id = p_request;
  RETURN n;
END $$;

-- expire_units: nightly sweep of unreserved stock past its expiry date.
CREATE FUNCTION expire_units() RETURNS int LANGUAGE plpgsql AS $$
DECLARE n int;
BEGIN
  UPDATE blood_unit SET status = 'EXPIRED' WHERE status = 'AVAILABLE' AND expiry_date <= current_date;
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $$;
