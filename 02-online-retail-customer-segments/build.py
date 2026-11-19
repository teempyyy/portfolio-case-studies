"""
Online Retail II: who are the best customers, who is slipping away, and do new
customers come back? Cleans the raw Kaggle CSV, then builds
  - outputs/customer_segments.csv     one row per customer: R, F, M, scores, segment
  - outputs/segment_summary.csv       customers, revenue and averages per segment
  - outputs/cohort_retention.csv      % of each monthly cohort still buying N months later
  - outputs/data_quality_log.csv      every issue found and what was done
  - outputs/findings.json             the numbers quoted in the write-up
  - outputs/charts/*.png              charts for the case study page and the owner summary

Run:  ../.venv/bin/python -I build.py
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / "data" / "raw" / "online-retail" / "online_retail_II.csv"
OUT = HERE / "outputs"
CHARTS = OUT / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- 1. clean
raw = pd.read_csv(RAW, dtype={"Invoice": str, "StockCode": str, "Customer ID": "float64"})
raw["InvoiceDate"] = pd.to_datetime(raw["InvoiceDate"])
log = []


def note(issue, rows, action):
    log.append({"Issue": issue, "Rows affected": int(rows), "Action": action})


df = raw.copy()
note("Rows in the raw file", len(df), "Starting point")

d = df.duplicated()
note("Exact duplicate rows", d.sum(), "Removed")
df = df[~d]

adj = df["Invoice"].str.startswith("A")
note("Bad-debt adjustment invoices (start with A)", adj.sum(), "Removed: accounting entries, not sales")
df = df[~adj]

cancel = df["Invoice"].str.startswith("C")
cancels = df[cancel].copy()
note("Cancellation lines (invoice starts with C)", cancel.sum(), "Kept aside: reported as cancellations, not counted as sales")
df = df[~cancel]

bad = (df["Quantity"] <= 0) | (df["Price"] <= 0)
note("Non-cancelled lines with quantity or price of zero or less", bad.sum(), "Removed: stock write-offs and free lines")
df = df[~bad]

NONPRODUCT = r"^(POST|DOT|M|C2|D|S|BANK CHARGES|ADJUST\d*|AMAZONFEE|PADS|CRUK|B|TEST\d*|gift_.*)$"
nonprod = df["StockCode"].str.match(NONPRODUCT, case=False)
note("Postage, fees, manual and test lines (non-product stock codes)", nonprod.sum(),
     "Removed from product sales: POST, DOT, M, C2, BANK CHARGES, AMAZONFEE, gift vouchers and similar")
df = df[~nonprod]

df["Revenue"] = df["Quantity"] * df["Price"]
no_id = df["Customer ID"].isna()
note("Sales lines with no customer ID", no_id.sum(),
     f"Kept in total sales ({df.loc[no_id, 'Revenue'].sum() / df['Revenue'].sum():.1%} of revenue); left out of customer analysis")
note("Customer IDs stored as decimals (13085.0)", (~no_id).sum(), "Converted to whole numbers")
df["Customer ID"] = df["Customer ID"].astype("Int64")
note("Clean sales lines", len(df), "Used for the analysis")

cust = df[~no_id].copy()
cust["Month"] = cust["InvoiceDate"].dt.to_period("M")

# ---------------------------------------------------------------- 2. RFM on the last 12 months
SNAPSHOT = cust["InvoiceDate"].max().normalize() + pd.Timedelta(days=1)  # day after the last sale
START = SNAPSHOT - pd.DateOffset(years=1)
yr = cust[cust["InvoiceDate"] >= START]
rfm = yr.groupby("Customer ID").agg(
    LastPurchase=("InvoiceDate", "max"), Frequency=("Invoice", "nunique"), Monetary=("Revenue", "sum"))
rfm["Recency"] = (SNAPSHOT - rfm["LastPurchase"]).dt.days


def score(s, ascending):
    # quintiles on rank, so ties never stop the split; 5 = best
    r = s.rank(method="first", ascending=ascending)
    return pd.qcut(r, 5, labels=[1, 2, 3, 4, 5]).astype(int)


rfm["R"] = score(rfm["Recency"], ascending=False)  # fewer days since last purchase = higher score
rfm["F"] = score(rfm["Frequency"], ascending=True)
rfm["M"] = score(rfm["Monetary"], ascending=True)


def segment(r, f):
    # the common R × F segment map
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


rfm["Segment"] = [segment(r, f) for r, f in zip(rfm["R"], rfm["F"])]
ORDER = ["Champions", "Loyal", "Potential loyalists", "New", "Promising", "Need attention",
         "About to sleep", "At risk", "Can't lose", "Hibernating"]
ACTION = {
    "Champions": "Reward them; ask for reviews and referrals; first look at new products",
    "Loyal": "Upsell bundles and higher-value items; loyalty pricing",
    "Potential loyalists": "Membership or volume-discount offer to lock in a second habit",
    "New": "Welcome series; make the second order easy",
    "Promising": "Show best sellers; small time-limited offer",
    "Need attention": "Personal check-in; recommend based on what they bought",
    "About to sleep": "Reminder with popular items before they lapse",
    "At risk": "Win-back email with a reason to return; ask what changed",
    "Can't lose": "Call or email personally; these were big, frequent buyers",
    "Hibernating": "Low-cost reactivation only; don't spend much here",
}
seg = rfm.groupby("Segment").agg(Customers=("Recency", "size"), Revenue=("Monetary", "sum"),
                                 AvgRecencyDays=("Recency", "mean"), AvgOrders=("Frequency", "mean"),
                                 AvgSpend=("Monetary", "mean")).reindex(ORDER).dropna(how="all")
seg["CustomerShare"] = seg["Customers"] / seg["Customers"].sum()
seg["RevenueShare"] = seg["Revenue"] / seg["Revenue"].sum()
seg["Suggested action"] = seg.index.map(ACTION)
seg.round(4).to_csv(OUT / "segment_summary.csv")
rfm.reset_index().assign(LastPurchase=lambda x: x["LastPurchase"].dt.date).to_csv(OUT / "customer_segments.csv", index=False)

# ---------------------------------------------------------------- 3. cohort retention (all full months)
full = cust[cust["Month"] < pd.Period("2011-12", "M")]  # Dec 2011 has only 9 days
first = full.groupby("Customer ID")["Month"].min().rename("Cohort")
full = full.join(first, on="Customer ID")
full["Age"] = (full["Month"] - full["Cohort"]).apply(lambda p: p.n)
active = full.groupby(["Cohort", "Age"])["Customer ID"].nunique().unstack(fill_value=0)
size = active[0]
ret = active.div(size, axis=0)
# a cell exists only if that many months have been observed for the cohort
last = pd.Period("2011-11", "M")
for c in ret.index:
    for a in ret.columns:
        if (c + a) > last:
            ret.loc[c, a] = np.nan
ret.index = ret.index.astype(str)
ret.round(4).to_csv(OUT / "cohort_retention.csv")
# The data starts in Dec 2009, so that "cohort" is everyone already buying then,
# not new customers. It is shown on the chart but left out of new-customer figures.
first_month = ret.index[0]
new = ret.iloc[1:]
m1 = new[1].dropna()
m3 = new[3].dropna()
cohorts_12 = new[new[12].notna()]

# ---------------------------------------------------------------- 4. headline numbers
monthly = df.groupby(df["InvoiceDate"].dt.to_period("M")).agg(Revenue=("Revenue", "sum"))
monthly_c = cust.groupby("Month")["Customer ID"].nunique()
cprod = cancels[~cancels["StockCode"].str.match(NONPRODUCT, case=False)]
cancel_value = -(cprod["Quantity"] * cprod["Price"]).sum()
top20 = rfm["Monetary"].sort_values(ascending=False)
top20_share = top20.head(int(round(len(top20) * 0.2))).sum() / top20.sum()
one_order = (rfm["Frequency"] == 1).mean()

findings = {
    "period": f"{df['InvoiceDate'].min():%d %b %Y} – {df['InvoiceDate'].max():%d %b %Y}",
    "currency": "GBP",
    "raw_rows": len(raw), "clean_sales_lines": len(df),
    "revenue_total": round(df["Revenue"].sum(), 2),
    "revenue_no_customer_id_share": round(df.loc[no_id, "Revenue"].sum() / df["Revenue"].sum(), 4),
    "customers_total": int(cust["Customer ID"].nunique()),
    "countries": int(df["Country"].nunique()),
    "uk_revenue_share": round(df.loc[df["Country"] == "United Kingdom", "Revenue"].sum() / df["Revenue"].sum(), 4),
    "cancellation_lines": int(len(cancels)), "cancellation_product_lines": int(len(cprod)),
    "cancellation_value_products": round(cancel_value, 2),
    "cancellation_share_of_product_sales": round(cancel_value / df["Revenue"].sum(), 4),
    "rfm_window": f"{START:%d %b %Y} – {SNAPSHOT - pd.Timedelta(days=1):%d %b %Y}",
    "rfm_customers": int(len(rfm)), "rfm_revenue": round(rfm["Monetary"].sum(), 2),
    "top20pct_customers_revenue_share": round(top20_share, 4),
    "one_order_customers_share": round(one_order, 4),
    "segments": seg[["Customers", "Revenue", "CustomerShare", "RevenueShare", "AvgRecencyDays", "AvgOrders", "AvgSpend"]].round(4).to_dict(orient="index"),
    "new_cohorts": f"{new.index[0]} – {new.index[-1]}",
    "month1_retention_median_new": round(m1.median(), 4),
    "month1_retention_range_new": [round(m1.min(), 4), round(m1.max(), 4)],
    "month3_retention_median_new": round(m3.median(), 4),
    "month12_retention_median_new": round(cohorts_12[12].median(), 4),
    "month12_cohorts_counted": len(cohorts_12),
    "existing_customers_dec2009": int(size.iloc[0]),
    "existing_customers_dec2009_month12": round(ret.loc[first_month, 12], 4),
    "median_new_customers_per_month": int(size.iloc[1:].median()),
    "peak_month_revenue": str(monthly["Revenue"].idxmax()),
    "data_quality": log,
}
(OUT / "findings.json").write_text(json.dumps(findings, indent=2, default=str))
pd.DataFrame(log).to_csv(OUT / "data_quality_log.csv", index=False)

# ---------------------------------------------------------------- 5. charts
INK, ACC, LOSS, MUTED, SOFT = "#1c1917", "#c2410c", "#b91c1c", "#a8a29e", "#e7e5e4"
plt.rcParams.update({"font.family": "Helvetica", "font.size": 11, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.edgecolor": MUTED, "axes.labelcolor": INK})

s = seg.iloc[::-1]
fig, ax = plt.subplots(figsize=(10, 5.4), dpi=160)
y = np.arange(len(s))
ax.barh(y + 0.2, s["CustomerShare"] * 100, height=0.4, color=MUTED, label="Share of customers")
ax.barh(y - 0.2, s["RevenueShare"] * 100, height=0.4, color=INK, label="Share of revenue")
for yi, v in zip(y, s["RevenueShare"] * 100):
    ax.annotate(f"{v:.0f}%" if v >= 1 else "<1%", (v, yi - 0.2), xytext=(4, 0), textcoords="offset points", va="center", fontsize=9)
ax.set_yticks(y, s.index)
ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(decimals=0))
ax.set_title("Customer segments: share of customers vs share of revenue (last 12 months)", loc="left", fontweight="bold")
ax.legend(frameon=False, loc="lower right")
ax.grid(axis="x", color=SOFT)
fig.tight_layout()
fig.savefig(CHARTS / "segments-revenue-share.png")
plt.close(fig)

h = ret.loc[:, 0:12] * 100
fig, ax = plt.subplots(figsize=(10, 7.2), dpi=160)
im = ax.imshow(h.values, cmap="Oranges", vmin=0, vmax=50, aspect="auto")
for i in range(h.shape[0]):
    for j in range(h.shape[1]):
        v = h.values[i, j]
        if not np.isnan(v):
            ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=7.5,
                    color="white" if v >= 35 else INK)
ax.set_xticks(range(h.shape[1]), [str(c) for c in h.columns])
ax.set_yticks(range(h.shape[0]), [f"{i} (existing)" if i == first_month else i for i in h.index])
ax.set_xlabel("Months since first purchase")
ax.set_ylabel("First-purchase month")
ax.set_title("Cohort retention: % of each month's new customers who buy again", loc="left", fontweight="bold")
ax.spines[:].set_visible(False)
fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02, format=matplotlib.ticker.PercentFormatter(decimals=0))
fig.tight_layout()
fig.savefig(CHARTS / "cohort-retention.png")
plt.close(fig)

mfull = monthly.loc[:pd.Period("2011-11", "M")]
fig, ax = plt.subplots(figsize=(10, 4.2), dpi=160)
x = mfull.index.to_timestamp()
ax.bar(x, mfull["Revenue"] / 1000, width=20, color=INK)
ax.set_ylabel("Revenue, £ thousands")
ax2 = ax.twinx()
ax2.plot(x, monthly_c.loc[mfull.index].values, color=ACC, lw=2, marker="o", ms=3)
ax2.set_ylabel("Active customers", color=ACC)
ax2.spines["right"].set_visible(True)
ax2.spines["top"].set_visible(False)
ax.set_title("Monthly revenue and active customers, Dec 2009 – Nov 2011", loc="left", fontweight="bold")
ax.grid(axis="y", color=SOFT)
fig.tight_layout()
fig.savefig(CHARTS / "monthly-revenue-customers.png")
plt.close(fig)

print(json.dumps({k: v for k, v in findings.items() if k not in ("data_quality",)}, indent=2, default=str))
print(pd.DataFrame(log).to_string(index=False))
print(seg.round(3).to_string())
