"""Light, aggregated tables for the Streamlit app and the LLM assistant.

Only derived results are published (no raw weekly data): one row per product with its
normal-week level, category-week totals of the forecast backtest, and a handful of
example forecast series.
"""
from __future__ import annotations

import re

import duckdb
import pandas as pd

BRAND_PREFIX = {
    "PL": "Private label", "GM": "General Mills", "KELL": "Kellogg's", "QKER": "Quaker", "POST": "Post",
    "DIGRN": "DiGiorno", "DIGIORNO": "DiGiorno", "NWMN OWN": "Newman's Own", "FRSC": "Freschetta",
    "RLDGLD": "Rold Gold", "SNYDR": "Snyder's", "MKSL": "Mike-sell's", "SHURGD": "Shultz",
    "LSTRNE": "Listerine", "CREST": "Crest", "SCOPE": "Scope", "ACT": "ACT", "COLG": "Colgate",
}
WORDS = {"ANTSPTC": "antiseptic", "ANTSPC": "antiseptic", "MW": "mouthwash", "MTHWS": "mouthwash",
         "RNS": "rinse", "PZ": "pizza", "PEPP": "pepperoni", "PEPPRN": "pepperoni", "SUPRM": "supreme",
         "SR": "self-rising", "CHS": "cheese", "PRTZL": "pretzels", "HNY": "honey", "BN": "bunches",
         "OTS": "oats", "BT SZ": "bite size", "FRSTD": "frosted", "SHRD WHT": "shredded wheat",
         "TOASTD": "toasted", "CL": "cool", "BL": "blue", "SPG": "spring", "MNT": "mint",
         "FRS BRST": "fresh burst", "RSTR": "restoring", "SPLSH": "splash", "BBLGUM": "bubblegum",
         "FLUOR": "fluoride", "A/CAV": "anticavity", "WHTG": "whitening", "CLN": "clean", "TP": "",
         "PH": "pro-health", "FM SZ": "family size", "HNYBNCH": "honey bunches", "OT ALM": "oats almonds",
         "RSTD": "roasted", "BRCK OVN ITL": "brick oven Italian", "FF": "fat-free", "WHT": "wheat"}

CATEGORY_LABEL = {"COLD CEREAL": "Cold cereal", "FROZEN PIZZA": "Frozen pizza",
                  "BAG SNACKS": "Pretzels", "ORAL HYGIENE PRODUCTS": "Mouthwash"}


def readable_name(description: str, size: str) -> str:
    """'DIGRN PEPP PIZZA' -> 'DiGiorno pepperoni pizza (28.3 OZ)'."""
    d = description.upper().strip()
    brand = ""
    for prefix in sorted(BRAND_PREFIX, key=len, reverse=True):
        if d.startswith(prefix + " ") or d == prefix:
            brand, d = BRAND_PREFIX[prefix], d[len(prefix):].strip()
            break
    for abbr in sorted(WORDS, key=len, reverse=True):
        d = re.sub(rf"(?<![A-Z]){re.escape(abbr)}(?![A-Z])", WORDS[abbr], d)
    rest = re.sub(r"\s+", " ", d.lower()).strip()
    return f"{brand} {rest} ({size.lower()})".strip()


def build_app_tables(db_path: str, out_dir, backtest: pd.DataFrame | None = None) -> None:
    with duckdb.connect(db_path, read_only=True) as con:
        products = con.sql("""
            SELECT w.upc, w.category, w.manufacturer, w.description, p.product_size,
                   COUNT(DISTINCT w.store_id)                                AS n_stores,
                   AVG(w.units) FILTER (WHERE w.any_promo = 0)               AS normal_weekly_units_per_store,
                   AVG(w.base_price)                                         AS avg_base_price,
                   AVG(w.any_promo)                                          AS share_of_weeks_on_promo
            FROM weekly_panel w JOIN products p USING (upc)
            GROUP BY ALL ORDER BY category, manufacturer, description
        """).df()
    products["product_name"] = [readable_name(d, s) for d, s in zip(products["description"], products["product_size"])]
    products["category_label"] = products["category"].map(CATEGORY_LABEL)
    products.to_csv(out_dir / "products.csv", index=False)

    if backtest is None:
        return
    models = ["units", "seasonal_naive", "moving_average", "regression", "lightgbm"]
    cat_week = backtest.groupby(["category", "week"], observed=True)[models].sum().reset_index()
    cat_week.to_csv(out_dir / "forecast_category_weekly.csv", index=False)

    # one example series per category: its best-selling product in its largest store
    examples = []
    for cat, g in backtest.groupby("category", observed=True):
        upc, store = g.groupby(["upc", "store_id"], observed=True)["units"].sum().idxmax()
        examples.append(g[(g["upc"] == upc) & (g["store_id"] == store)])
    ex = pd.concat(examples)[["category", "upc", "store_id", "week", "horizon", "any_promo", "units",
                              "moving_average", "lightgbm", "lightgbm_p10", "lightgbm_p90"]]
    ex.to_csv(out_dir / "forecast_examples.csv", index=False)
