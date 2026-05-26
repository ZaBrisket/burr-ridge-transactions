-- Analytical views over the unified warehouse.

CREATE OR REPLACE VIEW burr_ridge_parcels AS
SELECT *
FROM parcels
WHERE valid_to IS NULL;

CREATE OR REPLACE VIEW arms_length_sales AS
SELECT
    s.*,
    p.address_normalized AS parcel_address,
    p.township
FROM sales s
LEFT JOIN burr_ridge_parcels p
       ON s.county = p.county
      AND s.pin_normalized = p.pin_normalized
WHERE s.is_arms_length = TRUE
  AND s.sale_date >= DATE '2013-01-01';

CREATE OR REPLACE VIEW sales_with_characteristics AS
SELECT
    s.county,
    s.pin_normalized,
    s.sale_date,
    s.sale_price,
    s.document_number,
    s.deed_type,
    s.is_arms_length,
    s.confidence_score,
    p.address_normalized,
    c.building_sqft,
    c.year_built,
    c.bedrooms,
    c.bathrooms,
    p.lot_sqft,
    a.assessed_value
FROM sales s
LEFT JOIN burr_ridge_parcels p
       ON s.county = p.county AND s.pin_normalized = p.pin_normalized
LEFT JOIN characteristics c
       ON s.county = c.county
      AND s.pin_normalized = c.pin_normalized
      AND c.tax_year = date_part('year', s.sale_date)
LEFT JOIN assessments a
       ON s.county = a.county
      AND s.pin_normalized = a.pin_normalized
      AND a.tax_year = date_part('year', s.sale_date);

CREATE OR REPLACE VIEW annual_summary AS
SELECT
    date_part('year', sale_date)::INTEGER AS sale_year,
    county,
    count(*)            AS sale_count,
    median(sale_price)  AS median_price,
    avg(sale_price)     AS mean_price,
    min(sale_price)     AS min_price,
    max(sale_price)     AS max_price
FROM arms_length_sales
GROUP BY 1, 2
ORDER BY 1, 2;
