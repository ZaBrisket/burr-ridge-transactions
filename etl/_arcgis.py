"""Generic paginated ArcGIS REST FeatureServer/MapServer query.

Yields GeoJSON features. Handles `resultOffset` pagination using `maxRecordCount`.
"""
from typing import Iterator
from ._http import get


def query_features(
    layer_url: str,
    where: str = "1=1",
    out_fields: str = "*",
    out_sr: int = 4326,
    page_size: int = 1000,
    geometry_envelope: tuple[float, float, float, float] | None = None,
) -> Iterator[dict]:
    """Page through an ArcGIS REST layer and yield GeoJSON features.

    layer_url example: https://gis.dupageco.org/arcgis/rest/services/OpenData/Parcels/MapServer/0
    """
    base_params = {
        "where": where,
        "outFields": out_fields,
        "outSR": out_sr,
        "f": "geojson",
        "resultRecordCount": page_size,
    }
    if geometry_envelope:
        xmin, ymin, xmax, ymax = geometry_envelope
        base_params.update({
            "geometry": f"{xmin},{ymin},{xmax},{ymax}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
        })

    offset = 0
    total = 0
    while True:
        params = dict(base_params)
        params["resultOffset"] = offset
        r = get(f"{layer_url}/query", params=params, timeout=120)
        data = r.json()
        feats = data.get("features", [])
        if not feats:
            break
        for f in feats:
            yield f
            total += 1
        if len(feats) < page_size:
            break
        offset += page_size
    print(f"  ArcGIS query returned {total} features from {layer_url}")
