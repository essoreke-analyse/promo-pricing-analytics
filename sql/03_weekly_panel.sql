-- 03_weekly_panel.sql
-- Modelling table: one row per week x store x product, with the variables needed
-- for price elasticity, promo uplift and forecasting.
-- Variable definitions: docs/model_table.md

-- 1. US holidays that move grocery sales. A week (ending on a Wednesday) is flagged
--    when the holiday falls within its 7 days.
CREATE OR REPLACE TABLE holidays AS
SELECT * FROM (VALUES
    ('super_bowl',   DATE '2009-02-01'), ('super_bowl',   DATE '2010-02-07'), ('super_bowl',   DATE '2011-02-06'),
    ('memorial_day', DATE '2009-05-25'), ('memorial_day', DATE '2010-05-31'), ('memorial_day', DATE '2011-05-30'),
    ('july_4',       DATE '2009-07-04'), ('july_4',       DATE '2010-07-04'), ('july_4',       DATE '2011-07-04'),
    ('labor_day',    DATE '2009-09-07'), ('labor_day',    DATE '2010-09-06'), ('labor_day',    DATE '2011-09-05'),
    ('thanksgiving', DATE '2009-11-26'), ('thanksgiving', DATE '2010-11-25'), ('thanksgiving', DATE '2011-11-24'),
    ('christmas',    DATE '2009-12-25'), ('christmas',    DATE '2010-12-25'), ('christmas',    DATE '2011-12-25')
) AS h(holiday, holiday_date);

CREATE OR REPLACE TABLE calendar AS
WITH weeks AS (
    SELECT DISTINCT week FROM sales
)
SELECT
    w.week,
    DENSE_RANK() OVER (ORDER BY w.week)                         AS week_index,   -- 1..156, for trends
    YEAR(w.week)                                                AS year,
    MONTH(w.week)                                               AS month,
    WEEKOFYEAR(w.week)                                          AS week_of_year,
    -- holiday falls inside the week (NULL if none)
    MAX(h.holiday) FILTER (WHERE h.holiday_date >  w.week - INTERVAL 7 DAY
                             AND h.holiday_date <= w.week)      AS holiday,
    -- holiday falls in the 7 days AFTER the week: shoppers stock up beforehand
    MAX(h.holiday) FILTER (WHERE h.holiday_date >  w.week
                             AND h.holiday_date <= w.week + INTERVAL 7 DAY) AS pre_holiday
FROM weeks w
LEFT JOIN holidays h
       ON h.holiday_date >  w.week - INTERVAL 7 DAY
      AND h.holiday_date <= w.week + INTERVAL 7 DAY
GROUP BY w.week;

-- 2. Competitive context within the same store, week and category.
--    "Other brands" = other manufacturers; "own brand" = the brand's other products
--    (cannibalisation). Own row is excluded by subtracting it from the group totals.
CREATE OR REPLACE TABLE category_context AS
WITH s AS (
    SELECT s.*, p.category, p.manufacturer
    FROM sales s JOIN products p USING (upc)
),
brand_week AS (            -- totals per store x week x category x manufacturer
    SELECT store_id, week, category, manufacturer,
           COUNT(*)                                   AS n,
           SUM(discount_depth)                        AS sum_disc,
           SUM((mechanic <> 'No promo')::INT)         AS n_promo,
           SUM((feature = 1 OR display = 1)::INT)     AS n_support
    FROM s GROUP BY ALL
),
cat_week AS (              -- same totals per store x week x category
    SELECT store_id, week, category,
           SUM(n) AS n, SUM(sum_disc) AS sum_disc, SUM(n_promo) AS n_promo, SUM(n_support) AS n_support
    FROM brand_week GROUP BY ALL
)
SELECT
    s.week, s.store_id, s.upc,
    -- other brands in the category (competitors)
    c.n - b.n                                                           AS n_competitor_products,
    (c.sum_disc - b.sum_disc)   / NULLIF(c.n - b.n, 0)                  AS competitor_avg_discount,
    (c.n_promo - b.n_promo)     / NULLIF(c.n - b.n, 0)                  AS competitor_promo_share,
    (c.n_support - b.n_support) / NULLIF(c.n - b.n, 0)                  AS competitor_support_share,
    -- other products of the same brand (cannibalisation)
    (b.n_promo - (s.mechanic <> 'No promo')::INT) / NULLIF(b.n - 1, 0)  AS own_brand_other_promo_share
FROM s
JOIN brand_week b USING (store_id, week, category, manufacturer)
JOIN cat_week   c USING (store_id, week, category);

-- 3. The panel itself.
--    Lags and leads use a calendar self-join (week - 7 days), not LAG(), because a series
--    can skip weeks: LAG() would then return a row that is several weeks old.
CREATE OR REPLACE TABLE weekly_panel AS
SELECT
    -- keys
    s.week, s.store_id, s.upc,
    p.category, p.sub_category, p.manufacturer, p.description,
    st.store_segment, st.state,

    -- target and price
    s.units,
    LN(s.units)                                  AS log_units,
    s.price,
    s.base_price,
    LN(s.price)                                  AS log_price,
    LN(s.base_price)                             AS log_base_price,
    GREATEST(s.discount_depth, 0)                AS discount_depth,

    -- promotion mechanics of the current week
    s.feature, s.display, s.tpr_only, s.mechanic,
    (s.mechanic <> 'No promo')::INT              AS any_promo,

    -- dynamics: promotion just before / just after (pantry loading, post-promo dip)
    COALESCE((prev.mechanic <> 'No promo')::INT, 0)   AS promo_prev_week,
    COALESCE((nxt.mechanic  <> 'No promo')::INT, 0)   AS promo_next_week,
    (prev.week IS NULL)::INT                          AS prev_week_missing,
    prev.units                                        AS units_prev_week,

    -- how many of the 4 previous weeks were on promotion (promotion fatigue)
    s.promo_weeks_last_4,

    -- competition and cannibalisation
    cc.n_competitor_products,
    cc.competitor_avg_discount,
    cc.competitor_promo_share,
    cc.competitor_support_share,
    cc.own_brand_other_promo_share,

    -- calendar
    cal.week_index, cal.year, cal.month, cal.week_of_year, cal.holiday, cal.pre_holiday,

    -- data quality flags (see docs/data_quality_log.md)
    (s.price > s.base_price * 1.05)::INT          AS flag_price_above_base,
    (s.visits > s.units)::INT                     AS flag_visits_gt_units
FROM (
    -- RANGE window = calendar time, so skipped weeks are handled correctly
    SELECT *,
           COALESCE(SUM((mechanic <> 'No promo')::INT) OVER (
               PARTITION BY store_id, upc ORDER BY week
               RANGE BETWEEN INTERVAL 28 DAY PRECEDING AND INTERVAL 1 DAY PRECEDING), 0) AS promo_weeks_last_4
    FROM sales
) s
JOIN products p          USING (upc)
JOIN stores st           USING (store_id)
JOIN calendar cal        USING (week)
JOIN category_context cc USING (week, store_id, upc)
LEFT JOIN sales prev
       ON prev.store_id = s.store_id AND prev.upc = s.upc AND prev.week = s.week - INTERVAL 7 DAY
LEFT JOIN sales nxt
       ON nxt.store_id  = s.store_id AND nxt.upc  = s.upc AND nxt.week  = s.week + INTERVAL 7 DAY;
