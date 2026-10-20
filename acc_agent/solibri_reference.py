"""Build the held-out test cases (decision 2026-10-13) from Solibri Office checking reports.

Door clear width: every door is labelled from the stated convention computed on the IFC
and compared with Solibri; a disagreement stops generation unless adjudicated below.
EC3-2026 catalogue rules (decision 2026-10-16): Solibri is the authority, as in the EC3
benchmark. An element in the rule's scope fails when an issue of the Solibri rule with
the rule's message lists it, and passes otherwise.
Solibri reports and the ruleset live outside the repository; their hashes are recorded.

    python solibri_reference.py              # write all held-out cases
    python solibri_reference.py --check      # regenerate and compare with stored files
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from ground_truth import WORKSPACE_ROOT, GroundTruth, load, resolve_model_path
from reference_v2 import REGULATION_HEADER, REPORT_LINE, TOLERANCE_MM, sha256
from simple_rules import BY_ID as CALIBRATION_RULES

TIER = "heldout"
REVIEW_DATE = "2026-10-17"
SOLIBRI_VERSION = "26.9.0.123"
SOLIBRI_DIR = WORKSPACE_ROOT / "gitignore" / "solibri_work"
RULESET = SOLIBRI_DIR / "thesis_heldout.cset"
EC3_MODELS = "ACC-function-generation/acc/bim_models"  # EC3 repository, commit 7e8b949
MODELS = {
    "clinic": f"{EC3_MODELS}/dental_clinic/arc.ifc",
    "duplex": f"{EC3_MODELS}/duplex/arc.ifc",
    "esplanades": "heldout_models/Esplanades_1807_EP_AR_v18.ifc",
    "fzk": f"{EC3_MODELS}/fzk_house/arc.ifc",
    "nus": "heldout_models/ISSUE_068_ARK_NUS_skolebygg.ifc",
    "schependomlaan": "heldout_models/Schependomlaan.ifc",
    "smiley": f"{EC3_MODELS}/smiley_west/arc.ifc",
    "wohnung": "heldout_models/ISSUE_159_kleine_Wohnung_R22.ifc",
}
GUID = re.compile(r"[0-9A-Za-z_$]{22}")

DOOR_WIDTH_MM = 900.0
DOOR_WIDTH_REPORTS = {
    "clinic": "door_width__clinic.xlsx",
    "schependomlaan": "door_width__schependomlaan.xlsx",
    "smiley": "door_width__Smiley-West.xlsx",
}
DOOR_WIDTH_REPORT_NOTES = {
    "clinic": " The Solibri report was produced on the original buildingSMART Clinic_Architectural.ifc; this EC3 "
              "copy has the same doors (GUIDs, widths, lining) and reproduces it.",
}
DOOR_WIDTH_SOLIBRI = (
    "SOL/208 Accessible Door Rule, sub-rule 404.2.2 reduced to clear width: Use spaces off; one requirement "
    "row * / * with min width 900 mm, min height 0, max threshold 99999 mm, min glazing 0 %, no free-area "
    "requirements; default frame and panel thickness 0; no property overrides. Role Get Started (the "
    "Schependomlaan report was made under Example Rules; no classification is used by this rule)."
)
DOOR_WIDTH_RULE = (
    "Every door must have a clear width of at least 900 mm.\n"
    + REGULATION_HEADER
    + "DIN 18040-1:2010-10 (Accessible buildings - publicly accessible buildings), 4.3.3.2 Dimensional "
    "requirements, Table 1 (paraphrased): all doors must provide a clear width of at least 90 cm.\n"
    "Benchmark convention: the clear width of a door is its overall width (IfcDoor.OverallWidth) minus twice "
    "the lining thickness recorded in the IfcDoorLiningProperties of its door type. When the door type "
    "records no lining thickness, the clear width is the overall width. A door without a recorded overall "
    "width cannot be judged: label it ALERT, and do NOT report it as a violation.\n"
    "\nLabel every door."
    + REPORT_LINE.format(entity="IfcDoor")
)
CURTAIN_WALL = (
    "Curtain-wall door; recorded OverallWidth 899.55 mm is within the 0.5 mm tolerance of 900 mm used by every "
    "benchmark reference and stated in the agent's label protocol. Solibri applies no tolerance and flags it."
)
ADJUDICATIONS = {
    "3LjuaIy0TB9BYwqsSadrQS": ("PASS", CURTAIN_WALL),
    "0bpfxAz3XBrAx$RjFuHv4q": ("PASS", CURTAIN_WALL),
}


def solibri_report(path: Path) -> dict[str, list[dict]]:
    """Issues per rule name of a Result Summary report (template 'Issue and Components').

    Rule names that occur more than once are left out, so they cannot be read ambiguously.
    """
    import openpyxl

    rows = [[v for v in row if v not in (None, "")]
            for row in openpyxl.load_workbook(path, data_only=True).worksheets[0].iter_rows(values_only=True)]
    parsed, current = [], None
    for row in rows:
        if any(isinstance(v, str) and v.startswith("SOL/") for v in row):
            current = []
            parsed.append((row[0], int(row[-1]), current))
        elif len(row) == 4 and isinstance(row[2], str) and row[2].startswith("Tolerance:"):
            current = None  # a rule set row
        elif any(isinstance(v, str) and v.endswith(" Severity") for v in row):
            current.append({"title": row[0], "text": row[1], "severity": row[2], "count": int(row[-1]),
                            "components": 0, "guids": [], "names": []})
        elif current and 1 <= len(row) <= 2:  # a component row; the model itself has no GUID
            current[-1]["components"] += 1
            if isinstance(row[-1], str) and GUID.fullmatch(row[-1]):
                current[-1]["guids"].append(row[-1])
                current[-1]["names"].append(row[0] if len(row) > 1 else "")
    for rule, declared, issues in parsed:
        if declared != len(issues) or any(issue["count"] != issue["components"] for issue in issues):
            raise ValueError(f"{path.name}: {rule!r} parsed counts differ from the declared counts.")
    names = Counter(rule for rule, _, _ in parsed)
    return {rule: issues for rule, _, issues in parsed if names[rule] == 1}


def solibri_issues(path: Path) -> tuple[dict[str, dict], int]:
    """Door clear-width issues of an SOL/208 report keyed by GUID, and the issue count."""
    (issues,) = solibri_report(path).values()
    flagged = {}
    for issue in issues:
        found = re.search(r"width is ([\d.,]+) mm", issue["text"])
        if (not issue["title"].endswith(" has dimension violations") or "too narrow" not in issue["text"]
                or found is None or len(issue["guids"]) != 1):
            raise ValueError(f"{path.name}: unexpected issue {issue['title']!r}.")
        flagged[issue["guids"][0]] = {"component": issue["title"].split()[0], "name": issue["names"][0],
                                      "width_mm": float(found.group(1).replace(".", "").replace(",", ".")),
                                      "severity": issue["severity"]}
    return flagged, len(issues)


def lining_thickness(door, scale: float) -> float | None:
    import ifcopenshell.util.element as element_util

    if any(rel.RelatingPropertyDefinition.is_a("IfcDoorLiningProperties") for rel in door.IsDefinedBy
           if rel.is_a("IfcRelDefinesByProperties")):
        raise ValueError(f"{door.GlobalId}: occurrence-level lining properties. Review required.")
    door_type = element_util.get_type(door)
    for definition in (getattr(door_type, "HasPropertySets", None) or []):
        if definition.is_a("IfcDoorLiningProperties") and definition.LiningThickness:
            return round(definition.LiningThickness * scale, 2)
    return None


def build_door_width(model_id: str) -> GroundTruth:
    import ifcopenshell
    import ifcopenshell.util.unit as unit_util

    ifc_rel, report = MODELS[model_id], SOLIBRI_DIR / DOOR_WIDTH_REPORTS[model_id]
    path = resolve_model_path(ifc_rel)
    model = ifcopenshell.open(str(path))
    scale = unit_util.calculate_unit_scale(model) * 1000.0
    flagged, _ = solibri_issues(report)
    doors = model.by_type("IfcDoor")
    labels, provenance, unscored = {}, {}, []
    for door in doors:
        solibri = flagged.get(door.GlobalId)
        if door.OverallWidth is None:
            unscored.append(door)
            continue
        overall = round(door.OverallWidth * scale, 2)
        lining = lining_thickness(door, scale)
        clear = round(overall - 2 * lining, 2) if lining else overall
        computed = "PASS" if clear >= DOOR_WIDTH_MM - TOLERANCE_MM else "FAIL"
        label, conflict = computed, None
        if computed != ("FAIL" if solibri else "PASS"):
            if door.GlobalId not in ADJUDICATIONS:
                raise ValueError(f"{door.GlobalId}: convention {computed}, Solibri {'FAIL' if solibri else 'PASS'}. Adjudicate.")
            label, conflict = ADJUDICATIONS[door.GlobalId]
        labels[door.GlobalId] = label
        provenance[door.GlobalId] = {
            "name": door.Name, "overall_width_mm": overall, "lining_thickness_mm": lining, "clear_width_mm": clear,
            "solibri": solibri, "label": label, "conflict": conflict}
    outside = sorted(set(flagged) - {door.GlobalId for door in doors})
    if any(model.by_guid(guid) is None for guid in outside):
        raise ValueError(f"{report.name}: flagged GUIDs missing from the IFC.")
    unscored_ids = sorted(door.GlobalId for door in unscored)
    counts = Counter(labels.values())
    unscored_note = ""
    if unscored:
        names = Counter(door.Name for door in unscored)
        unscored_note = (f" {len(unscored)} IfcDoor objects without a recorded width are unscored "
                         f"({dict(sorted(names.items()))}); Solibri flagged {sum(d.GlobalId in flagged for d in unscored)} of them from geometry.")
    reference = {
        "version": 1, "evaluation_scope": "annotated_subset" if unscored else "full_population",
        "population": len(doors), "ifc_sha256": sha256(path),
        "solibri": {"version": SOLIBRI_VERSION, "configuration": DOOR_WIDTH_SOLIBRI,
                    "ruleset_file": RULESET.name, "ruleset_sha256": sha256(RULESET),
                    "report_file": report.name, "report_sha256": sha256(report), "issues": len(flagged),
                    "outside_scope": [{"guid": guid, "class": model.by_guid(guid).is_a(), **flagged[guid]} for guid in outside]},
        "status": "Solibri SOL/208 issues reproduced from the IFC under the stated convention; disagreements adjudicated with reasons.",
        "policy": f"Clear width = OverallWidth - 2 x type LiningThickness (else OverallWidth) >= {DOOR_WIDTH_MM:g} mm with {TOLERANCE_MM} mm tolerance.",
        "limitations": "Solibri measures door geometry including the frame when no lining thickness is recorded; outcomes agree here, values may differ." + unscored_note
                       + DOOR_WIDTH_REPORT_NOTES.get(model_id, ""),
    }
    if unscored:
        reference["unscored_ids"] = unscored_ids
    return GroundTruth(
        case_id=f"door_clear_width__{model_id}", rule=DOOR_WIDTH_RULE, ifc_path=ifc_rel, clause="DIN 18040-1 4.3.3.2 Table 1",
        complexity=2, threshold_mm=DOOR_WIDTH_MM, tolerance_mm=TOLERANCE_MM, labels=dict(sorted(labels.items())),
        violations=sorted(g for g, label in labels.items() if label == "FAIL"),
        provenance=dict(sorted(provenance.items())), source=f"solibri_reference.py::build_door_width ({report.name})",
        notes=f"Door clear width on {len(doors)} IfcDoor: {dict(sorted(counts.items()))}.{unscored_note}",
        reference={"tier": TIER, "review_date": REVIEW_DATE, **reference},
    )


# --------------------------------------------------------------------------- #
# EC3-2026 catalogue rules, labelled from Solibri issues (decision 2026-10-16)
# --------------------------------------------------------------------------- #
EC3_REPORTS = {
    "clinic": "ec3_clinic_check.xlsx",
    "duplex": "ec3_duplex_check.xlsx",
    "fzk": "ec3_fzk_check.xlsx",
    "schependomlaan": "ec3_schependomlaan_check.xlsx",
    "smiley": "ec3_smiley_check.xlsx",
    "esplanades": "ec3_esplanades_check.xlsx",
    "nus": "ec3_nus_check.xlsx",
    "wohnung": "ec3_wohnung_check.xlsx",
}
EC3_SOLIBRI = (
    "The four rule sets of the EC3-2026 Solibri projects (ADA and ABA Accessibility Guidelines, Advanced Space "
    "Check, BIM Validation - Architectural, General Space Check) with their classifications, unchanged. EC3 "
    "models: their arc.smc; other models: ec3_template.smc (the EC3 smiley_west project with the model "
    "replaced through Update Models). Report template CheckingSummaryTemplate - Issue and Components."
)
def _source(name: str, text: str = "") -> str:
    """Source line quoting the EC3-2026 catalogue description of the rule, when it describes this rule."""
    return f"\nSource: rule '{name}' of the EC3-2026 rule catalogue" + (f": {text}\n" if text else ".\n")


ADA_504_2 = (
    REGULATION_HEADER + "ADA and ABA Accessibility Guidelines (2004), 504.2 Treads and Risers: All steps on a "
    "flight of stairs shall have uniform riser heights and uniform tread depths. Risers shall be 4 inches "
    "(100 mm) high minimum and 7 inches (180 mm) high maximum. Treads shall be 11 inches (280 mm) deep minimum.\n"
)
STAIR_CONVENTION = (
    "Benchmark convention: judge every stair as a whole, from its steps as modelled in its geometry; recorded "
    "step properties may be missing, zero or inconsistent with the geometry. "
)
SPACE_COMPONENTS = "walls, curtain walls, columns, slabs and roofs"
ROOF_SLABS_NA = (
    "Roof slabs (IfcSlab with PredefinedType ROOF) belong to the roof and are not assessed: label them NA."
)


def _text(requirement: str, source: str, convention: str, noun: str, entity: str) -> str:
    return f"{requirement}{source}{convention}\n\nLabel every {noun}." + REPORT_LINE.format(entity=entity)


@dataclass(frozen=True)
class Ec3Rule:
    rule_id: str
    solibri_rule: str  # rule name in the Solibri report
    message: str | None  # regex an issue text must match; None accepts every issue of the rule
    scope: tuple[str, ...]
    complexity: int
    clause: str
    rule: str
    single_subject: bool = False  # an issue naming several scope elements does not identify the failing one
    roof_slabs_na: bool = False  # Solibri classifies IfcSlab ROOF as roofs, outside its slab rules


EC3_RULES = (
    Ec3Rule(
        "stair_riser_height", "504.2 Treads and Risers", r"riser height is .* height for the risers is",
        ("IfcStair",), 1, "ADA 504.2",
        _text("Every stair must have risers between 100 mm and 180 mm high.", ADA_504_2,
              STAIR_CONVENTION + "The limits apply in inches as written: 4 in = 101.6 mm and 7 in = 177.8 mm. A stair "
              "fails when its typical riser height (the height shared by its regular steps) is below 101.6 mm or "
              "above 177.8 mm. A first or last step that differs from the others is covered by a separate "
              "uniformity check, and tread depth by a separate tread check.", "stair", "IfcStair"),
        single_subject=True),
    Ec3Rule(
        "stair_tread_depth", "504.2 Treads and Risers", r"tread length is .* length for the tread is",
        ("IfcStair",), 1, "ADA 504.2",
        _text("Every stair must have treads at least 280 mm deep.", ADA_504_2,
              STAIR_CONVENTION + "The limit applies in inches as written: 11 in = 279.4 mm. A stair fails when its "
              "typical tread depth (the horizontal going from one riser to the next, shared by its regular steps) "
              "is below 279.4 mm. Riser heights are covered by separate checks.", "stair", "IfcStair"),
        single_subject=True),
    Ec3Rule(
        "stair_uniform_risers", "504.2 Treads and Risers", r"has steps at the (beginning|end) that are non-uniform",
        ("IfcStair",), 2, "ADA 504.2",
        _text("All steps of a stair must have uniform riser heights.", ADA_504_2,
              STAIR_CONVENTION + "Only riser heights are compared. The first riser is measured from the floor the "
              "stair starts on, the last riser up to the floor it arrives at. A stair fails when the riser of its "
              "first step or of its last step differs from the riser height of its other steps by more than 0.5 mm. "
              "The riser and tread limits are covered by separate checks.", "stair", "IfcStair"),
        single_subject=True),
    Ec3Rule(
        "stair_slab_connection", "504.2 Treads and Risers", r"is not connected to slabs? at the (beginning|end)",
        ("IfcStair",), 2, "EC3 504.2 stair-slab connection",
        _text("Every stair must be connected to slabs at its beginning and at its end.",
              _source("504.2 Treads and Risers", "All stairs shall be connected to slabs."),
              STAIR_CONVENTION + "A stair is connected at its beginning when its bottom step starts on a slab "
              "(a floor or landing slab), and at its end when its top step arrives at a slab. A stair fails when it "
              "is not connected at its beginning, at its end, or at both.", "stair", "IfcStair"),
        single_subject=True),
    Ec3Rule(
        "door_front_clearance", "Clearance in Front of Doors", None, ("IfcDoor",), 3, "EC3 BIM validation",
        _text("The area in front of every door must be free of building components.",
              _source("Clearance in Front of Doors", "This rule checks there is enough clearance in front of doors."),
              "Benchmark convention: the free area is a box directly in front of the door opening, on the side to "
              "which the door opens. It is as wide and as high as the door and as deep as the door is wide, shrunk "
              "by 50 mm on each side so that components merely touching it do not count. A door fails when any "
              "building component other than a space (walls, curtain walls, slabs, floor finishes and other "
              "coverings, columns, doors, windows, stairs, railings, furniture, building services or other objects) "
              "intersects its free area.", "door", "IfcDoor"),
        single_subject=True),
    Ec3Rule(
        "doors_windows_storey", "Doors and Windows", None, ("IfcDoor", "IfcWindow"), 2, "BIM validation",
        CALIBRATION_RULES["doors_windows_storey"].rule_text(None)),
    Ec3Rule(
        "slab_thickness_range", "Slab Thickness", None, ("IfcSlab",), 1, "EC3 BIM validation",
        _text("Every slab must have a thickness between 30 mm and 1000 mm inclusive.",
              _source("Slab Thickness", "This rule checks that slab thickness is not too small or too large."),
              "Benchmark convention: the thickness of a slab is the thickness of its own construction: the total of "
              "its material layers or its recorded thickness, or else the depth of its body. A slab fails when it is "
              "thinner than 30 mm or thicker than 1000 mm. " + ROOF_SLABS_NA, "slab", "IfcSlab"),
        roof_slabs_na=True),
    Ec3Rule(
        "slab_fall_protection", "Slabs must be Guarded against Falling", None, ("IfcSlab",), 3, "EC3 BIM validation",
        _text("No one may be able to fall from the edge of a slab.",
              _source("Slabs must be Guarded against Falling", (
                  "This rule checks that it is not possible to fall from slabs. The rule checks that horizontal "
                  "components are surrounded by vertical components, such as walls or railings. If no vertical "
                  "component exists on the edge of a horizontal component, another horizontal component or stairs "
                  "needs to continue and the drop to the other horizontal component must not be more than "
                  "specified.")),
              "Benchmark convention: check every edge of every slab. An edge is safe when (a) walls, railings, "
              "columns, stairs or other objects stand along it as a barrier at least 1.00 m high above the slab top, "
              "with gaps of at most 100 mm between barrier parts and between the slab and the barrier, or (b) "
              "another slab, a stair, a ramp or the site, at least 200 mm wide, continues within 100 mm of the edge "
              "and at most 500 mm below the slab top. A slab fails when part of its edge is neither guarded nor "
              "continued: a missing barrier, a barrier lower than 1.00 m, a barrier that does not cover the whole "
              "edge, or a continuing surface too far away, too narrow or more than 500 mm below. " + ROOF_SLABS_NA,
              "slab", "IfcSlab"),
        single_subject=True, roof_slabs_na=True),
    Ec3Rule(
        "space_contains_components", "Space Validation", r"are inside the space", ("IfcSpace",), 2,
        "EC3 BIM validation",
        _text(f"No {SPACE_COMPONENTS.replace(' and ', ' or ')} may lie inside a space.",
              _source("Space Validation", (
                  "This rule checks that space geometry and location are correct. It also checks intersections "
                  "(inside only) with other components. This template focuses only on the 'inside' check: "
                  "components that are inside the space.")),
              f"Benchmark convention: spaces are bounded by {SPACE_COMPONENTS}, not filled with them. A space fails "
              "when one or more of these components lies inside its volume. Components that only cut through the "
              "space boundary are covered by a separate intersection check; doors, windows, furniture and other "
              "spaces are ignored.", "space", "IfcSpace"),
        single_subject=True),
    Ec3Rule(
        "space_component_intersection", "Space Validation", r"Space intersects with", ("IfcSpace",), 2,
        "EC3 BIM validation",
        _text(f"A space must not intersect {SPACE_COMPONENTS.replace(' and ', ' or ')}.",
              _source("Space Validation", (
                  "This rule checks that space geometry and location are correct. It checks that space does not "
                  "incorrectly intersect with slabs, walls or other components. This template focuses only on the "
                  "'intersect' check.")),
              "Benchmark convention: a space fails when its volume overlaps a wall, curtain wall, column, slab or "
              "roof by more than 30 mm; smaller overlaps at the space boundary are tolerated. Components lying "
              "entirely inside the space are covered by a separate check; doors, windows, furniture and other "
              "spaces are ignored.",
              "space", "IfcSpace"),
        single_subject=True),
    Ec3Rule(
        "space_storey_elevation", "Spaces in Same Building Storey Must Have Same Bottom Elevation", None,
        ("IfcSpace",), 2, "EC3 BIM validation",
        _text("Spaces in the same building storey must share the same bottom elevation.",
              _source("Spaces in Same Building Storey Must Have Same Bottom Elevation"),
              "Benchmark convention: the bottom elevation of a space is the lowest point of its modelled volume. "
              "When the spaces of a building storey do not all share one bottom elevation (differences of more than "
              "0.5 mm count), every space of that storey fails, including those at the most common elevation. The "
              "spaces of a storey that all share one bottom elevation pass.", "space", "IfcSpace")),
    Ec3Rule(
        "unallocated_floor_area", "Unallocated Areas", None, ("IfcWall", "IfcCurtainWall", "IfcColumn"), 3,
        "EC3 BIM validation",
        _text("Every enclosed floor area of a building storey must be allocated to a space.",
              _source("Unallocated Areas", "This rule checks that space geometry and location are correct."),
              "Benchmark convention: on each building storey, find floor areas enclosed by walls, curtain walls and "
              "columns that are occupied by no space, wall or column. Every such unallocated area larger than "
              "0.50 m2 is a violation, reported through the walls, curtain walls and columns that surround it: each "
              "of them fails. All other walls, curtain walls and columns pass.", "wall, curtain wall and column",
              "IfcWall or IfcCurtainWall or IfcColumn")),
)
EC3_BY_ID = {rule.rule_id: rule for rule in EC3_RULES}
KNOWN_RULES = ("doors_windows_storey", "slab_thickness_range", "space_storey_elevation")  # calibration rules, new models
STAIR_RULES = ("stair_riser_height", "stair_tread_depth", "stair_uniform_risers", "stair_slab_connection")
EXCLUDED = {  # Solibri's reading contradicts the IFC geometry, so its issues are no reference
    f"{rule}__schependomlaan": "Solibri reads every flight with 1313 mm risers (geometry: about 188 mm) and "
                               "flags non-uniform steps on 3 of 6 identically modelled flights."
    for rule in STAIR_RULES
}
SMILEY_ROUNDING = (
    "Solibri reports beginning 348 mm and elsewhere 347 mm; the stair geometry rises 347.5 mm at every step, so the "
    "difference is display rounding, not a difference above the 0.5 mm stated in the rule."
)
EC3_ADJUDICATIONS = {  # case -> {GlobalId: (label, reason)} where the stated convention overrides Solibri
    "stair_uniform_risers__smiley": {guid: ("PASS", SMILEY_ROUNDING) for guid in (
        "00g$7A$xj1Yw7$pz0Gu5Jl", "0QL6xmUc54YQTL8_HTe$PR", "0j2BPntubCLvFyPyFS3XrS", "1HA569_750YQ6p1wDgzt4W",
        "1KW$AVfrjEkB34OWNk8Cdy", "1wkrvIms59MRradq0vI9vQ", "2QdKt0EeDDihduxfDG8NT8", "2WCholb_92w9VGgEQcoe8M",
        "3Ohp$OuUb3IhgebzR81n9X", "3QuFvRNNbDWRsEhil9DPsO")},
    "stair_uniform_risers__esplanades": {guid: ("PASS", (
        "Solibri reports beginning 160 mm and elsewhere 159 mm; measured from the storey floor the first riser is "
        "159.5 mm like the others and the last tread meets the next floor, so the difference is display rounding."))
        for guid in ("137S7XuHL$hLQIcF7yTLvo", "0$6xGwHfe7xv6o3XCOF8P1", "2DX9LYzXmwiwJnld$NY4Hf", "0YVg95JNGjBkES1se81M7T")},
    "stair_uniform_risers__nus": {"3iPInG7tz8TQ8k$JBnn$fn": ("PASS", (
        "Solibri reports end 168 mm and elsewhere 167 mm; every riser, including the first and last to the storey "
        "floors, measures 166.6-166.7 mm, so the difference is display rounding."))},
}
UNSCORED = (  # (rule ids or None for all, model id or None for all, reason, predicate): left out of scoring
    (None, "nus", "IfcSpace objects with LongName 'Area' are whole-storey GFA zones from Revit area plans that overlap "
                  "the rooms; they are not rooms (user, 2026-10-16).",
     lambda element: element.is_a("IfcSpace") and element.LongName == "Area"),
    (("doors_windows_storey",), None, "Doors and windows that are parts of a curtain wall fill no opening; the "
     "calibration text counts them as orphans, Solibri relates them to the curtain wall, so the stated rule does not "
     "decide them.",
     lambda element: not element.FillsVoids and bool(element.Decomposes)
     and element.Decomposes[0].RelatingObject.is_a("IfcCurtainWall")),
    (STAIR_RULES, None, "An IfcStair that is a part of another IfcStair duplicates its parent stair; Solibri reports "
     "the parent.",
     lambda element: bool(element.Decomposes) and element.Decomposes[0].RelatingObject.is_a("IfcStair")),
)


def build_ec3(rule_id: str, model_id: str) -> GroundTruth:
    import ifcopenshell

    spec, report = EC3_BY_ID[rule_id], SOLIBRI_DIR / EC3_REPORTS[model_id]
    ifc_rel = MODELS[model_id]
    path = resolve_model_path(ifc_rel)
    model = ifcopenshell.open(str(path))
    issues = solibri_report(report)[spec.solibri_rule]
    if any(issue["components"] != len(issue["guids"]) for issue in issues):
        raise ValueError(f"{report.name}: {spec.solibri_rule!r} lists components without a GUID.")
    if any(model.by_guid(guid) is None for issue in issues for guid in issue["guids"]):
        raise ValueError(f"{report.name}: flagged GUIDs missing from the IFC.")
    scope = {element.GlobalId: element for name in spec.scope for element in model.by_type(name)}
    policies = [(reason, predicate) for rules, model_ids, reason, predicate in UNSCORED
                if (rules is None or rule_id in rules) and model_ids in (None, model_id)]
    excluded = {guid: reason for guid, element in scope.items() for reason, predicate in policies if predicate(element)}
    matched = [issue for issue in issues if spec.message is None or re.search(spec.message, issue["text"])]
    failed, ambiguous = defaultdict(list), set()
    for issue in matched:
        subjects = [guid for guid in issue["guids"] if guid in scope and guid not in excluded]
        if spec.single_subject and len(subjects) > 1:
            ambiguous.update(subjects)
            continue
        for guid in subjects:
            failed[guid].append(issue["title"])
    unscored = sorted((ambiguous - set(failed)) | set(excluded))
    roofs = {guid for guid, element in scope.items()
             if spec.roof_slabs_na and element.is_a("IfcSlab") and element.PredefinedType == "ROOF"}
    if roofs & (set(failed) | ambiguous):
        raise ValueError(f"{report.name}: {spec.solibri_rule!r} flags a roof slab. Review the scope.")
    labels, provenance = {}, {}
    adjudications = EC3_ADJUDICATIONS.get(f"{rule_id}__{model_id}", {})
    if any(guid not in failed for guid in adjudications):
        raise ValueError(f"{rule_id}__{model_id}: an adjudicated element is not flagged by Solibri.")
    for guid, element in sorted(scope.items()):
        if guid in unscored:
            continue
        labels[guid] = "NA" if guid in roofs else "FAIL" if guid in failed else "PASS"
        provenance[guid] = {"name": element.Name, "class": element.is_a(), "label": labels[guid]}
        if guid in failed:
            provenance[guid]["issues"] = sorted(set(failed[guid]))
        if guid in adjudications:
            labels[guid], provenance[guid]["conflict"] = adjudications[guid]
            provenance[guid]["label"] = labels[guid]
    failed = {guid: issues for guid, issues in failed.items() if labels[guid] == "FAIL"}
    counts = Counter(labels.values())
    ambiguous_only = ambiguous - set(failed)
    unscored_note = (f" {len(ambiguous_only)} elements appear only in issues naming several of them, so the failing "
                     "one is not identified; they are unscored." if ambiguous_only else "")
    for reason, count in Counter(excluded.values()).items():
        unscored_note += f" {count} unscored: {reason}"
    reference = {
        "version": 1, "evaluation_scope": "annotated_subset" if unscored else "full_population",
        "population": len(scope), "ifc_sha256": sha256(path),
        "solibri": {"version": SOLIBRI_VERSION, "configuration": EC3_SOLIBRI, "rule": spec.solibri_rule,
                    "message": spec.message, "report_file": report.name, "report_sha256": sha256(report),
                    "rule_issues": len(issues), "matching_issues": len(matched)},
        "status": "Labels taken from the Solibri issues of the rule (the authority, as in the EC3 benchmark).",
        "policy": "FAIL: a scope element listed by an issue of the Solibri rule whose text matches the message; "
                  "PASS: every other scope element" + ("; NA: IfcSlab ROOF (a roof for Solibri)" if roofs else "")
                  + (f"; {len(adjudications)} recorded adjudications override Solibri with reasons." if adjudications else "."),
        "limitations": "The geometric judgement is Solibri's and is not recomputed independently." + unscored_note,
    }
    if unscored:
        reference["unscored_ids"] = unscored
    return GroundTruth(
        case_id=f"{rule_id}__{model_id}", rule=spec.rule, ifc_path=ifc_rel, clause=spec.clause,
        complexity=spec.complexity, tolerance_mm=TOLERANCE_MM, labels=labels,
        violations=sorted(failed), provenance=provenance,
        source=f"solibri_reference.py::build_ec3 ({report.name})",
        notes=f"{spec.solibri_rule} on {len(scope)} {' or '.join(spec.scope)}: {dict(sorted(counts.items()))}.{unscored_note}",
        reference={"tier": TIER, "review_date": REVIEW_DATE, **reference},
    )


BUILDERS = {f"door_clear_width__{m}": (lambda m=m: build_door_width(m)) for m in DOOR_WIDTH_REPORTS}
RULES = {case_id: DOOR_WIDTH_RULE for case_id in BUILDERS}
REPORT_FILES = {f"door_clear_width__{m}": SOLIBRI_DIR / report for m, report in DOOR_WIDTH_REPORTS.items()}
for _spec in EC3_RULES:
    for _model in EC3_REPORTS:
        if f"{_spec.rule_id}__{_model}" in EXCLUDED:
            continue
        BUILDERS[f"{_spec.rule_id}__{_model}"] = lambda r=_spec.rule_id, m=_model: build_ec3(r, m)
        RULES[f"{_spec.rule_id}__{_model}"] = _spec.rule
        REPORT_FILES[f"{_spec.rule_id}__{_model}"] = SOLIBRI_DIR / EC3_REPORTS[_model]


def verify_recorded(case: GroundTruth, ifc_sha256: str) -> list[str]:
    """Fast consistency check of a stored held-out case; ``--check`` regenerates the evidence."""
    if case.case_id not in BUILDERS or case.reference.get("tier") != TIER:
        return ["Not a registered held-out case."]
    issues = []
    if case.reference.get("ifc_sha256") != ifc_sha256:
        issues.append("IFC fingerprint differs from the recorded reference.")
    if case.rule != RULES[case.case_id]:
        issues.append("Rule text differs from the builder.")
    if set(case.provenance) != set(case.labels) or any(case.provenance[g].get("label") != label for g, label in case.labels.items()):
        issues.append("Recorded provenance and labels disagree.")
    return issues


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", action="append", choices=sorted(BUILDERS))
    parser.add_argument("--check", action="store_true", help="regenerate and compare with the stored cases")
    args = parser.parse_args()
    failed = False
    for case_id in args.only or sorted(BUILDERS):
        if not REPORT_FILES[case_id].exists():
            print(f"{case_id}: skipped, {REPORT_FILES[case_id].name} not exported yet.")
            continue
        case = BUILDERS[case_id]()
        if args.check:
            same = load(case_id).as_dict() == json.loads(json.dumps(case.as_dict()))
            failed |= not same
            print(f"{case_id}: regenerated evidence {'matches' if same else 'DIFFERS FROM'} the stored case.")
        else:
            print(f"Saved {case_id}: {case.label_counts} to {case.save()}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
