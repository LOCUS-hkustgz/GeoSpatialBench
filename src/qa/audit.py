"""Independent structural, geometry, oracle and public-prompt audit for new QA cases."""

from collections import Counter
import json
from pathlib import Path
from shapely.geometry import shape
from shapely.wkt import loads as load_wkt
from ..data_io import read_rows, index_rows
from ..relations import CORE_28_IDS
from ..prompts import qa_prompt
from .oracle import recompute
from .forms import topology_mcq, non_topology_mcq

ACTIVE = list(CORE_28_IDS)


def geometry_kind(geometry_type: str) -> str:
    if "Point" in geometry_type:
        return "P"
    if "LineString" in geometry_type:
        return "L"
    if "Polygon" in geometry_type:
        return "A"
    return "X"


def geometry_signature(item: dict) -> str:
    return "-".join(geometry_kind(o["geometry_type"]) for o in item["objects"])


def serialization_regression(items: list[dict]) -> dict:
    o04 = [x for x in items if x["relation_id"] == "O04"]
    failures = []
    for item in o04:
        a, b, c = [load_wkt(o["geometry_wkt"]) for o in item["objects"]]
        cross = (c.x - a.x) * (b.y - a.y) - (c.y - a.y) * (b.x - a.x)
        dot = (b.x - a.x) * (c.x - a.x) + (b.y - a.y) * (c.y - a.y)
        length2 = (c.x - a.x) ** 2 + (c.y - a.y) ** 2
        actual = cross == 0 and 0 < dot < length2
        if actual != (item["gold"]["answer"] == "yes"):
            failures.append(item["item_id"])
    m18 = [x for x in items if x["relation_id"] == "M18"]
    if not all(
        "three decimal places" in x["task"]
        and x["gold"]["scoring"].get("absolute_tolerance") == 0.001
        for x in m18
    ):
        failures.append("M18-precision-contract")
    return {
        "status": "PASS" if not failures else "FAIL",
        "checked_o04": len(o04),
        "checked_m18": len(m18),
        "failures": failures,
    }


def topology_recompute(item: dict):
    rid = item["relation_id"]
    a, b = (load_wkt(o["geometry_wkt"]) for o in item["objects"][:2])
    if rid == "T01":
        return a.equals(b)
    if rid == "T02":
        return a.disjoint(b)
    if rid == "T03":
        return "yes" if a.intersects(b) else "no"
    if rid == "T04":
        return a.touches(b)
    if rid == "T05":
        return a.crosses(b)
    if rid == "T06":
        return a.contains(b) if item["gold"]["answer"] == "contains" else a.within(b)
    if rid == "T08":
        return a.overlaps(b)
    if rid == "T09":
        return a.covers(b)
    if rid == "T11":
        return "yes" if a.contains(b) and not a.equals(b) else "no"
    raise KeyError(rid)


def payload_from_prompt(text: str) -> dict:
    start = text.index('{"type":"FeatureCollection"')
    markers = [
        p for p in (text.find("\nAnswer format:", start), text.find("\nOptions:", start)) if p >= 0
    ]
    end = min(markers)
    return json.loads(text[start:end])


def audit(root: Path) -> dict:
    items = read_rows(root / "qa/items.jsonl")
    mcq_by_id = index_rows(read_rows(root / "qa/gold_mcq4.jsonl"), "item_id")
    errors, warnings = [], []
    if set(mcq_by_id) != {item["item_id"] for item in items}:
        errors.append("MCQ gold/item ID mismatch")
    regression = serialization_regression(items)
    if regression["status"] != "PASS":
        errors.append(f"serialization regression failed: {regression['failures']}")
    counts = Counter(x["relation_id"] for x in items)
    if len(items) != 700:
        errors.append(f"expected 700 canonical items, got {len(items)}")
    if list(counts) != ACTIVE:
        errors.append("relation order/content differs from the active relation list")
    if any(counts[r] != 25 for r in ACTIVE):
        errors.append(f"not exactly 25 items per relation: {dict(counts)}")
    ids = [x["item_id"] for x in items]
    if len(ids) != len(set(ids)):
        errors.append("duplicate item IDs")
    if any("difficulty" in x or "difficulty_label" in x for x in items):
        errors.append("difficulty labels were assigned")
    if any("design_factors" not in x for x in items):
        errors.append("missing objective design_factors")

    invalid, oracle_fail = [], []
    object_count = 0
    for x in items:
        object_count += len(x["objects"])
        for o in x["objects"]:
            g = load_wkt(o["geometry_wkt"])
            if g.is_empty or not g.is_valid:
                invalid.append([x["item_id"], o["id"]])
        expected = x["gold"]["answer"]
        if x["relation_id"].startswith("T"):
            actual = topology_recompute(x)
            good = actual is True if x["relation_id"] not in {"T03", "T11"} else actual == expected
        else:
            actual = recompute(x)
            good = (
                abs(float(actual) - float(expected)) <= 1e-6
                if isinstance(expected, (int, float))
                else actual == expected
            )
        if not good:
            oracle_fail.append({"item_id": x["item_id"], "expected": expected, "actual": actual})
    if invalid:
        errors.append(f"invalid/empty geometries: {invalid[:10]}")
    if oracle_fail:
        errors.append(f"oracle mismatches: {oracle_fail[:10]}")

    prompt_counts, prompt_lengths, mode_fail, leakage = {}, {}, [], []
    forbidden = (
        "relation_id",
        "gold_answer",
        "gold_label",
        "source_id",
        "computed_truth",
        "oracle_operation",
    )
    for form in ("open", "mcq4"):
        rows = [
            qa_prompt(item, form, mcq_by_id[item["item_id"]], index)
            for index, item in enumerate(items)
        ]
        key = form + ":geojson_exact"
        prompt_counts[key] = len(rows)
        prompt_lengths[key] = round(
            sum(len(row["messages"][0]["content"]) for row in rows) / max(1, len(rows)), 1
        )
        for row, source in zip(rows, items):
            text = row["messages"][0]["content"]
            if any(token in text for token in forbidden):
                leakage.append(row["prompt_id"])
            payload = payload_from_prompt(text)
            if len(payload["features"]) != len(source["objects"]):
                mode_fail.append([row["prompt_id"], "feature count"])
            for feature, obj in zip(payload["features"], source["objects"]):
                shown, original = shape(feature["geometry"]), load_wkt(obj["geometry_wkt"])
                if feature["properties"] != {"id": obj["id"]}:
                    mode_fail.append([row["prompt_id"], "feature ID or attribute leakage"])
                if not shown.equals_exact(original, 1e-6):
                    mode_fail.append([row["prompt_id"], "exact geometry"])
    if mode_fail:
        errors.append(f"prompt fidelity failures: {mode_fail[:10]}")
    if leakage:
        errors.append(f"model-facing leakage: {leakage[:10]}")

    open_gold = read_rows(root / "qa/gold_open.jsonl")
    mcq_gold = read_rows(root / "qa/gold_mcq4.jsonl")
    open_by_id = index_rows(open_gold, "item_id")
    if set(open_by_id) != set(mcq_by_id):
        errors.append("Open/MCQ gold ID mismatch")
    for item in items:
        gold = open_by_id.get(item["item_id"], {})
        if (
            gold.get("answer") != item["gold"]["answer"]
            or gold.get("scoring") != item["gold"]["scoring"]
        ):
            errors.append(f"Open gold differs from canonical item: {item['item_id']}")
    letter_counts = Counter(gold["answer_letter"] for gold in mcq_gold)
    if letter_counts != Counter({"A": 175, "B": 175, "C": 175, "D": 175}):
        errors.append(f"MCQ letter imbalance: {dict(letter_counts)}")
    for index, item in enumerate(items):
        gold = mcq_by_id[item["item_id"]]
        options = gold["options"]
        if len(options) != 4 or len(set(options)) != 4:
            errors.append(f"MCQ needs four unique options: {item['item_id']}")
        expected = (topology_mcq if item["relation_id"].startswith("T") else non_topology_mcq)(
            item, index
        )
        if (
            options != expected[1]
            or gold["answer_letter"] != expected[2]
            or gold["answer_option"] != expected[1]["ABCD".index(expected[2])]
        ):
            errors.append(f"MCQ gold differs from canonical item: {item['item_id']}")

    balance = {
        r: Counter(str(x["gold"]["answer"]) for x in items if x["relation_id"] == r) for r in ACTIVE
    }
    for rid in ("T03", "T11", "M14", "O04", "O08"):
        if len(balance[rid]) < 2:
            warnings.append(f"{rid} lacks answer-class balance")
    if balance["T03"] != Counter({"yes": 13, "no": 12}):
        errors.append(f"T03 must be balanced 13/12: {dict(balance['T03'])}")
    if balance["T11"] != Counter({"yes": 13, "no": 12}):
        errors.append(f"T11 must be balanced 13/12: {dict(balance['T11'])}")
    o06 = [x for x in items if x["relation_id"] == "O06"]
    decision_checks = {
        "T03_independent_yes_no_query": set(balance["T03"]) <= {"yes", "no"},
        "T11_inherited_definition": all(
            x["gold"]["oracle"].get("definition") == "contains(A,B) and not equals(A,B)"
            for x in items
            if x["relation_id"] == "T11"
        ),
        "M02_polygon_polygon_only": all(
            all("Polygon" in o["geometry_type"] for o in x["objects"])
            for x in items
            if x["relation_id"] == "M02"
        ),
        "M12_has_hole_cases": any(
            x["gold"]["oracle"]["interior_ring_count"] > 0
            for x in items
            if x["relation_id"] == "M12"
        ),
        "M15_exactly_four_candidates": all(
            sum(o["role"] == "candidate" for o in x["objects"]) == 4
            for x in items
            if x["relation_id"] == "M15"
        ),
        "M18_exactly_ten_explicit_POIs": all(
            sum(o["role"] == "explicit_poi" for o in x["objects"]) == 10
            for x in items
            if x["relation_id"] == "M18"
        ),
        "O06_attribute_only": all(
            not x["mode_information_sufficient"]["geojson_exact"]
            and x["mode_information_sufficient"]["geojson_exact_attributes"]
            for x in o06
        ),
    }
    if not all(decision_checks.values()):
        errors.append(f"locked design decision failed: {decision_checks}")

    # v5.0.1 uses relation-aware quotas instead of forcing a global 1:1:1 ratio.
    expected_quotas = {
        "D01": Counter({"P-P": 9, "P-A": 4, "A-P": 4, "A-A": 8}),
        "D02": Counter({"P-P": 9, "P-A": 4, "A-P": 4, "A-A": 8}),
        "D04": Counter({"P-P": 9, "P-A": 4, "A-P": 4, "A-A": 8}),
        "M01": Counter({"P-P": 5, "P-L": 4, "P-A": 4, "L-L": 4, "L-A": 4, "A-A": 4}),
        "M14": Counter({"P-P": 5, "P-L": 4, "P-A": 4, "L-L": 4, "L-A": 4, "A-A": 4}),
    }
    actual_quotas = {
        rid: Counter(geometry_signature(x) for x in items if x["relation_id"] == rid)
        for rid in expected_quotas
    }
    quota_fail = {
        rid: {"expected": dict(expected_quotas[rid]), "actual": dict(actual_quotas[rid])}
        for rid in expected_quotas
        if actual_quotas[rid] != expected_quotas[rid]
    }
    if quota_fail:
        errors.append(f"v5.0.1 geometry-signature quotas failed: {quota_fail}")
    expected_direction_classes = {
        "D01": Counter({"N": 7, "E": 6, "S": 6, "W": 6}),
        "D02": Counter({"N": 4, "NE": 3, "E": 3, "SE": 3, "S": 3, "SW": 3, "W": 3, "NW": 3}),
        "D04": Counter({"N": 4, "NE": 3, "E": 3, "SE": 3, "S": 3, "SW": 3, "W": 3, "NW": 3}),
    }
    actual_direction_classes = {
        rid: Counter(
            x["design_factors"].get("direction_class") for x in items if x["relation_id"] == rid
        )
        for rid in expected_direction_classes
    }
    direction_fail = {
        rid: {
            "expected": dict(expected_direction_classes[rid]),
            "actual": dict(actual_direction_classes[rid]),
        }
        for rid in expected_direction_classes
        if actual_direction_classes[rid] != expected_direction_classes[rid]
    }
    if direction_fail:
        errors.append(f"direction class quotas failed: {direction_fail}")

    object_counts = Counter()
    item_presence = Counter()
    composition = Counter()
    for x in items:
        kinds = [geometry_kind(o["geometry_type"]) for o in x["objects"]]
        object_counts.update(kinds)
        item_presence.update(set(kinds))
        composition[
            "mixed"
            if len(set(kinds)) > 1
            else {"P": "point_only", "L": "line_only", "A": "area_only"}.get(kinds[0], "unknown")
        ] += 1
    expected_objects = Counter({"P": 946, "L": 534, "A": 419})
    expected_presence = Counter({"P": 373, "L": 330, "A": 303})
    expected_composition = Counter(
        {"point_only": 123, "line_only": 130, "area_only": 141, "mixed": 306}
    )
    if object_counts != expected_objects:
        errors.append(
            f"global geometry object counts changed: expected {dict(expected_objects)}, got {dict(object_counts)}"
        )
    if item_presence != expected_presence:
        errors.append(
            f"item geometry exposure changed: expected {dict(expected_presence)}, got {dict(item_presence)}"
        )
    if composition != expected_composition:
        errors.append(
            f"item composition changed: expected {dict(expected_composition)}, got {dict(composition)}"
        )
    exposure_total = sum(item_presence.values())
    object_total = sum(object_counts.values())
    geometry_balance = {
        "signature_quotas": {rid: dict(actual_quotas[rid]) for rid in actual_quotas},
        "direction_class_quotas": {
            rid: dict(actual_direction_classes[rid]) for rid in actual_direction_classes
        },
        "object_counts": dict(object_counts),
        "object_percent": {k: round(100 * v / object_total, 2) for k, v in object_counts.items()},
        "items_containing_type": dict(item_presence),
        "exposure_normalized_percent": {
            k: round(100 * v / exposure_total, 2) for k, v in item_presence.items()
        },
        "item_composition": dict(composition),
    }

    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "canonical_items": len(items),
            "relations": len(counts),
            "by_relation": dict(counts),
            "prompt_files": prompt_counts,
        },
        "geometry": {"objects_checked": object_count, "invalid": invalid},
        "oracle": {"items_checked": len(items), "mismatches": oracle_fail},
        "prompt_fidelity": {"failures": len(mode_fail), "average_characters": prompt_lengths},
        "leakage": {"forbidden_hits": len(leakage)},
        "mcq_correct_letter_counts": dict(letter_counts),
        "answer_balance": {r: dict(c) for r, c in balance.items()},
        "decision_checks": decision_checks,
        "geometry_balance": geometry_balance,
        "serialization_regression": regression,
    }
