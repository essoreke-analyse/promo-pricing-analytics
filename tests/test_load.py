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
