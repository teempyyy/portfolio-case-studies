"""
Recomputes the headline numbers without scikit-learn or pandas, straight from the raw
CSV and outputs/test_predictions.csv, and compares them with outputs/findings.json.

Run:  ../.venv/bin/python -I check.py
"""

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / "data" / "raw" / "telco-churn" / "Telco-Customer-Churn.csv"
OUT = HERE / "outputs"
f = json.loads((OUT / "findings.json").read_text())

with open(RAW, newline="") as fh:
    raw = list(csv.DictReader(fh))
with open(OUT / "test_predictions.csv", newline="") as fh:
    pred = [(r["customerID"], float(r["risk"]), int(r["left"])) for r in csv.DictReader(fh)]
with open(OUT / "split.csv", newline="") as fh:
    split = list(csv.DictReader(fh))

checks = []


def check(name, mine, theirs, tol=0.0):
    ok = abs(mine - theirs) <= tol if isinstance(mine, float) else mine == theirs
    checks.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {mine} vs {theirs}")


# Data
check("customers", len({r["customerID"] for r in raw}), f["customers"])
check("churn rate %", round(100 * sum(r["Churn"] == "Yes" for r in raw) / len(raw), 1), f["churn_rate_pct"])
check("blank TotalCharges", sum(r["TotalCharges"].strip() == "" for r in raw), f["blank_total_charges"])

# Split: every customer once, test never seen in training
ids = [r["customerID"] for r in split]
train = {r["customerID"] for r in split if r["set"] == "train"}
test = {r["customerID"] for r in split if r["set"] == "test"}
check("split covers every customer once", len(ids) == len(set(ids)) == len(raw), True)
check("train and test don't overlap", len(train & test), 0)
check("test customers", len(test), f["test_customers"])
check("predictions are the test customers", {p[0] for p in pred} == test, True)

# Test scores
y = [p[2] for p in pred]
r = [p[1] for p in pred]
n1 = sum(y)
n0 = len(y) - n1
check("leavers in the test", n1, f["test_leavers"])
check("Brier", round(sum((a - b) ** 2 for a, b in zip(r, y)) / len(y), 4), f["test"]["brier"], 1e-4)

# ROC AUC as the chance a random leaver outranks a random stayer (ties count half)
order = sorted(range(len(r)), key=lambda i: r[i])
ranks = [0.0] * len(r)
i = 0
while i < len(order):
    j = i
    while j + 1 < len(order) and r[order[j + 1]] == r[order[i]]:
        j += 1
    for k in range(i, j + 1):
        ranks[order[k]] = (i + j) / 2 + 1
    i = j + 1
auc = (sum(rk for rk, yy in zip(ranks, y) if yy) - n1 * (n1 + 1) / 2) / (n1 * n0)
check("ROC AUC", round(auc, 4), f["test"]["auc"], 1e-4)

# Who to call first
ranked = sorted(pred, key=lambda p: -p[1])
for share in (0.1, 0.2, 0.3, 0.5):
    n = round(len(ranked) * share)
    check(f"caught in top {int(share * 100)}% (%)", round(100 * sum(p[2] for p in ranked[:n]) / n1, 1),
          f["caught_pct"][f"top{int(share * 100)}"], 0.05)
n20 = round(len(ranked) * 0.2)
check("top 20% customers", n20, f["top20_customers"])
check("leavers in top 20%", sum(p[2] for p in ranked[:n20]), f["top20_leavers"])

# Calibration: biggest gap between predicted and actual across the ten tenths
asc = sorted(pred, key=lambda p: p[1])
size = len(asc) / 10
gaps = []
for t in range(10):
    chunk = asc[round(t * size):round((t + 1) * size)]
    gaps.append(abs(sum(p[1] for p in chunk) / len(chunk) - sum(p[2] for p in chunk) / len(chunk)))
check("largest calibration gap (points)", round(100 * max(gaps), 1), f["calibration_max_gap_pts"], 0.15)

print(f"\n{sum(checks)} of {len(checks)} checks pass")
raise SystemExit(0 if all(checks) else 1)
