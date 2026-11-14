"""Task maps with an offline default and optional authenticated map backgrounds."""

import json
import math
import os
from pathlib import Path
import sys
import time

from .data_io import read_rows, write_json, sha256, select_per_relation

SIZE = 1536
PLOT = (100, 150, 1436, 1400)  # left, top, right, bottom in PNG pixels
COLORS = ["#2066a8", "#de6835", "#238c6b", "#9b59b6", "#bd8b1e", "#536678"]
ANNOTATION_STYLE = "geometry_aware_v1"


def scene_hash(row, editing):
    """Hash visible initial geometry and attributes, excluding reference edits."""
    import hashlib

    features = scene_features(row, editing)
    visible = {
        "id": row["task_id" if editing else "item_id"],
        "relation_id": row["relation_id"],
        "features": [(fid, geometry.wkt, attrs) for fid, geometry, attrs in features],
    }
    return hashlib.sha256(
        json.dumps(visible, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


def image_metadata(image_path, row, editing):
    from PIL import Image

    image_path = Path(image_path)
    metadata_path = image_path.with_suffix(".frame.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("scene_sha256") != scene_hash(row, editing):
        raise ValueError(f"Image belongs to a different scene: {image_path.name}")
    if metadata.get("image_sha256") != sha256(image_path):
        raise ValueError(f"Image hash differs from render metadata: {image_path.name}")
    basemap_zoom = None
    if metadata.get("renderer") == "pillow_basemap_v2":
        basemap_zoom = metadata["basemap"]["max_zoom"]
    expected = frame_for(row, editing, basemap_zoom=basemap_zoom)
    if any(metadata.get(key) != value for key, value in expected.items() if key != "renderer"):
        raise ValueError(
            f"Image coordinate frame differs from the current renderer: {image_path.name}"
        )
    if metadata.get("renderer") in ("pillow_basemap_v1", "pillow_basemap_v2"):
        from .basemaps import georeference, PROVIDERS

        basemap = metadata.get("basemap", {})
        if basemap.get("provider") not in PROVIDERS or basemap.get("georeference") != georeference(
            row, editing
        ):
            raise ValueError(f"Image basemap metadata differs from the scene: {image_path.name}")
    elif metadata.get("renderer") != "offline_metric_v1" or "basemap" in metadata:
        raise ValueError(f"Unknown image renderer: {image_path.name}")
    with Image.open(image_path) as image:
        image.verify()
        if image.size != (SIZE, SIZE) or image.format != "PNG":
            raise ValueError("Expected a 1536 x 1536 PNG")
    return metadata


def scene_features(task, editing):
    from shapely import wkt

    if editing:
        return [
            (f["feature_id"], wkt.loads(f["wkt"]), f.get("semantics", {}))
            for f in task["scene_features"]
        ]
    return [
        (f["id"], wkt.loads(f["geometry_wkt"]), f.get("source_attributes", {}))
        for f in task["objects"]
    ]


def frame_for(task, editing=True, *, basemap_zoom=None):
    features = scene_features(task, editing)
    minx = min(g.bounds[0] for _, g, _ in features)
    miny = min(g.bounds[1] for _, g, _ in features)
    maxx = max(g.bounds[2] for _, g, _ in features)
    maxy = max(g.bounds[3] for _, g, _ in features)
    left, top, right, bottom = PLOT if basemap_zoom is None else (0, 0, SIZE, SIZE)
    scale = max((maxx - minx) / (right - left), (maxy - miny) / (bottom - top), 0.01) * 1.25
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    renderer = "offline_metric_v1"
    if basemap_zoom is not None:
        from .basemaps import native_metres_per_pixel, RENDERER

        if (
            isinstance(basemap_zoom, bool)
            or not isinstance(basemap_zoom, int)
            or not 1 <= basemap_zoom <= 19
        ):
            raise ValueError("Basemap zoom must be an integer from 1 to 19")
        scale = max(scale, native_metres_per_pixel(task, editing, (cx, cy), basemap_zoom))
        renderer = RENDERER
    return {
        "xmin": cx - (right - left) * scale / 2,
        "ymax": cy + (bottom - top) * scale / 2,
        "metres_per_pixel": scale,
        "plot_pixels": [left, top, right, bottom],
        "canvas_pixels": [SIZE, SIZE],
        "renderer": renderer,
    }


def to_pixels(geometry, frame):
    from shapely import affinity

    scale = frame["metres_per_pixel"]
    left, top, _, _ = frame["plot_pixels"]
    return affinity.affine_transform(
        geometry,
        [1 / scale, 0, 0, -1 / scale, left - frame["xmin"] / scale, top + frame["ymax"] / scale],
    )


def from_pixels(geometry, frame):
    from shapely import affinity

    scale = frame["metres_per_pixel"]
    left, top, _, _ = frame["plot_pixels"]
    return affinity.affine_transform(
        geometry, [scale, 0, 0, -scale, frame["xmin"] - left * scale, frame["ymax"] + top * scale]
    )


def draw_geometry(ax, geom, color):
    from matplotlib.path import Path as MPath
    from matplotlib.patches import PathPatch

    if hasattr(geom, "geoms"):
        for part in geom.geoms:
            draw_geometry(ax, part, color)
    elif geom.geom_type == "Point":
        ax.scatter(
            [geom.x], [geom.y], s=75, color=color, edgecolors="white", linewidths=1, zorder=5
        )
    elif geom.geom_type in ("LineString", "LinearRing"):
        xs, ys = geom.xy
        ax.plot(xs, ys, color=color, linewidth=2.6, zorder=3)
        if len(xs) > 1:
            ax.annotate(
                "",
                xy=(xs[-1], ys[-1]),
                xytext=(xs[-2], ys[-2]),
                arrowprops={"arrowstyle": "->", "color": color, "lw": 2},
                zorder=4,
            )
            ax.scatter([xs[0]], [ys[0]], color=color, s=16, zorder=4)
    elif geom.geom_type == "Polygon":
        # Preserve holes with consistently oriented rings.
        from shapely.geometry.polygon import orient

        geom = orient(geom, sign=1.0)
        vertices, codes = [], []
        for ring in [geom.exterior, *geom.interiors]:
            coords = list(ring.coords)
            vertices.extend(coords)
            codes.extend([MPath.MOVETO] + [MPath.LINETO] * (len(coords) - 2) + [MPath.CLOSEPOLY])
        ax.add_patch(
            PathPatch(MPath(vertices, codes), facecolor=color, edgecolor=color, alpha=0.24, lw=2)
        )


def render_case(
    case,
    task="both",
    per_relation=0,
    basemap="none",
    basemap_style=None,
    basemap_zoom=19,
    basemap_cache=None,
    dry_run=False,
):
    if basemap != "none":
        return render_basemap_case(
            case, task, per_relation, basemap, basemap_style, basemap_zoom, basemap_cache, dry_run
        )
    if basemap_style is not None or basemap_cache is not None or basemap_zoom != 19:
        raise ValueError("Basemap settings require --basemap geoapify or stadia")
    if dry_run:
        counts = {
            kind: len(select_per_relation(read_rows(Path(case) / kind / name), per_relation))
            for kind, name in (("qa", "items.jsonl"), ("editing", "tasks.jsonl"))
            if task in (kind, "both")
        }
        return {"dry_run": True, "scenes": counts, "network_calls": 0}
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["savefig.bbox"] = None
    from matplotlib.lines import Line2D

    case = Path(case).resolve()
    counts = {}
    for kind in ("qa", "editing"):
        if task not in ("both", kind):
            continue
        editing = kind == "editing"
        rows = select_per_relation(
            read_rows(case / kind / ("tasks.jsonl" if editing else "items.jsonl")), per_relation
        )
        target = case / "images" / kind
        target.mkdir(parents=True, exist_ok=True)
        for row in rows:
            row_id = row["task_id" if editing else "item_id"]
            frame = frame_for(row, editing)
            image_path = target / f"{row_id}.png"
            if image_path.exists():
                metadata = image_metadata(image_path, row, editing)
                if metadata.get("renderer") != "offline_metric_v1":
                    raise ValueError(
                        "Cached image uses a basemap; use a new output directory for offline maps"
                    )
                continue
            features = scene_features(row, editing)
            fig = plt.figure(figsize=(12, 12), dpi=128, facecolor="#ffffff")
            left, top, right, bottom = PLOT
            ax = fig.add_axes(
                [left / SIZE, (SIZE - bottom) / SIZE, (right - left) / SIZE, (bottom - top) / SIZE]
            )
            mpp = frame["metres_per_pixel"]
            ax.set_xlim(frame["xmin"], frame["xmin"] + (right - left) * mpp)
            ax.set_ylim(frame["ymax"] - (bottom - top) * mpp, frame["ymax"])
            ax.set_aspect("equal")
            ax.set_facecolor("#f6f8fa")
            handles = []
            for i, (fid, geom, attrs) in enumerate(features):
                color = COLORS[i % len(COLORS)]
                draw_geometry(ax, geom, color)
                c = geom.centroid
                ax.annotate(
                    fid,
                    (c.x, c.y),
                    xytext=(5 + 8 * (i % 3), 5 + 10 * (i % 4)),
                    textcoords="offset points",
                    color=color,
                    fontsize=10,
                    weight="bold",
                    zorder=8,
                    bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "none", "pad": 1.2},
                )
                label = fid
                if row["relation_id"] == "O06":
                    label += f" (layer={attrs.get('layer', attrs.get('osm_layer', '?'))})"
                handles.append(Line2D([0], [0], color=color, lw=3, label=label))
            ax.grid(alpha=0.18)
            ax.ticklabel_format(style="plain", useOffset=False)
            ax.set_xlabel("Easting / local x (metres)")
            ax.set_ylabel("Northing / local y (metres)")
            # Large projected northings leave no room for an external axis title.
            ax.yaxis.set_label_coords(0.025, 0.5)
            ax.yaxis.label.set_bbox({"facecolor": "#f6f8fa", "edgecolor": "none", "alpha": 0.9})
            ax.legend(
                handles=handles,
                loc="upper left",
                fontsize=8,
                ncol=min(4, len(handles)),
                framealpha=0.95,
            )
            ax.text(0.98, 0.97, "N ↑", transform=ax.transAxes, ha="right", va="top", fontsize=14)
            fig.text(0.5, 0.965, f"{row_id} · annotated task geometry", ha="center", fontsize=15)
            fig.text(
                0.5,
                0.035,
                "Offline metric renderer · no basemap · geometry: © OpenStreetMap contributors",
                ha="center",
                fontsize=9,
                color="#536678",
            )
            fig.savefig(image_path, dpi=128)
            plt.close(fig)
            frame.update(scene_sha256=scene_hash(row, editing), image_sha256=sha256(image_path))
            write_json(target / f"{row_id}.frame.json", frame)
        counts[kind] = len(rows)
    return {"rendered": counts, "canvas": SIZE, "renderer": "offline_metric_v1"}


def _directed_feature(row, editing, feature_id):
    """Show stored direction only on the feature whose direction the task uses."""
    relation = row["relation_id"]
    if relation == "D05":
        return feature_id == ("F1" if editing else "F01")
    if relation in ("O01", "O02"):
        return feature_id == ("F1" if editing else "F00")
    # QA D06 asks for an undirected axis; Editing D06 requires a directed heading.
    return editing and relation == "D06" and feature_id == "F0"


def _draw_pixel_geometry(canvas, geometry, color, directed=False):
    from PIL import Image, ImageDraw, ImageColor

    draw = ImageDraw.Draw(canvas)
    if hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            _draw_pixel_geometry(canvas, part, color, directed)
    elif geometry.geom_type == "Point":
        x, y = geometry.x, geometry.y
        draw.ellipse((x - 10, y - 10, x + 10, y + 10), fill=color, outline="white", width=3)
    elif geometry.geom_type in ("LineString", "LinearRing"):
        points = list(geometry.coords)
        draw.line(points, fill=color, width=7, joint="curve")
        if not directed:
            return
        x0, y0 = points[0]
        radius = min(4, geometry.length * 0.08)
        draw.ellipse((x0 - radius, y0 - radius, x0 + radius, y0 + radius), fill=color)
        for a, b in reversed(list(zip(points, points[1:]))):
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            if length > 1e-9:
                ux, uy = dx / length, dy / length
                head = min(20, geometry.length * 0.28, length * 0.8)
                half_width = head * 0.4
                draw.polygon(
                    [
                        b,
                        (b[0] - head * ux - half_width * uy, b[1] - head * uy + half_width * ux),
                        (b[0] - head * ux + half_width * uy, b[1] - head * uy - half_width * ux),
                    ],
                    fill=color,
                )
                break
    elif geometry.geom_type == "Polygon":
        mask = Image.new("L", canvas.size)
        pen = ImageDraw.Draw(mask)
        pen.polygon(list(geometry.exterior.coords), fill=60)
        for ring in geometry.interiors:
            pen.polygon(list(ring.coords), fill=0)
        fill = Image.new("RGBA", canvas.size, ImageColor.getrgb(color))
        fill.putalpha(mask)
        canvas.alpha_composite(fill)
        for ring in (geometry.exterior, *geometry.interiors):
            draw.line(list(ring.coords), fill=color, width=6, joint="curve")


def _label_layout(geometries, sizes, reserved):
    """Place labels away from symbols and small areas; attach leaders to real geometry."""
    from shapely.geometry import LineString, box
    from shapely.ops import nearest_points

    occupied = [box(*rect).buffer(4) for rect in reserved]
    leaders = []
    result = {}
    # Small symbols get first choice; areas still reserve their boundaries/fills below.
    order = sorted(
        range(len(geometries)), key=lambda i: (geometries[i].area > 0, geometries[i].length > 0, i)
    )
    for i in order:
        geometry = geometries[i]
        w, h = sizes[i]
        blockers = [
            (g.boundary if g.area > 20 * w * h else g).buffer(7 if g.length == 0 else 5)
            for g in geometries
        ]
        anchor = (
            geometry.interpolate(0.5, normalized=True)
            if geometry.geom_type == "LineString"
            else geometry.representative_point()
        )
        references = [anchor.bounds, geometry.bounds]
        # A point inside a small building needs candidates outside that building too.
        references += [
            g.bounds
            for j, g in enumerate(geometries)
            if j != i and g.area <= 20 * w * h and g.distance(anchor) < max(w, h)
        ]
        candidates = set()
        for xmin, ymin, xmax, ymax in references:
            cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
            for gap in (14, 28):
                for x, y in (
                    (xmax + gap, cy - h / 2),
                    (cx - w / 2, ymin - gap - h),
                    (xmin - gap - w, cy - h / 2),
                    (cx - w / 2, ymax + gap),
                    (xmax + gap, ymin - gap - h),
                    (xmin - gap - w, ymin - gap - h),
                    (xmax + gap, ymax + gap),
                    (xmin - gap - w, ymax + gap),
                ):
                    x, y = min(SIZE - w - 12, max(12, x)), min(SIZE - h - 12, max(12, y))
                    candidates.add((x, y, x + w, y + h))
        best = None
        for rect in sorted(candidates):
            label = box(*rect)
            overlap = sum(label.intersection(b).area for b in occupied)
            covered = sum(label.intersection(b).area for b in blockers)
            source = geometry.boundary if geometry.area else anchor
            start, end = nearest_points(source, label)
            a, b = start.coords[0], end.coords[0]
            for corner in ((b[0], a[1]), (a[0], b[1])):
                path = LineString([a, corner, b])
                hits = sum(path.intersection(o).length for o in occupied)
                crossings = sum(path.crosses(other) for other in leaders)
                # Prefer short leaders; do not trade a large detour for tiny incidental crossings.
                other_features = sum(
                    path.intersection(g).length for j, g in enumerate(blockers) if j != i
                )
                other_features += max(0, path.intersection(blockers[i]).length - 8)
                score = (
                    overlap,
                    covered,
                    hits,
                    path.length + 6 * other_features + 24 * crossings,
                    rect,
                    corner,
                )
                if best is None or score < best[0]:
                    best = (score, rect, list(path.coords))
        _, rect, coordinates = best
        occupied.append(box(*rect).buffer(5))
        leaders.append(LineString(coordinates))
        result[i] = (rect, coordinates)
    return [result[i] for i in range(len(geometries))]


def _render_basemap_scene(row, editing, frame, background, plan, image_path):
    from collections import defaultdict
    from PIL import Image, ImageDraw, ImageFont
    from shapely import affinity

    left, top, right, bottom = frame["plot_pixels"]
    width, height = right - left, bottom - top
    features = scene_features(row, editing)
    overlay = Image.new("RGBA", (width * 2, height * 2))
    pixel_geometries = [to_pixels(geometry, frame) for _, geometry, _ in features]
    draw_order = sorted(
        range(len(features)),
        key=lambda i: (pixel_geometries[i].area == 0, pixel_geometries[i].length == 0),
    )
    for i in draw_order:
        fid, geometry, _ = features[i]
        pixel = affinity.translate(to_pixels(geometry, frame), xoff=-left, yoff=-top)
        _draw_pixel_geometry(
            overlay,
            affinity.scale(pixel, xfact=2, yfact=2, origin=(0, 0)),
            COLORS[i % len(COLORS)],
            directed=_directed_feature(row, editing, fid),
        )
    image = background.convert("RGBA")
    image.alpha_composite(overlay.resize((width, height), Image.Resampling.LANCZOS))
    image = image.convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default(size=22)
    small = ImageFont.load_default(size=18)
    title_font = ImageFont.load_default(size=28)
    ink = "#263238"

    def card(rect):
        draw.rounded_rectangle(
            rect, radius=10, fill=(255, 255, 255, 242), outline="#d7dfe3", width=1
        )

    # One compact key instead of separate title, subtitle and oversized legend margins.
    title = row["task_id" if editing else "item_id"]
    subtitle = f"{plan['provider']} / {plan['style']}"
    labels = [
        fid
        + (
            f" · layer {attrs.get('layer', attrs.get('osm_layer', '?'))}"
            if row["relation_id"] == "O06"
            else ""
        )
        for fid, _, attrs in features
    ]
    columns = min(4, len(labels))
    cell = max(draw.textlength(label, font=font) for label in labels) + 54
    header_width = (
        max(
            draw.textlength(title, font=title_font),
            draw.textlength(subtitle, font=small),
            columns * cell,
        )
        + 32
    )
    header = (24, 24, 24 + header_width, 120 + math.ceil(len(labels) / columns) * 32)
    card(header)
    draw.text((40, 39), title, font=title_font, fill=ink)
    draw.text((40, 77), subtitle, font=small, fill="#536678")
    for i, label in enumerate(labels):
        x, y = 40 + i % columns * cell, 114 + i // columns * 32
        draw.line((x, y + 11, x + 24, y + 11), fill=COLORS[i % len(COLORS)], width=4)
        draw.text((x + 34, y), label, font=font, fill=ink)

    north = (SIZE - 84, 24, SIZE - 24, 124)
    card(north)
    nx = SIZE - 54
    draw.text((nx, 47), "N", anchor="mm", font=font, fill=ink)
    draw.line((nx, 104, nx, 72), fill=ink, width=3)
    draw.polygon([(nx, 64), (nx - 7, 78), (nx + 7, 78)], fill=ink)

    target = 180 * frame["metres_per_pixel"]
    power = 10 ** math.floor(math.log10(target))
    length = max(v * power for v in (1, 2, 5) if v * power <= target)
    bar = length / frame["metres_per_pixel"]
    scale = (24, SIZE - 102, 64 + bar, SIZE - 24)
    card(scale)
    sx, sy = 44, SIZE - 46
    draw.text((sx + bar / 2, sy - 24), f"{length:g} m", anchor="mm", font=small, fill=ink)
    draw.line((sx, sy, sx + bar, sy), fill=ink, width=3)
    for x in (sx, sx + bar):
        draw.line((x, sy - 5, x, sy + 5), fill=ink, width=3)

    credit_font = ImageFont.load_default(size=17)
    credit_width = max(
        draw.textlength(plan[k], font=credit_font) for k in ("attribution", "attribution_urls")
    )
    credits = (SIZE - 48 - credit_width, SIZE - 86, SIZE - 24, SIZE - 24)
    card(credits)
    draw.text(
        (SIZE - 36, SIZE - 65), plan["attribution"], anchor="rm", font=credit_font, fill="#536678"
    )
    draw.text(
        (SIZE - 36, SIZE - 42),
        plan["attribution_urls"],
        anchor="rm",
        font=credit_font,
        fill="#536678",
    )

    # Exact coincident points keep their true position; concentric rings expose both IDs.
    points = defaultdict(list)
    for i, (_, geometry, _) in enumerate(features):
        if geometry.geom_type == "Point":
            points[tuple(geometry.coords[0])].append(i)
    for coordinates, indices in points.items():
        if len(indices) > 1:
            from shapely.geometry import Point

            point = to_pixels(Point(coordinates), frame)
            for j, i in enumerate(indices):
                radius = 6 + 4 * (len(indices) - j - 1)
                draw.ellipse(
                    (point.x - radius, point.y - radius, point.x + radius, point.y + radius),
                    outline=COLORS[i % len(COLORS)],
                    width=3,
                )

    label_font = ImageFont.load_default(size=20)
    text_boxes = [draw.textbbox((0, 0), fid, font=label_font) for fid, _, _ in features]
    sizes = [(b[2] - b[0] + 14, b[3] - b[1] + 10) for b in text_boxes]
    placements = _label_layout(pixel_geometries, sizes, [header, north, scale, credits])
    # Leaders sit below labels, use white casing for contrast, and never carry arrowheads.
    for i, (_, coordinates) in enumerate(placements):
        if math.dist(coordinates[0], coordinates[-1]) > 3:
            from shapely.geometry import LineString

            leader = LineString(coordinates)
            # Stop short of the feature symbol so the leader cannot masquerade as its outline.
            gap = 8 if pixel_geometries[i].length == 0 else 3
            if leader.length > gap:
                from shapely.ops import substring

                points = list(substring(leader, gap, leader.length).coords)
                draw.line(points, fill=(255, 255, 255, 235), width=5, joint="curve")
                draw.line(points, fill="#53616c", width=2, joint="curve")
    for i, ((fid, _, _), (label, _)) in enumerate(zip(features, placements)):
        color = COLORS[i % len(COLORS)]
        draw.rounded_rectangle(label, radius=5, fill="white", outline=color, width=2)
        draw.text((label[0] + 7, label[1] + 5 - text_boxes[i][1]), fid, font=label_font, fill=color)
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(image_path)


def render_basemap_case(case, task, per_relation, provider, style, zoom, cache, dry_run):
    from .basemaps import Basemap, RENDERER, rendered_at

    client = Basemap(provider, style, zoom, cache)
    case = Path(case).resolve()
    jobs, counts, requests = [], {}, {}
    # Preflight every selected scene and existing image before any network call.
    for kind, name in (("qa", "items.jsonl"), ("editing", "tasks.jsonl")):
        if task not in ("both", kind):
            continue
        editing = kind == "editing"
        rows = select_per_relation(read_rows(case / kind / name), per_relation)
        counts[kind] = len(rows)
        for row in rows:
            frame = frame_for(row, editing, basemap_zoom=client.max_zoom)
            plan = client.plan(row, editing, frame)
            plan["annotations"] = ANNOTATION_STYLE
            image_path = case / "images" / kind / f"{row['task_id' if editing else 'item_id']}.png"
            if image_path.exists():
                metadata = image_metadata(image_path, row, editing)
                if metadata.get("renderer") != RENDERER or metadata.get("basemap") != plan:
                    raise ValueError(
                        "Cached image uses different basemap settings; use a new output directory"
                    )
                continue
            jobs.append((row, editing, frame, plan, image_path))
            for path, _, _ in client.requests(plan):
                if not path.exists():
                    requests[path] = 0.25 if provider == "geoapify" else 2000
    if dry_run:
        return {
            "dry_run": True,
            "scenes": counts,
            "images_to_render": len(jobs),
            "downloads": len(requests),
            "estimated_credits": sum(requests.values()),
            "network_calls": 0,
        }
    if requests and not os.environ.get(client.settings["key_env"]):
        raise ValueError(
            f"Set {client.settings['key_env']} in .env or the environment to download basemaps"
        )
    print(
        f"{provider}: {len(jobs)} images to render, {sum(counts.values()) - len(jobs)} reused; "
        f"{len(requests)} downloads, estimated {sum(requests.values()):g} credits",
        file=sys.stderr,
        flush=True,
    )
    for index, (row, editing, frame, plan, image_path) in enumerate(jobs, 1):
        started = last_update = time.monotonic()
        print(
            f"[{index}/{len(jobs)}] {image_path.stem}: loading basemap…",
            file=sys.stderr,
            flush=True,
        )

        def progress(done, total):
            nonlocal last_update
            now = time.monotonic()
            if done == total or now - last_update >= 3:
                print(f"  tiles {done}/{total} · {now - started:.1f}s", file=sys.stderr, flush=True)
                last_update = now

        background = client.background(plan, frame, progress)
        _render_basemap_scene(row, editing, frame, background, plan, image_path)
        metadata = {
            **frame,
            "renderer": RENDERER,
            "basemap": plan,
            "rendered_at": rendered_at(),
            "scene_sha256": scene_hash(row, editing),
            "image_sha256": sha256(image_path),
        }
        write_json(image_path.with_suffix(".frame.json"), metadata)
        print(
            f"  saved {image_path.name} · {time.monotonic() - started:.1f}s",
            file=sys.stderr,
            flush=True,
        )
    return {
        "rendered": counts,
        "canvas": SIZE,
        "renderer": RENDERER,
        "basemap": {"provider": provider, "style": client.style},
    }


def decode_pixel_edit(task, row):
    from shapely import wkt
    from shapely.geometry import shape
    from .editing.transforms import extract_json_obj

    payload = row.get("pixel_output")
    if payload is None:
        payload = extract_json_obj(row.get("prediction", ""))
    if not isinstance(payload, dict):
        raise ValueError("Expected pixel-output JSON")
    pixel = shape(payload["geometry"])
    if pixel.is_empty or not pixel.is_valid or not all(math.isfinite(v) for v in pixel.bounds):
        raise ValueError("Invalid pixel geometry")
    basemap_zoom = None
    if row.get("renderer") == "pillow_basemap_v2":
        from .basemaps import georeference

        basemap = row.get("basemap", {})
        if basemap.get("georeference") != georeference(task, True):
            raise ValueError("Prediction basemap frame differs from the task")
        basemap_zoom = basemap["max_zoom"]
    frame = frame_for(task, basemap_zoom=basemap_zoom)
    geometry = from_pixels(pixel, frame)
    if payload.get("layer") is not None and (
        isinstance(payload["layer"], bool) or not float(payload["layer"]).is_integer()
    ):
        raise ValueError("Layer must be an integer ordinal value")
    ctx = {"predicted_F0_layer": payload["layer"]} if payload.get("layer") is not None else {}
    gt_pixel = to_pixels(wkt.loads(task["ground_truth_wkt"]), frame)
    return geometry, ctx, float(pixel.hausdorff_distance(gt_pixel))
