# 03 · Telco churn prediction: who to call first

The data is IBM's [Telco Customer Churn](https://github.com/IBM/telco-customer-churn-on-icp4d/blob/master/data/Telco-Customer-Churn.csv) sample, released under the Apache 2.0 license. It has 7,043 customers of a fictional phone and internet provider: their services, contract, billing, and whether they left in the last month. 26.5% did.

The question: which customers are most likely to leave, so a retention team with limited time knows who to call first?

## Files

- `build.py` cleans the data, compares three ways of scoring churn risk with 5-fold cross-validation, tests the chosen one once on customers it never saw, and writes `outputs/`.
- `check.py` recomputes the headline numbers from the raw CSV and the saved predictions without scikit-learn or pandas, and compares them with the outputs. All 17 checks pass.
- `outputs/test_predictions.csv` has every held-out customer's risk score and whether they actually left.
- `outputs/model_comparison.csv`, `outputs/calibration.csv`, `outputs/churn_drivers.csv`, `outputs/split.csv`, `outputs/findings.json` and `outputs/charts/` hold the rest.

## Cleaning

| Issue | Rows | What I did |
|---|---|---|
| Duplicate customer IDs | 0 | None found |
| `TotalCharges` blank | 11 | All 11 have 0 months of tenure: new customers who haven't been billed yet, so I set it to 0 |

19 columns go into the model: 3 numeric (months as a customer, monthly charge, total charges) and 16 categories (contract, internet service, payment method, add-ons and so on). The customer ID is left out.

## Method

I set aside 20% of customers (1,409, stratified so they have the same churn rate) before doing anything else. They were scored once, at the end.

On the other 80% I compared three approaches with 5-fold cross-validation:

| Approach | Brier (lower is better) | ROC AUC | Average precision |
|---|---|---|---|
| **Logistic regression** | **0.135** | 0.846 | 0.662 |
| Gradient-boosted trees | 0.137 | 0.843 | 0.658 |
| Lookup table: churn rate by contract type and tenure band | 0.158 | 0.783 | 0.488 |

I chose by Brier score because the risk scores are meant to be read as probabilities ("this customer has a 60% chance of leaving"), not only to rank customers. Logistic regression won, but the gap to the boosted trees (0.0015) is smaller than the variation between folds (about 0.005), so the honest reading is that they're tied, and the simpler, easier-to-explain model is the better choice. Both clearly beat the lookup table, which is what you could build in a spreadsheet.

## Results on the held-out customers

| Measure | Logistic regression | Lookup table |
|---|---|---|
| Brier score | 0.138 | 0.155 |
| ROC AUC | 0.842 | 0.791 |
| Leavers reached by calling the riskiest 20% | **49.7%** (186 of 374) | 44.7% |

Calling the riskiest 20% of customers (282 people) reaches half of everyone who leaves, against 20% if you called at random. Two in three of the customers called (66%) do leave, against 26.5% overall. The riskiest 10% reaches 28.1% of leavers; the riskiest 30% reaches 65.0%.

The probabilities can be trusted: split the customers into tenths by predicted risk, and predicted churn is within 7 points of actual churn in every tenth (the largest gap is 6.9 points, in the eighth tenth).

## What drives churn

Shuffling one column at a time and measuring how much the ROC AUC drops shows what the model relies on. Months as a customer matters far more than anything else (17.2 points), followed by internet service (3.9), contract type (3.5) and monthly charge (3.2). Months as a customer and total charges move together, so their importance is shared between them.

In the raw data:

- Month-to-month customers leave at 42.7%, against 11.3% on one-year and 2.8% on two-year contracts.
- New customers are the most at risk: 52.9% of those in their first 6 months leave, against 9.5% after 4 years.
- Fiber customers leave at 41.9%, against 19.0% on DSL.
- Customers paying by electronic check leave at 45.3%.

## Recommendations

1. Each month, score every customer and give the retention team the riskiest 20% to call. That list holds half of next month's leavers.
2. Focus offers on month-to-month customers in their first year: the biggest single group of leavers. A discount for moving to a one-year contract is the obvious test.
3. Look into why fiber customers leave at twice the DSL rate. Price, reliability and competitor offers are the first things to check.
4. Measure the calls: keep a random group that isn't called, so the team can see how many leavers the calls actually save.

## Limits

This is one snapshot of a sample dataset, so the model can't learn from changes over time, and the "drivers" show what predicts leaving, not what causes it. A real deployment would retrain on fresh data each month and check the scores against what actually happened.
