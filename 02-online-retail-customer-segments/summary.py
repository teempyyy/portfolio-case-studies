"""Writes outputs/owner_summary.html from findings.json and segment_summary.csv.
Print it to PDF with:  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new
  --no-pdf-header-footer --print-to-pdf=outputs/Owner_Summary.pdf outputs/owner_summary.html"""
import json
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent / "outputs"
F = json.loads((OUT / "findings.json").read_text())
seg = pd.read_csv(OUT / "segment_summary.csv", index_col=0)
S = F["segments"]
pct = lambda x: f"{x * 100:.0f}%" if x >= 0.01 else "<1%"
gbp = lambda x: f"£{x:,.0f}"
top2_c = S["Champions"]["CustomerShare"] + S["Loyal"]["CustomerShare"]
top2_r = S["Champions"]["RevenueShare"] + S["Loyal"]["RevenueShare"]
wb_n = S["At risk"]["Customers"] + S["Can't lose"]["Customers"]
wb_r = S["At risk"]["Revenue"] + S["Can't lose"]["Revenue"]

rows = "".join(
    f"<tr><td><b>{i}</b></td><td class=n>{int(r.Customers):,}</td><td class=n>{pct(r.RevenueShare)}</td>"
    f"<td class=n>{r.AvgRecencyDays:.0f}</td><td class=n>{r.AvgOrders:.1f}</td><td>{r['Suggested action']}</td></tr>"
    for i, r in seg.iterrows())

html = f"""<!doctype html><html><head><meta charset=utf-8><title>Customer segments: owner summary</title>
<style>
@page {{ size: A4; margin: 12mm 13mm; }}
body {{ font: 9pt/1.4 Helvetica, Arial, sans-serif; color: #1c1917; margin: 0; }}
h1 {{ font-size: 17pt; margin: 0; }} .sub {{ color: #78716c; margin: 2px 0 10px; }}
.k {{ display: flex; gap: 8px; margin-bottom: 10px; }} .k div {{ flex: 1; border: 1px solid #e7e5e4; border-radius: 6px; padding: 6px 8px; }}
.k b {{ display: block; font-size: 14pt; color: #c2410c; }}
h2 {{ font-size: 10.5pt; margin: 10px 0 4px; }} ol {{ margin: 0; padding-left: 16px; }} li {{ margin-bottom: 3px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 8pt; }} th {{ text-align: left; background: #f5f5f4; padding: 3px 5px; }}
td {{ padding: 3px 5px; border-bottom: 1px solid #e7e5e4; vertical-align: top; }} .n {{ text-align: right; white-space: nowrap; }}
img {{ width: 100%; }} .foot {{ color: #78716c; font-size: 7.5pt; margin-top: 6px; }}
</style></head><body>
<h1>Who your best customers are, and who is slipping away</h1>
<div class=sub>UK online gift-ware wholesaler · customers who bought {F['rfm_window'].replace(' – ', ' to ')} · practice analysis on public data (UCI Online Retail II)</div>
<div class=k>
<div><b>{F['rfm_customers']:,}</b>customers bought in the last 12 months</div>
<div><b>{pct(top2_r)}</b>of revenue from Champions + Loyal, {pct(top2_c)} of customers</div>
<div><b>{gbp(wb_r)}</b>spent last year by {wb_n:,} customers now drifting away</div>
<div><b>{pct(F['month1_retention_median_new'])}</b>of new customers buy again the next month (median)</div>
</div>
<h2>What to do</h2>
<ol>
<li><b>Protect the top {pct(top2_c)}.</b> Champions and Loyal customers bring {pct(top2_r)} of revenue. Give them priority service, early access to new ranges and volume pricing. Each Champion spent {gbp(S['Champions']['AvgSpend'])} on average last year.</li>
<li><b>Win back {wb_n:,} drifting customers before the next peak.</b> "At risk" and "Can't lose" customers spent {gbp(wb_r)} last year but haven't ordered for 4 to 5 months on average. Contact the {S["Can't lose"]['Customers']} "Can't lose" accounts personally; send the rest a win-back offer.</li>
<li><b>Get new customers to a second order.</b> Only {pct(F['month1_retention_median_new'])} of new customers buy again the next month and {pct(F['month12_retention_median_new'])} are still buying a year later (median of {F['month12_cohorts_counted']} monthly groups). {pct(F['one_order_customers_share'])} of last year's customers ordered once. A welcome series that aims for a second order within 30 days costs little and targets the biggest gap.</li>
</ol>
<h2>Segments (last 12 months)</h2>
<table><tr><th>Segment</th><th class=n>Customers</th><th class=n>Revenue share</th><th class=n>Days since last order</th><th class=n>Orders</th><th>Suggested action</th></tr>{rows}</table>
<div class=foot>Revenue = quantity × price in GBP, after removing {F['data_quality'][1]['Rows affected']:,} duplicate rows, cancellations, postage and fee lines.
{pct(F['revenue_no_customer_id_share'])} of revenue has no customer ID and is not in the segments. New-customer repeat rates use monthly groups from Jan 2010 to Nov 2011 (Dec 2009 is customers already buying when the data starts).
Segments use R (days since last order) and F (number of orders) scored 1 to 5 by fifths.</div>
</body></html>"""
(OUT / "owner_summary.html").write_text(html)
print("written")
