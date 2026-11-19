"""Independent check: rebuilds the headline numbers in SQL (SQLite) straight from
the raw CSV and compares them with outputs/. Run: ../.venv/bin/python -I check.py"""
import csv, json, re, sqlite3, sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / "data" / "raw" / "online-retail" / "online_retail_II.csv"
F = json.loads((HERE / "outputs" / "findings.json").read_text())
seg = pd.read_csv(HERE / "outputs" / "customer_segments.csv")
ret = pd.read_csv(HERE / "outputs" / "cohort_retention.csv", index_col=0)

NONPRODUCT = re.compile(r"^(POST|DOT|M|C2|D|S|BANK CHARGES|ADJUST\d*|AMAZONFEE|PADS|CRUK|B|TEST\d*|gift_.*)$", re.I)
db = sqlite3.connect(":memory:")
db.create_function("nonprod", 1, lambda s: 1 if NONPRODUCT.match(s or "") else 0)
db.execute("CREATE TABLE raw (inv TEXT, code TEXT, descr TEXT, qty INT, dt TEXT, price REAL, cust TEXT, country TEXT)")
with open(RAW, newline="", encoding="utf-8") as f:
    r = csv.reader(f); next(r)
    db.executemany("INSERT INTO raw VALUES (?,?,?,?,?,?,?,?)",
                   ((a, b, c, int(d), e, float(g), (h.split(".")[0] if h else None), i) for a, b, c, d, e, g, h, i in r))
db.executescript("""
CREATE TABLE dedup AS SELECT DISTINCT * FROM raw;
CREATE TABLE sales AS SELECT *, qty*price AS rev, substr(dt,1,7) AS ym FROM dedup
  WHERE inv NOT LIKE 'A%' AND inv NOT LIKE 'C%' AND qty > 0 AND price > 0 AND nonprod(code) = 0;
""")
q = lambda s: db.execute(s).fetchone()
checks = []
def chk(name, got, want, tol=0.0001):
    ok = abs(got - want) <= tol * max(1, abs(want))
    checks.append((name, got, want, ok))

chk("Clean sales lines", q("SELECT count(*) FROM sales")[0], F["clean_sales_lines"])
chk("Total revenue (£)", q("SELECT sum(rev) FROM sales")[0], F["revenue_total"])
chk("Revenue share with no customer ID", q("SELECT sum(CASE WHEN cust IS NULL THEN rev END)/sum(rev) FROM sales")[0], F["revenue_no_customer_id_share"], 0.001)
chk("Customers", q("SELECT count(DISTINCT cust) FROM sales WHERE cust IS NOT NULL")[0], F["customers_total"])
chk("UK revenue share", q("SELECT sum(CASE WHEN country='United Kingdom' THEN rev END)/sum(rev) FROM sales")[0], F["uk_revenue_share"], 0.001)
chk("Cancelled product value (£)", -q("SELECT sum(qty*price) FROM dedup WHERE inv LIKE 'C%' AND nonprod(code)=0")[0], F["cancellation_value_products"])

# RFM inputs for the last 12 months, per customer
db.executescript("""
CREATE TABLE yr AS SELECT * FROM sales WHERE cust IS NOT NULL AND dt >= '2010-12-10';
CREATE TABLE rfm AS SELECT cust, julianday('2011-12-10') - julianday(max(dt)) AS rec_raw,
  count(DISTINCT inv) AS freq, sum(rev) AS mon FROM yr GROUP BY cust;
""")
chk("RFM customers", q("SELECT count(*) FROM rfm")[0], F["rfm_customers"])
chk("RFM revenue (£)", q("SELECT sum(mon) FROM rfm")[0], F["rfm_revenue"])
sql = pd.read_sql("SELECT cust, CAST(rec_raw AS INT) AS rec, freq, mon FROM rfm", db).astype({"cust": int}).set_index("cust")
mine = seg.set_index("Customer ID")
both = sql.join(mine, how="inner")
chk("Per-customer frequency matches (customers)", int((both["freq"] == both["Frequency"]).sum()), len(sql))
chk("Per-customer spend matches (customers)", int(((both["mon"] - both["Monetary"]).abs() < 0.01).sum()), len(sql))
chk("Per-customer recency matches (customers)", int((both["rec"] == both["Recency"]).sum()), len(sql))
chk("One-order customers share", q("SELECT avg(freq = 1) FROM rfm")[0], F["one_order_customers_share"], 0.001)

# segment rule covers every R x F cell exactly once, and matches the file
def segment(r, f):
    if r == 5 and f >= 4: return "Champions"
    if r >= 3 and f >= 4: return "Loyal"
    if r >= 4 and f in (2, 3): return "Potential loyalists"
    if r == 5 and f == 1: return "New"
    if r == 4 and f == 1: return "Promising"
    if r == 3 and f == 3: return "Need attention"
    if r == 3 and f <= 2: return "About to sleep"
    if r <= 2 and f == 5: return "Can't lose"
    if r <= 2 and f in (3, 4): return "At risk"
    return "Hibernating"
chk("Segment matches R/F scores (customers)", int(sum(segment(r, f) == s for r, f, s in zip(seg.R, seg.F, seg.Segment))), len(seg))
chk("Scores split into fifths (R)", seg.R.value_counts().max() - seg.R.value_counts().min(), 0, 1)

# cohort retention from SQL for a few cells
db.executescript("""
CREATE TABLE cm AS SELECT DISTINCT cust, ym FROM sales WHERE cust IS NOT NULL AND ym < '2011-12';
CREATE TABLE coh AS SELECT cust, min(ym) AS c FROM cm GROUP BY cust;
""")
def cell(cohort, age):
    y, m = map(int, cohort.split("-")); m += age; y += (m - 1) // 12; m = (m - 1) % 12 + 1
    tgt = f"{y}-{m:02d}"
    n = q(f"SELECT count(*) FROM coh WHERE c='{cohort}'")[0]
    k = q(f"SELECT count(*) FROM coh JOIN cm USING (cust) WHERE c='{cohort}' AND ym='{tgt}'")[0]
    return k / n
for c, a in [("2010-01", 1), ("2010-03", 3), ("2010-11", 12), ("2011-06", 2), ("2011-10", 1)]:
    chk(f"Retention {c} +{a} months", cell(c, a), ret.loc[c, str(a)], 0.001)

for n, g, w, ok in checks:
    print(f"{'OK' if ok else 'MISMATCH':8} {n:44} sql={g!s:>16} build={w!s:>16}")
bad = [c for c in checks if not c[3]]
print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed")
sys.exit(1 if bad else 0)
