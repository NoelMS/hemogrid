"""Rebuild the HemoGrid database: schema, logic, views, then realistic demo data (relational + MongoDB)."""
import pathlib, random, sys, datetime as dt
import psycopg
from pymongo import MongoClient

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from config import PG_DSN, MONGO_URI

random.seed(7)
TODAY = dt.date.today()

FIRST_M = "Arjun Rahul Vikram Karthik Suresh Naveen Pranav Imran Joseph Daniel Mohan Sanjay Faisal Ashwin Gokul Harish Irfan Kiran Manoj Nikhil".split()
FIRST_F = "Priya Ananya Divya Meera Fatima Sneha Lakshmi Kavya Nisha Pooja Revathi Shruti Swathi Aisha Deepa Janani Maya Nandini Sowmya Tanvi".split()
LAST = "Nair Iyer Menon Pillai Reddy Naidu Kumar Raj Sharma Khan Thomas Mathew George Varghese Gounder Krishnan Subramanian Das Joseph Chandran".split()
CITIES = ["Coimbatore"] * 6 + ["Tiruppur"] * 2 + ["Erode", "Salem", "Palakkad", "Pollachi", "Ooty"]
# Indian ABO/Rh distribution (percent) - makes O- genuinely scarce
GROUPS = ["O+"] * 37 + ["B+"] * 32 + ["A+"] * 22 + ["AB+"] * 7 + ["O-"] * 2 + ["B-"] * 1 + ["A-"] * 1 + ["AB-"] * 1
POLICY = {"PRBC": 6, "PLASMA": 4, "PLT": 3}
HOSPITALS = [("Kovai Medical Centre", "Coimbatore", "TN-CBE-0114"), ("PSG Institute Hospital", "Coimbatore", "TN-CBE-0231"),
             ("Government General Hospital", "Coimbatore", "TN-CBE-0007"), ("Sri Ramakrishna Hospital", "Coimbatore", "TN-CBE-0302"),
             ("Tiruppur District Hospital", "Tiruppur", "TN-TUP-0045"), ("Erode Trauma Centre", "Erode", "TN-ERD-0118")]
CAMPS = [("Karunya Campus Drive", "Karunya Auditorium"), ("Textile Mills Association Camp", "Avinashi Road"),
         ("Rotary Mega Camp", "Race Course"), ("Police Welfare Camp", "Police Grounds"), ("IT Park Drive", "Saravanampatti"),
         ("Church Youth Camp", "RS Puram"), ("Lions Club Camp", "Gandhipuram"), ("College Fest Drive", "Siruvani Road")]


def apply_sql(cur):
    for f in sorted((ROOT / "db").glob("0[123]_*.sql")):
        cur.execute(f.read_text(encoding="utf-8"))


def main():
    mongo = MongoClient(MONGO_URI)
    mongo.drop_database("hemogrid")
    reports = mongo.hemogrid.screening_reports

    with psycopg.connect(PG_DSN.replace("options=-csearch_path=hemo", ""), autocommit=True) as c:
        cur = c.cursor()
        apply_sql(cur)
        cur.execute("SET search_path = hemo")
        cur.executemany("INSERT INTO component_type VALUES (%s,%s,%s,%s)", [
            ("WB", "Whole blood", 35, "2-6 C"), ("PRBC", "Packed red cells", 42, "2-6 C"),
            ("PLASMA", "Fresh frozen plasma", 365, "-30 C"), ("PLT", "Platelet concentrate", 5, "20-24 C agitated")])
        cur.executemany("INSERT INTO stock_policy VALUES (%s,%s,%s)",
                        [(g, k, max(1, round(v * (0.4 if g.endswith('-') else 1))))
                         for g in sorted(set(GROUPS)) for k, v in POLICY.items()])

        def person(sex, age_lo, age_hi):
            first = random.choice(FIRST_F if sex == "F" else FIRST_M)
            dob = TODAY - dt.timedelta(days=random.randint(age_lo * 365, age_hi * 365))
            cur.execute("INSERT INTO person (full_name, sex, dob, city) VALUES (%s,%s,%s,%s) RETURNING person_id",
                        (f"{first} {random.choice(LAST)}", sex, dob, random.choice(CITIES)))
            return cur.fetchone()[0]

        staff = []
        for role, n in (("PHLEBOTOMIST", 5), ("LAB_TECH", 3), ("COORDINATOR", 3), ("ADMIN", 1)):
            for _ in range(n):
                pid = person(random.choice("MF"), 24, 55)
                cur.execute("INSERT INTO staff VALUES (%s,%s)", (pid, role))
                staff.append((pid, role))
        phleb = [p for p, r in staff if r == "PHLEBOTOMIST"]
        coord = [p for p, r in staff if r == "COORDINATOR"]

        cur.executemany("INSERT INTO hospital (name, city, licence_no) VALUES (%s,%s,%s)", HOSPITALS)
        camp_ids = []
        for i, (n, v) in enumerate(CAMPS):
            cur.execute("INSERT INTO camp (name, venue, camp_date, coordinator_id) VALUES (%s,%s,%s,%s) RETURNING camp_id",
                        (n, v, TODAY - dt.timedelta(days=4 + i * 7), random.choice(coord)))
            camp_ids.append(cur.fetchone()[0])

        donors = []
        for _ in range(420):
            sex = random.choices("MF", [62, 38])[0]
            pid = person(sex, 19, 58)
            g = random.choice(GROUPS)
            cur.execute("INSERT INTO donor (person_id, blood_group) VALUES (%s,%s)", (pid, g))
            donors.append((pid, g, sex))
            for _ in range(random.choice((1, 1, 1, 2))):
                cur.execute("INSERT INTO donor_phone VALUES (%s,%s) ON CONFLICT DO NOTHING",
                            (pid, "+91" + str(random.choice((6, 7, 8, 9))) + "".join(random.choices("0123456789", k=9))))
            for cid in random.sample(camp_ids, random.choice((0, 1, 1, 2))):
                cur.execute("INSERT INTO donor_camp VALUES (%s,%s) ON CONFLICT DO NOTHING", (pid, cid))

        # Donations across the last 55 days (platelets last 5 days, so the stock mix is realistic)
        donations = []
        for pid, g, sex in random.sample(donors, 330):
            when = TODAY - dt.timedelta(days=random.randint(0, 55))
            cur.execute("INSERT INTO donation (donor_id, camp_id, staff_id, donated_on, volume_ml) "
                        "VALUES (%s,%s,%s,%s,%s) RETURNING donation_id",
                        (pid, random.choice(camp_ids + [None] * 4), random.choice(phleb), when, random.choice((350, 450, 450))))
            donations.append((cur.fetchone()[0], pid, g, sex, when))

        docs = []
        for did, pid, g, sex, when in donations:
            ok = random.random() > 0.045
            cur.execute("SELECT record_screening(%s,%s,%s)", (did, "PASS" if ok else "FAIL", random.random() < 0.85))
            markers = {k: "NEGATIVE" for k in ("hiv", "hbsag", "hcv", "syphilis", "malaria")}
            if not ok:
                markers[random.choice(list(markers))] = "REACTIVE"
            q = {"weight_kg": random.randint(48, 92), "recent_travel": random.random() < 0.12,
                 "tattoo_last_6m": random.random() < 0.06,
                 "on_medication": random.sample(["metformin", "amlodipine", "levothyroxine", "iron supplements"],
                                                k=random.choice((0, 0, 1)))}
            if sex == "F":
                q["pregnancy_history"] = random.choice(("none", "none", "past"))
            if random.random() < 0.2:
                q["notes"] = random.choice(("first-time donor", "regular donor, 4th donation", "reported mild dizziness last time"))
            docs.append({"donation_id": did, "donor_id": pid, "tested_on": dt.datetime.combine(when, dt.time(15, 0)),
                         "hb_gdl": round(random.uniform(12.2, 16.4), 1), "markers": markers,
                         "result": "PASS" if ok else "FAIL", "questionnaire": q,
                         "flags": [k for k, v in markers.items() if v != "NEGATIVE"]})
        reports.insert_many(docs)
        reports.create_index("donation_id", unique=True)
        reports.create_index([("flags", 1)])

        cur.execute("SELECT expire_units()")

        # Recipients + requests in mixed states
        rec = []
        for _ in range(60):
            pid = person(random.choice("MF"), 3, 80)
            cur.execute("INSERT INTO recipient VALUES (%s,%s)", (pid, random.choice(GROUPS)))
            rec.append(pid)
        reqs = []
        for _ in range(34):
            cur.execute("INSERT INTO request (hospital_id, patient_id, component, units_needed, urgency, created_at) "
                        "VALUES (%s,%s,%s,%s,%s, now() - make_interval(hours => %s)) RETURNING request_id",
                        (random.randint(1, len(HOSPITALS)), random.choice(rec),
                         random.choices(["PRBC", "PLASMA", "PLT"], [6, 2, 2])[0], random.choice((1, 1, 2, 2, 3, 4)),
                         random.choices(["ROUTINE", "URGENT", "EMERGENCY"], [5, 3, 2])[0], random.randint(1, 70)))
            reqs.append(cur.fetchone()[0])
        for r in reqs[:24]:
            cur.execute("SELECT allocate_units(%s)", (r,))
        for r in reqs[:10]:
            cur.execute("SELECT status FROM request WHERE request_id=%s", (r,))
            if cur.fetchone()[0] == "FULFILLED":
                cur.execute("SELECT issue_request(%s)", (r,))
        cur.execute("SELECT count(*) FROM blood_unit")
        units = cur.fetchone()[0]
        print(f"seeded: {len(donors)} donors, {len(donations)} donations, {units} units, "
              f"{len(reqs)} requests, {len(docs)} mongo reports")


if __name__ == "__main__":
    main()
