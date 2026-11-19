# Portfolio case studies

Practice projects I built on public Kaggle data for my freelance portfolio. None of this is client work. You can see the write-ups at [dj-labs-portfolio.vercel.app](https://dj-labs-portfolio.vercel.app/?role=data).

| # | Project | Level | What it covers |
|---|---|---|---|
| 01 | [Superstore sales dashboard](01-superstore-sales-dashboard/) | Beginner | Cleaning the data, defining the KPIs, an Excel dashboard built from formulas, and where discounts cost margin |
| 02 | [Online Retail customer segments](02-online-retail-customer-segments/) | Intermediate | RFM segmentation and cohort retention in Python, checked again in SQL |

## Running it

```bash
python3 -m venv .venv
.venv/bin/pip install pandas openpyxl matplotlib
```

The raw data isn't in this repo. Download each dataset from Kaggle into `data/raw/<name>/` (each project's README has the link), then run that project's `build.py`.
