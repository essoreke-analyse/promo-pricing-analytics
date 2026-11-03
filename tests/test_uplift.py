import numpy as np
import pandas as pd

from promo_pricing.uplift import breakeven_margin_of_promo, promo_economics


def one_promo(units=300.0, baseline=100.0, base_price=4.0, price=3.0):
    return pd.DataFrame({"units": [units], "baseline_units": [baseline],
                         "incremental_units": [units - baseline],
                         "base_price": [base_price], "price": [price]})


def test_trade_spend_counts_every_promoted_unit():
    e = promo_economics(one_promo(), gross_margin=0.3)
    assert e["trade_spend"].iloc[0] == 300 * 1.0          # $1 discount on all 300 units
    assert e["subsidised_spend"].iloc[0] == 100 * 1.0     # of which 100 would have sold anyway


def test_incremental_profit_by_hand():
    # margin 50 % of $4 = $2 per unit normally, $1 during the promotion
    e = promo_economics(one_promo(), gross_margin=0.5)
    profit_promo, profit_baseline = 300 * 1.0, 100 * 2.0
    assert np.isclose(e["incremental_profit"].iloc[0], profit_promo - profit_baseline)


def test_breakeven_margin_gives_zero_incremental_profit():
    p = one_promo()
    m = breakeven_margin_of_promo(p.units, p.baseline_units, p.base_price, p.price)[0]
    e = promo_economics(p, gross_margin=m)
    assert np.isclose(e["incremental_profit"].iloc[0], 0.0)


def test_no_breakeven_when_promo_adds_no_volume():
    p = one_promo(units=100.0, baseline=100.0)
    assert np.isnan(breakeven_margin_of_promo(p.units, p.baseline_units, p.base_price, p.price)[0])
