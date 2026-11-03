from pathlib import Path

import duckdb
import pytest

DB = Path(__file__).resolve().parents[1] / "data" / "frat.duckdb"

pytestmark = pytest.mark.skipif(not DB.exists(), reason="build data/frat.duckdb first (see README)")


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(DB), read_only=True)
    yield c
    c.close()


def scalar(con, query):
    return con.sql(query).fetchall()[0][0]


def test_keys_are_unique(con):
    assert scalar(con, "SELECT COUNT(*) - COUNT(DISTINCT (week, store_id, upc)) FROM sales") == 0


def test_prices_and_units_are_positive(con):
    assert scalar(con, "SELECT COUNT(*) FROM sales WHERE price <= 0 OR base_price <= 0 OR units <= 0") == 0


def test_mechanic_matches_flags(con):
    wrong = scalar(con, """
        SELECT COUNT(*) FROM sales WHERE
            (mechanic = 'Feature + Display' AND NOT (feature = 1 AND display = 1)) OR
            (mechanic = 'TPR only' AND (tpr_only = 0 OR feature = 1 OR display = 1)) OR
            (mechanic = 'No promo' AND feature + display + tpr_only > 0)
    """)
    assert wrong == 0


def test_every_sale_has_a_store_and_a_product(con):
    assert scalar(con, "SELECT COUNT(*) FROM sales ANTI JOIN stores USING (store_id)") == 0
    assert scalar(con, "SELECT COUNT(*) FROM sales ANTI JOIN products USING (upc)") == 0


# ---- stores lookup ----

def test_one_row_per_store(con):
    assert scalar(con, "SELECT COUNT(*) - COUNT(DISTINCT store_id) FROM stores") == 0


# ---- weekly_panel (sql/03_weekly_panel.sql) ----

def test_panel_has_one_row_per_sale(con):
    assert scalar(con, "SELECT COUNT(*) FROM weekly_panel") == scalar(con, "SELECT COUNT(*) FROM sales")
    assert scalar(con, "SELECT COUNT(*) - COUNT(DISTINCT (week, store_id, upc)) FROM weekly_panel") == 0


def test_previous_week_uses_calendar_not_previous_row(con):
    # When the series skips a week, the previous row is NOT last week:
    # promo_prev_week must be 0 and prev_week_missing must be 1.
    wrong = scalar(con, """
        WITH g AS (
            SELECT store_id, upc, week,
                   LAG(week) OVER (PARTITION BY store_id, upc ORDER BY week) AS prev_row_week
            FROM sales
        )
        SELECT COUNT(*) FROM g JOIN weekly_panel w USING (store_id, upc, week)
        WHERE g.week - g.prev_row_week > 7
          AND (w.promo_prev_week <> 0 OR w.prev_week_missing <> 1)
    """)
    assert wrong == 0


def test_promo_weeks_last_4_is_between_0_and_4(con):
    assert scalar(con, "SELECT COUNT(*) FROM weekly_panel WHERE promo_weeks_last_4 NOT BETWEEN 0 AND 4") == 0


def test_competitor_shares_are_valid(con):
    bad = scalar(con, """
        SELECT COUNT(*) FROM weekly_panel
        WHERE competitor_promo_share   NOT BETWEEN 0 AND 1
           OR competitor_support_share NOT BETWEEN 0 AND 1
           OR own_brand_other_promo_share NOT BETWEEN 0 AND 1
    """)
    assert bad == 0


def test_every_year_has_each_holiday(con):
    assert scalar(con, "SELECT COUNT(DISTINCT holiday || year) FROM calendar WHERE holiday IS NOT NULL") == 18
