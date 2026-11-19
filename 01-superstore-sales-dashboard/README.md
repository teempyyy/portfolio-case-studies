# 01 · Superstore sales dashboard

The data is the [Superstore Dataset](https://www.kaggle.com/datasets/vivek468/superstore-dataset-final) on Kaggle, which is Tableau sample data shared for educational use. It has 9,994 order lines from January 2014 to December 2017, in US dollars.

Sales grew 52% from 2014 to 2017, but the profit margin stayed between 10% and 13% a year. I wanted to find out which products, regions and discounts were holding profit down.

## Files

- `build.py` cleans the raw CSV and writes everything in `outputs/`.
- `check_workbook.py` works out each workbook formula on its own and compares the result with the pandas figures. All 28 checks pass.
- `outputs/Superstore_Sales_Dashboard.xlsx` is the dashboard. The Read me sheet has the definitions, the data-quality log and the steps for adding new data. The Dashboard sheet has a year selector, the KPIs, and tables and charts by region, category and discount. There are also Sub-Category, States, Monthly and Data sheets.
- `outputs/findings.json` holds every number quoted below.
- `outputs/charts/` has the charts used on the portfolio page.

## Data quality

| Issue | Rows | What I did |
|---|---|---|
| Dates stored as text | 9,994 | Converted them to dates |
| Postal codes missing the leading zero | 449 | Stored them as 5-character text |
| Exact duplicate order line | 1 | Removed it |
| Product IDs used for more than one product name | 32 IDs (337 rows) | Kept and flagged them; the analysis works by sub-category |
| Customer names | all | Left them out of the workbook |

## Findings

Lines discounted above 20% are 13.9% of all lines, and together they lost $135,364. Without them, profit would have been $421,773 instead of $286,409.

Margin drops as the discount rises: 29.5% with no discount, 11.9% at 1 to 20%, then −10.1% at 21 to 30%, −24.8% at 31 to 50% and −119.2% above 50%.

Furniture makes a 2.5% margin, against 17.0% for Office Supplies and 17.4% for Technology. Three sub-categories lose money: Tables (−$17,725), Bookcases (−$3,473) and Supplies (−$1,189).

The Central region gives the highest average discount (24.0%) and has the lowest margin (7.9%). The states with the biggest losses are Texas (−$25,729), Ohio (−$16,959) and Pennsylvania (−$15,560).

September, November and December bring in 42.9% of sales.

My recommendation is to cap routine discounts at 20% and require approval above that, starting with Furniture and the Central region.
