import math

import pandas as pd
import pytest

from promo_pricing.simulator import simulate


@pytest.fixture
def inputs():
    return pd.DataFrame([{
        "upc": 1, "product_name": "Test pizza", "category_label": "Frozen pizza",
        "normal_weekly_units_per_store": 10.0, "avg_base_price": 5.0, "n_stores": 2,
        "elasticity": -2.0, "elasticity_shrunk": -2.0, "ci_low": -2.2, "ci_high": -1.8,
        "feature_effect": 0.5, "display_effect": 0.25,
    }])


def test_no_change_means_no_effect(inputs):
    s = simulate(inputs, 1, price_change=0.0)
    assert s.units_per_store == 10.0
    assert s.chain_profit_change == 0.0 and s.trade_spend == 0.0 and s.roi is None


def test_price_cut_uses_constant_elasticity(inputs):
    s = simulate(inputs, 1, price_change=-0.10)
    assert math.isclose(s.units_per_store, 10 * 0.9 ** -2.0)


def test_support_multiplies_volume(inputs):
    s = simulate(inputs, 1, price_change=0.0, feature=True, display=True)
    assert math.isclose(s.units_per_store, 10 * 1.5 * 1.25)


def test_profit_by_hand(inputs):
    # 2 stores, margin 40 % of $5 = $2/unit; $1 discount -> $1/unit during the promotion
    s = simulate(inputs, 1, price_change=-0.20, gross_margin=0.40)
    units = 2 * 10 * 0.8 ** -2.0
    assert math.isclose(s.chain_profit_change, units * 1.0 - 20 * 2.0)
    assert math.isclose(s.trade_spend, units * 1.0)


def test_breakeven_margin_gives_zero_profit(inputs):
    s = simulate(inputs, 1, price_change=-0.15, display=True)
    s0 = simulate(inputs, 1, price_change=-0.15, display=True, gross_margin=s.breakeven_margin)
    assert abs(s0.chain_profit_change) < 1e-9


def test_extrapolation_is_flagged(inputs):
    assert simulate(inputs, 1, price_change=-0.5).warnings
    assert not simulate(inputs, 1, price_change=-0.1).warnings


def test_unknown_product(inputs):
    with pytest.raises(KeyError):
        simulate(inputs, 999)
