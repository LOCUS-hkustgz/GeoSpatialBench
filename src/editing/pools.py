"""Metric feature-pool capping, localization and scene serialization."""

from __future__ import annotations

import json
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

import geopandas as gpd
from shapely import affinity
from shapely.geometry.base import BaseGeometry


# --------------------------------------------------------------------- geometry
def localize(geoms: Sequence[BaseGeometry]) -> Tuple[List[BaseGeometry], float, float]:
    """Translate ``geoms`` so their common bbox centre sits at the origin.

    Returns ``(local_geoms, ox, oy)`` with ``local = translate(g, -ox, -oy)``.
    """
    minx = min(g.bounds[0] for g in geoms)
    miny = min(g.bounds[1] for g in geoms)
    maxx = max(g.bounds[2] for g in geoms)
    maxy = max(g.bounds[3] for g in geoms)
    ox = (minx + maxx) / 2.0
    oy = (miny + maxy) / 2.0
    local = [affinity.translate(g, xoff=-ox, yoff=-oy) for g in geoms]
    return local, ox, oy


def feature_record(
    feature_id: str,
    geom: BaseGeometry,
    semantics: Optional[Dict[str, Any]],
    source_object_id: Any,
) -> Dict[str, Any]:
    """Scene-feature dict consumed by ``constraints.evaluate_edit``."""
    c = geom.centroid
    return {
        "feature_id": feature_id,
        "geometry_type": geom.geom_type,
        "wkt": geom.wkt,
        "geojson": json.loads(gpd.GeoSeries([geom]).to_json())["features"][0]["geometry"],
        "bounding_box": [float(v) for v in geom.bounds],
        "centroid": [float(c.x), float(c.y)],
        "area": float(geom.area),
        "length": float(geom.length),
        "semantics": dict(semantics or {}),
        "source_object_id": source_object_id,
    }


# ------------------------------------------------------------------------ pools


def _cap(df: gpd.GeoDataFrame, n: int, rng: random.Random) -> gpd.GeoDataFrame:
    if n is None or len(df) <= n:
        return df.reset_index(drop=True)
    idx = sorted(rng.sample(range(len(df)), n))
    return df.iloc[idx].reset_index(drop=True)


def cap_pools(
    pools: Tuple[gpd.GeoDataFrame, ...],
    *,
    max_buildings: int = 8000,
    max_green: int = 600,
    max_roads: int = 2500,
    max_points: int = 20000,
    seed: int = 42,
) -> Tuple[gpd.GeoDataFrame, ...]:
    rng = random.Random(seed)
    bdf, gdf, rdf, pdf = pools
    return (
        _cap(bdf, max_buildings, rng),
        _cap(gdf, max_green, rng),
        _cap(rdf, max_roads, rng),
        _cap(pdf, max_points, rng),
    )
