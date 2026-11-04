"""Tools the assistant can call. Each tool reads the result tables written by the pipeline
(reports/tables/) and returns plain JSON-serialisable data, so every number in an answer
comes from the analysis, never from the language model's memory.
"""
from __future__ import annotations

import difflib
import json
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from promo_pricing.simulator import load_inputs, simulate

TABLES = Path(__file__).resolve().parents[3] / "reports" / "tables"

CATEGORY_ALIASES = {
    "FROZEN PIZZA": ["pizza", "frozen pizza", "pizzas"],
    "COLD CEREAL": ["cereal", "cereals", "cold cereal", "céréales", "cereales", "breakfast cereal"],
    "ORAL HYGIENE PRODUCTS": ["mouthwash", "mouth wash", "oral hygiene", "bain de bouche", "rinse"],
    "BAG SNACKS": ["pretzels", "pretzel", "bag snacks", "bretzels", "snacks"],
}
# common brand names -> manufacturer code used in the data
BRAND_ALIASES = {
    "digiorno": "TOMBSTONE", "kraft": "TOMBSTONE", "tombstone": "TOMBSTONE",
    "freschetta": "TONYS", "tony's": "TONYS", "tonys": "TONYS",
    "newman's own": "KING", "newman": "KING", "king": "KING",
    "listerine": "WARNER", "warner": "WARNER", "crest": "P & G", "scope": "P & G", "p&g": "P & G", "p & g": "P & G",
    "act": "CHATTEM", "chattem": "CHATTEM", "colgate": "COLGATE",
    "cheerios": "GENERAL MI", "general mills": "GENERAL MI", "kellogg": "KELLOGG", "kellogg's": "KELLOGG",
    "post": "POST FOODS", "quaker": "QUAKER",
    "rold gold": "FRITO LAY", "frito lay": "FRITO LAY", "snyder's": "SNYDER S", "snyders": "SNYDER S",
    "mike-sell's": "MKSL", "mikesells": "MKSL", "mksl": "MKSL", "shultz": "SHULTZ",
    "private label": "PRIVATE LABEL", "store brand": "PRIVATE LABEL", "marque de distributeur": "PRIVATE LABEL",
}
MECHANICS = {"tpr only": "TPR only", "tpr": "TPR only", "price cut only": "TPR only", "display": "Display",
             "feature": "Feature", "feature + display": "Feature + Display", "feature and display": "Feature + Display"}
BRAND_LABEL = {"TOMBSTONE": "DiGiorno (Kraft)", "TONYS": "Freschetta / Tony's", "KING": "Newman's Own",
               "WARNER": "Listerine", "P & G": "Crest / Scope (P&G)", "CHATTEM": "ACT (Chattem)",
               "COLGATE": "Colgate", "GENERAL MI": "General Mills (Cheerios)", "KELLOGG": "Kellogg's",
               "POST FOODS": "Post", "QUAKER": "Quaker", "FRITO LAY": "Rold Gold (Frito-Lay)",
               "SNYDER S": "Snyder's", "MKSL": "Mike-sell's", "SHULTZ": "Shultz", "PRIVATE LABEL": "Private label"}
CATEGORY_LABEL = {"COLD CEREAL": "Cold cereal", "FROZEN PIZZA": "Frozen pizza",
                  "BAG SNACKS": "Pretzels", "ORAL HYGIENE PRODUCTS": "Mouthwash"}


class ToolError(ValueError):
    """Raised for bad arguments; the message is returned to the model so it can correct itself."""


@lru_cache(maxsize=None)
def _table(name: str) -> pd.DataFrame:
    return pd.read_csv(TABLES / name)


@lru_cache(maxsize=1)
def _sim_inputs() -> pd.DataFrame:
    return load_inputs(TABLES)


def _category(value: str) -> str:
    v = value.strip().lower()
    for code, aliases in CATEGORY_ALIASES.items():
        if v == code.lower() or v in aliases or v == CATEGORY_LABEL[code].lower():
            return code
    raise ToolError(f"Unknown category '{value}'. Use one of: pizza, cereal, mouthwash, pretzels.")


def _brand(value: str, category: str) -> str:
    v = value.strip().lower()
    code = BRAND_ALIASES.get(v, value.strip().upper())
    brands = set(_table("cross_price_elasticities.csv").query("category == @category")["brand_whose_sales_move"])
    if code not in brands:
        raise ToolError(f"Brand '{value}' not found in {CATEGORY_LABEL[category]}. Available: {sorted(brands)}")
    return code


def _r(x, nd=3):
    return None if x is None or pd.isna(x) else round(float(x), nd)


# ---------------- tools ----------------

def find_products(query: str, category: str | None = None) -> dict:
    """Fuzzy search of products by name or brand; returns their upc codes."""
    p = _table("products.csv")
    if category:
        p = p[p["category"] == _category(category)]
    q = query.lower()
    words = [w for w in re.split(r"\W+", q) if w]
    scored = []
    for _, r in p.iterrows():
        name = r["product_name"].lower()
        overlap = sum(w in name for w in words) / max(len(words), 1)
        ratio = difflib.SequenceMatcher(None, q, name).ratio()
        scored.append((overlap + 0.5 * ratio, r))
    scored.sort(key=lambda t: -t[0])
    matches = [{"upc": int(r["upc"]), "product_name": r["product_name"], "category": r["category_label"]}
               for score, r in scored[:5] if score > 0.3]
    return {"query": query, "matches": matches, "source": "products.csv"}


def get_category_summary(category: str) -> dict:
    """Median price elasticity of a category and what a 10 % price cut does."""
    c = _category(category)
    row = _table("elasticity_by_category.csv").set_index("category").loc[c]
    return {"category": CATEGORY_LABEL[c], "products": int(row["products"]),
            "median_own_price_elasticity": _r(row["median_elasticity"], 2),
            "median_elasticity_with_week_fixed_effects_lower_bound": _r(row["median_elasticity_week_fe"], 2),
            "units_change_for_10pct_price_cut": _r(row["units_change_for_10pct_cut"]),
            "breakeven_gross_margin_for_10pct_price_cut": _r(row["breakeven_margin_10pct_cut"]),
            "source": "elasticity_by_category.csv"}


def get_product_elasticity(upc: int) -> dict:
    """Own-price elasticity of one product, its confidence interval and promotion effects."""
    t = _table("own_price_elasticities.csv")
    r = t[t["upc"] == int(upc)]
    if r.empty:
        raise ToolError(f"Unknown upc {upc}. Use find_products first.")
    r = r.iloc[0]
    name = _table("products.csv").set_index("upc").loc[int(upc), "product_name"]
    return {"upc": int(upc), "product_name": name, "category": CATEGORY_LABEL[r["category"]],
            "own_price_elasticity": _r(r["elasticity"], 2), "ci95_low": _r(r["ci_low"], 2), "ci95_high": _r(r["ci_high"], 2),
            "elasticity_shrunk_to_category": _r(r["elasticity_shrunk"], 2),
            "elasticity_with_week_fixed_effects": _r(r["elasticity_week_fe"], 2),
            "feature_effect_on_units": _r(r["feature_effect"]), "display_effect_on_units": _r(r["display_effect"]),
            "post_promotion_week_effect": _r(r["post_promo_effect"]), "source": "own_price_elasticities.csv"}


def get_cross_elasticity(category: str, brand_whose_price_changes: str, brand_whose_sales_move: str | None = None) -> dict:
    """Effect of one brand's price on the sales of the other brands of its category."""
    c = _category(category)
    price_brand = _brand(brand_whose_price_changes, c)
    t = _table("cross_price_elasticities.csv").query("category == @c and brand_whose_price_changes == @price_brand")
    if brand_whose_sales_move:
        t = t[t["brand_whose_sales_move"] == _brand(brand_whose_sales_move, c)]
    rows = [{"brand_whose_sales_move": BRAND_LABEL.get(r["brand_whose_sales_move"], r["brand_whose_sales_move"]), "elasticity": _r(r["elasticity"], 2),
             "t_stat": _r(r["t_stat"], 1), "significant": bool(abs(r["t_stat"]) >= 2),
             "is_own_elasticity": r["brand_whose_sales_move"] == price_brand} for _, r in t.iterrows()]
    return {"category": CATEGORY_LABEL[c], "brand_whose_price_changes": BRAND_LABEL.get(price_brand, price_brand), "effects": rows,
            "reading": "positive = substitutes: a 1 % price increase of the first brand raises the other brand's units by that %",
            "source": "cross_price_elasticities.csv"}


def get_promo_performance(category: str, mechanic: str | None = None, gross_margin: float | None = 0.35) -> dict:
    """Baseline vs incremental volume and ROI of promotions by mechanic, at 25, 35 or 45 % gross margin."""
    c = _category(category)
    gross_margin = 0.35 if gross_margin is None else gross_margin
    m = min((0.25, 0.35, 0.45), key=lambda x: abs(x - float(gross_margin)))
    vol = _table("promo_volume_decomposition.csv").query("category == @c")
    roi = _table("promo_roi.csv").query("category == @c and gross_margin == @m")
    if mechanic:
        mech = MECHANICS.get(mechanic.strip().lower())
        if mech is None:
            raise ToolError(f"Unknown mechanic '{mechanic}'. Use: TPR only, Display, Feature, Feature + Display.")
        vol, roi = vol[vol["mechanic"] == mech], roi[roi["mechanic"] == mech]
    out = []
    for _, v in vol.iterrows():
        r = roi[roi["mechanic"] == v["mechanic"]].iloc[0]
        out.append({"mechanic": v["mechanic"], "promo_weeks": int(v["promo_weeks"]), "avg_discount": _r(v["avg_discount"]),
                    "baseline_share_of_promoted_units": _r(v["baseline_share"]),
                    "incremental_share_from_price_cut": _r(v["incremental_from_price_share"]),
                    "incremental_share_from_feature_display": _r(v["incremental_from_support_share"]),
                    "median_breakeven_gross_margin": _r(v["median_breakeven_margin"]),
                    "trade_spend_usd": round(float(r["trade_spend"])), "incremental_profit_usd": round(float(r["incremental_profit"])),
                    "roi": _r(r["roi"], 2), "share_of_weeks_profitable": _r(r["share_of_weeks_profitable"])})
    note = None if m == float(gross_margin) else f"Results exist for 25, 35 and 45 % margins only; {m:.0%} used."
    return {"category": CATEGORY_LABEL[c], "gross_margin_assumed": m, "mechanics": out, "note": note,
            "source": "promo_volume_decomposition.csv, promo_roi.csv"}


def get_forecast_accuracy(segment: str | None = "all weeks") -> dict:
    """Backtest accuracy (WAPE, bias) of the four forecast models and the P10-P90 coverage."""
    t = _table("forecast_backtest_metrics.csv")
    seg = (segment or "all weeks").strip().lower()
    if seg in {"promo", "promotion", "promotions", "promotion weeks"}:
        seg = "promotion weeks"
    elif seg in {"no promo", "normal", "normal weeks", "weeks without promotion"}:
        seg = "weeks without promotion"
    elif seg not in {"all weeks"}:
        try:
            seg = "category " + _category(segment)
        except ToolError:
            raise ToolError("segment must be 'all weeks', 'promotion weeks', 'weeks without promotion' or a category")
    rows = t[t["segment"] == seg]
    models = {r["model"]: {"wape": _r(r["wape"]), "bias": _r(r["bias"])} for _, r in rows.iterrows() if r["model"] != "lightgbm P10-P90"}
    cov = rows.loc[rows["model"] == "lightgbm P10-P90", "coverage"]
    return {"segment": seg, "models": models, "p10_p90_coverage": _r(cov.iloc[0]) if len(cov) else None,
            "setup": "7 forecast dates x 4 weeks ahead over the last 28 weeks; promotion plan known in advance",
            "source": "forecast_backtest_metrics.csv"}


def simulate_promotion(upc: int, price_change: float, feature: bool | None = False, display: bool | None = False,
                       gross_margin: float | None = 0.35) -> dict:
    """What-if for one product: price change (e.g. -0.10 for a 10 % cut), feature, display, margin."""
    try:
        margin = 0.35 if gross_margin is None else float(gross_margin)
        s = simulate(_sim_inputs(), int(upc), float(price_change), bool(feature), bool(display), margin)
    except (KeyError, ValueError) as e:
        raise ToolError(str(e))
    d = s.to_dict()
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items()} | {
        "unit": "chain = all stores carrying the product, one week", "source": "simulator (own_price_elasticities.csv, products.csv)"}


def get_data_quality() -> dict:
    """Results of the data-quality checks on the raw data."""
    t = _table("data_quality.csv")
    return {"checks": dict(zip(t["check"], t["value"].astype(str))), "source": "data_quality.csv"}


TOOLS = {f.__name__: f for f in [find_products, get_category_summary, get_product_elasticity, get_cross_elasticity,
                                 get_promo_performance, get_forecast_accuracy, simulate_promotion, get_data_quality]}

_CATEGORY_PARAM = {"type": "string", "description": "pizza, cereal, mouthwash or pretzels"}
# Optional parameters accept null: some providers (e.g. Groq) validate tool calls strictly,
# and models often send null for "no value".
_OPTIONAL_CATEGORY = {"type": ["string", "null"], "description": "optional: pizza, cereal, mouthwash or pretzels"}
TOOL_SCHEMAS = [
    {"name": "find_products", "description": "Find products (and their upc code) by name or brand. Call this before any product-level tool.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "category": _OPTIONAL_CATEGORY}, "required": ["query"]}},
    {"name": "get_category_summary", "description": "Median own-price elasticity of a category, units change and break-even gross margin for a 10 % price cut.",
     "parameters": {"type": "object", "properties": {"category": _CATEGORY_PARAM}, "required": ["category"]}},
    {"name": "get_product_elasticity", "description": "Own-price elasticity of one product with 95 % interval, feature/display effects and post-promotion effect.",
     "parameters": {"type": "object", "properties": {"upc": {"type": "integer"}}, "required": ["upc"]}},
    {"name": "get_cross_elasticity", "description": "Cross-price elasticities: effect of one brand's price on the units of other brands in the same category.",
     "parameters": {"type": "object", "properties": {"category": _CATEGORY_PARAM,
                    "brand_whose_price_changes": {"type": "string"}, "brand_whose_sales_move": {"type": ["string", "null"]}},
                    "required": ["category", "brand_whose_price_changes"]}},
    {"name": "get_promo_performance", "description": "Baseline vs incremental volume, trade spend, incremental profit, ROI and break-even margin of promotions in a category, by mechanic (TPR only, Display, Feature, Feature + Display).",
     "parameters": {"type": "object", "properties": {"category": _CATEGORY_PARAM,
                    "mechanic": {"type": ["string", "null"], "description": "optional: TPR only, Display, Feature or Feature + Display"},
                    "gross_margin": {"type": ["number", "null"], "description": "0.25, 0.35 or 0.45; default 0.35"}}, "required": ["category"]}},
    {"name": "get_forecast_accuracy", "description": "Backtest WAPE and bias of the forecast models (seasonal naive, moving average, regression, LightGBM) and P10-P90 coverage, for all weeks, promotion weeks, weeks without promotion or a category.",
     "parameters": {"type": "object", "properties": {"segment": {"type": ["string", "null"],
                    "description": "optional, default 'all weeks': 'all weeks', 'promotion weeks', 'weeks without promotion' or a category"}}}},
    {"name": "simulate_promotion", "description": "Simulate one promoted week for a product across all its stores: volume, revenue and gross profit change, ROI, break-even margin.",
     "parameters": {"type": "object", "properties": {"upc": {"type": "integer"},
                    "price_change": {"type": "number", "description": "relative change, e.g. -0.10 for a 10 % price cut"},
                    "feature": {"type": ["boolean", "null"]}, "display": {"type": ["boolean", "null"]},
                    "gross_margin": {"type": ["number", "null"], "description": "share of base price, default 0.35"}},
                    "required": ["upc", "price_change"]}},
    {"name": "get_data_quality", "description": "Data-quality checks on the raw data (rows, duplicates, missing values, flagged rows).",
     "parameters": {"type": "object", "properties": {}}},
]


def call_tool(name: str, arguments: dict | str) -> str:
    """Run a tool and return its result as a JSON string (errors are returned, not raised)."""
    if isinstance(arguments, str):
        arguments = json.loads(arguments or "{}")
    arguments = {k: v for k, v in (arguments or {}).items() if v is not None}   # null = use the default
    if name not in TOOLS:
        return json.dumps({"error": f"unknown tool {name}"})
    try:
        return json.dumps(TOOLS[name](**arguments), default=str)
    except ToolError as e:
        return json.dumps({"error": str(e)})
    except TypeError as e:
        return json.dumps({"error": f"bad arguments for {name}: {e}"})
