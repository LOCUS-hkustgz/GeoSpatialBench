"""Independent recomputation of non-topological QA answers."""

import math
import shapely
from shapely.geometry import Point
from shapely.wkt import loads as load_wkt
from . import geometry as nt


def recompute(item: dict):
    rid = item["relation_id"]
    os = item["objects"]
    gs = [load_wkt(o["geometry_wkt"]) for o in os]
    if rid in {"D01", "D02", "D04"}:
        v = nt.bearing(gs[0].centroid, gs[1].centroid)
        return nt.sector4(v) if rid == "D01" else nt.sector8(v) if rid == "D02" else round(v, 2)
    if rid == "D05":
        line, p = gs
        a, b = Point(line.coords[0]), Point(line.coords[-1])
        rel = ((nt.bearing(a, p) - nt.bearing(a, b) + 180) % 360) - 180
        if abs(rel) <= 45:
            return "front"
        if 45 < rel <= 135:
            return "right"
        if -135 <= rel < -45:
            return "left"
        return "back"
    if rid == "D06":
        return nt.axis4(nt.bearing(Point(gs[0].coords[0]), Point(gs[0].coords[-1])))
    if rid == "M01":
        return round(gs[0].distance(gs[1]), 2)
    if rid == "M02":
        return round(gs[0].boundary.distance(gs[1].boundary), 2)
    if rid == "M04":
        return round(abs(gs[0].x - gs[1].x) + abs(gs[0].y - gs[1].y), 2)
    if rid == "M08":
        return round(float(shapely.hausdorff_distance(gs[0], gs[1], densify=0.25)), 2)
    if rid == "M12":
        return round(gs[0].boundary.length, 2)
    if rid == "M14":
        radius = item["gold"]["oracle"]["buffer_radius_m"]
        return "yes" if gs[0].distance(gs[1]) <= radius + 1e-9 else "no"
    if rid == "M15":
        ds = {o["id"]: gs[0].distance(g) for o, g in zip(os[1:], gs[1:])}
        return min(ds, key=ds.get)
    if rid == "M18":
        count = sum(gs[0].covers(g) for g in gs[1:])
        return round(count / (gs[0].area / 1e6), 3)
    if rid == "O01":
        route = gs[0]
        ordered = sorted(zip(os[1:], gs[1:]), key=lambda z: route.project(z[1], normalized=True))
        return ">".join(x[0]["id"] for x in ordered)
    if rid == "O02":
        route = gs[0]
        ordered = sorted(zip(os[1:], gs[1:]), key=lambda z: route.project(z[1], normalized=True))
        return f"before={ordered[0][0]['id']}; after={ordered[1][0]['id']}"
    if rid == "O03":
        line, a, b = gs
        p, q = Point(line.coords[0]), Point(line.coords[-1])

        def cross(x):
            return (q.x - p.x) * (x.y - p.y) - (q.y - p.y) * (x.x - p.x)

        return "same_side" if cross(a) * cross(b) > 0 else "opposite_sides"
    if rid == "O04":
        a, b, c = gs
        vx, vy = c.x - a.x, c.y - a.y
        wx, wy = b.x - a.x, b.y - a.y
        t = (wx * vx + wy * vy) / (vx * vx + vy * vy)
        support_distance = abs(vx * wy - vy * wx) / math.hypot(vx, vy)
        return "yes" if support_distance <= 1e-6 and 0 < t < 1 else "no"
    if rid == "O06":
        la = float(os[0]["source_attributes"].get("layer", 0))
        lb = float(os[1]["source_attributes"].get("layer", 0))
        return "same_layer" if la == lb else "F01" if la > lb else "F02"
    if rid == "O08":
        edges = [o for o in os if o["role"] == "network_edge"]
        graph = nt.edge_graph(edges)
        snap = 0.01
        start, target = gs[-2], gs[-1]
        ks = (round(start.x / snap), round(start.y / snap))
        kt = (round(target.x / snap), round(target.y / snap))
        ok, _ = nt.reachable(graph, ks, kt)
        return "yes" if ok else "no"
    raise KeyError(rid)
