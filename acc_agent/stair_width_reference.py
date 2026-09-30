"""Build the full-population v8 staircase-width reference with independent IFC evidence.

Labels come from the expert comparison workbook, including the E.2.4 applicability
rows that the subset importer skips. Every stair also receives evidence computed
here from the IFC: containing spaces and storey, modelled rise, and a clear-width
measurement between the flight's side boundaries. Disagreements between expert
and IFC evidence stop generation unless an explicit adjudication is recorded.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import re
from dataclasses import replace

import numpy as np

from ground_truth import GT_DIR, GroundTruth, load
from import_bca_gt import GT_COMPARISON_DIR, STAIRCASE_E331_REGULATION

CASE_ID = "staircase_width_v8"
SUBSET_CASE_ID = "staircase_width_v8_deprecated_v1"
WORKBOOK = "staircase_width.xlsx"
SHEET = "Staircase width_bca__e-3-3__v8"
THRESHOLD_MM = 1000.0
HANDRAIL_LIMIT_M = 0.080  # E.3.3.1 note: larger handrail projections reduce the clear width
MIN_LANE_M = 0.3  # narrower gaps (e.g. behind a balustrade) are not walkable lanes
HEIGHTS_M = np.round(np.arange(0.1, 2.0001, 0.05), 3)  # E.3.2.1 zone above the treads
BALUSTRADE_BELOW_M = 0.5  # railing parts this low are balustrade, not a handrail
SECTIONS = np.linspace(0.1, 0.9, 41)  # avoid landings and floor edges at flight ends
NOT_OBSTACLES = ("IfcSpace", "IfcOpeningElement", "IfcSlab", "IfcRoof", "IfcCovering", "IfcAnnotation")
WIDTH_AGREEMENT_MM = 10

APPLICABILITY_TEXT = (
    "E.2.1 A staircase (including a flight of 2 steps or more) shall provide a safe and "
    "suitable passage for movement of people.\n"
    "E.2.2 A staircase must have - ... (c) sufficient width, tread and riser to avoid injury; ...\n"
    "E.2.4 The requirements in paragraph E.2.2(b) and (c) do not apply to a staircase located "
    "in any of the following rooms or spaces:\n"
    "  (a) any equipment or plant room;\n"
    "  (b) any production area of an industrial building;\n"
    "  (c) any attic that - (ii) does not exceed an area of 10 square metres; and (iii) is in "
    "a residential building;\n"
    "  (d) any house built for the owner's own use."
)
LABELLING_POLICY = (
    "Label every IfcStair. Use NA for a staircase exempt under E.2.1 or E.2.4. Use "
    "MANUAL_CHECK for a staircase located in a cinema, theatre or amphitheatre space, or "
    "whose stair shape type is not defined in the model (IfcStair PredefinedType "
    "NOTDEFINED); the reference checker does not assess these automatically. Measure the "
    "clear width from walls or other solid elements, or from the edge of the stair flight "
    "where there is none; a railing reduces the width only where it projects more than "
    "80 mm inside that line, and a railing within the flight divides it so that the "
    "narrowest part counts. This policy comes from the reference checker, not from the "
    "regulation text."
)
RULE = (
    "The clear width of the staircase must be at least 1 m.\n\n"
    "Regulatory text (the authoritative clauses - use them to interpret the requirement "
    "and its applicability; you must still work out how to measure it from the IFC "
    "geometry):\nBCA Approved Document (Acceptable Solutions) V7.08 - applicability:\n"
    f"{APPLICABILITY_TEXT}\n\n{STAIRCASE_E331_REGULATION}\n\n"
    f"Benchmark labelling policy: {LABELLING_POLICY}\n\n"
    "Report the GlobalId of every element (modelled as IfcStair) that does NOT satisfy "
    "this requirement."
)

# Reviewed disagreements between expert rows and IFC evidence (2026-09-28).
ADJUDICATIONS: dict[str, dict] = {
    "35pIuS$v94_8nIIWR7TtCO": {
        "label": "FAIL",
        "reason": "Expert: 1000 mm PASS. In the IFC a railing runs along Run 2 75-125 mm inside the 1000 mm flight edge, leaving 875 mm under the stated convention (and under a strict balustrade reading). Labelled from the model geometry; the subset case keeps the expert label.",
    },
    "38SnCByaD3oPaKe_iSvSu4": {
        "label": "NA",
        "reason": "Flight rises from the 2nd storey into the 9.7 m2 residential attic room; the expert treats it as that attic's staircase (E.2.4(c)). Its base is in a 28.7 m2 living room, so the 'located in' reading is an interpretation.",
    },
}


def expert_rows(path=None) -> dict[str, dict]:
    """All v8 workbook rows keyed by GlobalId, mapped to element labels."""
    import openpyxl

    sheet = openpyxl.load_workbook(path or GT_COMPARISON_DIR / WORKBOOK, data_only=True)[SHEET]
    rows = list(sheet.iter_rows(values_only=True))
    column = {str(name).strip().lower(): index for index, name in enumerate(rows[0]) if name}
    out = {}
    for row in rows[1:]:
        guid, clause = row[column["guid"]], row[column["clause"]]
        bucket, message = str(row[column["gt_bucket"]] or "").strip().lower(), str(row[column["gt_message"]] or "")
        out[guid] = {"clause": clause, "bucket": bucket, "message": message, "label": expert_label(clause, bucket, message)}
        width = re.search(r"is (\d+)\s*mm", message)
        out[guid]["width_mm"] = int(width.group(1)) if width else None
    return out


def expert_label(clause: str, bucket: str, message: str) -> str:
    if clause == "e.3.3.1" and bucket in ("pass", "fail"):
        return bucket.upper()
    if clause == "e.2.4" and bucket == "exempt":
        return "NA"
    if clause == "e.2.4" and bucket == "alert" and "manual check" in message.lower():
        return "MANUAL_CHECK"
    raise ValueError(f"Unmapped expert row: clause={clause!r} bucket={bucket!r}. Review required.")


def applicability_finding(evidence: dict) -> tuple[str | None, str]:
    """Independent NA/MANUAL_CHECK decision from recorded IFC evidence."""
    names = " ".join(space["name"].upper() for space in evidence["spaces"])
    if evidence["predefined_type"] == "NOTDEFINED":
        return "MANUAL_CHECK", "Stair shape type NOTDEFINED (reference-checker policy)."
    if any(word in names for word in ("CINEMA", "THEATRE", "AMPHITHEATRE")):
        return "MANUAL_CHECK", "Located in a cinema/theatre space (reference-checker policy)."
    if any(word in names for word in ("PLANT", "EQUIPMENT")):
        return "NA", "Located in a plant/equipment room (E.2.4(a))."
    if "PRODUCTION" in names:
        return "NA", "Located in a production area (E.2.4(b)); building use is not recorded in the IFC."
    if "ATTIC" in evidence["storey"].upper() and any(
            space["area_m2"] is not None and space["area_m2"] <= 10.0 and "RESIDENTIAL" in (space["occupancy"] or "").upper()
            for space in evidence["spaces"]):
        return "NA", "Attic storey, residential space of at most 10 m2 (E.2.4(c))."
    rise, riser = evidence["modelled_rise_mm"], evidence["riser_height_mm"]
    if rise is not None and riser and rise < 1.5 * riser:
        return "NA", "Modelled flight rises by a single step; fewer than 2 steps is not a staircase (E.2.1)."
    return None, "No exemption or manual-check condition found."


def lane_widths(intervals: list[dict], half: float) -> dict[str, float]:
    """Narrowest walkable lane across one section, under two reference-line readings.

    ``intervals`` hold obstacle extents along the section axis (centre = 0, flight edges
    at +-half) with ``kind`` 'solid' or 'rail' and, for railings, the extent of parts
    below BALUSTRADE_BELOW_M as ``low``. Reading ``edge`` measures from walls/solids or
    the flight edge and treats railings as handrails (deducted only above 80 mm
    projection); ``balustrade`` measures from a balustrade's own inner side.
    """
    items = sorted((i for i in intervals if i["hi"] > -half and i["lo"] < half), key=lambda i: i["lo"])
    lanes, cursor = [], -half
    for item in items:
        if item["lo"] - cursor >= MIN_LANE_M:
            lanes.append((cursor, item["lo"]))
        cursor = max(cursor, item["hi"])
    if half - cursor >= MIN_LANE_M:
        lanes.append((cursor, half))
    result = {"edge": np.inf, "balustrade": np.inf}
    for n, (a, b) in enumerate(lanes):
        previous_end = lanes[n - 1][1] if n else None
        next_start = lanes[n + 1][0] if n + 1 < len(lanes) else None
        left = [i for i in items if i["hi"] <= a + 1e-9 and (previous_end is None or i["lo"] >= previous_end - 1e-9)]
        right = [i for i in items if i["lo"] >= b - 1e-9 and (next_start is None or i["hi"] <= next_start + 1e-9)]
        for reading in result:
            lo = _boundary(left, a, -1, half, previous_end is None, reading)
            hi = _boundary(right, b, 1, half, next_start is None, reading)
            result[reading] = min(result[reading], hi - lo)
    return result


def _boundary(cluster, face, outward, half, reaches_edge, reading):
    adjacent = [i for i in cluster if abs((i["hi"] if outward < 0 else i["lo"]) - face) < 1e-9]
    if not adjacent or any(i["kind"] == "solid" for i in adjacent):
        return face
    solids = [i for i in cluster if i["kind"] == "solid"]
    if solids:
        reference = max(i["hi"] for i in solids) if outward < 0 else min(i["lo"] for i in solids)
    elif reaches_edge:
        reference = outward * half
    else:
        return face  # an intermediate railing divides the staircase
    lows = [i["low"] for i in adjacent if i.get("low")]
    if reading == "balustrade" and lows:
        reference = max(low[1] for low in lows) if outward < 0 else min(low[0] for low in lows)
    return face if abs(face - reference) > HANDRAIL_LIMIT_M else reference


def _hits(origin, direction, triangles):
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    e1, e2 = b - a, c - a
    h = np.cross(direction, e2)
    det = (e1 * h).sum(1)
    valid = np.abs(det) > 1e-12
    inverse = np.where(valid, 1 / np.where(valid, det, 1), 0)
    s = origin - a
    u = inverse * (s * h).sum(1)
    q = np.cross(s, e1)
    v = inverse * (q * direction).sum(1)
    t = inverse * (e2 * q).sum(1)
    hit = valid & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
    return t[hit], np.nonzero(hit)[0]


def _circle_centre(xy):
    def fit(points):
        solution = np.linalg.lstsq(np.c_[2 * points, np.ones(len(points))], (points ** 2).sum(1), rcond=None)[0]
        return solution[:2]

    centre = fit(xy)
    for _ in range(5):
        radius = np.linalg.norm(xy - centre, axis=1)
        centre = fit(xy[radius >= np.percentile(radius, 85)])
    return centre


def _sections(vertices, spiral):
    """(origin_xy, axis_xy, half_width, tread_top_z) across the walking direction."""
    xy = vertices[:, :2]
    if spiral:
        centre = _circle_centre(xy)
        relative = xy - centre
        angle = np.arctan2(relative[:, 1], relative[:, 0])
        radius = np.linalg.norm(relative, axis=1)
        ordered = np.sort(angle)
        gaps = np.diff(np.r_[ordered, ordered[0] + 2 * np.pi])
        start = ordered[(np.argmax(gaps) + 1) % len(ordered)]
        swept = (angle - start) % (2 * np.pi)
        inner, outer = np.percentile(radius, 0.5), np.percentile(radius, 99.5)
        for fraction in SECTIONS:
            target = fraction * swept.max()
            near = np.abs(swept - target) < 0.03
            if near.sum() >= 3:
                axis = np.array([np.cos(start + target), np.sin(start + target)])
                yield centre + axis * (inner + outer) / 2, axis, (outer - inner) / 2, vertices[near, 2].max()
        return
    centred = xy - xy.mean(0)
    _, vectors = np.linalg.eigh(np.cov(centred.T))
    slope = [abs(np.corrcoef(centred @ vectors[:, i], vertices[:, 2])[0, 1]) for i in range(2)]
    run = vectors[:, int(np.argmax(slope))]
    axis = np.array([-run[1], run[0]])
    along, across = centred @ run, centred @ axis
    lo, hi = across.min(), across.max()
    for fraction in SECTIONS:
        target = along.min() + fraction * (along.max() - along.min())
        near = np.abs(along - target) < 0.05
        if near.sum() >= 3:
            yield xy.mean(0) + run * target + axis * (lo + hi) / 2, axis, (hi - lo) / 2, vertices[near, 2].max()


def _section_intervals(origin, axis, half, top, triangles, owners, is_rail):
    direction = np.array([axis[0], axis[1], 0.0])
    extents: dict[int, dict] = {}
    for height in HEIGHTS_M:
        start = np.array([origin[0], origin[1], top + height]) - direction * (half + 1.0)
        t, index = _hits(start, direction, triangles)
        position = t - (half + 1.0)
        keep = (position >= -half - 1e-6) & (position <= half + 1e-6)
        for value, owner in zip(position[keep], owners[index[keep]]):
            item = extents.setdefault(int(owner), {"lo": np.inf, "hi": -np.inf, "low": None,
                                                   "kind": "rail" if is_rail[owner] else "solid", "owner": int(owner)})
            item["lo"], item["hi"] = min(item["lo"], value), max(item["hi"], value)
            if item["kind"] == "rail" and height <= BALUSTRADE_BELOW_M:
                low = item["low"] or (np.inf, -np.inf)
                item["low"] = (min(low[0], value), max(low[1], value))
    return list(extents.values())


def load_meshes(model) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    import ifcopenshell.geom

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    iterator = ifcopenshell.geom.iterator(settings, model, multiprocessing.cpu_count())
    meshes = {}
    if iterator.initialize():
        while True:
            shape = iterator.get()
            faces = np.array(shape.geometry.faces).reshape(-1, 3)
            if len(faces):
                meshes[shape.id] = (np.array(shape.geometry.verts).reshape(-1, 3), faces)
            if not iterator.next():
                break
    return dict(sorted(meshes.items()))


def clear_width(model, meshes, stair) -> dict | None:
    """Narrowest lane over all flights and sections of *stair*, in millimetres."""
    import ifcopenshell.util.element as element_util

    flights = [p for p in element_util.get_decomposition(stair) if p.is_a("IfcStairFlight") and p.id() in meshes]
    if not flights:
        return None
    spiral = stair.PredefinedType in ("SPIRAL_STAIR", "CURVED_RUN_STAIR")
    best = {}
    for flight in flights:
        vertices = meshes[flight.id()][0]
        low, high = vertices.min(0) - [1.5, 1.5, 0.1], vertices.max(0) + [1.5, 1.5, 2.5]
        parts, owner_ids = [], []
        for identifier, (v, f) in meshes.items():
            if identifier == flight.id() or (v.max(0) < low).any() or (v.min(0) > high).any():
                continue
            if model.by_id(identifier).is_a() in NOT_OBSTACLES:
                continue
            triangles = v[f]
            near = ~((triangles.max(1) < low).any(1) | (triangles.min(1) > high).any(1))
            parts.append(triangles[near])
            owner_ids += [identifier] * int(near.sum())
        triangles = np.concatenate(parts) if parts else np.zeros((0, 3, 3))
        owners = np.array(owner_ids, dtype=int)
        is_rail = {identifier: model.by_id(identifier).is_a("IfcRailing") for identifier in set(owner_ids)}
        for origin, axis, half, top in _sections(vertices, spiral):
            intervals = _section_intervals(origin, axis, half, top, triangles, owners, is_rail)
            for reading, value in lane_widths(intervals, half).items():
                if reading not in best or value < best[reading][0]:
                    bounding = sorted({model.by_id(i["owner"]).Name for i in intervals if i["hi"] > -half and i["lo"] < half})
                    best[reading] = (value, flight.GlobalId, round(2 * half * 1000), bounding)
    if not best:
        return None
    edge, balustrade = best["edge"], best["balustrade"]
    return {
        "method": "radial sections" if spiral else "cross sections",
        "edge_reading_mm": round(edge[0] * 1000), "balustrade_reading_mm": round(balustrade[0] * 1000),
        "narrowest_flight": edge[1], "flight_width_mm": edge[2], "elements_in_section": edge[3],
    }


def stair_evidence(model, meshes, spaces, stair) -> dict:
    import ifcopenshell.util.element as element_util

    parts = [p for p in element_util.get_decomposition(stair) if not p.is_a("IfcRailing") and p.id() in meshes]
    if stair.id() in meshes:
        parts.append(stair)
    vertices = np.vstack([meshes[p.id()][0] for p in parts])
    low, high = vertices.min(0), vertices.max(0)
    samples = [np.array([x, y, z]) for x in np.linspace(low[0], high[0], 5)[1:-1]
               for y in np.linspace(low[1], high[1], 5)[1:-1] for z in (low[2] + 0.3, (low[2] + high[2]) / 2)]
    containing = []
    for space, triangles in spaces:
        count = sum(_inside(point, triangles) for point in samples)
        if count:
            properties = {k: val for pset in element_util.get_psets(space).values() for k, val in pset.items()}
            area = next((properties[k] for k in ("NetFloorArea", "GrossFloorArea", "Area") if k in properties), None)
            containing.append({"guid": space.GlobalId, "name": f"{space.LongName or ''} {space.Name or ''}".strip(),
                               "area_m2": None if area is None else round(float(area), 3),
                               "occupancy": properties.get("OccupancyType"), "samples": f"{count}/{len(samples)}"})
    common = element_util.get_psets(stair).get("Pset_StairCommon", {})
    flights = [p for p in parts if p.is_a("IfcStairFlight")]
    rise = None
    if flights:
        rise = round(max(meshes[p.id()][0][:, 2].max() - meshes[p.id()][0][:, 2].min() for p in flights) * 1000)
    return {
        "name": stair.Name, "predefined_type": stair.PredefinedType,
        "storey": getattr(element_util.get_container(stair), "Name", "") or "",
        "spaces": sorted(containing, key=lambda s: s["name"]),
        "pset_number_of_risers": common.get("NumberOfRiser"),
        "riser_height_mm": round(common["RiserHeight"], 1) if common.get("RiserHeight") else None,
        "modelled_rise_mm": rise,
    }


def _inside(point, triangles) -> bool:
    t, _ = _hits(point, np.array([1.0, 1e-7, 2e-7]), triangles)
    return int((t > 0).sum()) % 2 == 1


def measured_label(width_mm: int) -> str:
    return "PASS" if width_mm >= THRESHOLD_MM - 0.5 else "FAIL"


def reconcile(guid: str, expert: dict, evidence: dict, width: dict | None) -> dict:
    finding, reason = applicability_finding(evidence)
    record = {**evidence, "expert": {k: expert[k] for k in ("clause", "bucket", "message", "width_mm")},
              "applicability": {"finding": finding, "reason": reason}, "clear_width": width}
    conflicts = []
    if finding != (expert["label"] if expert["label"] in ("NA", "MANUAL_CHECK") else None):
        conflicts.append(f"applicability: IFC evidence gives {finding}, expert gives {expert['label']}")
    if expert["label"] in ("PASS", "FAIL"):
        if width is None:
            conflicts.append("no measurable flight geometry")
        else:
            by_edge = measured_label(width["edge_reading_mm"])
            record["measured_label"] = by_edge
            if by_edge != expert["label"]:
                conflicts.append(f"width: edge reading {width['edge_reading_mm']} mm gives {by_edge}, expert {expert['width_mm']} mm gives {expert['label']}")
            record["width_agreement"] = (
                "within 10 mm" if expert["width_mm"] is not None and abs(width["edge_reading_mm"] - expert["width_mm"]) <= WIDTH_AGREEMENT_MM
                else "same outcome, different width" if by_edge == expert["label"] else "outcome conflict")
            record["balustrade_reading_changes_outcome"] = measured_label(width["balustrade_reading_mm"]) != by_edge
    record["conflicts"] = conflicts
    adjudication = ADJUDICATIONS.get(guid)
    if conflicts and adjudication is None:
        raise ValueError(f"{guid}: {'; '.join(conflicts)}. Record an adjudication before regenerating.")
    if adjudication:
        record["adjudication"] = adjudication
    record["label"] = adjudication["label"] if adjudication else expert["label"]
    return record


def build_case() -> GroundTruth:
    import ifcopenshell

    subset = load(SUBSET_CASE_ID)
    model_path = subset.resolve_ifc()
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    if digest != subset.reference.get("ifc_sha256"):
        raise ValueError("The v8 IFC differs from the audited model. Review it before regenerating.")
    model = ifcopenshell.open(str(model_path))
    experts = expert_rows()
    stairs = model.by_type("IfcStair")
    if set(experts) != {stair.GlobalId for stair in stairs}:
        raise ValueError("Expert workbook rows do not cover exactly the IfcStair population.")
    meshes = load_meshes(model)
    spaces = [(space, meshes[space.id()][0][meshes[space.id()][1]]) for space in model.by_type("IfcSpace") if space.id() in meshes]
    provenance = {}
    for stair in sorted(stairs, key=lambda s: s.GlobalId):
        evidence = stair_evidence(model, meshes, spaces, stair)
        width = clear_width(model, meshes, stair)
        provenance[stair.GlobalId] = reconcile(stair.GlobalId, experts[stair.GlobalId], evidence, width)
    labels = {guid: record["label"] for guid, record in provenance.items()}
    for guid, record in provenance.items():
        if subset.labels.get(guid, record["label"]) != record["label"] and "adjudication" not in record:
            raise ValueError(f"{guid}: differs from the subset reference without adjudication.")
    counts = {label: list(labels.values()).count(label) for label in sorted(set(labels.values()))}
    sensitive = sorted(g for g, r in provenance.items() if r.get("balustrade_reading_changes_outcome"))
    agreement = [r["width_agreement"] for r in provenance.values() if "width_agreement" in r]
    measured = (f"Independent measurement: {agreement.count('within 10 mm')} of {len(agreement)} expert widths within "
                f"{WIDTH_AGREEMENT_MM} mm, {len(agreement) - agreement.count('outcome conflict')} of {len(agreement)} outcomes agree.")
    return replace(
        subset, case_id=CASE_ID, rule=RULE, labels=labels,
        violations=sorted(g for g, label in labels.items() if label == "FAIL"),
        provenance=provenance, source=f"stair_width_reference.py::build_case ({WORKBOOK}::{SHEET}, e.3.3.1 + e.2.4)",
        notes=f"Full population of 59 IfcStair: {counts}. Expert workbook labels with independent IFC applicability and clear-width evidence. The 49-stair subset case remains unchanged.",
        reference={
            "version": "full-population-v1", "supersedes": SUBSET_CASE_ID, "review_date": "2026-09-28",
            "evaluation_scope": "full_population", "ifc_sha256": digest, "population": len(stairs),
            "status": f"expert workbook labels cross-checked against IFC evidence with {sum('adjudication' in r for r in provenance.values())} recorded adjudications; not independent expert certification",
            "width_convention": "Stated in the rule text: clear width between walls/solids or flight edges; railings reduce the width only where they project more than 80 mm; a railing within the flight divides it and the narrowest lane counts. " + measured,
            "balustrade_sensitive_ids": sensitive,
            "limitations": "The stated convention differs from a strict reading measured from each balustrade's own inner side, which would change the outcome for the listed IDs. Industrial building use and residential-unit status are not recorded in the IFC; the E.2.4 and manual-check conditions rely on space names, storey names and occupancy properties. Geometry checks corroborate the workbook; they are not independent expert certification.",
        },
    )


def verify_recorded(case: GroundTruth) -> list[str]:
    """Fast consistency check of a stored case against the workbook and adjudications.

    Geometry is not recomputed here (about two minutes); use ``--check`` for that.
    """
    issues = []
    if case.rule != RULE:
        issues.append("Rule text differs from the builder.")
    experts = expert_rows()
    if set(experts) != set(case.provenance) or set(case.labels) != set(case.provenance):
        issues.append("Provenance, labels and workbook rows do not cover the same stairs.")
        return issues
    for guid, record in case.provenance.items():
        expert = experts[guid]
        if record.get("expert") != {k: expert[k] for k in ("clause", "bucket", "message", "width_mm")}:
            issues.append(f"{guid}: recorded expert row differs from the workbook.")
        if record.get("adjudication") != ADJUDICATIONS.get(guid):
            issues.append(f"{guid}: recorded adjudication differs from the builder.")
        if record.get("conflicts") and guid not in ADJUDICATIONS:
            issues.append(f"{guid}: unadjudicated conflict.")
        expected = ADJUDICATIONS[guid]["label"] if guid in ADJUDICATIONS else expert["label"]
        if case.labels[guid] != expected or record.get("label") != expected:
            issues.append(f"{guid}: label differs from expert row or adjudication.")
    return issues


def main() -> None:
    import sys

    case = build_case()
    if "--check" in sys.argv:
        stored = load(CASE_ID)
        same = stored.as_dict() == json.loads(json.dumps(case.as_dict()))
        print(f"{CASE_ID}: regenerated evidence {'matches' if same else 'DIFFERS FROM'} the stored case.")
        raise SystemExit(0 if same else 1)
    print(f"Saved {case.case_id}: {case.label_counts} to {case.save()}")


if __name__ == "__main__":
    main()
