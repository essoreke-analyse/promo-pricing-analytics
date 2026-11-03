-- 01_load.sql
-- Typed, clean tables built from the raw sheets (raw_stores, raw_products, raw_transactions).
-- Clean rules are documented in docs/data_quality_log.md.

CREATE OR REPLACE TABLE stores AS
SELECT
    STORE_ID::INTEGER              AS store_id,
    STORE_NAME                     AS store_name,
    ADDRESS_CITY_NAME              AS city,
    ADDRESS_STATE_PROV_CODE        AS state,
    MSA_CODE::INTEGER              AS msa_code,
    SEG_VALUE_NAME                 AS store_segment,      -- VALUE / MAINSTREAM / UPSCALE
    PARKING_SPACE_QTY::INTEGER     AS parking_spaces,
    SALES_AREA_SIZE_NUM::INTEGER   AS sales_area_sqft,
    AVG_WEEKLY_BASKETS::DOUBLE     AS avg_weekly_baskets
FROM raw_stores;

CREATE OR REPLACE TABLE products AS
SELECT
    UPC::BIGINT       AS upc,
    DESCRIPTION       AS description,
    MANUFACTURER      AS manufacturer,
    CATEGORY          AS category,
    SUB_CATEGORY      AS sub_category,
    PRODUCT_SIZE      AS product_size
FROM raw_products;

-- One row per week x store x product, with promo mechanic and discount depth.
CREATE OR REPLACE TABLE sales AS
SELECT
    WEEK_END_DATE::DATE      AS week,
    STORE_NUM::INTEGER       AS store_id,
    UPC::BIGINT              AS upc,
    UNITS::INTEGER           AS units,
    VISITS::INTEGER          AS visits,
    HHS::INTEGER             AS households,
    SPEND::DOUBLE            AS spend,
    PRICE::DOUBLE            AS price,
    BASE_PRICE::DOUBLE       AS base_price,
    FEATURE::INTEGER         AS feature,
    DISPLAY::INTEGER         AS display,
    TPR_ONLY::INTEGER        AS tpr_only,
    CASE
        WHEN FEATURE = 1 AND DISPLAY = 1 THEN 'Feature + Display'
        WHEN FEATURE = 1                 THEN 'Feature'
        WHEN DISPLAY = 1                 THEN 'Display'
        WHEN TPR_ONLY = 1                THEN 'TPR only'
        ELSE 'No promo'
    END                      AS mechanic,
    1 - PRICE / NULLIF(BASE_PRICE, 0) AS discount_depth
FROM raw_transactions
-- Rows unusable for price modelling (see quality log): missing or non-positive price / units.
WHERE PRICE > 0
  AND BASE_PRICE > 0
  AND UNITS > 0;
