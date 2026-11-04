"""What-if simulation of one promoted week for one product, from the fitted models.

units = normal weekly units x (1 + price change) ** elasticity
                             x (1 + feature effect) if featured
                             x (1 + display effect) if on display

The elasticity used is the shrunk estimate of notebook 02 (more stable for products sold
in few stores). Profit is gross profit with a margin expressed as a share of the base price.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

TABLES = Path(__file__).resolve().parents[2] / "reports" / "tables"
OBSERVED_MAX_DISCOUNT = 0.40     # deeper cuts are rare in the data: results become extrapolation


@dataclass
class Simulation:
    upc: int
    product_name: str
    category: str
    price_change: float
    feature: bool
    display: bool
    gross_margin: float
    base_price: float
    promo_price: float
    elasticity: float
    normal_units_per_store: float
    units_per_store: float
    volume_change: float
    n_stores: int
    chain_normal_units: float
    chain_units: float
    chain_revenue_change: float
    chain_profit_change: float
    trade_spend: float
    roi: float | None
    breakeven_margin: float | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def load_inputs(tables: Path = TABLES) -> pd.DataFrame:
    """One row per product: names, normal level, base price, elasticity and promo effects."""
    products = pd.read_csv(tables / "products.csv")
    el = pd.read_csv(tables / "own_price_elasticities.csv")[
        ["upc", "elasticity", "elasticity_shrunk", "ci_low", "ci_high", "feature_effect", "display_effect"]]
    return products.merge(el, on="upc", how="left")


def simulate(inputs: pd.DataFrame, upc: int, price_change: float = -0.10, feature: bool = False,
             display: bool = False, gross_margin: float = 0.35) -> Simulation:
    """price_change: relative change of the shelf price vs base price (-0.10 = 10 % cut)."""
    rows = inputs[inputs["upc"] == upc]
    if rows.empty:
        raise KeyError(f"unknown product {upc}")
    r = rows.iloc[0]
    warnings = []
    if not -0.9 < price_change < 1:
        raise ValueError("price_change must be between -90 % and +100 %")
    if price_change < -OBSERVED_MAX_DISCOUNT:
        warnings.append(f"Discounts deeper than {OBSERVED_MAX_DISCOUNT:.0%} are rare in the data: treat the result as an extrapolation.")
    if price_change > 0:
        warnings.append("Price increases are rare in the data: the elasticity is assumed symmetric.")
    feat_eff = float(r["feature_effect"]) if feature else 0.0
    disp_eff = float(r["display_effect"]) if display else 0.0
    if feature and feat_eff == 0:
        warnings.append("This product was never featured in the data: no feature effect can be estimated.")
    if display and disp_eff == 0:
        warnings.append("This product was never on display in the data: no display effect can be estimated.")

    e = float(r["elasticity_shrunk"])
    base_price = float(r["avg_base_price"])
    promo_price = base_price * (1 + price_change)
    normal = float(r["normal_weekly_units_per_store"])
    units = normal * (1 + price_change) ** e * (1 + feat_eff) * (1 + disp_eff)

    n = int(r["n_stores"])
    unit_margin = gross_margin * base_price
    discount = max(base_price - promo_price, 0.0)
    chain_normal, chain_units = normal * n, units * n
    revenue_change = chain_units * promo_price - chain_normal * base_price
    profit_change = chain_units * (unit_margin - (base_price - promo_price)) - chain_normal * unit_margin
    trade_spend = discount * chain_units
    roi = profit_change / trade_spend if trade_spend > 0 else None
    incr = chain_units - chain_normal
    breakeven = (discount * chain_units) / (base_price * incr) if (incr > 0 and discount > 0) else None
    if unit_margin - discount < 0:
        warnings.append("The discount is larger than the unit margin: every unit is sold at a loss.")

    return Simulation(
        upc=int(upc), product_name=r["product_name"], category=r["category_label"],
        price_change=price_change, feature=feature, display=display, gross_margin=gross_margin,
        base_price=base_price, promo_price=promo_price, elasticity=e,
        normal_units_per_store=normal, units_per_store=units, volume_change=units / normal - 1,
        n_stores=n, chain_normal_units=chain_normal, chain_units=chain_units,
        chain_revenue_change=revenue_change, chain_profit_change=profit_change,
        trade_spend=trade_spend, roi=roi, breakeven_margin=breakeven, warnings=warnings)
