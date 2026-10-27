-- HemoGrid: blood bank schema (PostgreSQL 16). All tables in 3NF/BCNF; multivalued facts
-- (donor phones, donor camp attendance) live in their own tables so the schema is 4NF.
DROP SCHEMA IF EXISTS hemo CASCADE;
CREATE SCHEMA hemo;
SET search_path = hemo;

CREATE DOMAIN blood_group AS text
  CHECK (VALUE IN ('A+','A-','B+','B-','AB+','AB-','O+','O-'));
CREATE DOMAIN component_code AS text
  CHECK (VALUE IN ('WB','PRBC','PLASMA','PLT'));

-- ---- Specialization: PERSON is the supertype of DONOR, RECIPIENT, STAFF (overlapping, partial)
CREATE TABLE person (
  person_id   serial PRIMARY KEY,
  full_name   text NOT NULL,
  sex         char(1) NOT NULL CHECK (sex IN ('M','F','O')),
  dob         date NOT NULL CHECK (dob < current_date),
  city        text NOT NULL
);

CREATE TABLE donor (
  person_id           int PRIMARY KEY REFERENCES person ON DELETE CASCADE,
  blood_group         blood_group NOT NULL,
  last_donation_date  date,
  deferred_until      date,                       -- set when screening fails
  CHECK (deferred_until IS NULL OR deferred_until >= last_donation_date)
);

CREATE TABLE recipient (
  person_id    int PRIMARY KEY REFERENCES person ON DELETE CASCADE,
  blood_group  blood_group NOT NULL
);

CREATE TABLE staff (
  person_id  int PRIMARY KEY REFERENCES person ON DELETE CASCADE,
  role       text NOT NULL CHECK (role IN ('PHLEBOTOMIST','LAB_TECH','COORDINATOR','ADMIN'))
);

-- Multivalued attribute of donor: a donor has several phones AND attends several camps.
-- Storing both in one table would force phone x camp rows (a 4NF violation, see docs/normalization.md).
CREATE TABLE donor_phone (
  donor_id  int REFERENCES donor ON DELETE CASCADE,
  phone     text CHECK (phone ~ '^\+?[0-9]{10,13}$'),
  PRIMARY KEY (donor_id, phone)
);

CREATE TABLE hospital (
  hospital_id  serial PRIMARY KEY,
  name         text NOT NULL UNIQUE,
  city         text NOT NULL,
  licence_no   text NOT NULL UNIQUE
);

CREATE TABLE camp (
  camp_id         serial PRIMARY KEY,
  name            text NOT NULL,
  venue           text NOT NULL,
  camp_date       date NOT NULL,
  coordinator_id  int NOT NULL REFERENCES staff
);

CREATE TABLE donor_camp (
  donor_id  int REFERENCES donor ON DELETE CASCADE,
  camp_id   int REFERENCES camp  ON DELETE CASCADE,
  PRIMARY KEY (donor_id, camp_id)
);

-- Lookup: shelf life is a function of component only (component -> shelf_days), so it is its own table.
CREATE TABLE component_type (
  component   component_code PRIMARY KEY,
  label       text NOT NULL,
  shelf_days  int  NOT NULL CHECK (shelf_days > 0),
  storage     text NOT NULL
);

-- Donor group is derived through donor_id, so it is not repeated on donation.
CREATE TABLE donation (
  donation_id  serial PRIMARY KEY,
  donor_id     int  NOT NULL REFERENCES donor,
  camp_id      int  REFERENCES camp,               -- NULL = walk-in at the centre
  staff_id     int  NOT NULL REFERENCES staff,
  donated_on   date NOT NULL DEFAULT current_date,
  volume_ml    int  NOT NULL CHECK (volume_ml BETWEEN 350 AND 450),
  screening    text NOT NULL DEFAULT 'PENDING' CHECK (screening IN ('PENDING','PASS','FAIL')),
  UNIQUE (donor_id, donated_on)
);

CREATE TABLE blood_unit (
  unit_id      serial PRIMARY KEY,
  barcode      text NOT NULL UNIQUE,
  donation_id  int NOT NULL REFERENCES donation,
  component    component_code NOT NULL REFERENCES component_type,
  blood_group  blood_group NOT NULL,               -- copied at labelling time on purpose: a unit label is immutable
  collected_on date NOT NULL,
  expiry_date  date NOT NULL,
  status       text NOT NULL DEFAULT 'QUARANTINE'
               CHECK (status IN ('QUARANTINE','AVAILABLE','RESERVED','ISSUED','EXPIRED','DISCARDED')),
  CHECK (expiry_date > collected_on),
  UNIQUE (donation_id, component)
);

CREATE TABLE request (
  request_id    serial PRIMARY KEY,
  hospital_id   int NOT NULL REFERENCES hospital,
  patient_id    int NOT NULL REFERENCES recipient,
  component     component_code NOT NULL REFERENCES component_type,
  units_needed  int NOT NULL CHECK (units_needed BETWEEN 1 AND 20),
  urgency       text NOT NULL CHECK (urgency IN ('ROUTINE','URGENT','EMERGENCY')),
  status        text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','PARTIAL','FULFILLED','ISSUED','CANCELLED')),
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- One unit can only ever be allocated once: this UNIQUE is the last line of defence against double allocation.
CREATE TABLE allocation (
  allocation_id  serial PRIMARY KEY,
  request_id     int NOT NULL REFERENCES request ON DELETE CASCADE,
  unit_id        int NOT NULL UNIQUE REFERENCES blood_unit,
  allocated_at   timestamptz NOT NULL DEFAULT now(),
  issued_at      timestamptz
);

-- Reorder level depends on the (group, component) pair, so it is not stored on component_type.
CREATE TABLE stock_policy (
  blood_group    blood_group,
  component      component_code REFERENCES component_type,
  reorder_level  int NOT NULL CHECK (reorder_level >= 0),
  PRIMARY KEY (blood_group, component)
);

CREATE TABLE stock_alert (
  alert_id     serial PRIMARY KEY,
  blood_group  blood_group NOT NULL,
  component    component_code NOT NULL,
  available    int NOT NULL,
  raised_at    timestamptz NOT NULL DEFAULT now(),
  cleared_at   timestamptz
);

CREATE TABLE unit_audit (
  audit_id    bigserial PRIMARY KEY,
  unit_id     int NOT NULL,
  old_status  text,
  new_status  text NOT NULL,
  changed_at  timestamptz NOT NULL DEFAULT now(),
  changed_by  text NOT NULL DEFAULT current_user
);

-- ---- Indexes. Measured with EXPLAIN ANALYZE in scripts/demo_indexing.py
-- B+ tree (PostgreSQL's default btree): allocation search is "group + component, available, soonest expiry first".
CREATE INDEX ix_unit_fefo ON blood_unit (blood_group, component, expiry_date) WHERE status = 'AVAILABLE';
-- Hash index: the barcode scanner only ever does equality lookups.
CREATE INDEX ix_unit_barcode_hash ON blood_unit USING hash (barcode);
-- Plain btree on a foreign key used for joins.
CREATE INDEX ix_donation_donor ON donation (donor_id, donated_on DESC);
CREATE INDEX ix_request_open   ON request (urgency, created_at) WHERE status IN ('OPEN','PARTIAL');
