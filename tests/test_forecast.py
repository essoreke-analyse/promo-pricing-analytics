from pathlib import Path

import duckdb
import numpy as np
import pytest

from promo_pricing.forecast import NUMERIC, bias, coverage, wape

DB = Path(__file__).resolve().parents[1] / "data" / "frat.duckdb"


# ---- metrics ----

def test_wape_by_hand():
    # errors 2 + 3 = 5 on 10 + 30 = 40 units
    assert wape([10, 30], [12, 27]) == 5 / 40


def test_wape_weights_by_volume():
    # the same 5-unit error weighs less on a big product than on a small one
    assert wape([100], [95]) < wape([10], [5])


def test_bias_sign():
    assert bias([10, 10], [12, 12]) == pytest.approx(0.2)    # over-forecast
    assert bias([10, 10], [8, 8]) == pytest.approx(-0.2)     # under-forecast


def test_coverage():
    assert coverage([5, 10, 20], [0, 0, 0], [10, 10, 10]) == pytest.approx(2 / 3)


# ---- no look-ahead in the forecast features ----

def test_feature_list_has_no_recent_sales():
    for leaky in ["units", "log_units", "units_prev_week", "prev_week_missing", "spend"]:
        assert leaky not in NUMERIC


@pytest.mark.skipif(not DB.exists(), reason="build data/frat.duckdb first (see README)")
def test_moving_average_uses_only_weeks_at_least_4_weeks_old():
    with duckdb.connect(str(DB), read_only=True) as con:
        wrong = con.sql("""
            WITH sample AS (
                SELECT store_id, upc, week, units_ma8_lag4
                FROM forecast_features
                WHERE units_ma8_lag4 IS NOT NULL
                USING SAMPLE reservoir(2000 ROWS) REPEATABLE (42)
            )
            SELECT COUNT(*) FROM sample f
            WHERE ABS(f.units_ma8_lag4 - (
                SELECT AVG(s.units) FROM sales s
                WHERE s.store_id = f.store_id AND s.upc = f.upc
                  AND s.week BETWEEN f.week - INTERVAL 77 DAY AND f.week - INTERVAL 28 DAY
            )) > 1e-9
        """).fetchall()[0][0]
    assert wrong == 0
