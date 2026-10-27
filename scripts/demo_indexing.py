"""Index demo: B+ tree vs hash vs no index, measured with EXPLAIN ANALYZE on a 400k-row scratch table.
Runs in the hemogrid_demo clone (create it first with demo_transactions.py) and saves docs/indexing_demo.txt."""
import io, pathlib, re, sys
import psycopg

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from config import PG_DSN

out = io.StringIO()


def say(m=""):
    print(m)
    out.write(m + "\n")


c = psycopg.connect(PG_DSN.replace("dbname=hemogrid", "dbname=hemogrid_demo"), autocommit=True)
c.execute("DROP TABLE IF EXISTS unit_big")
c.execute("""CREATE TABLE unit_big AS
  SELECT g AS unit_id, 'HG' || lpad(g::text, 8, '0') AS barcode,
         (ARRAY['O+','B+','A+','AB+','O-','B-','A-','AB-'])[1 + ((g * 7919) % 8)::int] AS blood_group,
         (ARRAY['PRBC','PLASMA','PLT'])[1 + ((g * 31) % 3)::int] AS component,
         current_date + (((g * 104729) % 400)::int - 300) AS expiry_date,
         CASE WHEN g % 5 = 0 THEN 'AVAILABLE' ELSE 'EXPIRED' END AS status
  FROM generate_series(1::bigint, 400000::bigint) g""")
c.execute("ANALYZE unit_big")

FEFO = ("SELECT unit_id FROM unit_big WHERE blood_group='O-' AND component='PRBC' AND status='AVAILABLE' "
        "ORDER BY expiry_date LIMIT 5")
BARCODE = "SELECT * FROM unit_big WHERE barcode='HG00271828'"
RANGE = "SELECT count(*) FROM unit_big WHERE expiry_date BETWEEN current_date AND current_date + 7"


def explain(sql, label):
    rows = [r[0] for r in c.execute("EXPLAIN (ANALYZE, BUFFERS OFF, COSTS OFF, TIMING OFF) " + sql)]
    used = next((r.strip() for r in rows if "Index" in r or "Seq Scan" in r), rows[0].strip()).lstrip("-> ")
    ms = float(re.search(r"Execution Time: ([\d.]+)", "\n".join(rows)).group(1))
    say(f"   {label:<34} {ms:>8.3f} ms   {used}")
    return ms


say("== Indexing, measured on 400,000 unit rows (scratch table unit_big) ==\n")
say("Q1  FEFO lookup (the allocate_units query shape): group + component + AVAILABLE, soonest expiry")
a = explain(FEFO, "no index")
c.execute("CREATE INDEX ix_big_fefo ON unit_big (blood_group, component, expiry_date) WHERE status = 'AVAILABLE'")
c.execute("ANALYZE unit_big")
b = explain(FEFO, "B+ tree (partial, composite)")
say(f"   -> {a / b:,.0f}x faster. The index is ordered on expiry inside each (group, component), so LIMIT 5 reads 5 entries, no sort.\n")

say("Q2  Barcode scan: equality lookup on one unit")
a = explain(BARCODE, "no index")
c.execute("CREATE INDEX ix_big_bc_btree ON unit_big USING btree (barcode)")
bt = explain(BARCODE, "B+ tree")
c.execute("DROP INDEX ix_big_bc_btree")
c.execute("CREATE INDEX ix_big_bc_hash ON unit_big USING hash (barcode)")
h = explain(BARCODE, "hash")
say(f"   -> both beat a full scan by ~{a / max(bt, h):,.0f}x; hash is O(1) but supports equality only.\n")

say("Q3  Range query: units expiring in the next 7 days")
c.execute("DROP INDEX ix_big_fefo")
explain(RANGE, "no index")
c.execute("CREATE INDEX ix_big_exp_hash ON unit_big USING hash (expiry_date)")
c.execute("ANALYZE unit_big")
explain(RANGE, "hash on expiry_date")
c.execute("DROP INDEX ix_big_exp_hash")
c.execute("CREATE INDEX ix_big_exp ON unit_big (expiry_date)")
c.execute("ANALYZE unit_big")
explain(RANGE, "B+ tree on expiry_date")
say("   -> a hash index cannot serve BETWEEN (the planner ignores it); ordered leaves chain left-to-right, so ranges are cheap.\n")
c.execute("DROP INDEX ix_big_bc_hash")
c.execute("CREATE INDEX ix_big_fefo ON unit_big (blood_group, component, expiry_date) WHERE status = 'AVAILABLE'")

say("Index sizes")
for name, in c.execute("SELECT indexrelid::regclass::text FROM pg_index WHERE indrelid='unit_big'::regclass ORDER BY 1"):
    size = c.execute("SELECT pg_size_pretty(pg_relation_size(%s::regclass))", (name,)).fetchone()[0]
    say(f"   {name:<16} {size}")
say(f"   table unit_big    {c.execute('SELECT pg_size_pretty(pg_relation_size(%s::regclass))', ('unit_big',)).fetchone()[0]}")
(ROOT / "docs" / "indexing_demo.txt").write_text(out.getvalue(), encoding="utf-8")
