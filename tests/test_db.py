"""Database behaviour checks. Run: .venv\\Scripts\\python tests\\test_db.py  (needs the seeded DB; every case rolls back)."""
import pathlib, sys
import psycopg
from psycopg import errors

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
from config import PG_DSN

conn = psycopg.connect(PG_DSN)
passed = 0


def case(fn):
    global passed
    try:
        fn()
        passed += 1
        print(f"  ok   {fn.__name__}")
    except Exception as e:  # noqa: BLE001 - report every failure, keep going
        print(f"  FAIL {fn.__name__}: {type(e).__name__}: {e}")
        sys.exit(1)
    finally:
        conn.rollback()


def one(sql, *a):
    return conn.execute(sql, a).fetchone()[0]


def fresh_donation(group, sex=None):
    """A new eligible donor of `group` plus a pending donation today."""
    q = "SELECT donor_id FROM v_eligible_donors e JOIN person p ON p.person_id = e.donor_id WHERE e.blood_group = %s"
    q += " AND p.sex = %s" if sex else ""
    q += " AND NOT EXISTS (SELECT 1 FROM donation WHERE donor_id = e.donor_id AND donated_on = current_date) LIMIT 1"
    donor = one(q, group, sex) if sex else one(q, group)
    staff = one("SELECT person_id FROM staff WHERE role = 'PHLEBOTOMIST' LIMIT 1")
    return donor, one("INSERT INTO donation (donor_id, staff_id, volume_ml) VALUES (%s,%s,450) RETURNING donation_id", donor, staff)


def clear_stock(group, comp):
    conn.execute("UPDATE blood_unit SET status = 'DISCARDED' WHERE blood_group = %s AND component = %s "
                 "AND status IN ('AVAILABLE')", (group, comp))


def test_compatibility_matrix():
    c = lambda u, p, k: one("SELECT compatible(%s,%s,%s)", u, p, k)
    assert c("O-", "AB+", "PRBC") and c("O-", "A-", "PRBC")
    assert not c("A+", "O+", "PRBC") and not c("B+", "B-", "PRBC") and not c("AB+", "A+", "PRBC")
    assert c("A-", "AB+", "PRBC") and c("A+", "AB+", "PRBC") and not c("A+", "A-", "PRBC")
    assert c("AB+", "O-", "PLASMA") and not c("O+", "A+", "PLASMA") and c("A+", "O+", "PLASMA")


def test_screening_pass_creates_labelled_units():
    _, did = fresh_donation("A+")
    assert one("SELECT record_screening(%s,'PASS',true)", did) == 3
    rows = conn.execute("SELECT component, blood_group, expiry_date - collected_on, barcode FROM blood_unit "
                        "WHERE donation_id = %s ORDER BY component", (did,)).fetchall()
    assert [r[0] for r in rows] == ["PLASMA", "PLT", "PRBC"]
    assert {r[1] for r in rows} == {"A+"}
    assert [r[2] for r in rows] == [365, 5, 42]
    assert all(r[3].startswith("HG") for r in rows)


def test_screening_fail_defers_donor_and_makes_no_units():
    donor, did = fresh_donation("B+")
    assert one("SELECT record_screening(%s,'FAIL')", did) == 0
    assert one("SELECT count(*) FROM blood_unit WHERE donation_id = %s", did) == 0
    assert one("SELECT deferred_until - current_date FROM donor WHERE person_id = %s", donor) == 365


def test_cannot_screen_twice():
    _, did = fresh_donation("O+")
    conn.execute("SELECT record_screening(%s,'PASS')", (did,))
    try:
        conn.execute("SELECT record_screening(%s,'PASS')", (did,))
        assert False, "second screening should fail"
    except errors.RaiseException:
        pass


def test_donation_gap_enforced():
    donor, _ = fresh_donation("O+", "F")                    # a woman just donated
    staff = one("SELECT person_id FROM staff LIMIT 1")
    try:
        conn.execute("INSERT INTO donation (donor_id, staff_id, volume_ml, donated_on) VALUES (%s,%s,450,current_date + 100)", (donor, staff))
        assert False, "120-day gap must be enforced for women"
    except errors.RaiseException as e:
        assert "next eligible" in str(e)


def test_illegal_status_transition_rejected():
    uid = one("SELECT unit_id FROM blood_unit WHERE status = 'EXPIRED' LIMIT 1")
    try:
        conn.execute("UPDATE blood_unit SET status = 'AVAILABLE' WHERE unit_id = %s", (uid,))
        assert False, "EXPIRED is terminal"
    except errors.RaiseException as e:
        assert "Illegal unit transition" in str(e)


def make_request(patient_group, comp="PRBC", n=1):
    pid = one("SELECT person_id FROM recipient WHERE blood_group = %s LIMIT 1", patient_group)
    return one("INSERT INTO request (hospital_id, patient_id, component, units_needed, urgency) VALUES (1,%s,%s,%s,'URGENT') RETURNING request_id",
               pid, comp, n)


def test_allocation_prefers_exact_group_then_soonest_expiry():
    clear_stock("A+", "PRBC"); clear_stock("O-", "PRBC")
    for g in ("O-", "A+", "A+"):
        _, did = fresh_donation(g)
        conn.execute("SELECT record_screening(%s,'PASS',true)", (did,))
    conn.execute("UPDATE blood_unit SET expiry_date = current_date + 3 WHERE status='AVAILABLE' AND blood_group='A+' AND component='PRBC'"
                 " AND unit_id = (SELECT min(unit_id) FROM blood_unit WHERE status='AVAILABLE' AND blood_group='A+' AND component='PRBC')")
    req = make_request("A+", "PRBC", 2)
    assert one("SELECT allocate_units(%s)", req) == 2
    groups = [r[0] for r in conn.execute("SELECT blood_group FROM blood_unit WHERE unit_id IN (SELECT unit_id FROM allocation WHERE request_id=%s)", (req,))]
    assert groups == ["A+", "A+"], groups                    # O- (universal donor) is kept back
    assert one("SELECT status FROM request WHERE request_id = %s", req) == "FULFILLED"


def test_partial_allocation_and_low_stock_alert():
    clear_stock("O-", "PRBC")
    _, did = fresh_donation("O-")
    conn.execute("SELECT record_screening(%s,'PASS',true)", (did,))
    req = make_request("O-", "PRBC", 3)
    assert one("SELECT allocate_units(%s)", req) == 1
    assert one("SELECT status FROM request WHERE request_id = %s", req) == "PARTIAL"
    assert one("SELECT count(*) FROM stock_alert WHERE blood_group='O-' AND component='PRBC' AND cleared_at IS NULL") == 1


def test_cancel_releases_units():
    req = make_request("O+", "PRBC", 1)
    n = one("SELECT allocate_units(%s)", req)
    assert one("SELECT cancel_request(%s)", req) == n
    assert one("SELECT count(*) FROM allocation WHERE request_id = %s", req) == 0


def test_issue_marks_units_issued():
    clear_stock("A-", "PRBC")
    _, did = fresh_donation("A-")
    conn.execute("SELECT record_screening(%s,'PASS',true)", (did,))
    req = make_request("A-", "PRBC", 1)
    assert one("SELECT allocate_units(%s)", req) == 1
    assert one("SELECT issue_request(%s)", req) == 1
    assert one("SELECT status FROM blood_unit WHERE unit_id IN (SELECT unit_id FROM allocation WHERE request_id=%s)", req) == "ISSUED"
    assert one("SELECT status FROM request WHERE request_id=%s", req) == "ISSUED"
    assert one("SELECT count(*) FROM unit_audit a JOIN allocation l USING (unit_id) WHERE l.request_id=%s", req) >= 3  # created, reserved, issued


def test_issue_requires_full_allocation():
    clear_stock("AB-", "PRBC")
    req = make_request("AB-", "PRBC", 2)
    try:
        conn.execute("SELECT issue_request(%s)", (req,))
        assert False
    except errors.RaiseException:
        pass


def test_unit_cannot_be_allocated_twice():
    row = conn.execute("SELECT request_id, unit_id FROM allocation LIMIT 1").fetchone()
    other = one("SELECT request_id FROM request WHERE request_id <> %s LIMIT 1", row[0])
    try:
        conn.execute("INSERT INTO allocation (request_id, unit_id) VALUES (%s,%s)", (other, row[1]))
        assert False
    except errors.UniqueViolation:
        pass


def test_roles_least_privilege():
    conn.execute("SET LOCAL ROLE hemo_viewer")
    try:
        conn.execute("DELETE FROM donor")
        assert False, "viewer must be read-only"
    except errors.InsufficientPrivilege:
        pass
    conn.rollback()
    conn.execute("SET LOCAL ROLE hemo_clinical")
    try:
        conn.execute("INSERT INTO donation (donor_id, staff_id, volume_ml) VALUES (1,1,450)")
        assert False, "clinical staff cannot create donations"
    except errors.InsufficientPrivilege:
        pass
    conn.rollback()
    conn.execute("SET LOCAL ROLE hemo_clinical")
    req = make_request("O+", "PRBC", 1)
    conn.execute("SELECT allocate_units(%s)", (req,))      # EXECUTE only; SECURITY DEFINER does the writes


for f in [v for k, v in list(globals().items()) if k.startswith("test_")]:
    case(f)
print(f"{passed} passed")
