"""Read-only benchmark checks; no agent execution or reference relabelling."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from completion import scope_classes
from ground_truth import GT_DIR, GroundTruth, load
from scoring import LABELS

PILOTS = ("slab_thickness__mall", "doors_windows_storey__condo", "staircase_width_v8")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def structural_issues(case: GroundTruth) -> list[str]:
    issues = []
    if any(label not in LABELS for label in case.labels.values()):
        issues.append("Unrecognised reference labels.")
    if len(case.violations) != len(set(case.violations)):
        issues.append("Duplicate violation IDs.")
    if case.labels and set(case.violations) != {guid for guid, label in case.labels.items() if label == "FAIL"}:
        issues.append("Stored violation list disagrees with reference FAIL labels.")
    if not case.rule.strip():
        issues.append("Rule is empty.")
    try:
        _ = case.unscored_ids
    except ValueError as exc:
        issues.append(str(exc))
    return issues


def condo_relationship_labels(model) -> dict[str, str]:
    fills = defaultdict(list)
    hosts = defaultdict(list)
    containers = defaultdict(list)
    parents = defaultdict(list)
    for relation in model.by_type("IfcRelFillsElement"):
        fills[relation.RelatedBuildingElement.id()].append(relation.RelatingOpeningElement)
    for relation in model.by_type("IfcRelVoidsElement"):
        hosts[relation.RelatedOpeningElement.id()].append(relation.RelatingBuildingElement)
    for relation in model.by_type("IfcRelContainedInSpatialStructure"):
        for element in relation.RelatedElements:
            containers[element.id()].append(relation.RelatingStructure)
    for relation in model.by_type("IfcRelAggregates"):
        for element in relation.RelatedObjects:
            parents[element.id()].append(relation.RelatingObject)

    def storey(element):
        visited = set()
        pending = [element]
        found = set()
        while pending:
            current = pending.pop()
            if current.id() in visited:
                continue
            visited.add(current.id())
            if current.is_a("IfcBuildingStorey"):
                found.add(current.GlobalId)
            else:
                pending.extend(containers[current.id()] + parents[current.id()])
        if len(found) > 1:
            raise ValueError("Ambiguous multi-storey containment requires adjudication.")
        return next(iter(found), None)

    labels = {}
    for element in model.by_type("IfcDoor") + model.by_type("IfcWindow"):
        openings = fills[element.id()]
        host_elements = [host for opening in openings for host in hosts[opening.id()]]
        if not host_elements:
            labels[element.GlobalId] = "FAIL"
            continue
        if len(host_elements) != 1:
            raise ValueError("Multiple hosts require adjudication.")
        own, host = storey(element), storey(host_elements[0])
        labels[element.GlobalId] = "ALERT" if own is None or host is None else "PASS" if own == host else "FAIL"
    return labels


def audit_case(case: GroundTruth, ifc_path: Path | None = None) -> dict:
    result = {"case_id": case.case_id, "status": "unreviewed", "issues": structural_issues(case),
              "reference_counts": case.label_counts, "reference_anchors": len(case.labels)}
    try:
        import ifcopenshell

        path = ifc_path or case.resolve_ifc()
        result["ifc_sha256"] = file_hash(path)
        model = ifcopenshell.open(str(path))
        excluded = case.unscored_ids
        subset = case.reference.get("evaluation_scope") == "annotated_subset"
        result["evaluation_scope"] = "annotated_subset" if subset else "full_population"
        result["unscored_ids"] = sorted(excluded)
        if subset and case.reference.get("ifc_sha256") != result["ifc_sha256"]:
            result["issues"].append("Subset reference IFC fingerprint differs from the current model.")
        classes = scope_classes(case.rule)
        if classes:
            anchors = {element.GlobalId for name in classes for element in model.by_type(name)}
            result.update(ifc_anchors=len(anchors), missing_reference_ids=sorted(anchors - set(case.labels)),
                          extra_reference_ids=sorted(set(case.labels) - anchors))
            if anchors != set(case.labels) | excluded:
                result["issues"].append("Reference labels and declared unscored IDs do not cover exactly the public IFC population.")
        elif subset:
            result["issues"].append("Subset scoring requires a verifiable public IFC class scope.")
        if case.case_id == "slab_thickness__mall_deprecated_v1":
            result["issues"].append("Legacy slab reference mistakes exported depth for thickness and misses recorded properties.")
        elif case.case_id == "slab_thickness__mall":
            from slab_reference import build_case

            rebuilt = build_case()
            if (case.labels != rebuilt.labels or case.provenance != rebuilt.provenance
                    or case.reference.get("ifc_sha256") != result["ifc_sha256"]):
                result["issues"].append("V2 labels, provenance or IFC fingerprint differ from recorded evidence.")
            result["status"] = "control-only"
            result["limitation"] = "Recorded-property adjudication, not expert certification. Zero FAIL examples: cannot measure violation detection."
        elif case.case_id == "doors_windows_storey__condo":
            actual = condo_relationship_labels(model)
            result["independent_counts"] = dict(Counter(actual.values()))
            if actual != case.labels:
                result["issues"].append("Raw IFC relationship traversal disagrees with reference labels.")
            result["status"] = "relations-checked"
            result["limitation"] = "Raw IFC relationships cross-checked, not an expert regulatory judgement."
        elif case.case_id == "staircase_width_v8_deprecated_v1":
            from import_bca_gt import CASES, extract

            imported, _ = extract(next(item for item in CASES if item.case_id == case.case_id))
            result["workbook_matches"] = imported.labels == case.labels
            if not result["workbook_matches"]:
                result["issues"].append("Expert workbook import differs from stored labels.")
            result["status"] = "expert-subset-checked" if subset else "workbook-checked"
            result["limitation"] = "Agreement is measured only on workbook-labelled stairs, not the full IFC population. Clear-width geometry and unlabelled stairs are not independently adjudicated."
        elif case.case_id == "staircase_width_v8":
            from stair_width_reference import verify_recorded

            result["issues"].extend(verify_recorded(case))
            if case.reference.get("ifc_sha256") != result["ifc_sha256"]:
                result["issues"].append("Full staircase reference IFC fingerprint differs from the current model.")
            result["status"] = "evidence-checked"
            result["limitation"] = "Workbook labels cross-checked against IFC spaces and measured clear widths at generation, with recorded adjudications; regenerate with stair_width_reference.py --check. Not independent expert certification."
        elif case.reference.get("tier") == "usable_2":
            from reference_v2 import verify_recorded as verify_usable_2

            result["issues"].extend(verify_usable_2(case, result["ifc_sha256"]))
            result["status"] = "evidence-checked"
            result["limitation"] = "Evidence recorded at generation (2026-09-29 review); regenerate with reference_v2.py --check. Not independent expert certification."
    except Exception as exc:
        result["issues"].append(f"Audit could not finish: {type(exc).__name__}: {exc}")
        result["status"] = "unverified"
    else:
        if result["issues"]:
            result["status"] = "invalid-or-incomplete"
    return result


def main():
    structural = []
    for path in sorted(GT_DIR.glob("*.json")):
        try:
            issues = structural_issues(load(path))
        except Exception as exc:
            issues = [str(exc)]
        if issues:
            structural.append({"file": path.name, "issues": issues})
    print(json.dumps({"case_files_checked": len(list(GT_DIR.glob('*.json'))),
                      "structural_issues": structural,
                      "pilots": [audit_case(load(name)) for name in PILOTS]}, indent=2))


if __name__ == "__main__":
    main()