-- 04_forecast_features.sql
-- Features for forecasting units 1 to 4 weeks ahead.
--
-- Rule against look-ahead: a forecast made at week T for week T+h (h = 1..4) may only use
-- sales up to week T. To use ONE feature set for all four horizons, every sales-based
-- feature is lagged by at least 4 weeks (28 days). The promotion calendar and prices of the
-- target week are treated as known in advance (promotions are planned weeks ahead).
--
-- Lags use calendar joins / RANGE windows (not LAG()) because series skip weeks.

CREATE OR REPLACE VIEW sales_any AS
SELECT store_id, upc, week, units, (mechanic <> 'No promo')::INT AS any_promo FROM sales;

CREATE OR REPLACE TABLE forecast_features AS
WITH w AS (
    SELECT
        p.*,
        -- recent level: average units over weeks t-4 .. t-11 (8 weeks, all >= 4 weeks old)
        AVG(units) OVER (
            PARTITION BY store_id, upc ORDER BY week
            RANGE BETWEEN INTERVAL 77 DAY PRECEDING AND INTERVAL 28 DAY PRECEDING)        AS units_ma8_lag4,
        -- level outside promotions over weeks t-4 .. t-25 (a cleaner baseline)
        AVG(units) FILTER (WHERE any_promo = 0) OVER (
            PARTITION BY store_id, upc ORDER BY week
            RANGE BETWEEN INTERVAL 181 DAY PRECEDING AND INTERVAL 28 DAY PRECEDING)       AS units_nopromo_avg26_lag4,
        -- number of weeks actually observed in the 8-week window
        COUNT(*) OVER (
            PARTITION BY store_id, upc ORDER BY week
            RANGE BETWEEN INTERVAL 77 DAY PRECEDING AND INTERVAL 28 DAY PRECEDING)        AS n_obs_ma8
    FROM weekly_panel p
)
SELECT
    w.*,
    l4.units   AS units_lag4,
    l5.units   AS units_lag5,
    l8.units   AS units_lag8,
    l52.units  AS units_lag52,          -- same week last year
    l52.any_promo AS promo_lag52        -- was it promoted last year? (seasonal naive is misleading if so)
FROM w
LEFT JOIN sales_any l4  ON l4.store_id  = w.store_id AND l4.upc  = w.upc AND l4.week  = w.week - INTERVAL 28 DAY
LEFT JOIN sales_any l5  ON l5.store_id  = w.store_id AND l5.upc  = w.upc AND l5.week  = w.week - INTERVAL 35 DAY
LEFT JOIN sales_any l8  ON l8.store_id  = w.store_id AND l8.upc  = w.upc AND l8.week  = w.week - INTERVAL 56 DAY
LEFT JOIN sales_any l52 ON l52.store_id = w.store_id AND l52.upc = w.upc AND l52.week = w.week - INTERVAL 364 DAY;
