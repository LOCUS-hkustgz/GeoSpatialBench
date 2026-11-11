"""Spatial calculations and canonical geometry serialization."""

from __future__ import annotations
from collections import defaultdict
import math
import shapely
from shapely.geometry import Point, LineString
from shapely.wkt import loads as load_wkt


def bearing(a: Point, b: Point) -> float:
    return (math.degrees(math.atan2(b.x - a.x, b.y - a.y)) + 360.0) % 360.0


def sector4(angle: float) -> str:
    return ["N", "E", "S", "W"][int(((angle + 45.0) % 360.0) // 90.0)]


def sector8(angle: float) -> str:
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int(((angle + 22.5) % 360.0) // 45.0)]


def axis4(angle: float) -> str:
    a = angle % 180.0
    if a < 22.5 or a >= 157.5:
        return "N-S"
    if a < 67.5:
        return "NE-SW"
    if a < 112.5:
        return "E-W"
    return "NW-SE"


def attrs_clean(attrs: dict | None) -> dict:
    keep = ("fclass", "name", "type", "oneway", "maxspeed", "layer", "bridge", "tunnel")
    return {k: attrs[k] for k in keep if attrs and k in attrs and attrs[k] not in (None, "")}


def obj(
    fid: str,
    role: str,
    geom,
    source: dict | None = None,
    derivation: str | None = None,
    attrs: dict | None = None,
) -> dict:
    src = source or {}
    return {
        "id": fid,
        "role": role,
        "geometry_type": geom.geom_type,
        "geometry_wkt": shapely.to_wkt(geom, rounding_precision=6),
        "source_id": src.get("source_id", "transparent-construction"),
        "source_layer": src.get("source_layer"),
        "source_attributes": attrs_clean(attrs if attrs is not None else src.get("attributes")),
        "derivation": derivation,
    }


def geom(o: dict):
    return load_wkt(o["geometry_wkt"])


def straight_chord(line_src: dict) -> tuple[LineString, dict]:
    g = load_wkt(line_src["geometry_wkt"])
    if g.geom_type == "MultiLineString":
        g = max(g.geoms, key=lambda z: z.length)
    return LineString([g.coords[0], g.coords[-1]]), line_src


def offset_point(line: LineString, frac: float, side: float, dist: float) -> Point:
    p = line.interpolate(frac, normalized=True)
    a, b = Point(line.coords[0]), Point(line.coords[-1])
    dx, dy = b.x - a.x, b.y - a.y
    n = math.hypot(dx, dy)
    return Point(p.x - side * dy / n * dist, p.y + side * dx / n * dist)


def split_chain(src: dict, n: int, prefix: str) -> tuple[list[dict], list[str]]:
    g = load_wkt(src["geometry_wkt"])
    if g.geom_type == "MultiLineString":
        g = max(g.geoms, key=lambda z: z.length)
    pts = [g.interpolate(i / n, normalized=True) for i in range(n + 1)]
    edges = [
        obj(
            f"{prefix}{i + 1:02d}",
            "network_edge",
            LineString([pts[i], pts[i + 1]]),
            src,
            "subedge sampled from real OSM road",
        )
        for i in range(n)
    ]
    return edges, [f"N{i + 1:02d}" for i in range(n + 1)]


def edge_graph(objects: list[dict], snap: float = 0.01) -> dict[tuple, set]:
    graph = defaultdict(set)
    for o in objects:
        g = geom(o)
        a, b = Point(g.coords[0]), Point(g.coords[-1])
        ka, kb = (round(a.x / snap), round(a.y / snap)), (round(b.x / snap), round(b.y / snap))
        graph[ka].add(kb)
        graph[kb].add(ka)
    return graph


def reachable(graph, start, target) -> tuple[bool, int | None]:
    q = [(start, 0)]
    seen = {start}
    while q:
        node, d = q.pop(0)
        if node == target:
            return True, d
        for nxt in graph.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                q.append((nxt, d + 1))
    return False, None
