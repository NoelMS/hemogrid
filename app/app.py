"""HemoGrid web app. Thin layer over PostgreSQL routines (db/02_logic.sql) and MongoDB screening reports."""
import datetime as dt
import json
import pathlib
import re

import markdown
import psycopg
from flask import Flask, abort, flash, g, redirect, render_template, request, url_for
from psycopg.rows import dict_row
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from config import MONGO_URI, PG_DSN
from queries import QUERIES

app = Flask(__name__)
app.secret_key = "hemogrid-local-demo"  # demo value; read it from the environment for a real deployment

GROUPS = ["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"]
COMPONENTS = {"PRBC": "Red cells", "PLASMA": "Plasma", "PLT": "Platelets", "WB": "Whole blood"}
STATUSES = ["AVAILABLE", "RESERVED", "ISSUED", "EXPIRED", "QUARANTINE", "DISCARDED"]
MARKERS = ["hiv", "hbsag", "hcv", "syphilis", "malaria"]
PAGE = 40
ROOT = pathlib.Path(__file__).resolve().parents[1]
# (slug, title, source file under docs/, one-line description)
DESIGN = [
    ("er", "ER diagram", "er-diagram.md", "Entities, relationships and the extended-ER features used."),
    ("normalization", "Normalization", "normalization.md", "Functional dependencies, 1NF to 5NF, and why each table is shaped the way it is."),
    ("algebra", "Relational algebra", "relational-algebra.md", "The key queries written as algebra, next to their SQL."),
    ("sql", "SQL objects", None, "Tables, triggers, routines, views and roles, straight from the install scripts."),
    ("indexing", "Indexing", "indexing_demo.txt", "B+ tree, partial and hash indexes measured with EXPLAIN ANALYZE."),
    ("transactions", "Transactions", "transactions_demo.txt", "Atomicity, locking, isolation levels and a deadlock, reproduced live."),
    ("nosql", "NoSQL", "nosql.md", "What lives in MongoDB and why."),
]

_mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=1200)


def db():
    if "db" not in g:
        g.db = psycopg.connect(PG_DSN, row_factory=dict_row, autocommit=True)
    return g.db


@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()


def q(sql, *args):
    return db().execute(sql, args).fetchall()


def q1(sql, *args):
    return db().execute(sql, args).fetchone()


def reports():
    return _mongo.hemogrid.screening_reports


def db_error(e):
    """Trigger and function failures raise with a human sentence; show it as-is."""
    return str(e).splitlines()[0]


@app.template_filter("rel")
def rel_days(d):
    n = (d - dt.date.today()).days
    return "today" if n == 0 else f"in {n}d" if n > 0 else f"{-n}d ago"


@app.template_filter("ts")
def fmt_ts(t):
    return t.strftime("%d %b %H:%M")


@app.context_processor
def nav():
    row = q1("SELECT (SELECT count(*) FROM stock_alert WHERE cleared_at IS NULL) AS alerts, "
             "(SELECT count(*) FROM request WHERE status IN ('OPEN','PARTIAL')) AS open_requests, "
             "(SELECT count(*) FROM donation WHERE screening = 'PENDING') AS pending")
    return {"nav": row, "GROUPS": GROUPS, "COMPONENTS": COMPONENTS, "today": dt.date.today()}


@app.route("/favicon.ico")
def favicon():
    return app.send_static_file("favicon.png")


# ------------------------------------------------------------------ dashboard
@app.route("/")
def dashboard():
    cells = {(r["blood_group"], r["component"]): r for r in q("SELECT * FROM v_stock")}
    alerts = q("SELECT * FROM stock_alert WHERE cleared_at IS NULL ORDER BY available, blood_group")
    expiring = q("SELECT * FROM v_expiring ORDER BY expiry_date, blood_group LIMIT 14")
    queue = q("SELECT * FROM v_request_board WHERE status IN ('OPEN','PARTIAL') "
              "ORDER BY CASE urgency WHEN 'EMERGENCY' THEN 0 WHEN 'URGENT' THEN 1 ELSE 2 END, created_at LIMIT 8")
    totals = q1("SELECT count(*) FILTER (WHERE status='AVAILABLE') AS available, count(*) FILTER (WHERE status='RESERVED') AS reserved, "
                "count(*) FILTER (WHERE status='EXPIRED') AS expired, count(*) FILTER (WHERE status='ISSUED') AS issued FROM blood_unit")
    return render_template("dashboard.html", cells=cells, alerts=alerts, expiring=expiring, queue=queue, totals=totals,
                           comps=["PRBC", "PLASMA", "PLT"])


@app.post("/sweep")
def sweep():
    n = q1("SELECT expire_units() AS n")["n"]
    flash(f"Expiry sweep complete: {n} unit(s) marked expired." if n else "Expiry sweep complete: nothing to expire.")
    return redirect(request.referrer or url_for("dashboard"))


# ------------------------------------------------------------------ inventory
@app.route("/inventory")
def inventory():
    f = {k: request.args.get(k, "") for k in ("group", "component", "status")}
    f["status"] = f["status"] or "AVAILABLE"
    page = max(int(request.args.get("page", 1) or 1), 1)
    where, args = [], []
    for col, key in (("blood_group", "group"), ("component", "component"), ("status", "status")):
        if f[key] and f[key] != "ANY":
            where.append(f"{col} = %s")
            args.append(f[key])
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = q1(f"SELECT count(*) AS n FROM blood_unit {clause}", *args)["n"]
    rows = q(f"SELECT unit_id, barcode, blood_group, component, status, collected_on, expiry_date FROM blood_unit {clause} "
             f"ORDER BY expiry_date, unit_id LIMIT {PAGE} OFFSET {(page - 1) * PAGE}", *args)
    return render_template("inventory.html", rows=rows, f=f, total=total, page=page, pages=max(1, -(-total // PAGE)),
                           statuses=STATUSES)


@app.route("/unit")
def unit_lookup():
    code = request.args.get("barcode", "").strip().upper()
    row = q1("SELECT unit_id FROM blood_unit WHERE barcode = %s", code)  # equality only -> hash index
    if not row:
        flash(f"No unit with barcode {code or '(empty)'}.")
        return redirect(url_for("inventory"))
    return redirect(url_for("unit", unit_id=row["unit_id"]))


@app.route("/unit/<int:unit_id>")
def unit(unit_id):
    u = q1("SELECT u.*, p.full_name AS donor, d.donated_on, d.donation_id, d.donor_id, ct.label, ct.storage, ct.shelf_days "
           "FROM blood_unit u JOIN donation d USING (donation_id) JOIN person p ON p.person_id = d.donor_id "
           "JOIN component_type ct USING (component) WHERE u.unit_id = %s", unit_id) or abort(404)
    audit = q("SELECT * FROM unit_audit WHERE unit_id = %s ORDER BY audit_id", unit_id)
    alloc = q1("SELECT a.*, r.request_id, h.name AS hospital FROM allocation a JOIN request r USING (request_id) "
               "JOIN hospital h USING (hospital_id) WHERE a.unit_id = %s", unit_id)
    return render_template("unit.html", u=u, audit=audit, alloc=alloc, report=mongo_report(u["donation_id"]))


def mongo_report(donation_id):
    try:
        return reports().find_one({"donation_id": donation_id}, {"_id": 0})
    except PyMongoError:
        return "unavailable"


# ------------------------------------------------------------------ donors
@app.route("/donors")
def donors():
    term = request.args.get("q", "").strip()
    grp = request.args.get("group", "")
    eligible = request.args.get("eligible") == "1"
    where, args = [], []
    if term:
        where.append("p.full_name ILIKE %s")
        args.append(f"%{term}%")
    if grp:
        where.append("d.blood_group = %s")
        args.append(grp)
    if eligible:
        where.append("p.person_id IN (SELECT donor_id FROM v_eligible_donors)")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = q(f"SELECT p.person_id, p.full_name, p.city, p.sex, d.blood_group, d.last_donation_date, d.deferred_until, "
             f"d.last_donation_date + CASE p.sex WHEN 'F' THEN 120 ELSE 90 END AS due, "
             f"(SELECT count(*) FROM donation x WHERE x.donor_id = p.person_id) AS donations "
             f"FROM donor d JOIN person p ON p.person_id = d.person_id {clause} ORDER BY p.full_name LIMIT 60", *args)
    return render_template("donors.html", rows=rows, term=term, sel=grp, eligible=eligible)


@app.route("/donors/new", methods=["GET", "POST"])
def donor_new():
    if request.method == "POST":
        f = request.form
        phone = re.sub(r"[ -]", "", f.get("phone", ""))
        try:
            with db().transaction():
                pid = q1("INSERT INTO person (full_name, sex, dob, city) VALUES (%s,%s,%s,%s) RETURNING person_id",
                         f["name"].strip(), f["sex"], f["dob"], f["city"].strip())["person_id"]
                q1("INSERT INTO donor (person_id, blood_group) VALUES (%s,%s) RETURNING person_id", pid, f["group"])
                if phone:
                    q1("INSERT INTO donor_phone VALUES (%s,%s) RETURNING donor_id", pid, phone)
            flash(f"Registered {f['name'].strip()}.")
            return redirect(url_for("donor", donor_id=pid))
        except psycopg.Error as e:
            flash(db_error(e), "error")
    return render_template("donor_new.html")


@app.route("/donors/<int:donor_id>")
def donor(donor_id):
    d = q1("SELECT p.*, d.blood_group, d.last_donation_date, d.deferred_until, "
           "e.eligible_from FROM donor d JOIN person p ON p.person_id = d.person_id "
           "LEFT JOIN v_eligible_donors e ON e.donor_id = d.person_id WHERE d.person_id = %s", donor_id) or abort(404)
    history = q("SELECT d.*, c.name AS camp, (SELECT count(*) FROM blood_unit u WHERE u.donation_id = d.donation_id) AS units "
                "FROM donation d LEFT JOIN camp c USING (camp_id) WHERE donor_id = %s ORDER BY donated_on DESC", donor_id)
    phones = [r["phone"] for r in q("SELECT phone FROM donor_phone WHERE donor_id = %s", donor_id)]
    camps = q("SELECT c.name, c.camp_date FROM donor_camp dc JOIN camp c USING (camp_id) WHERE dc.donor_id = %s ORDER BY camp_date DESC", donor_id)
    staff = q("SELECT s.person_id, p.full_name FROM staff s JOIN person p ON p.person_id = s.person_id WHERE s.role = 'PHLEBOTOMIST' ORDER BY 2")
    open_camps = q("SELECT camp_id, name, camp_date FROM camp ORDER BY camp_date DESC")
    return render_template("donor.html", d=d, history=history, phones=phones, camps=camps, staff=staff, open_camps=open_camps)


@app.post("/donors/<int:donor_id>/donate")
def donate(donor_id):
    f = request.form
    try:
        q1("INSERT INTO donation (donor_id, staff_id, camp_id, volume_ml) VALUES (%s,%s,%s,%s) RETURNING donation_id",
           donor_id, f["staff"], f.get("camp") or None, f["volume"])
        flash("Donation recorded. It is quarantined until screening is entered.")
    except psycopg.Error as e:
        flash(db_error(e), "error")
    return redirect(url_for("donor", donor_id=donor_id))


# ------------------------------------------------------------------ screening
@app.route("/screening")
def screening():
    pending = q("SELECT d.donation_id, d.donated_on, d.volume_ml, p.full_name, dn.blood_group, p.person_id "
                "FROM donation d JOIN donor dn ON dn.person_id = d.donor_id JOIN person p ON p.person_id = d.donor_id "
                "WHERE d.screening = 'PENDING' ORDER BY d.donated_on, d.donation_id")
    flag = request.args.get("flag", "")
    try:
        stats = list(reports().aggregate([
            {"$unwind": {"path": "$flags", "preserveNullAndEmptyArrays": False}},
            {"$group": {"_id": "$flags", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}]))
        found = list(reports().find({"flags": flag}, {"_id": 0, "donation_id": 1, "donor_id": 1, "hb_gdl": 1, "markers": 1})
                     .sort("donation_id", -1).limit(12)) if flag else []
        total = reports().count_documents({})
        nosql_ok = True
    except PyMongoError:
        stats, found, total, nosql_ok = [], [], 0, False
    return render_template("screening.html", pending=pending, stats=stats, found=found, flag=flag, total=total,
                           markers=MARKERS, nosql_ok=nosql_ok)


@app.post("/screening/<int:donation_id>")
def screen(donation_id):
    f = request.form
    markers = {m: ("REACTIVE" if f.get("reactive") == m else "NEGATIVE") for m in MARKERS}
    try:
        hb = float(f["hb"])
    except ValueError:
        flash("Haemoglobin must be a number, e.g. 13.4.", "error")
        return redirect(url_for("screening"))
    ok = "REACTIVE" not in markers.values() and hb >= 12.5
    try:
        row = q1("SELECT donor_id FROM donation WHERE donation_id = %s", donation_id) or abort(404)
        # Order matters: if Postgres rejects the screening (e.g. already screened) no orphan report is written.
        made = q1("SELECT record_screening(%s,%s,%s) AS n", donation_id, "PASS" if ok else "FAIL", f.get("split") == "1")["n"]
        report = {"donation_id": donation_id, "donor_id": row["donor_id"], "tested_on": dt.datetime.now(), "hb_gdl": hb,
                  "markers": markers, "result": "PASS" if ok else "FAIL",
                  "questionnaire": {"notes": f.get("notes", "").strip()} if f.get("notes", "").strip() else {},
                  "flags": [m for m, v in markers.items() if v != "NEGATIVE"] + (["low_hb"] if hb < 12.5 else [])}
        try:
            reports().replace_one({"donation_id": donation_id}, report, upsert=True)
        except PyMongoError:
            flash("Screening saved in PostgreSQL, but the MongoDB report store is unreachable.", "error")
        flash(f"Donation #{donation_id} PASSED: {made} unit(s) labelled and released to stock." if ok else
              f"Donation #{donation_id} FAILED screening: donor deferred for 365 days, no units created.")
    except psycopg.Error as e:
        flash(db_error(e), "error")
    return redirect(url_for("screening"))


# ------------------------------------------------------------------ requests
@app.route("/requests")
def requests_board():
    status = request.args.get("status", "ACTIVE")
    cond = {"ACTIVE": "status IN ('OPEN','PARTIAL','FULFILLED')", "ISSUED": "status = 'ISSUED'", "CANCELLED": "status = 'CANCELLED'"}.get(status, "TRUE")
    rows = q(f"SELECT * FROM v_request_board WHERE {cond} ORDER BY CASE urgency WHEN 'EMERGENCY' THEN 0 WHEN 'URGENT' THEN 1 ELSE 2 END, created_at LIMIT 80")
    units = {}
    for r in q("SELECT a.request_id, u.unit_id, u.barcode, u.blood_group, u.expiry_date FROM allocation a "
               "JOIN blood_unit u USING (unit_id) ORDER BY u.unit_id"):
        units.setdefault(r["request_id"], []).append(r)
    hospitals = q("SELECT hospital_id, name FROM hospital ORDER BY name")
    patients = q("SELECT r.person_id, p.full_name, r.blood_group FROM recipient r JOIN person p USING (person_id) ORDER BY p.full_name")
    return render_template("requests.html", rows=rows, units=units, status=status, hospitals=hospitals, patients=patients)


@app.post("/requests/new")
def request_new():
    f = request.form
    try:
        rid = q1("INSERT INTO request (hospital_id, patient_id, component, units_needed, urgency) VALUES (%s,%s,%s,%s,%s) RETURNING request_id",
                 f["hospital"], f["patient"], f["component"], f["units"], f["urgency"])["request_id"]
        got = q1("SELECT allocate_units(%s) AS n", rid)["n"] if f["urgency"] == "EMERGENCY" else None
        flash(f"Request #{rid} raised." + (f" Emergency auto-allocation reserved {got} unit(s)." if got is not None else ""))
    except psycopg.Error as e:
        flash(db_error(e), "error")
    return redirect(url_for("requests_board"))


@app.post("/requests/<int:rid>/<action>")
def request_action(rid, action):
    fn = {"allocate": "allocate_units", "issue": "issue_request", "cancel": "cancel_request"}.get(action) or abort(404)
    try:
        n = q1(f"SELECT {fn}(%s) AS n", rid)["n"]
        flash({"allocate": f"Request #{rid}: reserved {n} unit(s).", "issue": f"Request #{rid}: {n} unit(s) issued to the hospital.",
               "cancel": f"Request #{rid} cancelled; {n} unit(s) returned to stock."}[action])
    except psycopg.Error as e:
        flash(db_error(e), "error")
    return redirect(request.referrer or url_for("requests_board"))


# ------------------------------------------------------------------ design documentation
def render_doc(name):
    html = markdown.markdown((ROOT / "docs" / name).read_text(encoding="utf-8"), extensions=["tables", "fenced_code"])
    return re.sub(r'<pre><code class="language-mermaid">(.*?)</code></pre>',
                  lambda m: f'<pre class="mermaid">{m.group(1)}</pre>', html, flags=re.S)


@app.route("/design")
def design_index():
    return redirect(url_for("design", topic="er"))


@app.route("/design/<topic>")
def design(topic):
    item = next((d for d in DESIGN if d[0] == topic), None) or abort(404)
    body, sql_files, raw = "", [], ""
    if topic == "sql":
        sql_files = [(f.name, f.read_text(encoding="utf-8")) for f in sorted((ROOT / "db").glob("0*.sql"))]
    elif item[2].endswith(".md"):
        body = render_doc(item[2])
    else:
        raw = (ROOT / "docs" / item[2]).read_text(encoding="utf-8")
    cmd = {"indexing": r".venv\Scripts\python scripts\demo_indexing.py", "transactions": r".venv\Scripts\python scripts\demo_transactions.py"}.get(topic)
    return render_template("design.html", topics=DESIGN, topic=topic, item=item, body=body, sql_files=sql_files, raw=raw, cmd=cmd)


# ------------------------------------------------------------------ camps and query lab
@app.route("/camps")
def camps():
    rows = q("SELECT c.camp_id, c.name, c.venue, c.camp_date, p.full_name AS coordinator, "
             "(SELECT count(*) FROM donor_camp dc WHERE dc.camp_id = c.camp_id) AS registered, "
             "count(DISTINCT d.donation_id) AS donations, count(u.unit_id) AS units, "
             "count(DISTINCT d.donation_id) FILTER (WHERE d.screening = 'FAIL') AS failed "
             "FROM camp c JOIN person p ON p.person_id = c.coordinator_id LEFT JOIN donation d ON d.camp_id = c.camp_id "
             "LEFT JOIN blood_unit u ON u.donation_id = d.donation_id GROUP BY c.camp_id, p.full_name ORDER BY c.camp_date DESC")
    return render_template("camps.html", rows=rows)


@app.route("/query-lab")
def query_lab():
    results = []
    for item in QUERIES:
        try:
            rows = q(item["sql"])
            results.append({**item, "rows": rows, "cols": list(rows[0].keys()) if rows else []})
        except psycopg.Error as e:
            results.append({**item, "rows": [], "cols": [], "error": db_error(e)})
    mongo = []
    try:
        for item in MONGO_PIPELINES:
            mongo.append({**item, "rows": list(reports().aggregate(item["pipeline"]))})
    except PyMongoError:
        pass
    for m in mongo:
        m["text"] = json.dumps(m["pipeline"], indent=1, default=str)
    return render_template("query_lab.html", results=results, mongo=mongo)


MONGO_PIPELINES = [
    {"title": "Reactive markers by frequency", "note": "Document model: markers is a nested sub-document, flags an array.",
     "pipeline": [{"$unwind": "$flags"}, {"$group": {"_id": "$flags", "reports": {"$sum": 1}}}, {"$sort": {"reports": -1}}]},
    {"title": "Average haemoglobin by result", "note": "$group over a field the SQL schema does not even have.",
     "pipeline": [{"$group": {"_id": "$result", "avg_hb": {"$avg": "$hb_gdl"}, "n": {"$sum": 1}}},
                  {"$project": {"avg_hb": {"$round": ["$avg_hb", 2]}, "n": 1}}]},
    {"title": "Donors on medication", "note": "Flexible questionnaire: optional fields differ per document.",
     "pipeline": [{"$match": {"questionnaire.on_medication.0": {"$exists": True}}},
                  {"$unwind": "$questionnaire.on_medication"},
                  {"$group": {"_id": "$questionnaire.on_medication", "donors": {"$sum": 1}}}, {"$sort": {"donors": -1}}]},
]


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5057, debug=False)
