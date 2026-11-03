# Promo & Pricing Analytics — weekly retail panel data

How much do price cuts and promotions really move sales, and which ones pay off?
This project answers that question on 156 weeks of store-level sales for 55 consumer goods products, the kind of panel data used for Trade Promotion Management and Revenue Growth Management.

> **Status:** data loaded, quality-checked and explored; modelling table built; price elasticities estimated; promotion uplift and ROI measured. Forecasting is in progress.

## Key findings so far

### 1. Promotions: what moves sales

![Raw lift by mechanic](reports/figures/02_raw_lift_by_mechanic.png)

- **Feature + display multiplies weekly sales by 3 to 5**, while a price cut with only a shelf tag adds 20–60 %. The ranking TPR < display < feature < feature + display holds in every category.
- Part of that raw lift is the discount itself: **at equal price, feature and display still add +12 % to +52 %** of volume.
- **No measurable post-promotion dip** at weekly store level: promotions do not mainly pull forward future purchases.
- Pretzels show a winter peak and react to the week before Christmas (+35 %); frozen pizza peaks in Super Bowl week.

### 2. Price sensitivity

![Own-price elasticity by product](reports/figures/04_own_price_elasticity.png)

- **All 55 products have a negative, significant own-price elasticity.** Frozen pizza is the most price-sensitive category (median −2.7: a 10 % price cut lifts units by about 33 %), then cereal (−1.7), mouthwash and pretzels (−1.2).
- **A price cut pays off only for high-margin categories.** A 10 % cut raises gross profit only above a ~40 % gross margin for pizza, ~60 % for cereal and ~85 % for mouthwash and pretzels, where promotional money is better spent on display and feature.
- **Who takes the sales:** DiGiorno is the price reference in frozen pizza (a 10 % DiGiorno price increase lifts private label by 8.5 %); private label captures most switching from Listerine and Crest/Scope; Snyder's discounts mostly cannibalise other Snyder's products.
- **Method choice matters.** 59–84 % of price changes are chain-wide, so week fixed effects remove most of the price variation and give smaller elasticities; both specifications are reported as bounds.

### 3. Promotion return: incremental volume and ROI

![Where promoted volume comes from](reports/figures/07_promo_volume_decomposition.png)

- **A price cut alone mostly discounts sales that would have happened anyway**: with TPR only, 53 % (pizza) to 86 % (pretzels) of promoted units are baseline volume.
- **Feature and display do most of the work**: with feature + display, 59 % to 78 % of promoted units are incremental, and support brings more than half of the extra volume in 10 of the 12 supported combinations.
- **TPR-only promotions never pay off at normal margins** (median break-even margin 46 % to 139 %). They take 22 % of all trade spend but about two thirds of the gross-profit loss at a 35 % margin.
- **Best promotion: display on pretzels** — a 7 % average discount, profitable even at a 25 % margin.
- Recommendation: move TPR-only budgets to display, keep feature + display in pizza and cereal only where the margin exceeds ~35 %, and judge promotions on incremental profit, not volume lift.

### 4. Data quality

- 209 unusable rows excluded (missing or non-positive price or units); ~4,400 suspicious rows flagged and shown not to change the results.
- **Two stores were listed twice with conflicting segments**, which silently duplicated about 13,700 rows in joins; fixed at load time and covered by a test.
- About a third of the store × product series skip weeks, so previous/next-week features use a calendar join instead of `LAG()` — also tested.

Full log: [`docs/data_quality_log.md`](docs/data_quality_log.md) · Details: [`notebooks/01_eda.ipynb`](notebooks/01_eda.ipynb) (exploration) · [`notebooks/02_price_elasticity.ipynb`](notebooks/02_price_elasticity.ipynb) (price models) · [`notebooks/03_promo_uplift.ipynb`](notebooks/03_promo_uplift.ipynb) (uplift and ROI).

## Data

[dunnhumby — *Breakfast at the Frat*](https://www.dunnhumby.com/source-files/): weekly units, spend, shelf and base price, and promotion flags (feature in circular, in-store display, temporary price reduction) for the top products of 4 categories — cold cereal, frozen pizza, pretzels, mouthwash — in 77 stores across Ohio, Kentucky, Indiana and Texas, January 2009 – January 2012. 524,950 rows.

The raw file is not redistributed; see [`data/README.md`](data/README.md) to download it.

## Method

| Step | Notebook / script | Status |
| --- | --- | --- |
| Load into DuckDB, typed tables | `src/promo_pricing/load.py`, `sql/01_load.sql` | done |
| Data quality checks | `sql/02_quality_checks.sql`, [`docs/data_quality_log.md`](docs/data_quality_log.md) | done |
| Exploratory analysis | `notebooks/01_eda.ipynb` | done |
| Modelling table: promo dynamics, competition, holidays | `sql/03_weekly_panel.sql`, [`docs/model_table.md`](docs/model_table.md) | done |
| Own- and cross-price elasticities, robustness, empirical-Bayes shrinkage, break-even margins | `notebooks/02_price_elasticity.ipynb`, `src/promo_pricing/elasticity.py` | done |
| Baseline vs incremental volume, promo ROI, break-even margins | `notebooks/03_promo_uplift.ipynb`, `src/promo_pricing/uplift.py` | done |
| Weekly forecast with rolling backtest (WAPE, bias) | `notebooks/04_forecast_backtest.ipynb` | next |

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

pytest        # 19 tests; pytest.ini already points to src/
```
The loader builds the clean tables (`sql/01_load.sql`) and the modelling table (`sql/03_weekly_panel.sql`). Then open the notebooks in order and select the `.venv` kernel.

## Stack

Python (pandas, statsmodels, matplotlib) · SQL (DuckDB, window functions) · pytest · Git

## Author

Essoréké Kiheou — [LinkedIn](https://www.linkedin.com/in/essor%C3%A9k%C3%A9-kiheou-93996541b)
