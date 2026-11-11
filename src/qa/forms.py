"""Deterministic, relation-specific four-option question construction."""

from __future__ import annotations
import hashlib
import math
import random
from shapely.wkt import loads as load_wkt

LETTERS = "ABCD"


def stable_rng(key: str) -> random.Random:
    seed = int(hashlib.sha256(key.encode()).hexdigest()[:16], 16)
    return random.Random(seed)


def place_options(
    correct: str, distractors: list[str], correct_slot: int, key: str
) -> tuple[list[str], str]:
    if correct in distractors:
        distractors = [x for x in distractors if x != correct]
    unique = []
    for x in distractors:
        if x not in unique and x != correct:
            unique.append(x)
    if len(unique) < 3:
        raise ValueError(f"Need three unique distractors for {key}: {unique}")
    stable_rng(key).shuffle(unique)
    options = unique[:3]
    options.insert(correct_slot, correct)
    return options, LETTERS[correct_slot]


def fmt_num(x: float, decimals: int = 2) -> str:
    if decimals == 0:
        return str(int(round(x)))
    s = f"{x:.{decimals}f}"
    return s.rstrip("0").rstrip(".")


def nice_step(value: float, relation_id: str) -> float:
    if relation_id == "M18":
        raw = max(value * 0.25, 0.5)
    else:
        raw = max(value * 0.20, 5.0)
    power = 10 ** math.floor(math.log10(raw))
    scaled = raw / power
    nice = 1 if scaled <= 1 else 2 if scaled <= 2 else 5 if scaled <= 5 else 10
    return nice * power


def numeric_intervals(value: float, relation_id: str, target_bin: int) -> tuple[str, list[str]]:
    step = nice_step(value, relation_id)
    start = max(0.0, value - (target_bin + 0.5) * step)
    bounds = [start + i * step for i in range(5)]
    unit = "POIs/km²" if relation_id == "M18" else "m"
    decimals = 2 if relation_id == "M18" else 0
    opts = [
        f"{fmt_num(bounds[i], decimals)} ≤ value < {fmt_num(bounds[i + 1], decimals)} {unit}"
        for i in range(4)
    ]
    actual_bin = next(i for i in range(4) if bounds[i] <= value < bounds[i + 1])
    correct = opts[actual_bin]
    return correct, [x for x in opts if x != correct]


def non_topology_mcq(item: dict, item_index: int) -> tuple[str, list[str], str, dict]:
    rid = item["relation_id"]
    answer = item["gold"]["answer"]
    oracle = item["gold"]["oracle"]
    task = item["task"]
    if rid == "D01":
        correct, pool = answer, ["N", "E", "S", "W"]
    elif rid == "D02":
        pool = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
        correct = answer
    elif rid == "D04":
        correct = f"{fmt_num(float(answer), 2)}°"
        v = float(answer)
        pool = [correct] + [f"{fmt_num((v + d) % 360, 2)}°" for d in (15, 90, 180)]
    elif rid == "D05":
        correct, pool = answer, ["front", "right", "back", "left"]
    elif rid == "D06":
        correct, pool = answer, ["N-S", "NE-SW", "E-W", "NW-SE"]
    elif rid in {"M01", "M02", "M04", "M08", "M12", "M18"}:
        target_bin = item_index % 4
        correct, distractors = numeric_intervals(float(answer), rid, target_bin)
        options, letter = place_options(correct, distractors, target_bin, item["item_id"])
        task = task.replace("What is", "Which interval contains")
        return (
            task,
            options,
            letter,
            {"mcq_semantics": "four mutually exclusive numeric intervals", "open_answer": answer},
        )
    elif rid == "M14":
        d, r = oracle["distance_m"], oracle["buffer_radius_m"]
        pool = [
            f"distance ≤ 0.5r ({fmt_num(0.5 * r, 1)} m)",
            f"0.5r < distance ≤ r ({fmt_num(r, 1)} m)",
            f"r < distance ≤ 1.5r ({fmt_num(1.5 * r, 1)} m)",
            "distance > 1.5r",
        ]
        correct = (
            pool[0] if d <= 0.5 * r else pool[1] if d <= r else pool[2] if d <= 1.5 * r else pool[3]
        )
        task = f"Which distance band describes F02 relative to the closed {fmt_num(r, 1)}-metre buffer radius r around F01?"
    elif rid == "M15":
        correct, pool = answer, ["F01", "F02", "F03", "F04"]
    elif rid == "O01":
        correct = answer
        a = correct.split(">")
        pool = [
            correct,
            ">".join(reversed(a)),
            ">".join([a[1], a[0], a[2]]),
            ">".join([a[0], a[2], a[1]]),
        ]
    elif rid == "O02":
        correct = answer
        reverse = "before=F02; after=F01" if "before=F01" in correct else "before=F01; after=F02"
        pool = [
            correct,
            reverse,
            "F01 and F02 have the same route position",
            "at least one point is not on F00",
        ]
        task = "Which pairwise along-route statement is true for F01 and F02 in F00's stored coordinate direction?"
    elif rid == "O03":
        correct = (
            "F01 and F02 are on the same side"
            if answer == "same_side"
            else "F01 and F02 are on opposite sides"
        )
        pool = [
            correct,
            "F01 and F02 are on opposite sides"
            if answer == "same_side"
            else "F01 and F02 are on the same side",
            "F01 lies on F00 but F02 does not",
            "F02 lies on F00 but F01 does not",
        ]
        task = "Which statement describes F01 and F02 relative to the directed straight line F00?"
    elif rid == "O04":
        if answer == "yes":
            correct = "F02 is strictly between F01 and F03"
        elif oracle["distance_to_supporting_line_m"] <= oracle["collinearity_tolerance_m"]:
            t = oracle["projection_parameter_unclamped"]
            correct = (
                "F03 is strictly between F01 and F02"
                if t > 1
                else "F01 is strictly between F02 and F03"
            )
        else:
            correct = "the three points are not collinear"
        pool = [
            "F01 is strictly between F02 and F03",
            "F02 is strictly between F01 and F03",
            "F03 is strictly between F01 and F02",
            "the three points are not collinear",
        ]
        task = "Which ordinary three-point collinearity/between statement is true?"
    elif rid == "O06":
        correct = (
            "F01 is above F02"
            if answer == "F01"
            else "F02 is above F01"
            if answer == "F02"
            else "F01 and F02 are at the same layer"
        )
        pool = [
            "F01 is above F02",
            "F02 is above F01",
            "F01 and F02 are at the same layer",
            "F01 and F02 do not intersect in 2D",
        ]
    elif rid == "O08":
        steps = oracle["shortest_path_edges"]
        pool = [
            "reachable in 1–2 edges",
            "reachable in 3–4 edges",
            "reachable in 5 or more edges",
            "not reachable",
        ]
        correct = (
            "not reachable"
            if steps is None
            else pool[0]
            if steps <= 2
            else pool[1]
            if steps <= 4
            else pool[2]
        )
        task = "Using only shared edge endpoints as nodes, which reachability statement from S to T is true? Interior crossings do not create nodes."
    else:
        raise KeyError(rid)
    distractors = [x for x in pool if x != correct]
    target_slot = item_index % 4
    options, letter = place_options(correct, distractors, target_slot, item["item_id"])
    return (
        task,
        options,
        letter,
        {"mcq_semantics": "four mutually exclusive substantive outcomes", "open_answer": answer},
    )


TOPO_CONFUSIONS = {
    "equals": ["overlaps", "contains", "disjoint", "intersects"],
    "contains": ["covers", "equals", "within", "overlaps"],
    "within": ["contains", "covers", "intersects", "disjoint"],
    "covers": ["contains", "touches", "intersects", "disjoint"],
    "overlaps": ["equals", "intersects", "touches", "disjoint"],
    "crosses": ["intersects", "touches", "overlaps", "disjoint"],
    "touches": ["intersects", "crosses", "disjoint", "overlaps"],
    "intersects": ["crosses", "touches", "overlaps", "disjoint"],
    "disjoint": ["intersects", "touches", "crosses", "within"],
}


def topology_mcq(item, index):
    rid = item["relation_id"]
    answer = item["gold"]["answer"]
    oracle = item["gold"]["oracle"]
    if rid not in {"T03", "T11"}:
        correct = answer
        distractors = TOPO_CONFUSIONS[correct]
        options, letter = place_options(correct, distractors, index % 4, item["item_id"])
        task = item["task"]
        semantics = "most-specific topology label"
    elif rid == "T03":
        specifics = oracle["specific_predicates"]
        pool = [
            "disjoint",
            "touches without another listed specific relation",
            "crosses or overlaps",
            "equals, contains, within, or covers",
        ]
        correct = (
            "disjoint"
            if not oracle["intersects"]
            else pool[3]
            if any(x in specifics for x in ("equals", "contains", "within", "covers"))
            else pool[2]
            if any(x in specifics for x in ("crosses", "overlaps"))
            else pool[1]
        )
        options, letter = place_options(
            correct, [x for x in pool if x != correct], index % 4, item["item_id"]
        )
        task = "Which mutually exclusive intersection category describes F01 and F02?"
        semantics = "general intersects partition"
    else:
        pool = [
            "F01 equals F02",
            "F01 strictly contains F02",
            "F01 covers but does not contain F02",
            "F01 does not contain F02",
        ]
        correct = (
            pool[0]
            if oracle["equals"]
            else pool[1]
            if oracle["strict_contains"]
            else pool[2]
            if oracle["contains"] is False
            and load_wkt(item["objects"][0]["geometry_wkt"]).covers(
                load_wkt(item["objects"][1]["geometry_wkt"])
            )
            else pool[3]
        )
        options, letter = place_options(
            correct, [x for x in pool if x != correct], index % 4, item["item_id"]
        )
        task = (
            "Which statement is true under strict_contains(A,B)=contains(A,B) and not equals(A,B)?"
        )
        semantics = "inherited strict-contains partition"
    return task, options, letter, {"mcq_semantics": semantics, "open_answer": answer}


def make_gold(items):
    """Return the two reference tables without generating intermediate prompt packs."""
    open_gold, mcq_gold = [], []
    for index, item in enumerate(items):
        constructor = topology_mcq if item["relation_id"].startswith("T") else non_topology_mcq
        task, options, letter, semantics = constructor(item, index)
        open_gold.append(
            {
                "item_id": item["item_id"],
                "relation_id": item["relation_id"],
                "answer": item["gold"]["answer"],
                "scoring": item["gold"]["scoring"],
            }
        )
        mcq_gold.append(
            {
                "item_id": item["item_id"],
                "relation_id": item["relation_id"],
                "answer_letter": letter,
                "answer_option": options[LETTERS.index(letter)],
                "options": options,
                **semantics,
            }
        )
    return open_gold, mcq_gold
