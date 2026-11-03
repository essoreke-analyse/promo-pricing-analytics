-- 02_quality_checks.sql
-- Run against the RAW table so that every excluded or suspicious row is counted.
-- Each query returns one result (expected values are noted in docs/data_quality_log.md).

-- 1. Coverage
SELECT MIN(WEEK_END_DATE) AS first_week,
       MAX(WEEK_END_DATE) AS last_week,
       COUNT(DISTINCT WEEK_END_DATE) AS n_weeks,
       COUNT(DISTINCT STORE_NUM)     AS n_stores,
       COUNT(DISTINCT UPC)           AS n_products,
       COUNT(*)                      AS n_rows
FROM raw_transactions;

-- 2. Duplicate keys (week x store x product)
SELECT COUNT(*) - COUNT(DISTINCT (WEEK_END_DATE, STORE_NUM, UPC)) AS duplicate_keys
FROM raw_transactions;

-- 3. Orphan keys
SELECT COUNT(*) AS orphan_stores
FROM raw_transactions t ANTI JOIN raw_stores s ON t.STORE_NUM = s.STORE_ID;

SELECT COUNT(*) AS orphan_products
FROM raw_transactions t ANTI JOIN raw_products p ON t.UPC = p.UPC;

-- 4. Missing or impossible values
SELECT
    SUM((PRICE IS NULL)::INT)                     AS price_missing,
    SUM((BASE_PRICE IS NULL)::INT)                AS base_price_missing,
    SUM((PRICE <= 0)::INT)                        AS price_non_positive,
    SUM((UNITS <= 0)::INT)                        AS units_non_positive,
    SUM((PRICE > BASE_PRICE * 1.05)::INT)         AS price_above_base,      -- shelf price > base price
    SUM((ABS(SPEND - UNITS * PRICE) > 0.05 * SPEND)::INT) AS spend_inconsistent,
    SUM((VISITS > UNITS)::INT)                    AS more_baskets_than_units -- logically impossible
FROM raw_transactions;

-- 5. Series completeness: how many weeks does each store x product pair have?
WITH pairs AS (
    SELECT STORE_NUM, UPC, COUNT(*) AS n_weeks
    FROM raw_transactions
    GROUP BY ALL
)
SELECT COUNT(*)                      AS n_pairs,
       SUM((n_weeks = 156)::INT)     AS complete_pairs,
       MEDIAN(n_weeks)               AS median_weeks,
       SUM((n_weeks < 52)::INT)      AS pairs_under_one_year
FROM pairs;

-- 6. Promo mechanics are mutually exclusive except Feature + Display
SELECT FEATURE, DISPLAY, TPR_ONLY, COUNT(*) AS n_rows
FROM raw_transactions
GROUP BY ALL
ORDER BY n_rows DESC;
