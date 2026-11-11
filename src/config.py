"""Validate and normalize city vector inputs in a projected metric CRS."""

import os
from .data_io import write_json
from collections import Counter
import json
import math
from pathlib import Path
import geopandas as gpd
import pandas as pd
from pyproj import CRS

MIN_ROWS = {"pois": 750, "roads": 1250, "buildings": 650, "landuse": 25}
GEOMETRY_TYPES = {
    "pois": {"Point"},
    "roads": {"LineString", "MultiLineString"},
    "buildings": {"Polygon", "MultiPolygon"},
    "landuse": {"Polygon", "MultiPolygon"},
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_path(value: str, config_path: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (config_path.parent / path).resolve()


def validate_config(config: dict, config_path: Path) -> tuple[CRS, Path]:
    required = ("city_name", "id_prefix", "target_crs", "output_dir", "inputs")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError(f"Missing configuration keys: {missing}")
    prefix = str(config["id_prefix"])
    if not prefix.replace("-", "").isalnum() or len(prefix) > 12:
        raise ValueError("id_prefix must be <=12 alphanumeric/hyphen characters")
    crs = CRS.from_user_input(config["target_crs"])
    if not crs.is_projected:
        raise ValueError(
            "target_crs must be projected; geographic longitude/latitude is not allowed"
        )
    unit_names = {axis.unit_name.lower() for axis in crs.axis_info if axis.unit_name}
    if not unit_names or not all(
        name in {"metre", "meter", "metres", "meters"} for name in unit_names
    ):
        raise ValueError(f"target_crs axes must use metres, got {sorted(unit_names)}")
    for role in GEOMETRY_TYPES:
        entry = config["inputs"].get(role)
        if not entry or not entry.get("path"):
            raise ValueError(f"inputs.{role}.path is required")
        source_path = resolve_path(entry["path"], config_path)
        if not source_path.exists():
            raise FileNotFoundError(f"inputs.{role}.path does not exist: {source_path}")
    out = resolve_path(config["output_dir"], config_path)
    return crs, out


def normalized_flag(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "F"
    return "T" if str(value).strip().lower() in {"t", "true", "yes", "y", "1"} else "F"


def read_role(role: str, config: dict, config_path: Path, target_crs: CRS) -> gpd.GeoDataFrame:
    entry = config["inputs"][role]
    path = resolve_path(entry["path"], config_path)
    kwargs = {}
    if entry.get("layer") is not None:
        kwargs["layer"] = entry["layer"]
    bbox = entry.get("read_bbox", config.get("read_bbox"))
    if bbox is not None:
        if len(bbox) != 4:
            raise ValueError(f"inputs.{role}.read_bbox must contain four numbers")
        kwargs["bbox"] = tuple(bbox)
    frame = gpd.read_file(path, **kwargs)
    for field, accepted in entry.get("attribute_filter", {}).items():
        if field not in frame.columns or not isinstance(accepted, list):
            raise ValueError(
                f"inputs.{role}.attribute_filter needs an existing field and a list of accepted values"
            )
        frame = frame[frame[field].isin(accepted)].copy()
    if frame.crs is None:
        source_crs = entry.get("source_crs")
        if not source_crs:
            raise ValueError(f"inputs.{role} has no CRS; set source_crs explicitly")
        frame = frame.set_crs(source_crs)
    frame = (
        frame.dropna(subset=[frame.geometry.name]).explode(index_parts=False).reset_index(drop=True)
    )
    frame = frame[frame.geometry.geom_type.isin(GEOMETRY_TYPES[role])].copy()
    frame = frame[~frame.geometry.is_empty].to_crs(target_crs).reset_index(drop=True)
    invalid = int((~frame.geometry.is_valid).sum())
    if invalid:
        raise ValueError(
            f"inputs.{role} contains {invalid} invalid geometries after projection; repair the source first"
        )
    frame["_source_row_id"] = frame.index.astype(str)
    id_field = entry.get("id_field")
    if id_field:
        if id_field not in frame.columns:
            raise ValueError(f"inputs.{role}.id_field '{id_field}' is absent")
        frame["_source_row_id"] = frame[id_field].fillna(frame["_source_row_id"]).astype(str)
    frame["_source_name"] = entry.get("source_name") or entry.get("layer") or path.name

    if role == "roads":
        field_map = entry.get("field_map", {})
        for canonical in ("layer", "bridge", "tunnel"):
            source = field_map.get(canonical, canonical)
            constant = entry.get("constant_fields", {}).get(canonical)
            if source in frame.columns:
                frame[canonical] = frame[source]
            elif constant is not None:
                frame[canonical] = constant
            elif canonical == "layer":
                raise ValueError(
                    "roads need an ordinal layer field for O06; map it with field_map.layer"
                )
            else:
                frame[canonical] = "F"
        parsed_layer = pd.to_numeric(frame["layer"], errors="coerce")
        bad_layer = frame["layer"].notna() & parsed_layer.isna()
        if bad_layer.any():
            raise ValueError(
                "roads.layer contains non-numeric values; provide ordinal numeric layer values"
            )
        frame["layer"] = parsed_layer.fillna(0.0)
        frame["bridge"] = frame["bridge"].map(normalized_flag)
        frame["tunnel"] = frame["tunnel"].map(normalized_flag)

    filters = config.get("filters", {})
    if role == "roads":
        frame["_length"] = frame.length
        lo, hi = filters.get("road_length_m", [30, 1200])
        frame = frame[(frame._length > lo) & (frame._length < hi)]
    elif role in {"buildings", "landuse"}:
        frame["_area"] = frame.area
        key = "building_area_m2" if role == "buildings" else "landuse_area_m2"
        default = [50, 30000] if role == "buildings" else [20000, 3000000]
        lo, hi = filters.get(key, default)
        frame = frame[(frame._area > lo) & (frame._area < hi)]
    random_state = {"pois": 18, "roads": 19, "buildings": 20, "landuse": 21}[role]
    return frame.sample(frac=1, random_state=random_state).reset_index(drop=True)


def data_diagnostics(frames: dict[str, gpd.GeoDataFrame]) -> dict:
    checks = {}
    for role, frame in frames.items():
        checks[role] = {
            "rows_after_filtering": len(frame),
            "minimum_required": MIN_ROWS[role],
            "geometry_types": dict(Counter(frame.geometry.geom_type)),
            "enough_rows": len(frame) >= MIN_ROWS[role],
        }
    roads = frames["roads"]
    checks["roads"]["nonzero_layer_rows"] = int((roads["layer"] != 0).sum())
    checks["roads"]["bridge_or_tunnel_rows"] = int(
        ((roads["bridge"] == "T") | (roads["tunnel"] == "T")).sum()
    )
    return checks


def assert_data_ready(checks: dict) -> None:
    failures = [
        f"{role}: {value['rows_after_filtering']} < {value['minimum_required']}"
        for role, value in checks.items()
        if role in MIN_ROWS and not value["enough_rows"]
    ]
    if checks["roads"]["nonzero_layer_rows"] == 0:
        failures.append("roads: no non-zero layer values; O06 cannot test vertical ordering")
    if failures:
        raise RuntimeError(
            "Input data are not sufficient for the locked 700-item design: " + "; ".join(failures)
        )


def load_config(config_path):
    config_path = Path(config_path).resolve()
    config = read_json(config_path)
    if isinstance(config.get("seed"), bool) or not isinstance(config.get("seed"), int):
        raise ValueError(
            "Set an integer seed; historical Stockholm seed is unknown and cannot be reconstructed"
        )
    crs, out = validate_config(config, config_path)
    frames = {
        role: read_role(role, config, config_path, crs)
        for role in ("pois", "roads", "buildings", "landuse")
    }
    diagnostics = data_diagnostics(frames)
    assert_data_ready(diagnostics)
    for role, frame in frames.items():
        if frame["_source_row_id"].duplicated().any():
            # A source multipart geometry may have more than one exploded component.
            frame["_source_row_id"] = frame["_source_row_id"] + ":part-" + frame.index.astype(str)
    return config, crs, out, frames, diagnostics


ALIASES = {
    "pois": ["pois", "poi", "points", "gis_osm_pois_free"],
    "roads": ["roads", "road", "gis_osm_roads_free"],
    "buildings": ["buildings", "building", "gis_osm_buildings_a_free"],
    "landuse": ["landuse", "land_use", "regions", "gis_osm_landuse_a_free"],
}


def init_config(data, city, prefix, path, target_crs=None):
    import pyogrio

    data, path = Path(data).resolve(), Path(path).resolve()
    if path.exists():
        raise ValueError(f"Configuration already exists: {path}")
    layers = {str(name).lower(): str(name) for name, _ in pyogrio.list_layers(data)}
    config = {
        "city_name": city,
        "id_prefix": prefix,
        "dataset_name": "Describe your vector source and release date",
        "target_crs": target_crs,
        "output_dir": "../outputs/" + prefix.lower(),
        "seed": 20260819,
        "inputs": {},
        "filters": {
            "road_length_m": [30, 1200],
            "building_area_m2": [50, 30000],
            "landuse_area_m2": [20000, 3000000],
        },
    }
    for role, aliases in ALIASES.items():
        matches = [layers[name] for name in aliases if name in layers]
        if len(matches) != 1:
            raise ValueError(
                f"Cannot unambiguously infer {role} layer; run scripts/inspect_data.py and edit configs/city.example.json. Candidates: {matches}"
            )
        info = pyogrio.read_info(data, layer=matches[0])
        fields = set(info["fields"])
        entry = {
            "path": os.path.relpath(data, path.parent).replace("\\", "/"),
            "layer": matches[0],
            "attribute_fields": [f for f in ("name", "fclass", "type") if f in fields],
        }
        ids = [f for f in ("source_id", "osm_id", "osm_id2", "id") if f in fields]
        if ids:
            entry["id_field"] = ids[0]
        if role == "roads":
            layer_field = next((f for f in ("osm_layer", "layer", "z_order") if f in fields), None)
            if layer_field is None:
                raise ValueError(
                    "Roads lack a numeric ordinal layer field for O06; add it from verified source attributes and configure field_map.layer"
                )
            entry["field_map"] = {"layer": layer_field}
            entry["field_map"].update({f: f for f in ("bridge", "tunnel") if f in fields})
        config["inputs"][role] = entry
    if target_crs is None:
        pois = gpd.read_file(data, layer=config["inputs"]["pois"]["layer"], rows=1000)
        if pois.crs is None:
            raise ValueError("Input lacks CRS; set source_crs in a manual configuration")
        source = CRS(pois.crs)
        if source.is_projected and all(
            axis.unit_name.lower() in ("metre", "meter") for axis in source.axis_info
        ):
            target_crs = source.to_string()
        else:
            target_crs = pois.estimate_utm_crs().to_string()
        config["target_crs"] = target_crs
    write_json(path, config)
    return {
        "config": str(path),
        "target_crs": target_crs,
        "status": "CREATED",
        "next_step": "Review the inferred layers, CRS, source description and filter thresholds; then run scripts/validate_data.py --config CONFIG",
    }
