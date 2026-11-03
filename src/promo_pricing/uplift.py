"""Baseline vs incremental volume of each promotion, and its return.

The baseline of a promoted week is the volume the model predicts for the same week
with no promotion: shelf price back to the base price, no feature, no display,
everything else unchanged (store, season, competitors). Applying the predicted ratio
to the actual units keeps the week's own noise in both numbers.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from promo_pricing.elasticity import _formula


def fit_product_models(df: pd.DataFrame, spec: str = "time") -> dict:
    """Same log-log models as notebook 02 (main specification), kept for prediction."""
    models = {}
    for upc, g in df.groupby("upc"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            models[upc] = smf.ols(_formula(g, spec), g).fit()
    return models


def decompose_promotions(df: pd.DataFrame, models: dict) -> pd.DataFrame:
    """For every promoted week: baseline units, units added by the price cut,
    units added by feature/display on top of it."""
    promo = df[df["any_promo"] == 1].copy()
    parts = []
    for upc, g in promo.groupby("upc"):
        m = models[upc]
        no_support = g.assign(feature=0, display=0)                       # price cut only
        no_promo = no_support.assign(log_price=g["log_base_price"])        # nothing
        pred_actual = m.predict(g)
        pred_price_only = m.predict(no_support)
        pred_none = m.predict(no_promo)
        out = g[["week", "store_id", "upc", "category", "manufacturer", "description", "mechanic",
                 "units", "price", "base_price", "discount_depth"]].copy()
        out["baseline_units"] = g["units"] * np.exp(pred_none - pred_actual)
        out["price_only_units"] = g["units"] * np.exp(pred_price_only - pred_actual)
        parts.append(out)
    res = pd.concat(parts, ignore_index=True)
    res["incremental_units"] = res["units"] - res["baseline_units"]
    res["incr_from_price"] = res["price_only_units"] - res["baseline_units"]
    res["incr_from_support"] = res["units"] - res["price_only_units"]
    return res


def promo_economics(res: pd.DataFrame, gross_margin: float) -> pd.DataFrame:
    """Profit impact of each promoted week for whoever funds the discount.

    gross_margin: margin as a share of the base price in a normal week.
    - trade spend      = discount per unit x all units sold (the baseline units are discounted too)
    - incremental profit = profit during the promotion - profit the baseline would have made
                         = incremental units x (margin - discount) - baseline units x discount
    - ROI              = incremental profit / trade spend
    """
    out = res.copy()
    unit_margin = gross_margin * out["base_price"]
    discount = (out["base_price"] - out["price"]).clip(lower=0)
    out["trade_spend"] = discount * out["units"]
    out["incremental_profit"] = (out["incremental_units"] * (unit_margin - discount)
                                 - out["baseline_units"] * discount)
    out["subsidised_spend"] = discount * out["baseline_units"]
    return out


def breakeven_margin_of_promo(units, baseline_units, base_price, price):
    """Gross margin above which a promoted week adds profit (NaN if it adds no volume)."""
    incr = units - baseline_units
    disc = np.clip(base_price - price, 0, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        m = disc * units / (base_price * incr)
    return np.where(incr > 0, m, np.nan)
