"""Price elasticity models on the weekly panel.

Own-price elasticity per product (log-log OLS), brand-level cross-price elasticities,
empirical-Bayes shrinkage toward the category, and simple what-if helpers.
"""
from __future__ import annotations

import warnings

import duckdb
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

# Controls shared by all specifications
PROMO_CONTROLS = ["feature", "display", "promo_prev_week", "promo_next_week"]
COMPETITION_CONTROLS = ["competitor_avg_discount", "competitor_support_share", "own_brand_other_promo_share"]

# Two ways to absorb demand shocks (see notebook 02, section 2)
SPECS = {
    # Main: identification from price changes over time, with season and holiday controls.
    "time": "C(store_id) + C(holiday) + C(pre_holiday) + C(month) + week_index",
    # Robustness: week fixed effects remove all chain-wide shocks, but also most of the price variation.
    "week_fe": "C(store_id) + C(week)",
}


def load_panel(db_path: str) -> pd.DataFrame:
    """Read weekly_panel and fill the few structural NULLs used as regressors."""
    with duckdb.connect(db_path, read_only=True) as con:
        df = con.sql("SELECT * FROM weekly_panel").df()
    fill_zero = ["competitor_avg_discount", "competitor_support_share", "own_brand_other_promo_share"]
    df[fill_zero] = df[fill_zero].fillna(0)
    df["holiday"] = df["holiday"].fillna("none")
    df["pre_holiday"] = df["pre_holiday"].fillna("none")
    return df


def _formula(g: pd.DataFrame, spec: str) -> str:
    # Drop promo flags that never vary for this product (e.g. a product never featured)
    controls = [c for c in PROMO_CONTROLS + COMPETITION_CONTROLS if g[c].nunique() > 1]
    return "log_units ~ log_price + " + " + ".join(controls) + " + " + SPECS[spec]


def fit_own_elasticities(df: pd.DataFrame, spec: str = "time") -> pd.DataFrame:
    """One log-log regression per product. Standard errors clustered by week,
    because promotions and demand shocks are shared by all stores in a week."""
    rows = []
    for upc, g in df.groupby("upc"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = smf.ols(_formula(g, spec), g).fit(cov_type="cluster", cov_kwds={"groups": g["week"]})
        p, se = m.params, m.bse
        rows.append({
            "upc": upc,
            "category": g["category"].iloc[0],
            "manufacturer": g["manufacturer"].iloc[0],
            "description": g["description"].iloc[0],
            "n_obs": len(g),
            "elasticity": p["log_price"],
            "se": se["log_price"],
            "feature_effect": np.exp(p.get("feature", 0.0)) - 1,
            "display_effect": np.exp(p.get("display", 0.0)) - 1,
            "post_promo_effect": np.exp(p["promo_prev_week"]) - 1,
            "pre_promo_effect": np.exp(p["promo_next_week"]) - 1,
            "competitor_discount_coef": p["competitor_avg_discount"],
            "r2": m.rsquared,
        })
    out = pd.DataFrame(rows)
    out["ci_low"] = out["elasticity"] - 1.96 * out["se"]
    out["ci_high"] = out["elasticity"] + 1.96 * out["se"]
    return out


def shrink_to_category(res: pd.DataFrame) -> pd.DataFrame:
    """Empirical-Bayes shrinkage: noisy product estimates are pulled toward their
    category mean, precise ones barely move.

    Product estimate  e_i ~ N(theta_i, se_i^2), with theta_i ~ N(mu_cat, tau_cat^2).
    Posterior mean = w_i * e_i + (1 - w_i) * mu_cat, with w_i = tau^2 / (tau^2 + se_i^2).
    """
    out = res.copy()
    for cat, g in out.groupby("category"):
        prec = 1 / g["se"] ** 2
        mu = np.sum(prec * g["elasticity"]) / prec.sum()
        tau2 = max(g["elasticity"].var(ddof=1) - np.mean(g["se"] ** 2), 1e-4)   # method of moments
        w = tau2 / (tau2 + g["se"] ** 2)
        out.loc[g.index, "category_mean"] = mu
        out.loc[g.index, "shrink_weight"] = w
        out.loc[g.index, "elasticity_shrunk"] = w * g["elasticity"] + (1 - w) * mu
    return out


def brand_cross_elasticities(db_path: str, category: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Brand-level model: log(units of brand i) on the log prices of every brand in the category.

    Returns (elasticities, t-stats), both brands x brands. Row = brand whose sales move,
    column = brand whose price changes. Off-diagonal > 0 means substitutes.
    """
    with duckdb.connect(db_path, read_only=True) as con:
        b = con.execute("""
            SELECT manufacturer AS brand, store_id, week,
                   COALESCE(ANY_VALUE(holiday), 'none') AS holiday,
                   COALESCE(ANY_VALUE(pre_holiday), 'none') AS pre_holiday,
                   ANY_VALUE(month) AS month, ANY_VALUE(week_index) AS week_index,
                   SUM(units) AS units, AVG(log_price) AS log_price,
                   AVG(feature) AS feature, AVG(display) AS display
            FROM weekly_panel WHERE category = ? GROUP BY ALL
        """, [category]).df()

    brands = sorted(b["brand"].unique())
    var = {br: "p_" + "".join(ch for ch in br if ch.isalnum()) for br in brands}
    prices = b.pivot_table(index=["store_id", "week"], columns="brand", values="log_price")
    est, tst = {}, {}
    for br in brands:
        x = b[b["brand"] == br].set_index(["store_id", "week"]).copy()
        x["log_units"] = np.log(x["units"])
        terms, identified = [], []
        for other in brands:
            col = prices[other].reindex(x.index)
            # Two brands never on the shelf together (different regions): no cross effect can be estimated
            if col.notna().sum() < 100 or col.dropna().nunique() < 2:
                continue
            identified.append(other)
            # brand absent from the shelf that week: average price + an "absent" dummy
            x[var[other]] = col.fillna(col.mean())
            terms.append(var[other])
            absent = col.isna().astype(int)
            # keep the dummy only if absence varies within a store (otherwise store effects absorb it)
            if other != br and absent.groupby(level="store_id").nunique().max() > 1:
                x[var[other] + "_absent"] = absent
                terms.append(var[other] + "_absent")
        x = x.reset_index()
        # promo shares that never vary for this brand (e.g. never featured) are dropped
        terms += [c for c in ["feature", "display"] if x[c].nunique() > 1]
        f = ("log_units ~ " + " + ".join(terms) + " + "
             "C(store_id) + C(holiday) + C(pre_holiday) + C(month) + week_index")
        m = smf.ols(f, x).fit(cov_type="cluster", cov_kwds={"groups": x["week"]})
        est[br] = {o: m.params[var[o]] if o in identified else np.nan for o in brands}
        tst[br] = {o: m.tvalues[var[o]] if o in identified else np.nan for o in brands}
    return pd.DataFrame(est).T.loc[brands, brands], pd.DataFrame(tst).T.loc[brands, brands]


def volume_multiplier(elasticity: float, price_change: float) -> float:
    """Units after / units before for a relative price change (constant elasticity)."""
    return (1 + price_change) ** elasticity


def breakeven_margin(elasticity: float, discount: float) -> float:
    """Minimum gross margin (as a share of the regular price) above which a price cut
    of `discount` increases gross profit.

    Profit before: m * Q.  After: (m - d) * Q * L, with L = (1 - d) ** e.
    The cut pays off when (m - d) * L > m, i.e. m > d * L / (L - 1).
    Returns inf when the cut does not raise volume.
    """
    lift = volume_multiplier(elasticity, -discount)
    if lift <= 1:
        return float("inf")
    return discount * lift / (lift - 1)
