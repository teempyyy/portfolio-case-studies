# 02 · Online Retail customer segments

The data is [Online Retail II UCI](https://www.kaggle.com/datasets/mashlyn/online-retail-ii-uci) on Kaggle, released under CC0. It has 1,067,371 invoice lines from a UK online gift-ware wholesaler, from December 2009 to December 2011, in pounds. It comes from the UCI Machine Learning Repository (Chen, Sain and Guo, 2012).

I wanted to answer three questions: who the best customers are, who is drifting away, and whether new customers come back.

## Files

- `build.py` cleans the data, scores each customer, builds the segments and the cohort retention table, and writes `outputs/`.
- `check.py` rebuilds the main numbers in SQL (SQLite) straight from the raw CSV and compares them with the outputs. All 19 checks pass, including recency, frequency and spend for every one of the 4,261 customers.
- `summary.py` writes the one-page owner summary (`outputs/Owner_Summary.pdf`) from the computed results.
- `outputs/customer_segments.csv` has one row per customer: recency, frequency, spend, the 1 to 5 scores and the segment.
- `outputs/segment_summary.csv`, `outputs/cohort_retention.csv`, `outputs/findings.json` and `outputs/charts/` hold the rest.

## Cleaning

| Issue | Rows | What I did |
|---|---|---|
| Exact duplicate rows | 34,335 | Removed them |
| Bad-debt adjustments (invoice starts with A) | 6 | Removed them |
| Cancellations (invoice starts with C) | 19,104 | Set them aside; product cancellations came to £716,426, 3.6% of product sales |
| Quantity or price of zero or less, outside cancellations | 6,014 | Removed them |
| Postage, fees, manual and test lines | 4,572 | Removed them from product sales |
| No customer ID | 226,761 lines, 13.1% of revenue | Kept them in the totals and left them out of the customer analysis |

That leaves 1,003,340 sales lines worth £19.64M, from 5,852 customers in 43 countries. The UK accounts for 85.5% of revenue.

## Method

For the segments I used RFM on the last 12 months of data (10 December 2010 to 9 December 2011). Recency is the number of days since a customer's last order, frequency is the number of separate invoices, and monetary is total spend. Each is scored 1 to 5 by fifths, using ranks so that tied values still split evenly. The segment names come from the standard recency by frequency map.

For retention I grouped customers by the month of their first order and measured the share who bought again in each later month. December 2011 has only 9 days of data, so I left it out. December 2009 appears as "existing": the data starts that month, so the group contains customers who were already buying, and I left it out of the new-customer figures.

## Findings

4,261 customers bought in the last 12 months, spending £8.43M between them.

Champions are 618 customers (14.5%) and bring in 48.7% of revenue. Together with the Loyal segment, a third of customers (33.3%) bring in 74.9%. The top 20% of customers account for 74.4%.

The At risk (595) and Can't lose (57) segments spent £794,673 last year but haven't ordered for 144 and 125 days on average.

35.5% of customers placed only one order in the year.

Among new customers, a median of 20% buy again the next month and 15% are still buying 12 months later (across the 11 monthly groups from January to November 2010). The December 2010 group was the weakest, with 9% coming back the next month.

Revenue and the number of active customers rise every September to November, and November is the biggest month in both years.

My recommendations are to look after the Champions and Loyal customers, to contact the 652 drifting customers before the next peak season (the 57 Can't lose accounts personally), and to set up a welcome series that aims for a second order within 30 days.
