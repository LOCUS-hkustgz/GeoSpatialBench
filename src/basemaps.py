"""Authenticated map backgrounds reprojected into a metric task frame."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import io
import math
import os
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image
from pyproj import CRS, Transformer

from .data_io import ROOT

RENDERER = "pillow_basemap_v2"
HALF_WORLD = math.pi * 6378137.0
PROVIDERS = {
    "geoapify": {
        "key_env": "GEOAPIFY_API_KEY",
        "styles": ("osm-bright-grey", "osm-bright-smooth", "osm-bright"),
        "endpoint": "raster_tiles",
        "attribution": "© Geoapify · © OpenMapTiles · © OpenStreetMap contributors",
        "attribution_urls": "geoapify.com · openmaptiles.org · openstreetmap.org/copyright",
    },
    "stadia": {
        "key_env": "STADIA_API_KEY",
        "styles": ("alidade_smooth", "osm_bright"),
        "endpoint": "static_cacheable",
        "attribution": "© Stadia Maps · © OpenMapTiles · © OpenStreetMap contributors",
        "attribution_urls": "stadiamaps.com · openmaptiles.org · openstreetmap.org/copyright",
    },
}


def georeference(row, editing):
    if editing:
        value = row.get("source_frame")
        if not isinstance(value, dict):
            raise ValueError(
                f"{row['task_id']}: basemaps need source_frame (projected crs and origin). "
                "The fixed Editing case has no recorded origin; generate new tasks or "
                "supply verified source_frame metadata. Use --basemap none for local-only scenes."
            )
    else:
        value = {"crs": row["crs"], "origin": [0, 0]}
    origin = value.get("origin")
    if (
        not isinstance(origin, (list, tuple))
        or len(origin) != 2
        or not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
            for x in origin
        )
    ):
        raise ValueError("source_frame.origin must contain two finite numbers")
    if not value.get("crs"):
        raise ValueError("source_frame.crs is required")
    crs = CRS.from_user_input(value["crs"])
    if (
        not crs.is_projected
        or not crs.axis_info
        or any(
            a.unit_name.lower() not in {"metre", "meter", "metres", "meters"} for a in crs.axis_info
        )
    ):
        raise ValueError("Basemap alignment requires a projected CRS with metre axes")
    return {"crs": crs.to_string(), "origin": list(origin)}


def native_metres_per_pixel(row, editing, centre, zoom):
    """Keep the viewport at least as wide as the finest available source raster."""
    geo = georeference(row, editing)
    x, y = (centre[i] + geo["origin"][i] for i in range(2))
    transform = Transformer.from_crs(geo["crs"], 3857, always_xy=True)
    mx, my = transform.transform(x, y)
    east, north = transform.transform(x + 1, y), transform.transform(x, y + 1)
    stretch = min(math.hypot(east[0] - mx, east[1] - my), math.hypot(north[0] - mx, north[1] - my))
    if not math.isfinite(stretch) or stretch <= 0:
        raise ValueError("Cannot determine the scene's map resolution")
    return 2 * HALF_WORLD / (256 * 2**zoom) / stretch


class Basemap:
    def __init__(self, provider, style=None, max_zoom=19, cache=None):
        if provider not in PROVIDERS:
            raise ValueError("Basemap must be geoapify or stadia")
        self.provider = provider
        self.settings = PROVIDERS[provider]
        self.style = style or self.settings["styles"][0]
        if self.style not in self.settings["styles"]:
            raise ValueError(f"Supported {provider} styles: {', '.join(self.settings['styles'])}")
        if isinstance(max_zoom, bool) or not isinstance(max_zoom, int) or not 1 <= max_zoom <= 19:
            raise ValueError("--basemap-zoom must be an integer from 1 to 19")
        self.max_zoom = max_zoom
        self.cache = Path(cache or ROOT / "outputs/basemap_cache") / provider / self.style
        self._last_request = 0.0
        self._rate_lock = threading.Lock()

    def plan(self, row, editing, frame):
        """Plan from initial geometry only. All image coordinates stay in task metres."""
        geo = georeference(row, editing)
        left, top, right, bottom = frame["plot_pixels"]
        width, height = right - left, bottom - top
        ox, oy = geo["origin"]
        mpp = frame["metres_per_pixel"]
        bounds = (
            frame["xmin"] + ox,
            frame["ymax"] + oy - height * mpp,
            frame["xmin"] + ox + width * mpp,
            frame["ymax"] + oy,
        )
        transform = Transformer.from_crs(geo["crs"], 3857, always_xy=True)
        west, south, east, north = transform.transform_bounds(*bounds, densify_pts=21)
        if not all(math.isfinite(x) and abs(x) < HALF_WORLD for x in (west, south, east, north)):
            raise ValueError("Scene lies outside the supported Web Mercator map extent")
        resolution = max((east - west) / width, (north - south) / height)
        zoom = max(1, min(self.max_zoom, math.floor(math.log2(2 * HALF_WORLD / 256 / resolution))))
        while True:
            scale = 256 * 2**zoom / (2 * HALF_WORLD)
            # Two source pixels of padding keep bilinear samples inside the raster.
            x0, y0 = (
                math.floor((west + HALF_WORLD) * scale) - 2,
                math.floor((HALF_WORLD - north) * scale) - 2,
            )
            x1, y1 = (
                math.ceil((east + HALF_WORLD) * scale) + 2,
                math.ceil((HALF_WORLD - south) * scale) + 2,
            )
            if self.provider == "geoapify":
                x0, y0 = x0 // 256 * 256, y0 // 256 * 256
                x1, y1 = math.ceil(x1 / 256) * 256, math.ceil(y1 / 256) * 256
            else:
                # The static endpoint accepts at least 64 points per dimension
                # when attribution is rendered separately on the final canvas.
                dx, dy = max(0, 64 - (x1 - x0)), max(0, 64 - (y1 - y0))
                x0, y0 = x0 - dx // 2, y0 - dy // 2
                x1, y1 = x1 + dx - dx // 2, y1 + dy - dy // 2
            if self.provider != "stadia" or max(x1 - x0, y1 - y0) <= 4096:
                break
            zoom -= 1
            if zoom < 1:
                raise ValueError("Scene exceeds the Stadia static image size limit")
        return {
            "provider": self.provider,
            "style": self.style,
            "endpoint": self.settings["endpoint"],
            "max_zoom": self.max_zoom,
            "zoom": zoom,
            "pixel_box": [x0, y0, x1 - x0, y1 - y0],
            "georeference": geo,
            "attribution": self.settings["attribution"],
            "attribution_urls": self.settings["attribution_urls"],
        }

    def requests(self, plan):
        x0, y0, width, height = plan["pixel_box"]
        zoom = plan["zoom"]
        if self.provider == "geoapify":
            for y in range(y0 // 256, (y0 + height) // 256):
                for x in range(x0 // 256, (x0 + width) // 256):
                    yield self.cache / str(zoom) / str(x) / f"{y}.png", (x, y), (256, 256)
        else:
            yield self.cache / str(zoom) / f"{x0}_{y0}_{width}_{height}.png", None, (width, height)

    def fetch(self, path, tile, size, plan):
        if path.exists():
            with Image.open(path) as image:
                image.load()
                if image.size != size or image.format != "PNG":
                    raise ValueError(f"Invalid cached basemap image: {path}")
                return image.convert("RGB")
        key_env = self.settings["key_env"]
        key = os.environ.get(key_env)
        if not key:
            raise ValueError(f"Set {key_env} in .env or the environment to download basemaps")
        headers = {"User-Agent": "GeoSpatialBench (+https://geospatialbench.kgtx.cloud/)"}
        if self.provider == "geoapify":
            x, y = tile
            url = (
                f"https://maps.geoapify.com/v1/tile/{self.style}/{plan['zoom']}/{x}/{y}.png?"
                + urllib.parse.urlencode({"apiKey": key})
            )
        else:
            x0, y0, width, height = plan["pixel_box"]
            scale = 256 * 2 ** plan["zoom"] / (2 * HALF_WORLD)
            mx = (x0 + width / 2) / scale - HALF_WORLD
            my = HALF_WORLD - (y0 + height / 2) / scale
            lon, lat = Transformer.from_crs(3857, 4326, always_xy=True).transform(mx, my)
            # Static maps use a 512-point world at zoom 0 (MapLibre convention),
            # equivalent to XYZ's 256-pixel world at zoom 1.
            params = {
                "center": f"{lat:.12f},{lon:.12f}",
                "zoom": plan["zoom"] - 1,
                "size": f"{width}x{height}",
                "manual_attribution": "true",
            }
            url = (
                f"https://tiles.stadiamaps.com/static_cacheable/{self.style}.png?"
                + urllib.parse.urlencode(params)
            )
            headers["Authorization"] = "Stadia-Auth " + key
        # Four starts per second across workers, including bounded transient retries.
        # Authentication and quota failures stop immediately; never change provider.
        for attempt in range(3):
            with self._rate_lock:
                time.sleep(max(0, 0.25 - (time.monotonic() - self._last_request)))
                self._last_request = time.monotonic()
            try:
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = response.read()
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in (408, 500, 502, 503, 504) or attempt == 2:
                    raise RuntimeError(
                        f"{self.provider} basemap HTTP {exc.code}; check key, plan and quota"
                    ) from None
                reason = f"HTTP {exc.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                detail = getattr(exc, "reason", exc)
                reason = type(detail).__name__
                if attempt == 2 or isinstance(detail, ssl.SSLCertVerificationError):
                    raise RuntimeError(
                        f"{self.provider} basemap connection failed ({reason}); "
                        "rerun to reuse completed downloads"
                    ) from None
            print(
                f"  {self.provider}: {reason}; retry {attempt + 1}/2", file=sys.stderr, flush=True
            )
            time.sleep(2**attempt)
        # Never log signed URLs, request headers, credentials or provider bodies.
        try:
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                if image.size != size or image.format != "PNG":
                    raise ValueError("Unexpected map image dimensions or format")
                image = image.convert("RGB")
        except (OSError, ValueError):
            raise RuntimeError(f"{self.provider} did not return the expected PNG image") from None
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".png", delete=False) as stream:
            temporary = Path(stream.name)
        try:
            image.save(temporary)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return image

    def background(self, plan, frame, progress=None):
        x0, y0, width, height = plan["pixel_box"]
        raster = Image.new("RGB", (width, height))
        requests = list(self.requests(plan))
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(self.fetch, path, tile, size, plan): tile
                for path, tile, size in requests
            }
            try:
                for done, future in enumerate(as_completed(futures), 1):
                    tile = futures[future]
                    image = future.result()
                    offset = (tile[0] * 256 - x0, tile[1] * 256 - y0) if tile else (0, 0)
                    raster.paste(image, offset)
                    if progress:
                        progress(done, len(requests))
            except BaseException:
                for future in futures:
                    future.cancel()
                raise
        left, top, right, bottom = frame["plot_pixels"]
        geo = plan["georeference"]
        ox, oy = geo["origin"]
        mpp = frame["metres_per_pixel"]
        xs = frame["xmin"] + ox + (np.arange(right - left) + 0.5) * mpp
        ys = frame["ymax"] + oy - (np.arange(bottom - top) + 0.5) * mpp
        xx, yy = np.meshgrid(xs, ys)
        mx, my = Transformer.from_crs(geo["crs"], 3857, always_xy=True).transform(xx, yy)
        scale = 256 * 2 ** plan["zoom"] / (2 * HALF_WORLD)
        u, v = (mx + HALF_WORLD) * scale - x0 - 0.5, (HALF_WORLD - my) * scale - y0 - 0.5
        if not (
            np.isfinite(u).all()
            and np.isfinite(v).all()
            and u.min() >= 0
            and v.min() >= 0
            and u.max() < width - 1
            and v.max() < height - 1
        ):
            raise ValueError("Basemap does not cover the task pixel frame")
        ix, iy = np.floor(u).astype(int), np.floor(v).astype(int)
        fx, fy = (u - ix)[..., None], (v - iy)[..., None]
        pixels = np.asarray(raster, dtype=np.float32)
        rgb = (pixels[iy, ix] * (1 - fx) + pixels[iy, ix + 1] * fx) * (1 - fy) + (
            pixels[iy + 1, ix] * (1 - fx) + pixels[iy + 1, ix + 1] * fx
        ) * fy
        return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))


def rendered_at():
    return datetime.now(timezone.utc).isoformat()
