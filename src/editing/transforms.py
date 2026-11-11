"""Decode and execute edits without reading reference answers or scores."""

from __future__ import annotations
import json
import re
from typing import Any, Dict, Optional, Tuple
from shapely import affinity
from shapely import wkt as shapely_wkt
from shapely.geometry.base import BaseGeometry


def extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    if "</think>" in text:
        text = text.split("</think>")[-1]
    text = text.strip().strip("`")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start < 0:
        return _loose_dxdy(text)
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = text[start : i + 1]
                for candidate in (blob, blob.replace("'", '"')):
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        continue
                return _loose_dxdy(blob)
    return _loose_dxdy(text)


def _loose_dxdy(text: str) -> Optional[Dict[str, Any]]:
    dx = re.search(r"\bdx\b\s*[:=]\s*(-?\d+(?:\.\d+)?)", text, flags=re.I)
    dy = re.search(r"\bdy\b\s*[:=]\s*(-?\d+(?:\.\d+)?)", text, flags=re.I)
    if dx and dy:
        return {"op": "translate", "dx": float(dx.group(1)), "dy": float(dy.group(1))}
    return None


def _f0_and_scene(task: Dict[str, Any]) -> Tuple[Optional[BaseGeometry], Dict[str, BaseGeometry]]:
    scene: Dict[str, BaseGeometry] = {}
    for feat in task["scene_features"]:
        try:
            scene[feat["feature_id"]] = shapely_wkt.loads(feat["wkt"])
        except Exception:
            continue
    return scene.get("F0"), scene


def apply_transform(
    f0: BaseGeometry,
    spec: Dict[str, Any],
    scene: Dict[str, BaseGeometry],
) -> Tuple[Optional[BaseGeometry], Dict[str, Any], str]:
    op = str(spec.get("op") or spec.get("operation") or "").lower().strip()
    if not op:
        if any(k in spec for k in ("dx", "dy", "xoff", "yoff")):
            op = "translate"
        elif any(k in spec for k in ("angle_deg", "angle")):
            op = "rotate"
        elif any(k in spec for k in ("factor", "xfact", "scale")):
            op = "scale"
        elif any(k in spec for k in ("to", "target", "reference")):
            op = "snap"
        elif "layer" in spec:
            op = "attribute_edit"
        else:
            return None, spec, "unknown_op"

    if op in ("translate", "move"):
        dx = float(spec.get("dx", spec.get("xoff", 0)) or 0)
        dy = float(spec.get("dy", spec.get("yoff", 0)) or 0)
        norm = {"op": "translate", "dx": dx, "dy": dy}
        return affinity.translate(f0, xoff=dx, yoff=dy), norm, "ok"
    if op == "rotate":
        ang = float(spec.get("angle_deg", spec.get("angle", 0)) or 0)
        norm = {"op": "rotate", "angle_deg": ang}
        return affinity.rotate(f0, ang, origin=f0.centroid), norm, "ok"
    if op == "scale":
        factor = float(spec.get("factor", spec.get("scale", spec.get("xfact", 1))))
        yfact = float(spec.get("yfact", factor))
        if factor <= 0 or yfact <= 0:
            return None, spec, "nonpositive_scale"
        norm = {"op": "scale", "factor": factor, "yfact": yfact}
        return affinity.scale(f0, xfact=factor, yfact=yfact, origin=f0.centroid), norm, "ok"
    if op == "snap":
        ref_id = str(spec.get("to") or spec.get("target") or spec.get("reference") or "F1")
        ref = scene.get(ref_id)
        if ref is None:
            return None, {"op": "snap", "to": ref_id}, "missing_snap_target"
        return ref, {"op": "snap", "to": ref_id}, "ok"
    if op in ("attribute_edit", "attribute"):
        layer = spec.get("layer")
        if layer is None or isinstance(layer, bool) or not float(layer).is_integer():
            return None, spec, "invalid_layer"
        return f0, {"op": "attribute_edit", "layer": layer}, "ok"
    return None, {"op": op}, f"unsupported_op:{op}"


def is_identity(
    *,
    task_op: str,
    spec: Optional[Dict[str, Any]],
    before: Optional[BaseGeometry],
    after: Optional[BaseGeometry],
) -> bool:
    if (task_op or "").lower() == "attribute_edit":
        return False
    if after is None or before is None:
        return True
    if before.equals(after):
        return True
    if not spec:
        return True
    op = (spec.get("op") or "").lower()
    if op == "translate" and abs(float(spec.get("dx", 0))) + abs(float(spec.get("dy", 0))) < 1e-6:
        return True
    if op == "rotate" and abs(float(spec.get("angle_deg", 0)) % 360.0) < 1e-3:
        return True
    if op == "scale" and abs(float(spec.get("factor", 1)) - 1.0) < 1e-6:
        return True
    return False


def decode_transform(
    raw: str,
    f0: BaseGeometry,
    scene: Dict[str, BaseGeometry],
) -> Tuple[Optional[BaseGeometry], Optional[Dict[str, Any]], str]:
    spec = extract_json_obj(raw)
    if not spec:
        return None, None, "missing_json"
    geom, norm, status = apply_transform(f0, spec, scene)
    return geom, norm, status


def decode_edit(task, row):
    f0, scene = _f0_and_scene(task)
    spec = row.get("transform")
    if isinstance(spec, dict):
        geometry, spec, status = apply_transform(f0, spec, scene)
    elif row.get("prediction_wkt"):
        from shapely import wkt

        geometry = wkt.loads(row["prediction_wkt"])
        spec = None
        status = "wkt"
    else:
        geometry, spec, status = decode_transform(
            row.get("prediction", row.get("raw_response", "")), f0, scene
        )
    # The original reference context includes a known-good layer. Never use it for a prediction.
    context = (
        {"predicted_F0_layer": spec["layer"]}
        if spec and spec.get("op") == "attribute_edit" and spec.get("layer") is not None
        else {}
    )
    if geometry is None or not geometry.is_valid or geometry.is_empty:
        return None, context, status
    if spec is not None and is_identity(
        task_op=task.get("operation", ""), spec=spec, before=f0, after=geometry
    ):
        return None, context, "identity"
    return geometry, context, status
