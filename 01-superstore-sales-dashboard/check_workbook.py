"""Independent check of the dashboard formulas: evaluates the SUMIFS / IFERROR /
helper-column formulas used in the workbook against the Data sheet, then compares
with the pandas figures in outputs/findings.json. Run: ../.venv/bin/python -I check_workbook.py"""
import json, re, sys
from pathlib import Path
import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

HERE = Path(__file__).resolve().parent
wb = load_workbook(HERE / "outputs" / "Superstore_Sales_Dashboard.xlsx")
F = json.loads((HERE / "outputs" / "findings.json").read_text())
data = wb["Data"]
hdr = [c.value for c in data[1]]
rows = list(data.iter_rows(min_row=2, values_only=True))
df = pd.DataFrame(rows, columns=hdr)
L = {c: i for i, c in enumerate(hdr)}

# helper columns: evaluate the formula text of row 2 and the last row, then apply its logic to all rows
f_year, f_month, f_band, f_new = (data.cell(row=2, column=L[c] + 1).value for c in ["Year", "Month", "Discount Band", "New Order"])
assert f_year == "=YEAR(B2)" and f_month == "=DATE(YEAR(B2),MONTH(B2),1)", (f_year, f_month)
assert f_new == "=IF(COUNTIF($A$2:A2,A2)=1,1,0)", f_new
assert data.cell(row=len(rows) + 1, column=L["New Order"] + 1).value == f"=IF(COUNTIF($A$2:A{len(rows)+1},A{len(rows)+1})=1,1,0)"
df["Year"] = pd.to_datetime(df["Order Date"]).dt.year
df["Month"] = pd.to_datetime(df["Order Date"]).dt.to_period("M").dt.to_timestamp()
def band(d):  # mirrors the IF chain in the Discount Band formula
    return "0%" if d == 0 else "1–20%" if d <= 0.2 else "21–30%" if d <= 0.3 else "31–50%" if d <= 0.5 else "Over 50%"
assert f_band == '=IF(Q2=0,"0%",IF(Q2<=0.2,"1–20%",IF(Q2<=0.3,"21–30%",IF(Q2<=0.5,"31–50%","Over 50%"))))', f_band
df["Discount Band"] = df["Discount"].map(band)
df["New Order"] = (~df["Order ID"].duplicated()).astype(int)
letter = {chr(65 + i) if i < 26 else "A" + chr(65 + i - 26): c for i, c in enumerate(hdr)}

def series(ref):
    m = re.fullmatch(r"Data!\$([A-Z]+)\$2:\$([A-Z]+)\$(\d+)", ref)
    assert m and m.group(1) == m.group(2) and int(m.group(3)) == len(rows) + 1, ref
    return df[hdr[column_index_from_string(m.group(1)) - 1]]

def crit_mask(s, crit):
    if crit == "<>": return s.notna()
    if isinstance(crit, str) and crit.startswith(">"): return s > float(crit[1:])
    return s == crit

def ev(ws, ref, year):
    v = ws[ref].value
    if not (isinstance(v, str) and v.startswith("=")): return v
    if v == '=IF(C3="All","<>",C3)': return "<>" if year == "All" else year
    m = re.fullmatch(r"=IFERROR\(([A-Z]+\d+)/([A-Z]+\d+),0\)", v)
    if m:
        b = ev(ws, m.group(2), year); return 0 if not b else ev(ws, m.group(1), year) / b
    m = re.fullmatch(r"=SUMIFS\((.+)\)", v)
    assert m, v
    args = [a.strip() for a in m.group(1).split(",")]
    total = series(args[0]); mask = pd.Series(True, index=df.index)
    for rng, c in zip(args[1::2], args[2::2]):
        if c == "Dashboard!$C$4": c = ev(wb["Dashboard"], "C4", year)
        elif c.startswith('"'): c = c.strip('"')
        elif re.fullmatch(r"[A-Z]+\d+", c): c = ws[c].value
        mask &= crit_mask(series(rng), c)
    return float(total[mask].sum())

db = wb["Dashboard"]
checks = []
def chk(name, got, want, tol=0.01):
    ok = abs(got - want) <= tol * max(1, abs(want)) / 100
    checks.append((name, round(got, 4), round(want, 4), "OK" if ok else "MISMATCH"))

chk("Sales (All)", ev(db, "B7", "All"), F["sales"])
chk("Profit (All)", ev(db, "C7", "All"), F["profit"])
chk("Margin (All)", ev(db, "D7", "All"), F["margin"], tol=1)
chk("Orders (All)", ev(db, "E7", "All"), F["orders"])
chk("Deep-discount profit (All)", ev(db, "G7", "All"), F["deep_discount_profit"])
raw = pd.read_csv(HERE.parent / "data/raw/superstore/Sample - Superstore.csv", encoding="latin-1").drop_duplicates(subset=None)
raw = raw[~raw.drop(columns="Row ID").duplicated()]
raw["Y"] = pd.to_datetime(raw["Order Date"], format="%m/%d/%Y").dt.year
r17 = raw[raw.Y == 2017]
chk("Sales (2017)", ev(db, "B7", 2017), r17.Sales.sum())
chk("Orders (2017)", ev(db, "E7", 2017), r17["Order ID"].nunique())
for r in range(12, 16):
    k = db[f"B{r}"].value; chk(f"Region {k} margin", ev(db, f"E{r}", "All"), F["region_margin"][k], tol=1)
for r in range(19, 22):
    k = db[f"B{r}"].value; chk(f"Category {k} margin", ev(db, f"E{r}", "All"), F["category_margin"][k], tol=1)
for r in range(25, 30):
    k = db[f"B{r}"].value; chk(f"Band {k} margin", ev(db, f"E{r}", "All"), F["margin_by_band"][k], tol=1)
sc = wb["Sub-Category"]
for r in range(3, 6):
    k = sc[f"B{r}"].value
    if k in F["loss_subcategories"]: chk(f"Sub-cat {k} profit", ev(sc, f"D{r}", "All"), F["loss_subcategories"][k])
st = wb["States"]
for r in range(3, 8):
    k = st[f"B{r}"].value; chk(f"State {k} profit", ev(st, f"D{r}", "All"), F["loss_states_top5"][k])
mo = wb["Monthly"]
monthly_total = sum(ev(mo, f"C{r}", "All") for r in range(3, 3 + 48))
chk("Monthly sales add up to total", monthly_total, F["sales"])
for c in checks: print(f"{c[3]:8} {c[0]:32} workbook={c[1]:>14} pandas={c[2]:>14}")
bad = [c for c in checks if c[3] != "OK"]
print(f"\n{len(checks) - len(bad)}/{len(checks)} checks passed")
sys.exit(1 if bad else 0)
