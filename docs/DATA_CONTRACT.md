# Data requirements and provenance

## Bundled Stockholm data

The fixed case at `data/stockholm/` contains 700 QA scenes and 700 independent Editing tasks, each with 28 relations × 25 instances. QA uses EPSG:3006 projected coordinates; Editing uses scene-local metres. Included Qwen3.5-9B predictions match only the fixed `STO` scenes, not newly generated `STODEMO` scenes.

| Directory | Contents |
|---|---|
| `qa/` | Canonical scenes and Open/MCQ reference answers |
| `editing/` | Initial scenes, constraints and reference edits |
| `predictions/` | Qwen3.5-9B GeoJSON predictions |
| `vector/` | Source GeoPackage and provenance manifest |

Public prompts are generated from the selected scenes and matching references by `scripts/prepare_inputs.py`; they are not stored in the fixed case.

`vector/stockholm_sample.gpkg` is a four-layer sample in **EPSG:3006** (SWEREF 99 TM, metres). It can be opened with QGIS, ArcGIS or GeoPandas.

| Layer | Features | Geometry |
|---|---:|---|
| `pois` | 1,800 | Point |
| `roads` | 2,400 | LineString |
| `buildings` | 1,400 | Polygon |
| `landuse` | 60 | Polygon |

All layers include `source_id`, `name` and `fclass`. Roads also include `osm_layer`, `bridge` and `tunnel`. The sample retains **213 roads with nonzero layer values**, including intersecting pairs with unequal layers. Layer is ordinal vertical stacking, not elevation in metres; bridge/tunnel flags are normalized to `T` or `F`.

The sample is not a complete city extract. Source geometries are projected without simplification or shape clipping. Closed roads are excluded because first-to-last directional probes require distinct endpoints. Dense regions and observed POIs are retained for density tasks, both roads in selected unequal-layer pairs are preserved, and other features use deterministic sampling.

## Roles and fields

| Config role | Geometry after exploding multipart features | Minimum filtered features | Use |
|---|---|---:|---|
| `pois` | Point | 750 | Direction, distance, nearest neighbor, density |
| `roads` | LineString | 1,250 | Topology, orientation, order and network questions |
| `buildings` | Polygon | 650 | Topology, boundary distance and perimeter |
| `landuse` | Polygon | 25 | Region density and editing regions |

These counts are necessary for the locked QA sampler, not a guarantee that every relation is available. At least 25 candidate density regions must cover three or more supplied POIs. Vertical-order QA needs 2D-intersecting roads with usable numeric `layer` values, including nonzero values. Enlarge the extent when candidates are insufficient. Editing still uses this shared input check, even when fewer editing tasks are requested.

Each role specifies `path` and, for a multilevel format such as GeoPackage, `layer`. Formats supported by GeoPandas include GeoPackage, GeoJSON and Shapefile. Use a stable `id_field`; without it, source row positions are used and depend on file ordering. Multipart features are exploded; generation preserves a component suffix where needed. Wrong geometry types and empty geometries are filtered; invalid geometries are rejected and must be repaired in the source.

Roads must expose an ordinal numeric layer, mapped through `field_map.layer`. `bridge` and `tunnel` are optional flags. **Layer is vertical stacking order, not elevation in metres.** Missing numeric layer cells default to zero; an entirely zero layer column fails the full input check. Non-numeric non-null values are rejected. Do not fabricate bridge/tunnel/layer metadata to make the check pass.

```json
"roads": {
  "path": "../local_data/roads.geojson",
  "id_field": "osm_id",
  "field_map": {"layer": "z_order", "bridge": "is_bridge", "tunnel": "is_tunnel"},
  "attribute_fields": ["name", "type"]
}
```

`attribute_fields` are retained in canonical records. The public default GeoJSON QA mode sends geometry and anonymous IDs only, which makes O06 information-insufficient. Its excluded-subset score is reported separately. The map renderer explicitly shows the O06 layer values.

For a single mixed GeoJSON, several roles may point to the same file. Use a verified classification field to distinguish polygon roles:

```json
"buildings": {"path":"../local_data/city.geojson", "attribute_filter":{"role":["building"]}},
"landuse": {"path":"../local_data/city.geojson", "attribute_filter":{"role":["landuse","park"]}}
```

## Coordinates and filtering

Input layers must have a declared CRS, or an explicit `source_crs` in the role config. `target_crs` must be projected with metre axes. Longitude/latitude or foot-based projections are rejected for metric calculations. `scripts/configure_city.py` retains a metre-based source CRS; otherwise it estimates a UTM zone from up to 1,000 POIs. Review that estimate against your full city extent. You can always pass `--target-crs` explicitly.

If `read_bbox` is used, it is interpreted in the **source CRS**, per role. For differing layer CRSs, specify separate role-level `read_bbox` values. WGS84 boundaries cannot be applied directly to a projected source. Default strict filter intervals are roads (30, 1200) m, buildings (50, 30000) m² and regions (20000, 3000000) m². These are editable city parameters and appear in the config.

QA uses projected coordinates. Editing recentres each scene into a local metric frame. The local frame is not EPSG:4326 GeoJSON; coordinate units are stated in the prompt. Do not reproject the editing coordinates as if they were longitude/latitude.

Newly generated Editing tasks retain `source_frame`, for example `{"crs":"EPSG:3006","origin":[672500,6580000]}`. Source coordinates equal task coordinates plus this origin; the translation does not change task geometry or scoring. Basemap rendering uses this metadata, but model messages do not contain it. The fixed historical Editing case has no recorded origin and remains usable without a basemap; geographic placement requires verified source-frame metadata. The renderer never guesses a city centre or uses reference edits to locate a scene.

## What gets constructed

The 28 relations comprise T9 + D5 + M8 + O6. Their IDs are defined in `src/relations.py`; definitions and the four deferred relations are described in [the benchmark protocol](PROTOCOL.md#relations). QA uses observed geometries and source-derived controlled constructions. Editing uses a separate miner and scene pool, rejects already-satisfied targets during mining, and checks a feasible reference edit. Reference edits are not necessarily unique.

The QA full build performs independent geometry/oracle recomputation, serialization checks, MCQ balance and prompt leakage audits. A full Editing build requires each reference to satisfy its constraints and all 28 quotas to be complete. Geometry mixes are influenced by available source candidates and relation-specific quotas. The miner uses relation-specific quotas rather than a global F0 geometry-type cap; record the resulting mix when comparing cities.

The ready-to-run `configs/stockholm.example.json` uses the bundled four-layer vector subset and the `STODEMO` prefix for a new build. Its source GeoPackage is `data/stockholm/vector/stockholm_sample.gpkg`. The source selection excludes closed roads because the current sampler's first-to-last direction definitions require distinct endpoints; when preparing another city, provide enough open road segments for these constructions.

QA's relation-specific sampler seeds are fixed by its design; the configured `seed` controls Editing mining. The seed used for the fixed Stockholm case is unknown.

## Data provenance and licensing

The Stockholm geographic benchmark database and bundled source GeoPackage derive from **© OpenStreetMap contributors**, extracted from the **Geofabrik Sweden OSM release dated 2026-07-20**. The prepared QA clip covers approximately longitude **17.95–18.12** and latitude **59.29–59.37**; constructed scenes and the Editing pool can differ from that raw clip. Canonical records retain source IDs and derivations for auditing.

The OSM-derived benchmark database and source sample are distributed under the [Open Data Commons Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/). The repository's MIT license covers software and authored documentation, not the geographic database. Keep OpenStreetMap attribution with redistributed database extracts and rendered products; the offline renderer includes it on maps. See [OpenStreetMap copyright and attribution](https://www.openstreetmap.org/copyright) and the [Geofabrik Sweden source](https://download.geofabrik.de/europe/sweden.html).

The source sample's `vector/data_manifest.json` records source identities, selection seeds, actual bounds, source-file hashes and the sample checksum.

Included model predictions are research examples supplied alongside their source provenance. Newly calculated result tables and authored documentation fall under the repository's software/documentation license without removing source database obligations. Reference answers are public for reproducible scoring; inference sends only the corresponding model inputs.

For another city, record the vector source, extraction or release date, spatial extent and source license in `dataset_name` and the dataset documentation. City datasets and private GIS files retain their own source terms; this repository does not grant rights to those sources.
