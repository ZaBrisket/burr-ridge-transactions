-- Burr Ridge transaction warehouse — DuckDB DDL
-- Run idempotently via etl._db.bootstrap()

INSTALL spatial;
LOAD spatial;

CREATE TABLE IF NOT EXISTS parcels (
    county              TEXT NOT NULL,           -- 'cook' | 'dupage'
    pin_normalized      TEXT NOT NULL,
    pin_raw             TEXT,
    address_raw         TEXT,
    address_normalized  TEXT,
    township            TEXT,
    property_class      TEXT,
    lot_sqft            DOUBLE,
    geometry            GEOMETRY,
    valid_from          DATE NOT NULL,
    valid_to            DATE,
    source              TEXT,
    PRIMARY KEY (county, pin_normalized, valid_from)
);

CREATE TABLE IF NOT EXISTS sales (
    county              TEXT NOT NULL,
    pin_normalized      TEXT NOT NULL,
    sale_date           DATE NOT NULL,
    sale_price          DOUBLE,
    document_number     TEXT,
    deed_type           TEXT,
    is_arms_length      BOOLEAN,
    filter_flags        JSON,
    source              TEXT NOT NULL,           -- 'ccao' | 'mydec'
    source_url          TEXT,
    extracted_at        TIMESTAMP NOT NULL,
    confidence_score    INTEGER,
    PRIMARY KEY (county, source, document_number, pin_normalized, sale_date)
);

CREATE TABLE IF NOT EXISTS sales_crosscheck (
    county              TEXT NOT NULL,
    pin_normalized      TEXT NOT NULL,
    sale_date           DATE NOT NULL,
    ccao_price          DOUBLE,
    mydec_price         DOUBLE,
    price_delta         DOUBLE,
    matched             BOOLEAN,
    notes               TEXT,
    PRIMARY KEY (county, pin_normalized, sale_date)
);

CREATE TABLE IF NOT EXISTS characteristics (
    county              TEXT NOT NULL,
    pin_normalized      TEXT NOT NULL,
    tax_year            INTEGER NOT NULL,
    building_sqft       INTEGER,
    year_built          INTEGER,
    bedrooms            INTEGER,
    bathrooms           DOUBLE,
    construction_type   TEXT,
    source              TEXT,
    PRIMARY KEY (county, pin_normalized, tax_year)
);

CREATE TABLE IF NOT EXISTS assessments (
    county              TEXT NOT NULL,
    pin_normalized      TEXT NOT NULL,
    tax_year            INTEGER NOT NULL,
    assessed_value      DOUBLE,
    equalized_av        DOUBLE,
    source              TEXT,
    PRIMARY KEY (county, pin_normalized, tax_year)
);

CREATE SEQUENCE IF NOT EXISTS source_audit_seq START 1;

CREATE TABLE IF NOT EXISTS source_audit (
    audit_id            BIGINT DEFAULT nextval('source_audit_seq'),
    source_name         TEXT NOT NULL,
    source_url          TEXT,
    records_pulled      INTEGER,
    pulled_at           TIMESTAMP NOT NULL,
    notes               TEXT,
    PRIMARY KEY (audit_id)
);
