"""Fetch and cache the Village of Burr Ridge municipal boundary polygon.

Primary source: US Census TIGER/Line 2024 Places (Illinois) — stable URL, free, authoritative.
Burr Ridge GEOID = 1709681 (state FIPS 17, place FIPS 09681).
"""
import io
import json
import zipfile
import geopandas as gpd
from ._paths import RAW
from ._http import get

TIGER_URL = "https://www2.census.gov/geo/tiger/TIGER2024/PLACE/tl_2024_17_place.zip"
BURR_RIDGE_PLACE_GEOID = "1709980"
BOUNDARY_GEOJSON = RAW / "burr_ridge_boundary.geojson"


def fetch_boundary(force: bool = False):
    if BOUNDARY_GEOJSON.exists() and not force:
        gdf = gpd.read_file(BOUNDARY_GEOJSON)
        return gdf

    print(f"Fetching TIGER/Line places: {TIGER_URL}")
    r = get(TIGER_URL, timeout=120)
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    raw_zip = RAW / "tl_2024_17_place.zip"
    raw_zip.write_bytes(r.content)

    gdf = gpd.read_file(f"zip://{raw_zip}")
    burr = gdf[gdf["GEOID"] == BURR_RIDGE_PLACE_GEOID].copy()
    if burr.empty:
        raise RuntimeError(f"No place with GEOID {BURR_RIDGE_PLACE_GEOID} found in TIGER places file")

    burr = burr.to_crs(4326)
    burr.to_file(BOUNDARY_GEOJSON, driver="GeoJSON")

    area_sqmi = burr.to_crs(3435).area.iloc[0] / 27_878_400  # ft^2 → sq mi (IL East StatePlane)
    print(f"Burr Ridge boundary saved → {BOUNDARY_GEOJSON} (area ≈ {area_sqmi:.2f} sq mi)")
    if not (6.5 <= area_sqmi <= 8.0):
        print(f"  WARNING: area outside expected 6.5–8.0 sq mi range")
    return burr


if __name__ == "__main__":
    fetch_boundary(force=False)
