# Benchmark protocol

## Relations

The benchmark covers nine topology relations, five direction relations, eight metric relations and six order or composite relations. The tables summarize question semantics; the generator produces the model-facing English wording.

### Topology T: nine relations

| ID | Relation | Design rules |
|---|---|---|
| T01 | equals | Covers points, lines and areas; different coordinate orderings may represent topologically equal objects |
| T02 | disjoint | Disjoint geometries; generated cases use point–area, line–area and area–area pairs |
| T03 | intersects | An independent standard GIS yes/no predicate; may be true alongside equals, touches, crosses or overlaps |
| T04 | touches | Uses the standard GIS predicate across valid point–line, line–line, line–area and area–area signatures |
| T05 | crosses | Uses valid line–line and line–area signatures; area–area overlap is not treated as crosses |
| T06 | contains / within | Asks for the most specific directional relationship; contained objects may be points, lines or areas |
| T08 | overlaps | Same-dimensional objects partially overlap; neither fully contains the other |
| T09 | covers | Allows B to lie on A's boundary, unlike the interior requirement of contains |
| T11 | strict contains | Defined as `contains(A,B) and not equals(A,B)`; not an alias for `contains_properly` |

Most-specific topology questions use the priority `equals > contains > within > covers > overlaps > crosses > touches > intersects > disjoint`. T03 separately tests the general `intersects` predicate.

### Direction D: five relations

| ID | Relation | Design rules |
|---|---|---|
| D01 | Four-direction class | N/E/S/W only; PP=9, PA=4, AP=4, AA=8 per relation; non-point objects use centroids |
| D02 | Eight-direction class | N/NE/E/SE/S/SW/W/NW; the same geometry quotas and centroid rules as D01 |
| D04 | Bearing | Clockwise from north, with circular error tolerance ±1°; the same geometry quotas and centroid rules as D01 |
| D05 | Observer-relative direction | The observer stands at the road's first stored coordinate and faces its last coordinate |
| D06 | Object orientation | Classifies the object's axis using its stored coordinate direction |

### Metrics M: eight relations

| ID | Relation | Design rules |
|---|---|---|
| M01 | Euclidean distance | Minimum geometry distance; PP=5, with 4 each for PL/PA/LL/LA/AA |
| M02 | Boundary distance | Area–area only; shortest distance between the two boundaries |
| M04 | Manhattan distance | L1 distance computed from coordinate differences |
| M08 | Hausdorff distance | Symmetric discrete Hausdorff distance with Shapely `densify=0.25`, in metres |
| M12 | Perimeter | Total boundary length, including exterior rings and all interior-hole rings |
| M14 | Within a given distance | Closed-buffer predicate; PP=5, with 4 each for PL/PA/LL/LA/AA |
| M15 | Nearest neighbor | Selects the nearest object only among the four explicitly supplied candidates |
| M18 | Density | Counts only supplied P01–P10, including boundary points; divides by region area in km² and rounds to three decimal places |

### Order and composite O: six relations

| ID | Relation | Design rules |
|---|---|---|
| O01 | Linear order | Orders three positions along the route's stored coordinate direction |
| O02 | Along-line before/after | Tests pairwise before/after only |
| O03 | Same/opposite side | Uses a straight reference line or an explicitly defined local tangent; the sampler uses straight lines |
| O04 | Three-point between | Strict between for three collinear points; constructed probes remain exact in displayed coordinates |
| O06 | Vertical road order | Compares road `layer` values at a 2D intersection; `same_layer` is allowed |
| O08 | Network reachability | Only shared endpoints form nodes; interior geometric crossings do not connect automatically; multi-step paths use 2–6 edges |

### Four deferred relations

`D03` sixteen-direction classification, `D07` projection direction, `O07` containment transitivity and `O09` spatial-relation editing are deferred and are not generated as formal L1 questions.

## Sampling quotas

The QA sampler generates 700 questions: 28 relations with 25 questions each. Relations use geometry-signature quotas where applicable; relations with fixed geometric semantics use the required types.

P denotes a point, L a line and A an area. Signature order follows object order.

| Relations | Signature quotas per relation |
|---|---|
| D01, D02, D04 | PP=9, PA=4, AP=4, AA=8; non-point objects use their centroids |
| M01 | PP=5; PL, PA, LL, LA and AA each have 4 |
| M14 | PP=5; PL, PA, LL, LA and AA each have 4; actual distances are 10–500 metres |

A generated QA case contains 946 point objects, 534 line objects and 419 area objects. Counting whether each question includes a geometry type and normalizing across those type-presence counts gives approximately 37.08% points, 32.80% lines and 30.12% areas.

### Direction coverage

- D01: N=7; E, S and W each have 6.
- D02: N=4; each of the other seven directions has 3.
- D04: eight-sector coverage is N=4 and 3 for each other sector; answers are continuous bearings with a 1° tolerance.

Case outputs record geometry signatures, object types and direction coverage for analysis by relation or geometry type.

## QA

Gold and canonical files are evaluator inputs; `messages` are the model inputs. Source IDs, provenance, answers and oracle records are excluded. MCQ task wording differs from open-ended wording for intersection partitions, strict containment, numerical intervals and several ordering questions. The emitter uses relation-specific wording and the fixed gold option order.

Prediction rows require a unique `item_id` and `prediction` string. The endpoint runner adds prompt ID, model and form. External local inference systems can emit the same minimal schema:

```json
{"item_id":"CITY-L1-T01-001","prediction":"equals"}
```

Current scoring version is `complete_semantic_final_answer_v3_20261014`. Numeric answers require an unambiguous final number; MCQ requires an explicit final option. Nonnumeric answers must be complete terminal answers, optionally introduced by `Answer:` or `Final answer:`. Negations and alternative lists do not match a gold token merely by containing it. Metric tolerances are read from gold: distance/perimeter 1 m, circular bearing 1°, density 0.001. Content correctness and assessed format compliance are reported separately; format compliance is only assessed for numeric open answers and MCQ. `--scoring legacy` explicitly selects the former nonnumeric extraction for historical compatibility and records its version.

The full denominator is always the gold-set size. By-relation and family statistics, missing-output counts and information-sufficient statistics are included. Geometry-only `geojson_exact` does not expose O06's layer attributes; its sufficient-subset denominator is 675 for a full city. The offline renderer includes layer cards, so both `map_annotated` and `hybrid_geojson_exact` expose this information and use all 700 items for the sufficient subset. This does not apply to arbitrary historical image inputs.

## Structured editing

Model output is one transform JSON object. Examples:

```json
{"op":"translate","dx":12.5,"dy":-8.0}
{"op":"rotate","angle_deg":45}
{"op":"scale","factor":1.2}
{"op":"snap","to":"F1"}
{"op":"attribute_edit","layer":2}
```

Translation is in task metres. Rotation is counterclockwise about F0's centroid; scale is also about that centroid. Snap uses the named reference geometry. Only F0 is changed by the executor. Prediction rows require `task_id` and either `prediction` containing the model transform JSON, or a parsed `transform` object. An archival `prediction_wkt` adapter is also accepted for legacy exports; this is an evaluator adapter, not the transform-JSON model output protocol.

The final prediction must be parseable, nonempty, geometrically valid and satisfy every declared constraint. Geometric edits must change F0. O06 allows unchanged geometry but requires the predicted layer attribute. Reference `context.predicted_F0_layer` is used **only** to validate a reference edit; it is removed for model scoring. It cannot substitute for a missing model attribute. Directional rules and T04/O08 contact tolerances follow the task constraints.

Public Editing prompts contain anonymous feature IDs and task constraints, retaining the required layer information. QA prompts use fixed option order. Reference answers and source identifiers are not sent to the model.

The runner allows one corrective retry for undecodable/invalid or unchanged structured output. It reconstructs the initial geometry from the public scene already in the user message, and does not inspect gold or report constraint satisfaction. The evaluator scores the final recorded attempt. Transport retries are separate from this corrective retry. Resume requires identical prompt hashes, model, API root, API format and generation parameters.

## Offline images and raster editing

`map_annotated` sends the image, question/instruction and necessary constraints, withholding vector coordinates. `hybrid_geojson_exact` sends the matching image plus the structured input. Both use the same frozen scene geometry as GeoJSON. `prepare_inputs.py --per-relation 1` selects 28 items per task and writes matching items, tasks and gold under `OUT/case/`. Evaluate preview predictions against that prepared case. Use `--per-relation 0` for full runs. Scoring a preview against the full case with `--allow-partial` counts all missing outputs as failures.

`src/rendering.py` determines the plot rectangle and metres-per-pixel mapping for each renderer. Frame sidecars document the affine conversion; the evaluator recomputes it from the initial scene and recorded renderer settings instead of trusting a supplied prediction transform. PNGs are 1536×1536, x rightwards and y downwards. Pixel outputs use a single GeoJSON geometry object for F0 and, when required, a layer:

```json
{"geometry":{"type":"Point","coordinates":[750,720]}}
```

Frame sidecars hash both the visible initial scene and the PNG. Prompt preparation verifies those hashes and binds the image/frame hashes into each prompt; inference rejects altered images or metadata. Resume also binds all input image hashes. Frames depend only on initial geometry, so reference edits may legitimately move outside the displayed canvas. Finite off-canvas pixel coordinates are accepted and inverse-projected normally; reference diagnostics report this coverage instead of silently claiming all gold is visible.

The evaluator maps pixels back to task metres. Raster success requires a valid changed edit satisfying the strict constraints, or an edit within 4 pixels Hausdorff distance of the reference. Required attributes must still match; O06 may keep geometry unchanged. `strict_CSR` remains available per item and is distinct from `raster_tolerant_success`. The simple pixel runner retries parse/validity failures, but does not detect unchanged geometry from pixels before scoring; label this difference if comparing retry policies.

Default Image/Together inputs use the `offline_metric_v1` metric renderer. This input condition differs from the paper's OSM-basemap condition. Record the renderer, source data, seed, CRS and software versions with model results.

## Optional basemaps

`prepare_inputs.py` and `render_maps.py` accept `--basemap none|geoapify|stadia`. The default `none` keeps the existing offline renderer and needs no credentials. Network backgrounds use Pillow (`pillow_basemap_v2`) and fill the 1536×1536 canvas. A compact title/key, north arrow, metric scale bar and attribution sit over the map; feature labels and O06 layer values remain visible. Labels avoid symbols, outlines and small polygons; leaders attach to polygon boundaries, line bodies or actual point locations. Dark grey leaders have white casing for contrast and no arrowheads. Point symbols are drawn above lines and areas. Stored-direction arrows appear only on the reference road in D05, the reference route in O01/O02, and the target road in Editing D06; QA D06 uses an undirected axis. Arrowheads scale down for short line segments. The viewport fits the initial geometry with padding and expands very small scenes to respect the source resolution at the zoom cap. Exact coincident points use concentric markers without changing their coordinates. Task geometry and references do not change. The larger viewport has its own pixel transform; Image-only Editing predictions retain renderer and basemap settings so scoring can reconstruct it. Existing `offline_metric_v1` and `pillow_basemap_v1` images and predictions retain their original transforms.

Scripts read the repository-root `.env` with existing environment variables taking precedence. Use `.env.example` as the template; basemap downloads read `GEOAPIFY_API_KEY` or `STADIA_API_KEY`, separately from `MODEL_API_KEY`. Credentials, signed request URLs and provider error bodies are not written to reports or caches.

- **Geoapify:** raster tiles, default style `osm-bright-grey`; also `osm-bright-smooth` and `osm-bright`. Downloaded tiles are reused between scenes. Observe the account quota and required attribution. [Map tiles and storage policy](https://www.geoapify.com/map-tiles/).
- **Stadia:** the `static_cacheable` endpoint, default style `alidade_smooth`; also `osm_bright`. Each uncached background costs 2,000 credits under the published schedule, not the ordinary Static Maps rate. API access depends on the account plan; caching and public redistribution require the applicable license, including an active paid subscription for digital cacheable redistribution under the standard terms. [Static Maps](https://docs.stadiamaps.com/static-maps/), [pricing](https://stadiamaps.com/pricing/), [terms §30.3](https://stadiamaps.com/terms-of-service/).

`--basemap-style` selects one of the supported styles for that provider. `--basemap-zoom` caps XYZ-equivalent zoom (1–19, default 19); the renderer chooses a lower level for wider scenes. Stadia Static Maps use the equivalent 512-point-world zoom, one below XYZ zoom. A lower zoom cap widens the minimum viewport rather than excessively enlarging a few source pixels. The selected source level avoids requesting detail beyond the output resolution. `--basemap-cache PATH` changes the shared download cache (default `outputs/basemap_cache/`). Downloads use at most four workers with a shared limit of four request starts per second and a 30-second timeout. Transient connection/server failures get at most two retries; authentication and quota failures stop without retry or provider fallback. Scene counts, tile progress and elapsed time are printed to stderr. A rerun reuses completed downloads and images. For a no-network budget estimate:

```sh
python scripts/render_maps.py --case outputs/stockholm --basemap geoapify --dry-run
```

QA backgrounds use the scene CRS. Editing needs `source_frame.crs` and `source_frame.origin` from generation or verified original metadata. The fixed Editing case cannot be placed geographically from its local coordinates alone. All selected scenes and existing images are checked before downloads begin.

Frame sidecars record provider, style, actual zoom, source pixel bounds, geographic alignment, attribution and render time. Prompt and prediction records retain the basemap description, and score reports summarize renderer/provider/style in `input_conditions`; only messages and image bytes are sent to the model. Changing provider, style, zoom cap, source frame or annotation style requires a new image output directory. The current annotation style is recorded as `geometry_aware_v1`; existing tile caches remain reusable. Backgrounds may contain unlabelled features or newer data than the benchmark extract; questions and gold still refer only to the labelled task objects. Report this renderer/provider/style as a distinct input condition rather than equating it with the paper's maps. Provider map-image terms are separate from the repository's code and dataset licenses.

## Running APIs

Set `MODEL_API_KEY` in `.env` or your shell. `--key-env` selects another environment variable. `--api-format chat` appends `/chat/completions` to your API root; `--api-format responses` appends `/responses`. Pass the API root including `/v1` if your provider uses it. Models and roots are user-selected; the code does not assume provider-specific model availability or reasoning settings. `--temperature` is optional because some endpoints omit it. Record provider-specific settings with the experiment if extending the runner.

The runner sends only `messages` and optional image bytes. No gold file is loaded. `--dry-run` validates requests without a key or network call. Errors are written separately; missing predictions stay missing until a resumed run succeeds or are explicitly counted as failures by the evaluator.
