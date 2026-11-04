"""Run the whole project end to end and save every result table to reports/tables/.

Usage (from the repository root, after `pip install -e .`):
    python -m promo_pricing.pipeline                     # everything (about 8 minutes)
    python -m promo_pricing.pipeline --skip-forecast     # without the backtest (about 2 minutes)
    python -m promo_pricing.pipeline --rebuild           # rebuild the database from the Excel file first
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import duckdb
import pandas as pd

from promo_pricing import elasticity, forecast, uplift
from promo_pricing.app_data import build_app_tables
from promo_pricing.load import build_database

ROOT = Path(__file__).resolve().parents[2]
XLSX = ROOT / "data" / "dunnhumby_breakfast_at_the_frat.xlsx"
DB = ROOT / "data" / "frat.duckdb"
OUT = ROOT / "reports" / "tables"

log = logging.getLogger("pipeline")


def step(name):
    """Decorator that logs the start, end and duration of a pipeline step."""
    def wrap(fn):
        def run(*args, **kwargs):
            log.info("start  %s", name)
            t = time.time()
            result = fn(*args, **kwargs)
            log.info("done   %s (%.0f s)", name, time.time() - t)
            return result
        return run
    return wrap


@step("database")
def ensure_database(rebuild: bool) -> None:
    if rebuild or not DB.exists():
        if not XLSX.exists():
            raise FileNotFoundError(f"{XLSX} not found: download the data first (see data/README.md)")
        DB.unlink(missing_ok=True)
        build_database(XLSX, DB)


@step("data quality checks")
def quality_checks() -> pd.DataFrame:
    sql = (ROOT / "sql" / "02_quality_checks.sql").read_text(encoding="utf-8")
    rows = []
    with duckdb.connect(str(DB), read_only=True) as con:
        for statement in sql.split(";"):
            if "SELECT" not in statement:
                continue
            res = con.sql(statement).df()
            for col in res.columns:
                if len(res) == 1:                          # one-row checks: one line per column
                    rows.append({"check": col, "value": res[col].iloc[0]})
            if len(res) > 1:                               # the promo-flag combination table
                for _, r in res.iterrows():
                    rows.append({"check": "rows with FEATURE/DISPLAY/TPR_ONLY = "
                                 f"{r['FEATURE']}/{r['DISPLAY']}/{r['TPR_ONLY']}", "value": r["n_rows"]})
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "data_quality.csv", index=False)
    return out


@step("price elasticities")
def price_elasticities(panel: pd.DataFrame) -> pd.DataFrame:
    main = elasticity.shrink_to_category(elasticity.fit_own_elasticities(panel, spec="time"))
    week_fe = elasticity.fit_own_elasticities(panel, spec="week_fe")
    own = main.merge(week_fe[["upc", "elasticity"]].rename(columns={"elasticity": "elasticity_week_fe"}), on="upc")
    own.to_csv(OUT / "own_price_elasticities.csv", index=False)

    cross = []
    for cat in sorted(panel["category"].unique()):
        est, tstat = elasticity.brand_cross_elasticities(str(DB), cat)
        long = est.stack().rename("elasticity").to_frame().join(tstat.stack().rename("t_stat"))
        long.index.names = ["brand_whose_sales_move", "brand_whose_price_changes"]
        cross.append(long.reset_index().assign(category=cat))
    pd.concat(cross).to_csv(OUT / "cross_price_elasticities.csv", index=False)

    summary = own.groupby("category").agg(
        median_elasticity=("elasticity", "median"),
        median_elasticity_week_fe=("elasticity_week_fe", "median"),
        products=("upc", "count"))
    summary["units_change_for_10pct_cut"] = summary["median_elasticity"].apply(
        lambda e: elasticity.volume_multiplier(e, -0.10) - 1)
    summary["breakeven_margin_10pct_cut"] = summary["median_elasticity"].apply(
        lambda e: elasticity.breakeven_margin(e, 0.10))
    summary.to_csv(OUT / "elasticity_by_category.csv")
    return own


@step("promotion uplift and ROI")
def promotion_return(panel: pd.DataFrame) -> pd.DataFrame:
    promos = uplift.decompose_promotions(panel, uplift.fit_product_models(panel))
    promos["breakeven_margin"] = uplift.breakeven_margin_of_promo(
        promos["units"], promos["baseline_units"], promos["base_price"], promos["price"])

    g = promos.groupby(["category", "mechanic"])
    volume = pd.DataFrame({
        "promo_weeks": g.size(),
        "avg_discount": g["discount_depth"].mean(),
        "baseline_share": g["baseline_units"].sum() / g["units"].sum(),
        "incremental_from_price_share": g["incr_from_price"].sum() / g["units"].sum(),
        "incremental_from_support_share": g["incr_from_support"].sum() / g["units"].sum(),
        "median_breakeven_margin": g["breakeven_margin"].median(),
    })
    volume.to_csv(OUT / "promo_volume_decomposition.csv")

    scenarios = []
    for margin in (0.25, 0.35, 0.45):
        e = uplift.promo_economics(promos, gross_margin=margin).groupby(["category", "mechanic"])
        scenarios.append(pd.DataFrame({
            "gross_margin": margin,
            "trade_spend": e["trade_spend"].sum(),
            "spend_on_baseline": e["subsidised_spend"].sum(),
            "incremental_profit": e["incremental_profit"].sum(),
            "share_of_weeks_profitable": e["incremental_profit"].apply(lambda x: (x > 0).mean()),
        }).assign(roi=lambda d: d["incremental_profit"] / d["trade_spend"]))
    pd.concat(scenarios).to_csv(OUT / "promo_roi.csv")
    return volume


@step("forecast backtest")
def forecast_backtest() -> pd.DataFrame:
    feats = forecast.load_features(str(DB))
    bt, importance = forecast.rolling_backtest(feats, n_folds=7, horizon=4)
    models = ["seasonal_naive", "moving_average", "regression", "lightgbm"]
    segments = {"all weeks": bt, "weeks without promotion": bt[bt["any_promo"] == 0],
                "promotion weeks": bt[bt["any_promo"] == 1]}
    segments.update({f"category {c}": bt[bt["category"] == c] for c in bt["category"].unique()})
    rows = []
    for seg, d in segments.items():
        for m in models:
            rows.append({"segment": seg, "model": m, "wape": forecast.wape(d["units"], d[m]),
                         "bias": forecast.bias(d["units"], d[m])})
        rows.append({"segment": seg, "model": "lightgbm P10-P90",
                     "coverage": forecast.coverage(d["units"], d["lightgbm_p10"], d["lightgbm_p90"])})
    metrics = pd.DataFrame(rows)
    metrics.to_csv(OUT / "forecast_backtest_metrics.csv", index=False)
    importance.rename("gain").to_csv(OUT / "forecast_feature_importance.csv")
    bt.to_parquet(OUT / "forecast_backtest_predictions.parquet", index=False)
    return metrics


@step("app and assistant tables")
def app_tables() -> None:
    preds = OUT / "forecast_backtest_predictions.parquet"
    backtest = pd.read_parquet(preds) if preds.exists() else None
    build_app_tables(str(DB), OUT, backtest)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild", action="store_true", help="rebuild the database from the Excel file")
    parser.add_argument("--skip-forecast", action="store_true", help="skip the forecast backtest (slowest step)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    ensure_database(args.rebuild)
    quality_checks()
    panel = elasticity.load_panel(str(DB))
    price_elasticities(panel)
    promotion_return(panel)
    if not args.skip_forecast:
        forecast_backtest()
    app_tables()

    log.info("all done in %.0f s — results in %s", time.time() - t0, OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
