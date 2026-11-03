# Modelling table — `weekly_panel`

Built by `sql/03_weekly_panel.sql`. One row per week × store × product (524,741 rows), the same rows as `sales`.

## Keys and descriptors

| Column | Description |
| --- | --- |
| `week` | week-ending date (always a Wednesday) |
| `store_id`, `upc` | store and product identifiers |
| `category`, `sub_category`, `manufacturer`, `description` | product attributes; the manufacturer is used as the brand |
| `store_segment`, `state` | store attributes; `AMBIGUOUS` for the 2 stores listed twice with conflicting segments |

## Target and price

| Column | Description |
| --- | --- |
| `units`, `log_units` | units sold, and its natural log (target of the elasticity models) |
| `price`, `log_price` | shelf price actually charged |
| `base_price`, `log_base_price` | regular (non-promoted) price |
| `discount_depth` | 1 − price / base price, floored at 0 |

## Promotion

| Column | Description |
| --- | --- |
| `feature`, `display`, `tpr_only` | raw promotion flags (circular, in-store display, price cut with shelf tag only) |
| `mechanic` | Feature + Display / Feature / Display / TPR only / No promo |
| `any_promo` | 1 if any mechanic is active |

## Dynamics

| Column | Description | Why |
| --- | --- | --- |
| `promo_prev_week` | promotion on the same product in the same store exactly 7 days earlier | post-promotion dip: shoppers stocked up |
| `promo_next_week` | promotion exactly 7 days later | shoppers may wait for a known promotion |
| `prev_week_missing` | 1 if the previous calendar week has no record for this series | lets models separate "no promo" from "no data" |
| `units_prev_week` | units sold the previous calendar week (NULL if missing) | forecasting |
| `promo_weeks_last_4` | number of the 4 previous weeks with a promotion (0–4) | promotion fatigue |

Previous and next weeks are found with a **calendar self-join** (`week − 7 days`), not with `LAG()`: about a third of the series skip weeks, and `LAG()` would then return a row several weeks old. The 4-week count uses a `RANGE` window over calendar time for the same reason. Both are covered by tests.

## Competition and cannibalisation

Computed within the same store, week and category; the product's own row is excluded.

| Column | Description |
| --- | --- |
| `n_competitor_products` | number of other-brand products sold that week |
| `competitor_avg_discount` | average discount depth of other-brand products |
| `competitor_promo_share` | share of other-brand products on any promotion |
| `competitor_support_share` | share of other-brand products on feature or display |
| `own_brand_other_promo_share` | share of the brand's *other* products on promotion (NULL if the brand has a single product in that store-week) |

## Calendar

| Column | Description |
| --- | --- |
| `week_index` | 1 to 156, for trends |
| `year`, `month`, `week_of_year` | calendar parts |
| `holiday` | US holiday falling inside the week: super_bowl, memorial_day, july_4, labor_day, thanksgiving, christmas |
| `pre_holiday` | holiday falling in the 7 days after the week — the stock-up week |

## Quality flags

| Column | Description |
| --- | --- |
| `flag_price_above_base` | shelf price more than 5 % above base price |
| `flag_visits_gt_units` | more baskets than units — impossible, probably a recording error |
