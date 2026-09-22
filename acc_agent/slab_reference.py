"""Build the versioned mall slab reference from recorded IFC property evidence."""

from __future__ import annotations

import hashlib
from dataclasses import replace

from ground_truth import GT_DIR, GroundTruth, load

CASE_ID = "slab_thickness__mall_v2"
LEGACY_CASE_ID = "slab_thickness__mall"
TOLERANCE_MM = 0.5


def adjudicate(sources: list[dict], quantity_depth: dict | None = None) -> dict:
    if not sources:
        if quantity_depth is not None:
            raise ValueError("Depth-only slab needs review; no explicit thickness corroboration.")
        return {
            "label": "ALERT", "value_mm": None, "sources": [], "conflicting_sources": [],
            "decision": "No recorded thickness in instance or inherited type property sets. Geometry is not a fallback under this rule.",
        }
    values = [source["value_mm"] for source in sources]
    if len(sources) < 2 or max(values) - min(values) > TOLERANCE_MM:
        raise ValueError("Explicit thickness sources require review; expected at least two agreeing values.")
    outcomes = {100 - TOLERANCE_MM <= value <= 1000 + TOLERANCE_MM for value in values}
    if len(outcomes) != 1:
        raise ValueError("Thickness sources straddle the threshold; review required.")
    conflicts = []
    if quantity_depth is not None and abs(quantity_depth["value_mm"] - values[0]) > TOLERANCE_MM:
        conflicts.append({
            **quantity_depth,
            "reason": "Exported base depth conflicts with agreeing explicit thickness fields. Excluded under this mall-specific adjudication, not a universal IFC priority rule.",
        })
    return {
        "label": "PASS" if outcomes == {True} else "FAIL",
        "value_mm": values[0], "sources": sources, "conflicting_sources": conflicts,
        "quantity_depth": quantity_depth,
        "decision": "Explicit dimension and construction thickness values agree. Use recorded total/monolithic slab thickness; do not substitute a conflicting exported base depth.",
    }


def build_case() -> GroundTruth:
    import ifcopenshell
    import ifcopenshell.util.element
    import ifcopenshell.util.unit

    legacy = load(LEGACY_CASE_ID)
    model_path = legacy.resolve_ifc()
    model = ifcopenshell.open(str(model_path))
    scale_mm = ifcopenshell.util.unit.calculate_unit_scale(model) * 1000
    evidence = {}
    for slab in model.by_type("IfcSlab"):
        properties = ifcopenshell.util.element.get_psets(slab, psets_only=True, verbose=True)
        sources = []
        depth = None
        for pset_name, members in properties.items():
            for name, details in members.items():
                explicit = "thickness" in name.lower()
                if not explicit or not isinstance(details, dict):
                    continue
                value = details.get("value")
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                entity = model.by_id(details["id"])
                if getattr(entity, "Unit", None) is not None:
                    raise ValueError(f"{slab.GlobalId}: explicit property units need review before regeneration.")
                source = {"path": f"{pset_name}.{name}", "ifc_id": entity.id(),
                          "value": value, "value_mm": value * scale_mm,
                          "units": "IFC project length unit (no property override)"}
                sources.append(source)
        quantities = ifcopenshell.util.element.get_psets(slab, qtos_only=True)
        base = quantities.get("Qto_SlabBaseQuantities", {})
        if "Depth" in base:
            quantity = next(item for item in model.by_id(base["id"]).Quantities if item.Name == "Depth")
            if getattr(quantity, "Unit", None) is not None:
                raise ValueError(f"{slab.GlobalId}: base depth has explicit units; review required.")
            depth = {"path": "Qto_SlabBaseQuantities.Depth", "ifc_id": quantity.id(),
                     "value": base["Depth"], "value_mm": base["Depth"] * scale_mm,
                     "units": "IFC project length unit (no quantity override)"}
        try:
            decision = adjudicate(sorted(sources, key=lambda source: source["path"]), depth)
        except ValueError as exc:
            raise ValueError(f"{slab.GlobalId}: {exc}") from exc
        evidence[slab.GlobalId] = {"name": slab.Name, **decision}
    labels = {guid: item["label"] for guid, item in sorted(evidence.items())}
    counts = {label: list(labels.values()).count(label) for label in set(labels.values())}
    if counts != {"PASS": 100, "ALERT": 12}:
        raise ValueError(f"Mall population or evidence changed: {counts}. Review required.")
    digest = hashlib.sha256()
    with model_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    existing = GT_DIR / f"{CASE_ID}.json"
    if existing.exists() and load(existing).reference.get("ifc_sha256") != digest.hexdigest():
        raise ValueError("The IFC changed since reference v2 was recorded. Review it and create a new reference version.")
    return replace(
        legacy, case_id=CASE_ID, labels=labels, violations=[], provenance=dict(sorted(evidence.items())),
        source="slab_reference.py::build_case",
        notes="Version 2: 100 PASS, 12 ALERT, 0 FAIL. Property-based coverage/missing-data/false-positive control, not a violation-recall benchmark. Legacy version remains unchanged.",
        reference={
            "version": 2, "supersedes": LEGACY_CASE_ID, "review_date": "2026-09-07",
            "status": "evidence-backed project adjudication; not expert regulatory certification",
            "ifc_sha256": digest.hexdigest(), "length_scale_to_mm": scale_mm,
            "population": "All IfcSlab, including landings",
            "policy": "Recorded total/monolithic thickness within 100-1000 mm with 0.5 mm numerical tolerance; missing recorded thickness is ALERT. No geometry substitution.",
            "limitations": "Two agreeing properties may originate from the same authoring tool and are not independent expert judgements. Conflicting base-depth interpretation is specific to the audited mall export. Zero FAIL labels means violation recall cannot be evaluated.",
        },
    )


def main() -> None:
    case = build_case()
    destination = case.save()
    print(f"Saved {case.case_id}: {case.label_counts} to {destination}")


if __name__ == "__main__":
    main()