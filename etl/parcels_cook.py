"""Pull Cook County parcels for Burr Ridge.

Source: Cook County GIS `parcelHistorical/MapServer/{YEAR}` layer.
Filters by `MUNICIPALITY = 'VILLAGE OF BURR RIDGE'` server-side.

PIN structure: PIN10 (10-digit base) + PINA, PINSA, PINB, PINP suffix digits.
Full Cook PIN14 = PIN10 || PINA || PINSA || PINB || PINP (each 1 digit usually).
The layer also exposes a `Name` field whose alias is "PIN14" — that's the
canonical full string. We use that.
"""
import datetime as dt
import geopandas as gpd
from ._arcgis import query_features
from ._db import cursor, audit
from ._paths import RAW
from .normalize import normalize_pin_cook, normalize_address

PARCEL_YEAR = 2025  # most recent published; update annually
COOK_PARCELS_URL = (
    f"https://gis.cookcountyil.gov/traditional/rest/services/"
    f"parcelHistorical/MapServer/{PARCEL_YEAR}"
)
SOURCE_NAME = f"cook_central_parcels_{PARCEL_YEAR}"

OUT_FIELDS = ",".join([
    "Name",                 # alias PIN14 — full PIN
    "PIN10",
    "MUNICIPALITY",
    "PoliticalTownship",
    "AssessorBLDGclass",
    "TAXCODE",
])


def fetch() -> gpd.GeoDataFrame:
    print(f"Querying Cook parcels (year {PARCEL_YEAR}) WHERE MUNICIPALITY='VILLAGE OF BURR RIDGE'")
    feats = list(query_features(
        COOK_PARCELS_URL,
        where="MUNICIPALITY = 'VILLAGE OF BURR RIDGE'",
        out_fields=OUT_FIELDS,
    ))
    if not feats:
        raise RuntimeError("Cook Burr Ridge parcels query returned no features")
    gdf = gpd.GeoDataFrame.from_features(feats, crs=4326)
    print(f"  fetched {len(gdf)} parcels")
    out = RAW / "cook_parcels_burr_ridge.geojson"
    gdf.to_file(out, driver="GeoJSON")
    return gdf


def load() -> int:
    gdf = fetch()
    today = dt.date.today()
    rows = []
    for _, r in gdf.iterrows():
        pin_full = r.get("Name") or r.get("PIN10")  # Name's alias is PIN14
        pin = normalize_pin_cook(pin_full)
        if not pin:
            continue
        rows.append((
            "cook", pin, str(pin_full),
            None, None,  # address not in this layer; address dataset 3723-97qp gap-fills
            r.get("PoliticalTownship"),
            str(r.get("AssessorBLDGclass") or "") or None,
            None,  # lot_sqft — gap-fill from CCAO characteristics
            r.geometry.wkt if r.geometry else None,
            today, None, SOURCE_NAME,
        ))

    with cursor() as con:
        con.executemany(
            """
            INSERT INTO parcels (county, pin_normalized, pin_raw, address_raw,
                address_normalized, township, property_class, lot_sqft,
                geometry, valid_from, valid_to, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?,
                CASE WHEN ? IS NULL THEN NULL ELSE ST_GeomFromText(?) END,
                ?, ?, ?)
            ON CONFLICT (county, pin_normalized, valid_from) DO NOTHING
            """,
            [(*r[:8], r[8], r[8], *r[9:]) for r in rows],
        )
        audit(con, SOURCE_NAME, COOK_PARCELS_URL, len(rows),
              f"municipality='VILLAGE OF BURR RIDGE'; year={PARCEL_YEAR}")
    print(f"Loaded {len(rows)} Cook parcels into warehouse")
    return len(rows)


if __name__ == "__main__":
    load()
