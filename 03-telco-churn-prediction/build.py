"""
Telco customer churn: which customers are about to cancel, and who should the
retention team call first? Cleans IBM's public Telco Customer Churn data, compares
three ways of scoring churn risk, tests the chosen one once on held-out customers,
and writes
  - outputs/model_comparison.csv      cross-validated scores for each approach
  - outputs/test_predictions.csv      held-out customers: risk score and whether they left
  - outputs/split.csv                 which customers were used for training and which for the test
  - outputs/calibration.csv           predicted vs actual churn, by tenth of risk
  - outputs/churn_drivers.csv         how much each column matters to the model
  - outputs/data_quality_log.csv      every issue found and what was done
  - outputs/findings.json             the numbers quoted in the write-up
  - outputs/charts/*.png              charts for the case study page

Run:  ../.venv/bin/python -I build.py
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / "data" / "raw" / "telco-churn" / "Telco-Customer-Churn.csv"
OUT = HERE / "outputs"
CHARTS = OUT / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)
SEED = 42

# ---------------------------------------------------------------- 1. clean
raw = pd.read_csv(RAW, dtype=str, keep_default_na=False)
log = []


def note(issue, rows, action):
    log.append({"Issue": issue, "Rows affected": int(rows), "Action": action})


note("Rows in the raw file", len(raw), "Starting point")
dups = raw.duplicated("customerID").sum()
note("Duplicate customer IDs", dups, "None found" if dups == 0 else "Kept the first row")
raw = raw.drop_duplicates("customerID")

blank_total = (raw["TotalCharges"].str.strip() == "").sum()
blank_tenure = raw.loc[raw["TotalCharges"].str.strip() == "", "tenure"].astype(int)
note(
    "TotalCharges blank",
    blank_total,
    f"All {blank_total} have tenure {sorted(blank_tenure.unique().tolist())}: brand-new customers not billed yet, so set to 0",
)
df = raw.copy()
df["TotalCharges"] = pd.to_numeric(df["TotalCharges"].replace(r"^\s*$", "0", regex=True))
for c in ["tenure", "SeniorCitizen"]:
    df[c] = df[c].astype(int)
df["MonthlyCharges"] = df["MonthlyCharges"].astype(float)
df["SeniorCitizen"] = df["SeniorCitizen"].map({0: "No", 1: "Yes"})
df["left"] = (df["Churn"] == "Yes").astype(int)

NUM = ["tenure", "MonthlyCharges", "TotalCharges"]
CAT = [c for c in df.columns if c not in NUM + ["customerID", "Churn", "left"]]
note("Columns used as inputs", len(NUM) + len(CAT), f"{len(NUM)} numeric, {len(CAT)} categories; customerID left out")

# ---------------------------------------------------------------- 2. split
# 20% of customers are set aside and scored once, at the very end.
train, test = train_test_split(df, test_size=0.2, stratify=df["left"], random_state=SEED)
pd.DataFrame(
    {"customerID": pd.concat([train["customerID"], test["customerID"]]),
     "set": ["train"] * len(train) + ["test"] * len(test)}
).to_csv(OUT / "split.csv", index=False)
X_cols = NUM + CAT


# ---------------------------------------------------------------- 3. three approaches
class LookupTable:
    """The spreadsheet answer: churn rate of the customer's contract type and tenure band in the training data."""

    bands = [-1, 6, 12, 24, 48, 72]

    def _key(self, X):
        band = pd.cut(X["tenure"], self.bands).astype(str)
        return X["Contract"].astype(str) + " | " + band

    def fit(self, X, y):
        k = self._key(X)
        self.rates = pd.Series(y.values, index=k.values).groupby(level=0).mean()
        self.overall = float(y.mean())
        return self

    def predict_proba(self, X):
        p = self._key(X).map(self.rates).fillna(self.overall).to_numpy()
        return np.column_stack([1 - p, p])


def logistic():
    pre = ColumnTransformer([("num", StandardScaler(), NUM), ("cat", OneHotEncoder(handle_unknown="ignore"), CAT)])
    return Pipeline([("prep", pre), ("model", LogisticRegression(max_iter=2000, C=1.0))])


def boosted():
    pre = ColumnTransformer(
        [("num", "passthrough", NUM),
         ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), CAT)]
    )
    model = HistGradientBoostingClassifier(
        learning_rate=0.05, max_iter=250, max_leaf_nodes=15, min_samples_leaf=40, l2_regularization=1.0,
        categorical_features=list(range(len(NUM), len(NUM) + len(CAT))), random_state=SEED,
    )
    return Pipeline([("prep", pre), ("model", model)])


APPROACHES = {
    "Lookup table (contract × tenure)": LookupTable,
    "Logistic regression": logistic,
    "Gradient-boosted trees": boosted,
}

folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
rows = []
for name, make in APPROACHES.items():
    scores = {"brier": [], "auc": [], "ap": []}
    for tr, va in folds.split(train, train["left"]):
        m = make().fit(train.iloc[tr][X_cols], train.iloc[tr]["left"])
        p = m.predict_proba(train.iloc[va][X_cols])[:, 1]
        y = train.iloc[va]["left"]
        scores["brier"].append(brier_score_loss(y, p))
        scores["auc"].append(roc_auc_score(y, p))
        scores["ap"].append(average_precision_score(y, p))
    rows.append({
        "Approach": name,
        "Brier (lower is better)": np.mean(scores["brier"]),
        "Brier spread across folds": np.std(scores["brier"]),
        "ROC AUC": np.mean(scores["auc"]),
        "Average precision": np.mean(scores["ap"]),
    })
comparison = pd.DataFrame(rows).sort_values("Brier (lower is better)")
comparison.to_csv(OUT / "model_comparison.csv", index=False)
chosen = comparison.iloc[0]["Approach"]

# ---------------------------------------------------------------- 4. the one test
model = APPROACHES[chosen]().fit(train[X_cols], train["left"])
risk = model.predict_proba(test[X_cols])[:, 1]
y_test = test["left"].to_numpy()
pred = pd.DataFrame({"customerID": test["customerID"].values, "risk": risk, "left": y_test})
pred = pred.sort_values("risk", ascending=False).reset_index(drop=True)
pred.to_csv(OUT / "test_predictions.csv", index=False)


def caught(share):
    """Share of the customers who left that are in the riskiest `share` of the list."""
    n = int(round(len(pred) * share))
    return pred["left"].iloc[:n].sum() / pred["left"].sum()


test_scores = {
    "brier": brier_score_loss(y_test, risk),
    "auc": roc_auc_score(y_test, risk),
    "ap": average_precision_score(y_test, risk),
    "base_rate": float(y_test.mean()),
}
# The lookup table on the same test, for a like-for-like comparison.
lookup_risk = LookupTable().fit(train[X_cols], train["left"]).predict_proba(test[X_cols])[:, 1]
lookup_scores = {"brier": brier_score_loss(y_test, lookup_risk), "auc": roc_auc_score(y_test, lookup_risk)}
lk = pd.DataFrame({"risk": lookup_risk, "left": y_test}).sort_values("risk", ascending=False, kind="mergesort")
lookup_caught_20 = lk["left"].iloc[: int(round(len(lk) * 0.2))].sum() / lk["left"].sum()

# Calibration: when the model says 40%, do about 40% leave?
pred["tenth"] = pd.qcut(pred["risk"].rank(method="first"), 10, labels=range(1, 11)).astype(int)
calib = pred.groupby("tenth").agg(customers=("left", "size"), predicted=("risk", "mean"), actual=("left", "mean"))
calib = calib.sort_index(ascending=False)  # riskiest tenth first
calib.to_csv(OUT / "calibration.csv")

# ---------------------------------------------------------------- 5. what drives it
perm = permutation_importance(model, test[X_cols], y_test, scoring="roc_auc", n_repeats=20, random_state=SEED)
drivers = pd.DataFrame({"column": X_cols, "auc_drop": perm.importances_mean, "spread": perm.importances_std})
drivers = drivers.sort_values("auc_drop", ascending=False)
drivers.to_csv(OUT / "churn_drivers.csv", index=False)


def rate(col, val):
    s = df[df[col] == val]["left"]
    return round(float(s.mean()) * 100, 1), int(len(s))


band = pd.cut(df["tenure"], [-1, 6, 12, 24, 48, 72], labels=["0–6", "7–12", "13–24", "25–48", "49–72"])
by_tenure = df.groupby(band, observed=True)["left"].mean().mul(100).round(1).to_dict()

pd.DataFrame(log).to_csv(OUT / "data_quality_log.csv", index=False)

# ---------------------------------------------------------------- 6. findings
n_test = len(pred)
top20 = int(round(n_test * 0.2))
findings = {
    "customers": int(len(df)),
    "churn_rate_pct": round(float(df["left"].mean()) * 100, 1),
    "blank_total_charges": int(blank_total),
    "train_customers": int(len(train)),
    "test_customers": int(n_test),
    "chosen_approach": chosen,
    "cv": comparison.round(4).to_dict(orient="records"),
    "test": {k: round(float(v), 4) for k, v in test_scores.items()},
    "lookup_test": {k: round(float(v), 4) for k, v in lookup_scores.items()},
    "test_leavers": int(pred["left"].sum()),
    "top20_customers": top20,
    "top20_leavers": int(pred["left"].iloc[:top20].sum()),
    "caught_pct": {f"top{int(s * 100)}": round(caught(s) * 100, 1) for s in (0.1, 0.2, 0.3, 0.5)},
    "lookup_caught_top20_pct": round(float(lookup_caught_20) * 100, 1),
    "top20_churn_rate_pct": round(float(pred["left"].iloc[:top20].mean()) * 100, 1),
    "calibration_max_gap_pts": round(float((calib["predicted"] - calib["actual"]).abs().max()) * 100, 1),
    "top_drivers": drivers.head(5)[["column", "auc_drop"]].round(4).to_dict(orient="records"),
    "churn_pct_by": {
        "month_to_month": rate("Contract", "Month-to-month"),
        "one_year": rate("Contract", "One year"),
        "two_year": rate("Contract", "Two year"),
        "fiber": rate("InternetService", "Fiber optic"),
        "dsl": rate("InternetService", "DSL"),
        "electronic_check": rate("PaymentMethod", "Electronic check"),
        "tenure_band": {str(k): v for k, v in by_tenure.items()},
    },
}
(OUT / "findings.json").write_text(json.dumps(findings, indent=2, ensure_ascii=False))

# ---------------------------------------------------------------- 7. charts
INK, ACC, MUTED, SOFT = "#1c1917", "#c2410c", "#a8a29e", "#e7e5e4"
plt.rcParams.update({"font.family": "Helvetica", "font.size": 11, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.edgecolor": MUTED, "axes.labelcolor": INK})

# Who to call first: share of leavers reached vs share of customers called.
fig, ax = plt.subplots(figsize=(10, 5.4), dpi=160)
share = np.arange(0, n_test + 1) / n_test
got = np.concatenate([[0], pred["left"].cumsum().to_numpy()]) / pred["left"].sum()
ax.plot(share * 100, got * 100, color=ACC, lw=2.4, label="Calling customers in order of predicted risk")
ax.plot([0, 100], [0, 100], color=MUTED, lw=1.5, ls="--", label="Calling customers at random")
c20 = findings["caught_pct"]["top20"]
ax.scatter([20], [c20], color=ACC, zorder=3, s=40)
ax.annotate(f"Call the riskiest 20%: reach {c20:.0f}% of those who leave",
            xy=(20, c20), xytext=(3, 88), color=INK, fontsize=11,
            arrowprops={"arrowstyle": "-", "color": INK, "lw": 0.8})
ax.set_xlabel("Share of customers called")
ax.set_ylabel("Share of customers who left that were reached")
ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter())
ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter())
ax.set_xlim(0, 100)
ax.set_ylim(0, 102)
ax.grid(color=SOFT)
ax.legend(frameon=False, loc="lower right")
ax.set_title(f"Who to call first: {n_test:,} held-out customers", loc="left", fontweight="bold")
fig.tight_layout()
fig.savefig(CHARTS / "who-to-call-first.png")
plt.close(fig)

# What drives the prediction.
nice = {"tenure": "Months as a customer", "Contract": "Contract type", "MonthlyCharges": "Monthly charge",
        "TotalCharges": "Total charges so far", "InternetService": "Internet service", "PaymentMethod": "Payment method",
        "OnlineSecurity": "Online security add-on", "TechSupport": "Tech support add-on", "PaperlessBilling": "Paperless billing",
        "MultipleLines": "Multiple lines", "StreamingTV": "Streaming TV", "StreamingMovies": "Streaming movies",
        "OnlineBackup": "Online backup add-on", "DeviceProtection": "Device protection add-on",
        "SeniorCitizen": "Senior citizen", "Dependents": "Has dependents", "Partner": "Has a partner",
        "PhoneService": "Phone service", "gender": "Gender"}
top = drivers.head(8).iloc[::-1]
fig, ax = plt.subplots(figsize=(10, 4.8), dpi=160)
ax.barh([nice.get(c, c) for c in top["column"]], top["auc_drop"] * 100, color=INK, height=0.6)
for i, v in enumerate(top["auc_drop"] * 100):
    ax.text(v + 0.05, i, f"{v:.1f}", va="center", fontsize=10, color=INK)
ax.set_xlabel("Drop in ROC AUC (points) when the column is shuffled")
ax.set_axisbelow(True)
ax.grid(axis="x", color=SOFT)
ax.set_title("What the model leans on most", loc="left", fontweight="bold")
fig.tight_layout()
fig.savefig(CHARTS / "churn-drivers.png")
plt.close(fig)

# Calibration.
c = calib.sort_index()
fig, ax = plt.subplots(figsize=(10, 4.8), dpi=160)
x = np.arange(1, 11)
ax.bar(x - 0.2, c["predicted"] * 100, width=0.4, color=MUTED, label="Predicted churn")
ax.bar(x + 0.2, c["actual"] * 100, width=0.4, color=ACC, label="Actual churn")
ax.set_xticks(x, [f"{i}" for i in x])
ax.set_axisbelow(True)
ax.set_xlabel("Tenth of customers by predicted risk (1 = lowest, 10 = highest)")
ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter())
ax.grid(axis="y", color=SOFT)
ax.legend(frameon=False, loc="upper left")
gap = findings["calibration_max_gap_pts"]
ax.set_title(f"Predicted vs actual churn: within {gap:.0f} points in every tenth", loc="left", fontweight="bold")
fig.tight_layout()
fig.savefig(CHARTS / "predicted-vs-actual.png")
plt.close(fig)

print(json.dumps({k: findings[k] for k in ["chosen_approach", "test", "lookup_test", "caught_pct",
                                           "lookup_caught_top20_pct", "calibration_max_gap_pts"]}, indent=1))
print(comparison.round(4).to_string(index=False))
