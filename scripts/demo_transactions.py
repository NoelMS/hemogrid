"""Module 5 demo: ACID, races for the last O- unit, isolation levels, deadlock.
Runs on a scratch clone (hemogrid_demo) so the real data is untouched.  Output is also saved to docs/transactions_demo.txt.
"""
import pathlib, sys, threading, io
import psycopg
from psycopg import errors

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from config import PG_DSN

ADMIN = PG_DSN.replace("dbname=hemogrid", "dbname=postgres").replace("options=-csearch_path=hemo", "")
DEMO = PG_DSN.replace("dbname=hemogrid", "dbname=hemogrid_demo")
out = io.StringIO()


def say(msg=""):
    print(msg)
    out.write(msg + "\n")


def setup():
    with psycopg.connect(ADMIN, autocommit=True) as a:
        a.execute("DROP DATABASE IF EXISTS hemogrid_demo WITH (FORCE)")
        a.execute("CREATE DATABASE hemogrid_demo TEMPLATE hemogrid")
    c = psycopg.connect(DEMO, autocommit=True)
    c.execute("UPDATE blood_unit SET status='DISCARDED' WHERE blood_group='O-' AND component='PRBC' AND status='AVAILABLE'")
    donor = c.execute("SELECT donor_id FROM v_eligible_donors WHERE blood_group='O-' LIMIT 1").fetchone()[0]
    staff = c.execute("SELECT person_id FROM staff WHERE role='PHLEBOTOMIST' LIMIT 1").fetchone()[0]
    did = c.execute("INSERT INTO donation (donor_id, staff_id, volume_ml) VALUES (%s,%s,450) RETURNING donation_id", (donor, staff)).fetchone()[0]
    c.execute("SELECT record_screening(%s,'PASS',true)", (did,))
    pts = [r[0] for r in c.execute("SELECT person_id FROM recipient WHERE blood_group='O-' LIMIT 2")]
    reqs = [c.execute("INSERT INTO request (hospital_id, patient_id, component, units_needed, urgency) VALUES (%s,%s,'PRBC',1,'EMERGENCY') RETURNING request_id",
                      (h, pts[i % len(pts)])).fetchone()[0] for i, h in enumerate((1, 2))]
    return c, reqs


def race(worker, args_list):
    """Run worker(conn, *args, barrier) in parallel threads; return their results."""
    barrier, results = threading.Barrier(len(args_list)), [None] * len(args_list)

    def run(i, args):
        with psycopg.connect(DEMO) as conn:
            try:
                results[i] = worker(conn, *args, barrier)
            except Exception as e:  # noqa: BLE001
                conn.rollback()
                results[i] = f"{type(e).__name__}: {str(e).splitlines()[0]}"
    ts = [threading.Thread(target=run, args=(i, a)) for i, a in enumerate(args_list)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return results


def state(c, reqs):
    rows = c.execute("SELECT r.request_id, r.status, count(a.unit_id) FROM request r LEFT JOIN allocation a USING (request_id) "
                     "WHERE r.request_id = ANY(%s) GROUP BY 1,2 ORDER BY 1", (reqs,)).fetchall()
    return "; ".join(f"request {r[0]} -> {r[1]} ({r[2]} unit)" for r in rows)


def naive(conn, req, barrier):
    """Read-then-write with no lock: the textbook lost-update / double-booking bug."""
    uid = conn.execute("SELECT unit_id FROM blood_unit WHERE status='AVAILABLE' AND blood_group='O-' AND component='PRBC' LIMIT 1").fetchone()
    barrier.wait()                                           # both have now seen the same unit as free
    conn.execute("UPDATE blood_unit SET status='RESERVED' WHERE unit_id=%s", (uid[0],))
    conn.execute("INSERT INTO allocation (request_id, unit_id) VALUES (%s,%s)", (req, uid[0]))
    conn.commit()
    return f"request {req} got unit {uid[0]}"


def guarded(conn, req, barrier):
    barrier.wait()
    n = conn.execute("SELECT allocate_units(%s)", (req,)).fetchone()[0]
    conn.commit()
    return f"request {req} got {n} unit(s)"


def serializable(conn, req, barrier, retries=3):
    for attempt in range(1, retries + 1):
        try:
            conn.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            uid = conn.execute("SELECT unit_id FROM blood_unit WHERE status='AVAILABLE' AND blood_group='O-' AND component='PRBC' LIMIT 1").fetchone()
            if attempt == 1:
                barrier.wait()
            if not uid:
                conn.commit()
                return f"request {req}: no unit left (attempt {attempt})"
            conn.execute("UPDATE blood_unit SET status='RESERVED' WHERE unit_id=%s", (uid[0],))
            conn.execute("INSERT INTO allocation (request_id, unit_id) VALUES (%s,%s)", (req, uid[0]))
            conn.commit()
            return f"request {req} got unit {uid[0]} (attempt {attempt})"
        except errors.SerializationFailure:
            conn.rollback()
            say(f"    request {req}: SQLSTATE 40001 serialization_failure on attempt {attempt}, retrying")
    return f"request {req}: gave up"


def deadlock(conn, first, second, barrier):
    conn.execute("UPDATE blood_unit SET status = status WHERE unit_id=%s", (first,))
    barrier.wait()
    conn.execute("UPDATE blood_unit SET status = status WHERE unit_id=%s", (second,))
    conn.commit()
    return f"locked {first} then {second}: committed"


def reset(c, reqs):
    c.execute("DELETE FROM allocation WHERE request_id = ANY(%s)", (reqs,))
    c.execute("UPDATE blood_unit SET status='AVAILABLE' WHERE status='RESERVED' AND blood_group='O-' AND component='PRBC'")
    c.execute("UPDATE request SET status='OPEN' WHERE request_id = ANY(%s)", (reqs,))


def main():
    c, reqs = setup()
    unit = c.execute("SELECT unit_id FROM blood_unit WHERE status='AVAILABLE' AND blood_group='O-' AND component='PRBC'").fetchall()
    say("== Setup: exactly ONE O- red-cell unit is in stock; two EMERGENCY requests want it simultaneously ==")
    say(f"   unit {unit[0][0]}, requests {reqs}\n")

    say("1. Atomicity - a failure halfway rolls everything back")
    with psycopg.connect(DEMO) as t:
        try:
            t.execute("SELECT allocate_units(%s)", (reqs[0],))
            t.execute("INSERT INTO allocation (request_id, unit_id) SELECT %s, unit_id FROM allocation WHERE request_id=%s", (reqs[1], reqs[0]))
        except errors.UniqueViolation:
            t.rollback()
    say(f"   after ROLLBACK: {state(c, reqs)}  (unit is AVAILABLE again: "
        f"{c.execute('SELECT status FROM blood_unit WHERE unit_id=%s', (unit[0][0],)).fetchone()[0]})\n")

    say("2. Naive read-then-write at READ COMMITTED (no lock)")
    for r in race(naive, [(reqs[0],), (reqs[1],)]):
        say(f"   {r}")
    say(f"   -> {state(c, reqs)}")
    say("   Both transactions read the unit as free. Only the UNIQUE(allocation.unit_id) constraint stopped a double allocation;")
    say("   the loser's work was thrown away with an error instead of being handled.\n")
    reset(c, reqs)

    say("3. allocate_units(): SELECT ... FOR UPDATE SKIP LOCKED (READ COMMITTED)")
    for r in race(guarded, [(reqs[0],), (reqs[1],)]):
        say(f"   {r}")
    say(f"   -> {state(c, reqs)}")
    say("   One request wins the row lock; the other skips it, sees no stock and stays OPEN - clean, no error.\n")
    reset(c, reqs)

    say("4. SERIALIZABLE isolation with retry loop")
    for r in race(serializable, [(reqs[0],), (reqs[1],)]):
        say(f"   {r}")
    say(f"   -> {state(c, reqs)}")
    say("   The database detects the read/write dependency cycle and aborts one transaction; the application retries it.\n")
    reset(c, reqs)

    say("5. Deadlock: two sessions lock the same two units in opposite order")
    a, b = [r[0] for r in c.execute("SELECT unit_id FROM blood_unit WHERE status='AVAILABLE' ORDER BY unit_id LIMIT 2")]
    res = race(deadlock, [(a, b), (b, a)])
    for r in res:
        say(f"   {r}")
    assert any("DeadlockDetected" in str(r) for r in res), "expected a deadlock victim"
    say("   PostgreSQL's deadlock detector aborts one victim (SQLSTATE 40P01). Fix: always lock rows in a fixed order (ORDER BY unit_id).\n")

    say("6. Durability: a commit is a WAL flush")
    lsn0 = c.execute("SELECT pg_current_wal_lsn()").fetchone()[0]
    c.execute("UPDATE blood_unit SET status=status WHERE unit_id=%s", (a,))
    say(f"   WAL position {lsn0} -> {c.execute('SELECT pg_current_wal_lsn()').fetchone()[0]} after one committed UPDATE "
        f"(synchronous_commit={c.execute('SHOW synchronous_commit').fetchone()[0]})")
    c.close()
    (ROOT / "docs" / "transactions_demo.txt").write_text(out.getvalue(), encoding="utf-8")


if __name__ == "__main__":
    main()
