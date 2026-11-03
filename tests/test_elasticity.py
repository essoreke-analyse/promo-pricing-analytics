import math

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from promo_pricing.elasticity import breakeven_margin, shrink_to_category, volume_multiplier


def test_volume_multiplier():
    assert volume_multiplier(-2.0, -0.10) == (0.9) ** -2.0
    assert volume_multiplier(0.0, -0.10) == 1.0


def test_breakeven_margin_makes_profit_unchanged():
    e, d = -2.5, 0.10
    m = breakeven_margin(e, d)
    lift = volume_multiplier(e, -d)
    profit_before = m * 1.0
    profit_after = (m - d) * lift
    assert math.isclose(profit_before, profit_after, rel_tol=1e-9)


def test_breakeven_margin_is_infinite_when_volume_does_not_rise():
    assert breakeven_margin(0.0, 0.10) == float("inf")


def test_shrinkage_moves_noisy_estimates_more():
    res = pd.DataFrame({
        "category": ["A"] * 4,
        "elasticity": [-1.0, -2.0, -3.0, 1.0],
        "se": [0.1, 0.1, 0.1, 2.0],          # the last estimate is very noisy
    })
    out = shrink_to_category(res)
    moved = (out["elasticity_shrunk"] - out["elasticity"]).abs()
    assert moved.iloc[3] > moved.iloc[:3].max()
    # every shrunk value lies between the raw value and the category mean
    lo = np.minimum(out["elasticity"], out["category_mean"]) - 1e-12
    hi = np.maximum(out["elasticity"], out["category_mean"]) + 1e-12
    assert ((out["elasticity_shrunk"] >= lo) & (out["elasticity_shrunk"] <= hi)).all()


def test_log_log_regression_recovers_a_known_elasticity():
    # Simulated data with a true elasticity of -2: the method must find it.
    rng = np.random.default_rng(0)
    price = rng.uniform(2, 4, 5000)
    units = np.exp(5 - 2.0 * np.log(price) + rng.normal(0, 0.1, 5000))
    df = pd.DataFrame({"log_units": np.log(units), "log_price": np.log(price)})
    est = smf.ols("log_units ~ log_price", df).fit().params["log_price"]
    assert abs(est - (-2.0)) < 0.02
