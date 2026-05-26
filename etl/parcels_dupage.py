"""Pull DuPage County parcels for Burr Ridge.

Source: DuPage GIS `Tyler/ParcelsRealEstateCCWGS84SR4326` MapServer layer 0.
Filters by `MUNICIPALITY = 'BURR RIDGE'` server-side (faster + more accurate
than a spatial intersect against TIGER boundary, since the county uses the
official municipal annexation polygon).

Layer also exposes current assessed value (FCVTOTAL) and tax amount, which we
persist into `assessments` for the most recent tax year — saving us from
needing the Downers Grove Township Excel for current-year DuPage AVs.
"""
import datetime as dt
import geopandas as gpd
from ._arcgis import query_features
from ._db import cursor, audit
from ._paths import RAW
from .normalize import normalize_pin_dupage, normalize_address

DUPAGE_PARCELS_URL = (
    "https://gis.dupageco.org/arcgis/rest/services/"
    "Tyler/ParcelsRealEstateCCWGS84SR4326/MapServer/0"
)
SOURCE_NAME = "dupage_gis_parcels"

OUT_FIELDS = ",".join([
    "PIN", "PROPCLASS", "ACREAGE", "MUNICIPALITY",
    "PROPSTNUM", "PROPSTDIR", "PROPSTNAME", "PROPCITY", "PROPZIP",
    "FCVTOTAL", "FCVLAND", "FCVIMP", "BILLVALUE", "TAXAMOUNT",
])


def fetch() -> gpd.GeoDataFrame:
    print(f"Querying DuPage parcels WHERE MUNICIPALITY='BURR RIDGE'")
    feats = list(query_features(
        DUPAGE_PARCELS_URL,
        where="UPPER(MUNICIPALITY) = 'BURR RIDGE'",
        out_fields=OUT_FIELDS,
    ))
    if not feats:
        raise RuntimeError("DuPage Burr Ridge parcels query returned no features")
    gdf = gpd.GeoDataFrame.from_features(feats, crs=4326)
    print(f"  fetched {len(gdf)} parcels")
    out = RAW / "dupage_parcels_burr_ridge.geojson"
    gdf.to_file(out, driver="GeoJSON")
    return gdf


def _build_address(r) -> str:
    parts = [
        str(r.get("PROPSTNUM") or "").strip(),
        str(r.get("PROPSTDIR") or "").strip(),
        str(r.get("PROPSTNAME") or "").strip(),
    ]
    line1 = " ".join(p for p in parts if p)
    city = str(r.get("PROPCITY") or "").strip()
    zip5 = str(r.get("PROPZIP") or "").strip()[:5]
    return ", ".join(p for p in [line1, city, "IL " + zip5 if zip5 else "IL"] if p)


def load() -> int:
    gdf = fetch()
    today = dt.date.today()
    parcel_rows, assess_rows = [], []
    current_year = today.year

    for _, r in gdf.iterrows():
        pin = normalize_pin_dupage(r.get("PIN"))
        if not pin:
            continue
        address_raw = _build_address(r)
        try:
            lot_sqft = float(r["ACREAGE"]) * 43560 if r.get("ACREAGE") else None
        except (TypeError, ValueError):
            lot_sqft = None

        parcel_rows.append((
            "dupage", pin, str(r.get("PIN")), address_raw or None,
            normalize_address(address_raw),
            None,  # township not in this layer; downstream lookup
            str(r.get("PROPCLASS") or "") or None,
            lot_sqft,
            r.geometry.wkt if r.geometry else None,
            today, None, SOURCE_NAME,
        ))

        try:
            fcv = float(r["FCVTOTAL"]) if r.get("FCVTOTAL") else None
        except (TypeError, ValueError):
            fcv = None
        if fcv:
            assess_rows.append(("dupage", pin, current_year, fcv, None, f"{SOURCE_NAME}:FCVTOTAL"))

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
            [(*r[:8], r[8], r[8], *r[9:]) for r in parcel_rows],
        )
        if assess_rows:
            con.executemany(
                """
                INSERT INTO assessments (county, pin_normalized, tax_year,
                    assessed_value, equalized_av, source)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (county, pin_normalized, tax_year) DO UPDATE SET
                    assessed_value = COALESCE(EXCLUDED.assessed_value, assessments.assessed_value),
                    source         = EXCLUDED.source
                """,
                assess_rows,
            )
        audit(con, SOURCE_NAME, DUPAGE_PARCELS_URL, len(parcel_rows),
              f"municipality=BURR RIDGE; current-year AVs={len(assess_rows)}")
    print(f"Loaded {len(parcel_rows)} DuPage parcels + {len(assess_rows)} current-year AVs")
    return len(parcel_rows)


if __name__ == "__main__":
    load()
