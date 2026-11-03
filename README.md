# Promo & Pricing Analytics — weekly retail panel data

How much do price cuts and promotions really move sales, and which ones pay off?
This project answers that question on 156 weeks of store-level sales for 55 consumer goods products, the kind of panel data used for Trade Promotion Management and Revenue Growth Management.

> **Status:** Day 1 done — data loaded, quality-checked and explored. Elasticity models, uplift decomposition and forecasting are in progress.

## Key findings so far

![Raw lift by mechanic](reports/figures/02_raw_lift_by_mechanic.png)

1. **Feature + display multiplies weekly sales by 3 to 5**, while a price cut with only a shelf tag adds 20–60 %. The ranking TPR < display < feature < feature + display holds in every category.
2. **Categories react very differently to price.** Preliminary log-log elasticities, within store × product: frozen pizza −2.7, cereal −1.6, mouthwash and pretzels −1.2.
3. **Pretzels barely respond to price cuts without support**: deep discounts there mostly give margin away.
4. **Support has value beyond the discount**: controlling for price, feature or display still add 30–70 % volume.

Details and charts: [`notebooks/01_eda.ipynb`](notebooks/01_eda.ipynb).

## Data

[dunnhumby — *Breakfast at the Frat*](https://www.dunnhumby.com/source-files/): weekly units, spend, shelf and base price, and promotion flags (feature in circular, in-store display, temporary price reduction) for the top products of 4 categories — cold cereal, frozen pizza, pretzels, mouthwash — in 77 stores across Ohio, Kentucky, Indiana and Texas, January 2009 – January 2012. 524,950 rows.

The raw file is not redistributed; see [`data/README.md`](data/README.md) to download it.

## Method

| Step | Notebook / script | Status |
| --- | --- | --- |
| Load into DuckDB, typed tables | `src/promo_pricing/load.py`, `sql/01_load.sql` | done |
| Data quality checks | `sql/02_quality_checks.sql`, [`docs/data_quality_log.md`](docs/data_quality_log.md) | done |
| Exploratory analysis | `notebooks/01_eda.ipynb` | done |
| Own- and cross-price elasticities with store and week fixed effects | `notebooks/02_price_elasticity.ipynb` | next |
| Baseline vs incremental volume, post-promotion dip, promo ROI | `notebooks/03_promo_uplift.ipynb` | planned |
| Weekly forecast with rolling backtest (WAPE, bias) | `notebooks/04_forecast_backtest.ipynb` | planned |

## How to run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    |    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# put the downloaded workbook in data/ (see data/README.md)

# Windows (PowerShell)
$env:PYTHONPATH="src"; python -m promo_pricing.load data\dunnhumby_breakfast_at_the_frat.xlsx data\frat.duckdb
# macOS / Linux
PYTHONPATH=src python -m promo_pricing.load data/dunnhumby_breakfast_at_the_frat.xlsx data/frat.duckdb

pytest
```
Then open `notebooks/01_eda.ipynb` and select the `.venv` kernel.

## Stack

Python (pandas, statsmodels, matplotlib) · SQL (DuckDB) · pytest · Git

## Author

Essoréké Kiheou — [LinkedIn](https://www.linkedin.com/in/essor%C3%A9k%C3%A9-kiheou-93996541b)
