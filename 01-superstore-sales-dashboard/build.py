"""
Superstore sales dashboard: clean the raw Kaggle export, then build
  - outputs/superstore_clean.csv        the cleaned data
  - outputs/data_quality_log.csv        every issue found and what was done
  - outputs/Superstore_Sales_Dashboard.xlsx  an Excel dashboard driven by formulas
  - outputs/charts/*.png                charts for the case study page
  - outputs/findings.json               the numbers quoted in the write-up

Run:  ../.venv/bin/python -I build.py
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / "data" / "raw" / "superstore" / "Sample - Superstore.csv"
OUT = HERE / "outputs"
CHARTS = OUT / "charts"
OUT.mkdir(exist_ok=True)
CHARTS.mkdir(exist_ok=True)

# ---------------------------------------------------------------- 1. clean
raw = pd.read_csv(RAW, encoding="latin-1")  # the export is not UTF-8
log = []


def note(issue, rows, action):
    log.append({"Issue": issue, "Rows affected": int(rows), "Action": action})


df = raw.copy()
df["Order Date"] = pd.to_datetime(df["Order Date"], format="%m/%d/%Y")
df["Ship Date"] = pd.to_datetime(df["Ship Date"], format="%m/%d/%Y")
note("Dates stored as text (M/D/YYYY)", len(df), "Converted Order Date and Ship Date to real dates")

short_zip = (df["Postal Code"] < 10000).sum()
df["Postal Code"] = df["Postal Code"].astype(str).str.zfill(5)
note("Postal codes lost their leading zero (e.g. 2108 instead of 02108)", short_zip, "Stored as 5-character text")

dupes = df.drop(columns="Row ID").duplicated()
note("Exact duplicate order line (same order, product, amounts)", dupes.sum(), "Removed the second copy")
df = df[~dupes].copy()

multi_name = df.groupby("Product ID")["Product Name"].nunique()
note(
    "Product IDs used for more than one product name",
    df["Product ID"].isin(multi_name[multi_name > 1].index).sum(),
    f"Kept; flagged. {int((multi_name > 1).sum())} IDs affected. Reports use Sub-Category, not product ID",
)

bad_ship = (df["Ship Date"] < df["Order Date"]).sum()
note("Ship date before order date", bad_ship, "None found" if bad_ship == 0 else "Flagged")
note("Missing values in any column", df.isna().sum().sum(), "None found")
note("Sales of zero or less", (df["Sales"] <= 0).sum(), "None found")
note("Discount outside 0–80%", ((df["Discount"] < 0) | (df["Discount"] > 0.8)).sum(), "None found")
note("Customer names (personal data)", len(df), "Dropped from the workbook; Customer ID is enough for analysis")

df["Ship Days"] = (df["Ship Date"] - df["Order Date"]).dt.days
df["Year"] = df["Order Date"].dt.year
df["Month"] = df["Order Date"].dt.to_period("M").dt.to_timestamp()
BANDS = ["0%", "1–20%", "21–30%", "31–50%", "Over 50%"]
df["Discount Band"] = pd.cut(df["Discount"], [-0.01, 0, 0.2, 0.3, 0.5, 0.8], labels=BANDS)

cols = ["Order ID", "Order Date", "Ship Date", "Ship Mode", "Customer ID", "Segment", "State", "City",
        "Postal Code", "Region", "Product ID", "Category", "Sub-Category", "Product Name",
        "Sales", "Quantity", "Discount", "Profit"]
clean = df[cols + ["Ship Days"]].copy()
clean.to_csv(OUT / "superstore_clean.csv", index=False, date_format="%Y-%m-%d")
pd.DataFrame(log).to_csv(OUT / "data_quality_log.csv", index=False)

# ---------------------------------------------------------------- 2. analysis (pandas = the check on the workbook)
T, P = df["Sales"].sum(), df["Profit"].sum()
orders = df["Order ID"].nunique()
yearly = df.groupby("Year").agg(Sales=("Sales", "sum"), Profit=("Profit", "sum"), Orders=("Order ID", "nunique"))
yearly["Margin"] = yearly["Profit"] / yearly["Sales"]
yearly["AOV"] = yearly["Sales"] / yearly["Orders"]


def by(col):
    g = df.groupby(col, observed=True).agg(Sales=("Sales", "sum"), Profit=("Profit", "sum"), Lines=("Sales", "size"))
    g["Margin"] = g["Profit"] / g["Sales"]
    return g


region, category, subcat, band, state = by("Region"), by("Category"), by("Sub-Category"), by("Discount Band"), by("State")
deep = df[df["Discount"] > 0.2]
cat_disc = df.groupby("Category")["Discount"].mean()
reg_disc = df.groupby("Region")["Discount"].mean()
season = df.groupby(df["Order Date"].dt.month)["Sales"].sum() / T

findings = {
    "period": f"{df['Order Date'].min():%b %Y} – {df['Order Date'].max():%b %Y}",
    "order_lines": len(df), "orders": orders, "customers": df["Customer ID"].nunique(),
    "sales": round(T, 2), "profit": round(P, 2), "margin": round(P / T, 4),
    "sales_growth_2014_2017": round(yearly.loc[2017, "Sales"] / yearly.loc[2014, "Sales"] - 1, 4),
    "aov_2014": round(yearly.loc[2014, "AOV"], 2), "aov_2017": round(yearly.loc[2017, "AOV"], 2),
    "deep_discount_lines": len(deep), "deep_discount_line_share": round(len(deep) / len(df), 4),
    "deep_discount_sales": round(deep["Sales"].sum(), 2), "deep_discount_profit": round(deep["Profit"].sum(), 2),
    "profit_without_deep_discount_lines": round(P - deep["Profit"].sum(), 2),
    "margin_by_band": band["Margin"].round(4).to_dict(),
    "category_margin": category["Margin"].round(4).to_dict(),
    "category_avg_discount": cat_disc.round(4).to_dict(),
    "region_margin": region["Margin"].round(4).to_dict(),
    "region_avg_discount": reg_disc.round(4).to_dict(),
    "loss_subcategories": subcat[subcat["Profit"] < 0]["Profit"].round(2).to_dict(),
    "loss_states_top5": state.sort_values("Profit").head(5)["Profit"].round(2).to_dict(),
    "sep_nov_dec_share": round(season.loc[[9, 11, 12]].sum(), 4),
    "data_quality": log,
}
(OUT / "findings.json").write_text(json.dumps(findings, indent=2, default=str))

# ---------------------------------------------------------------- 3. charts for the case study
INK, ACC, LOSS, MUTED = "#1c1917", "#c2410c", "#b91c1c", "#a8a29e"
plt.rcParams.update({"font.family": "Helvetica", "font.size": 11, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.edgecolor": MUTED, "axes.labelcolor": INK})

m = df.groupby("Month").agg(Sales=("Sales", "sum"), Profit=("Profit", "sum"))
fig, ax = plt.subplots(figsize=(10, 4.2), dpi=160)
ax.plot(m.index, m["Sales"] / 1000, color=INK, lw=2, label="Sales")
ax.plot(m.index, m["Profit"] / 1000, color=ACC, lw=2, label="Profit")
ax.set_ylabel("US$ thousands")
ax.set_title("Monthly sales and profit, 2014–2017", loc="left", fontweight="bold")
ax.legend(frameon=False, loc="upper left")
ax.grid(axis="y", color="#e7e5e4")
fig.tight_layout()
fig.savefig(CHARTS / "monthly-sales-profit.png")
plt.close(fig)

s = subcat.sort_values("Profit")
fig, ax = plt.subplots(figsize=(10, 5.2), dpi=160)
ax.barh(s.index, s["Profit"] / 1000, color=[LOSS if v < 0 else INK for v in s["Profit"]])
ax.axvline(0, color=MUTED, lw=1)
ax.set_xlabel("Profit, US$ thousands")
ax.set_title("Profit by sub-category: three lose money", loc="left", fontweight="bold")
ax.grid(axis="x", color="#e7e5e4")
fig.tight_layout()
fig.savefig(CHARTS / "profit-by-subcategory.png")
plt.close(fig)

fig, ax = plt.subplots(figsize=(10, 4.2), dpi=160)
vals = band["Margin"] * 100
bars = ax.bar(vals.index.astype(str), vals, color=[LOSS if v < 0 else INK for v in vals])
for b_, v in zip(bars, vals):
    ax.annotate(f"{v:.0f}%", (b_.get_x() + b_.get_width() / 2, v), ha="center",
                va="bottom" if v >= 0 else "top", xytext=(0, 4 if v >= 0 else -4), textcoords="offset points")
ax.axhline(0, color=MUTED, lw=1)
ax.set_ylim(vals.min() * 1.15, vals.max() * 1.3)
ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(decimals=0))
ax.set_ylabel("Profit margin")
ax.set_xlabel("Discount on the order line")
ax.set_title("Margin by discount: above 20% every band loses money", loc="left", fontweight="bold")
fig.tight_layout()
fig.savefig(CHARTS / "margin-by-discount.png")
plt.close(fig)

# ---------------------------------------------------------------- 4. Excel dashboard (formulas, so it recalculates)
wb = Workbook()
HEAD = PatternFill("solid", fgColor="1C1917")
SOFT = PatternFill("solid", fgColor="FFF7ED")
WHITE = Font(color="FFFFFF", bold=True)
BOLD = Font(bold=True)
TITLE = Font(bold=True, size=16)
THIN = Border(bottom=Side(style="thin", color="D6D3D1"))
MONEY, PCT, INT = '"$"#,##0', "0.0%", "#,##0"


def header(ws, row, labels, start=1):
    for i, h in enumerate(labels):
        c = ws.cell(row=row, column=start + i, value=h)
        c.fill, c.font = HEAD, WHITE
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def widths(ws, w):
    for i, v in enumerate(w, start=1):
        ws.column_dimensions[get_column_letter(i)].width = v


# --- Data sheet: the cleaned rows + helper columns written as formulas
ws = wb.active
ws.title = "Data"
data_cols = cols + ["Ship Days", "Year", "Month", "Discount Band", "New Order"]
header(ws, 1, data_cols)
L = {c: get_column_letter(i + 1) for i, c in enumerate(data_cols)}
for r, rec in enumerate(clean.itertuples(index=False), start=2):
    for i, v in enumerate(rec):
        ws.cell(row=r, column=i + 1, value=v.to_pydatetime() if isinstance(v, pd.Timestamp) else v)
    od = f"{L['Order Date']}{r}"
    ws[f"{L['Year']}{r}"] = f"=YEAR({od})"
    ws[f"{L['Month']}{r}"] = f"=DATE(YEAR({od}),MONTH({od}),1)"
    d = f"{L['Discount']}{r}"
    ws[f"{L['Discount Band']}{r}"] = (
        f'=IF({d}=0,"0%",IF({d}<=0.2,"1–20%",IF({d}<=0.3,"21–30%",IF({d}<=0.5,"31–50%","Over 50%"))))'
    )
    a = L["Order ID"]
    ws[f"{L['New Order']}{r}"] = f"=IF(COUNTIF(${a}$2:{a}{r},{a}{r})=1,1,0)"
N = len(clean) + 1
for c in ["Order Date", "Ship Date", "Month"]:
    for r in range(2, N + 1):
        ws[f"{L[c]}{r}"].number_format = "yyyy-mm-dd" if c != "Month" else "mmm yyyy"
for c, f in [("Sales", '#,##0.00'), ("Profit", '#,##0.00'), ("Discount", "0%")]:
    for r in range(2, N + 1):
        ws[f"{L[c]}{r}"].number_format = f
ws.freeze_panes = "A2"
ws.auto_filter.ref = f"A1:{get_column_letter(len(data_cols))}{N}"
widths(ws, [16, 11, 11, 14, 11, 11, 14, 14, 9, 9, 16, 15, 13, 40, 10, 8, 8, 10, 8, 6, 10, 11, 8])


def col(name):
    return f"Data!${L[name]}$2:${L[name]}${N}"


SALES, PROFIT, YEAR, NEW = col("Sales"), col("Profit"), col("Year"), col("New Order")
YCRIT = "Dashboard!$C$4"  # "<>" for all years, else the year

# --- Dashboard
db = wb.create_sheet("Dashboard", 0)
db["B1"] = "Superstore sales dashboard"
db["B1"].font = TITLE
db["B2"] = "Pick a year in C3. Every number and chart on this sheet follows it."
db["B3"], db["C3"] = "Year", "All"
db["B3"].font = BOLD
db["C3"].fill = SOFT
dv = DataValidation(type="list", formula1='"All,2014,2015,2016,2017"', allow_blank=False)
db.add_data_validation(dv)
dv.add("C3")
db["B4"], db["C4"] = "(filter used in formulas)", '=IF(C3="All","<>",C3)'
db["B4"].font = Font(color="A8A29E", italic=True, size=9)
db["C4"].font = Font(color="A8A29E", size=9)

kpis = [
    ("Sales", f"=SUMIFS({SALES},{YEAR},{YCRIT})", MONEY),
    ("Profit", f"=SUMIFS({PROFIT},{YEAR},{YCRIT})", MONEY),
    ("Profit margin", "=IFERROR(C7/B7,0)", PCT),
    ("Orders", f"=SUMIFS({NEW},{YEAR},{YCRIT})", INT),
    ("Average order value", "=IFERROR(B7/E7,0)", MONEY),
    ("Profit lost on lines discounted over 20%",
     f'=SUMIFS({PROFIT},{YEAR},{YCRIT},{col("Discount")},">0.2")', MONEY),
]
for i, (label, formula, fmt) in enumerate(kpis):
    c = 2 + i
    db.cell(row=6, column=c, value=label).font = Font(bold=True, color="57534E", size=10)
    db.cell(row=6, column=c).alignment = Alignment(wrap_text=True, vertical="top")
    v = db.cell(row=7, column=c, value=formula)
    v.number_format, v.font, v.fill = fmt, Font(bold=True, size=15), SOFT
db.row_dimensions[6].height = 30
widths(db, [2, 18, 18, 14, 12, 18, 22, 4])
db.conditional_formatting.add("G7", CellIsRule(operator="lessThan", formula=["0"], font=Font(bold=True, size=15, color="B91C1C")))


def summary(ws, top, title, label, keys, key_col):
    ws.cell(row=top, column=2, value=title).font = Font(bold=True, size=12)
    header(ws, top + 1, [label, "Sales", "Profit", "Margin"], start=2)
    for i, k in enumerate(keys):
        r = top + 2 + i
        ws.cell(row=r, column=2, value=k)
        ws.cell(row=r, column=3, value=f'=SUMIFS({SALES},{YEAR},{YCRIT},{col(key_col)},B{r})').number_format = MONEY
        ws.cell(row=r, column=4, value=f'=SUMIFS({PROFIT},{YEAR},{YCRIT},{col(key_col)},B{r})').number_format = MONEY
        ws.cell(row=r, column=5, value=f"=IFERROR(D{r}/C{r},0)").number_format = PCT
        for c in range(2, 6):
            ws.cell(row=r, column=c).border = THIN
    last = top + 1 + len(keys)
    ws.conditional_formatting.add(f"D{top+2}:E{last}", CellIsRule(operator="lessThan", formula=["0"], font=Font(color="B91C1C", bold=True)))
    return top + 2, last


def bar(ws, first, last, value_col, title, anchor, horizontal=False, h=7.5, w=15, fmt='"$"#,##0'):
    ch = BarChart()
    ch.type = "bar" if horizontal else "col"
    ch.title, ch.legend, ch.height, ch.width = title, None, h, w
    ch.add_data(Reference(ws, min_col=value_col, min_row=first - 1, max_row=last), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=2, min_row=first, max_row=last))
    ch.y_axis.numFmt = fmt
    ch.y_axis.delete = False
    ch.x_axis.delete = False
    ws.add_chart(ch, anchor)


f, l = summary(db, 10, "By region", "Region", ["West", "East", "Central", "South"], "Region")
bar(db, f, l, 4, "Profit by region", "G10", h=6.5)
f, l = summary(db, 17, "By category", "Category", ["Technology", "Office Supplies", "Furniture"], "Category")
bar(db, f, l, 5, "Margin by category", "G23", h=6.5, fmt="0%")
f, l = summary(db, 23, "By discount on the line", "Discount band", BANDS, "Discount Band")
bar(db, f, l, 5, "Margin by discount band", "G36", h=6.5, fmt="0%")

# --- Sub-category sheet
sc = wb.create_sheet("Sub-Category", 1)
order = subcat.sort_values("Profit").index.tolist()
f, l = summary(sc, 1, "Profit by sub-category (follows the Dashboard year)", "Sub-Category", order, "Sub-Category")
bar(sc, f, l, 4, "Profit by sub-category", "G2", horizontal=True, h=11, w=16)
widths(sc, [2, 16, 14, 14, 10])

# --- States sheet
stw = wb.create_sheet("States", 2)
order = state.sort_values("Profit").index.tolist()
summary(stw, 1, "Profit by state, worst first at build time (follows the Dashboard year)", "State", order, "State")
widths(stw, [2, 20, 14, 14, 10])

# --- Monthly sheet
mo = wb.create_sheet("Monthly", 3)
mo["B1"] = "Monthly trend (all years)"
mo["B1"].font = Font(bold=True, size=12)
header(mo, 2, ["Month", "Sales", "Profit", "Margin"], start=2)
months = sorted(df["Month"].unique())
MONTH = col("Month")
for i, mth in enumerate(months):
    r = 3 + i
    mo.cell(row=r, column=2, value=pd.Timestamp(mth).to_pydatetime()).number_format = "mmm yyyy"
    mo.cell(row=r, column=3, value=f"=SUMIFS({SALES},{MONTH},B{r})").number_format = MONEY
    mo.cell(row=r, column=4, value=f"=SUMIFS({PROFIT},{MONTH},B{r})").number_format = MONEY
    mo.cell(row=r, column=5, value=f"=IFERROR(D{r}/C{r},0)").number_format = PCT
lm = 2 + len(months)
lc = LineChart()
lc.title, lc.height, lc.width = "Monthly sales and profit", 8, 22
lc.add_data(Reference(mo, min_col=3, max_col=4, min_row=2, max_row=lm), titles_from_data=True)
lc.set_categories(Reference(mo, min_col=2, min_row=3, max_row=lm))
lc.x_axis.number_format = "mmm yy"
lc.y_axis.numFmt = '"$"#,##0'
lc.x_axis.delete = False
lc.y_axis.delete = False
mo.add_chart(lc, "G2")
widths(mo, [2, 12, 14, 14, 10])

# --- Definitions + data quality + how to update
gd = wb.create_sheet("Read me", 0)
rows = [
    ("Superstore sales dashboard", None),
    ("Practice project on public data: the Kaggle 'Superstore Dataset' (Tableau sample data). Not client work.", None),
    ("", None),
    ("How to update", None),
    ("1. Paste new order lines under the last row of the Data sheet, columns A–S, in the same order.", None),
    ("2. Copy the formulas in columns T–W (Year, Month, Discount Band, New Order) down to the new rows.", None),
    ("3. Every total on the Dashboard, Sub-Category, States and Monthly sheets recalculates. For new months, add a row to Monthly.", None),
    ("", None),
    ("Definitions", None),
    ("Sales", "Order line revenue after discount, in US dollars."),
    ("Profit", "Order line profit after discount, as recorded in the source data."),
    ("Profit margin", "Profit ÷ Sales for the same lines."),
    ("Orders", "Distinct Order IDs (the New Order column marks the first line of each order)."),
    ("Average order value", "Sales ÷ Orders."),
    ("Discount band", "The discount on the order line: 0%, 1–20%, 21–30%, 31–50%, over 50%."),
    ("Profit lost on lines discounted over 20%", "Sum of profit on lines with a discount above 20%. Negative = money lost."),
    ("", None),
    ("Data quality: what was found and fixed", None),
]
for i, (a, b) in enumerate(rows, start=1):
    gd.cell(row=i, column=2, value=a)
    if b:
        gd.cell(row=i, column=3, value=b)
for r in (1,):
    gd.cell(row=r, column=2).font = TITLE
for r in (4, 9, 18):
    gd.cell(row=r, column=2).font = Font(bold=True, size=12)
for r in range(10, 17):
    gd.cell(row=r, column=2).font = BOLD
q0 = len(rows) + 1
header(gd, q0, ["Issue", "Rows affected", "Action"], start=2)
for i, item in enumerate(log, start=q0 + 1):
    gd.cell(row=i, column=2, value=item["Issue"])
    gd.cell(row=i, column=3, value=item["Rows affected"]).number_format = INT
    gd.cell(row=i, column=4, value=item["Action"])
widths(gd, [2, 52, 60, 70])
for row in gd.iter_rows(min_row=1, max_row=gd.max_row):
    for c in row:
        c.alignment = Alignment(wrap_text=True, vertical="top")

wb.active = wb.sheetnames.index("Dashboard")
wb.save(OUT / "Superstore_Sales_Dashboard.xlsx")

# ---------------------------------------------------------------- 5. print the check figures
print(json.dumps({k: v for k, v in findings.items() if k != "data_quality"}, indent=2, default=str))
print(pd.DataFrame(log).to_string(index=False))
