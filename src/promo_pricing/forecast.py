"""Weekly unit forecasts 1-4 weeks ahead, evaluated with a rolling-origin backtest.

Models compared
- seasonal naive : same week last year (falls back to the moving average when missing)
- moving average : mean of weeks t-4 .. t-11
- regression     : the per-product log-log model of notebook 02 (price, promotions, season)
- LightGBM       : one global gradient-boosting model with the promotion calendar and
                   lagged sales, plus P10 / P90 quantile models for a low / high scenario
"""
from __future__ import annotations

import warnings

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from promo_pricing.elasticity import _formula

CATEGORICAL = ["store_id", "upc", "category", "manufacturer", "holiday", "pre_holiday", "store_segment"]
NUMERIC = [
    # known in advance: price and promotion plan of the target week
    "log_price", "log_base_price", "discount_depth", "feature", "display", "tpr_only",
    "promo_prev_week", "promo_next_week", "promo_weeks_last_4",
    "competitor_avg_discount", "competitor_promo_share", "competitor_support_share",
    "own_brand_other_promo_share",
    # calendar
    "week_of_year", "month", "week_index",
    # sales history, all at least 4 weeks old
    "units_lag4", "units_lag5", "units_lag8", "units_lag52", "promo_lag52",
    "units_ma8_lag4", "units_nopromo_avg26_lag4", "n_obs_ma8",
]
# Deliberately NOT used: units_prev_week / prev_week_missing (1 week old: would leak for h > 1)

LGB_PARAMS = dict(objective="tweedie", tweedie_variance_power=1.2, learning_rate=0.05,
                  num_leaves=63, min_data_in_leaf=50, feature_fraction=0.8,
                  bagging_fraction=0.8, bagging_freq=1, verbose=-1, seed=42,
                  deterministic=True, force_row_wise=True, num_threads=4)   # same result on every run


def load_features(db_path: str) -> pd.DataFrame:
    with duckdb.connect(db_path, read_only=True) as con:
        df = con.sql("SELECT * FROM forecast_features").df()
    df[["competitor_avg_discount", "competitor_support_share", "own_brand_other_promo_share"]] = \
        df[["competitor_avg_discount", "competitor_support_share", "own_brand_other_promo_share"]].fillna(0)
    df["holiday"] = df["holiday"].fillna("none")
    df["pre_holiday"] = df["pre_holiday"].fillna("none")
    for c in CATEGORICAL:
        df[c] = df[c].astype("category")
    # DuckDB returns nullable integers (Int32): convert to plain floats (NaN for missing)
    for c in NUMERIC + ["units", "any_promo"]:
        df[c] = df[c].astype("float64")
    return df


# ---------- metrics ----------

def wape(y, yhat) -> float:
    """Weighted absolute percentage error: total absolute error / total actual units."""
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    return np.abs(y - yhat).sum() / y.sum()


def bias(y, yhat) -> float:
    """Total forecast / total actual - 1. Positive = over-forecast (overstock risk)."""
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    return yhat.sum() / y.sum() - 1


def coverage(y, low, high) -> float:
    """Share of actuals falling inside [low, high]."""
    y = np.asarray(y, float)
    return float(np.mean((y >= np.asarray(low)) & (y <= np.asarray(high))))


# ---------- models ----------

def naive_forecasts(test: pd.DataFrame, train: pd.DataFrame) -> pd.DataFrame:
    fallback = train.groupby(["store_id", "upc"], observed=True)["units"].mean().rename("series_mean")
    t = test.join(fallback, on=["store_id", "upc"])
    ma = t["units_ma8_lag4"].fillna(t["series_mean"]).fillna(train["units"].mean())
    return pd.DataFrame({"moving_average": ma,
                         "seasonal_naive": t["units_lag52"].fillna(ma)}, index=test.index)


def regression_forecast(test: pd.DataFrame, train: pd.DataFrame) -> pd.Series:
    """Per-product log-log model; exp() of a log prediction is corrected with Duan's smearing factor."""
    out = pd.Series(np.nan, index=test.index)
    for upc, g in train.groupby("upc", observed=True):
        tg = test[test["upc"] == upc]
        if tg.empty:
            continue
        g = g.assign(store_id=g["store_id"].astype(str), holiday=g["holiday"].astype(str),
                     pre_holiday=g["pre_holiday"].astype(str))
        tg = tg.assign(store_id=tg["store_id"].astype(str), holiday=tg["holiday"].astype(str),
                       pre_holiday=tg["pre_holiday"].astype(str))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = smf.ols(_formula(g, "time"), g).fit()
        smear = np.mean(np.exp(m.resid))
        known = tg["store_id"].isin(g["store_id"].unique()) & tg["holiday"].isin(g["holiday"].unique()) \
            & tg["pre_holiday"].isin(g["pre_holiday"].unique())
        out.loc[tg.index[known]] = np.exp(m.predict(tg[known])) * smear
    return out


def lightgbm_forecasts(test: pd.DataFrame, train: pd.DataFrame, rounds: int = 500):
    """Point forecast (Tweedie) plus P10 and P90 quantile forecasts. Returns (predictions, point model)."""
    X, Xt = train[CATEGORICAL + NUMERIC], test[CATEGORICAL + NUMERIC]
    point = lgb.train(LGB_PARAMS, lgb.Dataset(X, train["units"]), num_boost_round=rounds)
    preds = {"lightgbm": point.predict(Xt)}
    for q in (0.1, 0.9):
        params = {**LGB_PARAMS, "objective": "quantile", "alpha": q}
        params.pop("tweedie_variance_power")
        mq = lgb.train(params, lgb.Dataset(X, train["units"]), num_boost_round=rounds // 2)
        preds[f"lightgbm_p{int(q * 100)}"] = mq.predict(Xt)
    out = pd.DataFrame(preds, index=test.index)
    # quantile models are trained separately: enforce P10 <= P90
    lo, hi = out[["lightgbm_p10", "lightgbm_p90"]].min(axis=1), out[["lightgbm_p10", "lightgbm_p90"]].max(axis=1)
    out["lightgbm_p10"], out["lightgbm_p90"] = lo.clip(lower=0), hi
    return out, point


def rolling_backtest(df: pd.DataFrame, n_folds: int = 7, horizon: int = 4, rounds: int = 500):
    """Rolling origin: for each fold, train on every week up to the origin T,
    forecast weeks T+1..T+horizon, then move the origin forward by `horizon` weeks."""
    last = int(df["week_index"].max())
    origins = [last - horizon * k for k in range(n_folds, 0, -1)]
    results, importances = [], []
    for T in origins:
        train = df[df["week_index"] <= T]
        test = df[(df["week_index"] > T) & (df["week_index"] <= T + horizon)]
        preds = naive_forecasts(test, train)
        preds["regression"] = regression_forecast(test, train)
        lgb_preds, model = lightgbm_forecasts(test, train, rounds)
        preds = preds.join(lgb_preds)
        preds["regression"] = preds["regression"].fillna(preds["moving_average"])
        keep = ["week", "week_index", "store_id", "upc", "category", "description", "any_promo", "units"]
        fold = test[keep].join(preds)
        fold["origin"], fold["horizon"] = T, fold["week_index"] - T
        results.append(fold)
        importances.append(pd.Series(model.feature_importance("gain"), index=model.feature_name(), name=T))
    return pd.concat(results), pd.concat(importances, axis=1).mean(axis=1).sort_values(ascending=False)
