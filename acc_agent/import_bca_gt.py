"""Import the advisor's BCA test cases into our GroundTruth JSON format.

The harness in ``bca_tests-harness_improvements/`` ships expert ground truth per
``(GUID, clause, requirement)`` tuple. The raw ``potential_ground_truth/*.csv``
files are gitignored, but the labels are preserved in the committed comparison
workbooks at ``analysis/gt_comparison/<rule>.xlsx`` (the ``gt_verdict`` /
``gt_bucket`` columns), one sheet per model.

We collapse one ``(rule, model-sheet, clause)`` into one of our cases:

- **labels** = the expert bucket of every labelled GUID, mapped onto our element
  label space: ``fail`` -> FAIL, ``pass`` -> PASS, ``exempt`` -> NA,
  ``alert`` -> ALERT. That mapping is the whole point of importing the buckets
  rather than a bit: the expert already distinguished "complies", "exempt from
  this clause" and "the model does not support a judgement", and flattening all
  three into "not a violation" throws away exactly the distinctions a checker
  gets wrong.
- **violation set** = the FAIL slice, kept so the binary metric is unchanged.
- ``blank`` rows (ground truth never authored) are skipped, not treated as PASS
    or NA. Explicit subset cases record unannotated IFC anchors outside scoring.

This lets the same CodeAct agent + set-agreement scorer used for the door rule
run against the harder, geometry-dependent BCA rules (e.g. staircase clear
width, headroom) without any change to the agent or the metric.

Usage:
    python import_bca_gt.py            # generate every registered case
    python import_bca_gt.py --list     # list the registered cases
    python import_bca_gt.py --only staircase_width_v8
"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from ground_truth import GT_DIR, GroundTruth, resolve_model_path

HARNESS_ROOT = resolve_model_path(
    "bca_tests-harness_improvements/bca_tests-harness_improvements"
)
GT_COMPARISON_DIR = HARNESS_ROOT / "analysis" / "gt_comparison"


@dataclass(frozen=True)
class BcaCase:
    """One importable case: a clause of a rule against one model."""

    case_id: str
    rule_file: str  # under analysis/gt_comparison/
    sheet: str
    clause: str
    ifc_rel: str  # relative to the workspace root
    entity_hint: str = ""  # e.g. "IfcStair"; helps the agent scope its search
    rule_override: str = ""  # use this rule text instead of the clause requirement
    regulation: str = ""  # verbatim regulatory clause text (fair interpretation input)
    complexity: int = 3  # Solihin & Eastman class; these rules need geometry
    evaluation_scope: str = "full_population"


# Verbatim regulatory text from the authoritative source, quoted so the agent has
# the same interpretation a human checker would read. This is the REGULATION, not a
# solution or measurement algorithm — the agent must still work out how to compute it
# from IFC geometry. Source: BCA Approved Document V7.08, para E.3.3.1 (and E.3.2.1),
# BCATestCases/Staircase width/Codes/approved-document-v7-08.pdf p.18-19.
STAIRCASE_E331_REGULATION = (
    "BCA Approved Document (Acceptable Solutions) — E.3.3 Width of staircase:\n"
    "E.3.3.1 The clear width of every staircase shall not be less than 1000 mm.\n"
    "Note: If the projection of the handrail into the clear width does NOT exceed "
    "80 mm on each side of the staircase, the width is measured from:\n"
    "  (a) the finished surfaces of the walls, if the staircase is enclosed on both "
    "sides by walls only; or\n"
    "  (b) the finished surface of the wall and the inner side of the balustrade, if "
    "the staircase has a wall on one side and a balustrade on the other; or\n"
    "  (c) the inner sides of the balustrades if the staircase has balustrades on "
    "both sides.\n"
    "If the projection of the handrail into the clear width EXCEEDS 80 mm on one or "
    "more side, the clear width is measured from:\n"
    "  (a) the finished surface of the wall and the inner side of the handrail, if "
    "the staircase has a wall on one side and a handrail on the other; or\n"
    "  (b) the inner sides of the handrails if the staircase has handrails on both "
    "sides.\n"
    "(E.3.2.1: no projection other than handrails is allowed into the staircase "
    "space within 2.0 m of the landing or pitch line.)"
)


# The strong candidates found in the ground-truth comparison workbooks. Each is a
# single clause with a clean pass/fail split whose GUIDs resolve in the model.
CASES: tuple[BcaCase, ...] = (
    # ⭐ True "clear width" geometric rule: 27 pass / 22 fail across 49 IfcStair.
    BcaCase(
        case_id="staircase_width_v8",
        rule_file="staircase_width.xlsx",
        sheet="Staircase width_bca__e-3-3__v8",
        clause="e.3.3.1",
        ifc_rel="bca_tests-harness_improvements/bca_tests-harness_improvements/"
        "BCATestCases/Staircase width/Test models/BCA_[E-3-3]_v8.ifc",
        entity_hint="IfcStair",
        regulation=STAIRCASE_E331_REGULATION,
        evaluation_scope="annotated_subset",
    ),
    # Exit access: 36 pass / 3 fail.
    BcaCase(
        case_id="exit_requirements_v0",
        rule_file="exit_requirements.xlsx",
        sheet="uat2_scdf_2.2.12_5_v0",
        clause="fc:2.2.12b",
        ifc_rel="bca_tests-harness_improvements/bca_tests-harness_improvements/"
        "BCATestCases/Location of exits & access to exits (EIB related)/"
        "Test models/uat2_scdf_2.2.12_5_v0.ifc",
    ),
    # Headroom (hardest, imbalanced): 171 pass / 1 fail across the condo model.
    BcaCase(
        case_id="headroom_condo_c32",
        rule_file="headroom.xlsx",
        sheet="Headroom_beta condo_uat1_v1",
        clause="c.3.2",
        ifc_rel="bca_tests-harness_improvements/bca_tests-harness_improvements/"
        "BCATestCases/Headroom/Test Models/beta condo_uat1_v1.ifc",
    ),
    # Planter box GFA (fuzzy rule, kept for completeness): 1 pass / 7 fail.
    BcaCase(
        case_id="planter_box_gfa",
        rule_file="planter_box.xlsx",
        sheet="20240313_URA_Planterbox",
        clause="-",
        ifc_rel="bca_tests-harness_improvements/bca_tests-harness_improvements/"
        "BCATestCases/Planter boxes/Test models/20240313_URA_Planterbox.ifc",
        entity_hint="IfcFurniture",
    ),
)


def _col_index(header: tuple, name: str) -> int:
    for i, cell in enumerate(header):
        if cell is not None and str(cell).strip().lower() == name:
            return i
    raise ValueError(f"Column {name!r} not found in header: {header!r}")


# The harness's expert buckets, mapped onto our element label space. An unknown
# bucket is deliberately absent rather than defaulted to PASS: guessing here
# would silently invent ground truth.
BUCKET_TO_LABEL = {
    "fail": "FAIL",
    "pass": "PASS",
    "exempt": "NA",
    "alert": "ALERT",
    "manual": "MANUAL_CHECK",
    "manual_check": "MANUAL_CHECK",
}


def _build_rule(requirement: str, entity_hint: str, regulation: str = "") -> str:
    req = (requirement or "").strip()
    if req:
        req = req[0].upper() + req[1:]
    scope = f" (modelled as {entity_hint})" if entity_hint else ""
    parts = [req]
    if regulation:
        parts.append(
            "\nRegulatory text (the authoritative clause — use it to interpret the "
            "requirement; you must still work out how to measure it from the IFC "
            "geometry):\n" + regulation.strip()
        )
    parts.append(
        f"\nReport the GlobalId of every element{scope} that does NOT satisfy this "
        f"requirement."
    )
    return "\n".join(parts)


def extract(case: BcaCase) -> tuple[GroundTruth, dict]:
    """Read *case* from its comparison workbook into a GroundTruth + a summary."""
    wb = openpyxl.load_workbook(GT_COMPARISON_DIR / case.rule_file, data_only=True)
    ws = wb[case.sheet]
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    ci = _col_index(header, "clause")
    gi = _col_index(header, "gt_bucket")
    gu = _col_index(header, "guid")
    ri = _col_index(header, "requirement")

    requirement = ""
    labels: dict[str, str] = {}
    buckets: dict[str, int] = {}
    unmapped: dict[str, int] = {}
    considered = 0
    for r in rows[1:]:
        if (r[ci] or "") != case.clause:
            continue
        bucket = str(r[gi] or "blank").strip().lower()
        if bucket == "blank":
            continue  # ground truth not authored for this row
        considered += 1
        buckets[bucket] = buckets.get(bucket, 0) + 1
        if not requirement and r[ri]:
            requirement = str(r[ri])
        label = BUCKET_TO_LABEL.get(bucket)
        if label is None:
            unmapped[bucket] = unmapped.get(bucket, 0) + 1
            continue
        if r[gu]:
            labels[str(r[gu])] = label
    if unmapped:
        raise ValueError(
            f"{case.case_id}: unrecognised ground-truth bucket(s) {unmapped}. "
            f"Add them to BUCKET_TO_LABEL rather than letting them be dropped."
        )

    fails = sorted(g for g, label in labels.items() if label == "FAIL")
    rule = case.rule_override or _build_rule(
        requirement, case.entity_hint, case.regulation
    )
    label_counts: dict[str, int] = {}
    for label in labels.values():
        label_counts[label] = label_counts.get(label, 0) + 1
    gt = GroundTruth(
        case_id=case.case_id,
        rule=rule,
        ifc_path=case.ifc_rel,
        violations=fails,
        labels=dict(sorted(labels.items())),
        complexity=case.complexity,
        clause=case.clause,
        source=f"{case.rule_file}::{case.sheet}::{case.clause}",
        notes=(
            f"Imported from gt_comparison. {len(fails)} fail / {considered} labelled "
            f"rows; expert buckets {buckets} -> labels "
            f"{dict(sorted(label_counts.items()))}."
        ),
    )
    if case.evaluation_scope == "annotated_subset":
        import ifcopenshell

        path = gt.resolve_ifc()
        model = ifcopenshell.open(str(path))
        anchors = {element.GlobalId for element in model.by_type(case.entity_hint)}
        if set(labels) - anchors:
            raise ValueError(f"{case.case_id}: labelled IDs fall outside the IFC scope.")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        gt.reference = {
            "version": "annotated-subset-v1",
            "evaluation_scope": "annotated_subset",
            "ifc_sha256": digest,
            "population": len(anchors),
            "unscored_ids": sorted(anchors - set(labels)),
            "limitation": "Workbook-labelled subset only; unannotated stairs have no reference judgment. Completion still requires the full IFC population.",
        }
    return gt, {"considered": considered, "buckets": buckets}


def _validate_guids(gt: GroundTruth) -> str:
    """Confirm the labelled GUIDs resolve in the IFC model; return a status note.

    Every anchor element is checked, not only the failures: a case whose PASS
    elements do not exist in the model would silently inflate union accuracy's
    denominator with GUIDs no run could ever label.
    """
    ifc_path = gt.resolve_ifc()
    if not ifc_path.exists():
        return f"IFC MISSING: {ifc_path}"
    import ifcopenshell

    model = ifcopenshell.open(str(ifc_path))
    guids = set(gt.labels) or set(gt.violations)
    missing = 0
    for guid in guids:
        try:
            model.by_guid(guid)
        except RuntimeError:
            missing += 1
    return (
        f"all {len(guids)} GUIDs resolve"
        if missing == 0
        else f"{missing}/{len(guids)} GUIDs missing"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List registered cases.")
    parser.add_argument("--only", type=str, default=None, help="Import one case id.")
    parser.add_argument(
        "--no-validate", action="store_true", help="Skip GUID-resolution check."
    )
    args = parser.parse_args()

    if args.list:
        for c in CASES:
            print(f"{c.case_id:<22} {c.rule_file} :: {c.sheet} :: {c.clause}")
        return

    cases = [c for c in CASES if (args.only is None or c.case_id == args.only)]
    if not cases:
        raise SystemExit(f"No case matches --only {args.only!r}")

    for case in cases:
        gt, _summary = extract(case)
        out = gt.save()
        status = "" if args.no_validate else f"  [{_validate_guids(gt)}]"
        print(
            f"{case.case_id:<22} {len(gt.violations):>3} fail / "
            f"{gt.anchor_count:>3} anchors  {gt.label_counts}  -> {out.name}{status}"
        )


if __name__ == "__main__":
    main()
