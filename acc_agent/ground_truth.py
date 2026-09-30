"""Ground-truth cases for scoring the agent.

A :class:`GroundTruth` pairs a rule + IFC model with the known-correct set of
violating GlobalIds, so a run's reported violations can be scored against it
(see :mod:`scoring`). Cases are stored as JSON under ``ground_truth/`` and can
be regenerated deterministically from the IFC model — for the door-width rule
the truth is read straight from each ``IfcDoor.OverallWidth``.

A case may also carry ``labels``: the rule's *anchor elements* (every element
the rule judges) mapped to PASS / FAIL / ALERT / MANUAL_CHECK / NA. That is
strictly more information than the violation set — it records what a compliant
element is, and separates "exempt" and "the model does not say" from "fine" —
and it is what union accuracy in :mod:`scoring` needs. ``violations`` stays as
the FAIL slice so older cases and the binary metric keep working unchanged.
Explicit ``annotated_subset`` references label only an authored subset and record
the remaining IFC anchors as ``unscored_ids``, never inferred PASS or NA labels.

The tolerance matters: stored widths carry floating-point noise (a nominal
900 mm door is exported as 899.999999… mm), so a door only counts as a real
violation when it is more than ``tolerance_mm`` below the threshold. This mirrors
``inspect_doors.py`` and keeps borderline doors out of the ground truth, which is
exactly where models tend to over-flag.

Usage (regenerate the default door case):

    python ground_truth.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = PROJECT_DIR.parent
GT_DIR = PROJECT_DIR / "ground_truth"

# A case ID names the check and never changes; the current reference owns it. A
# superseded reference keeps its file as ``<case_id>_deprecated_v<N>`` (oldest N=1).
DEPRECATED_MARK = "_deprecated_v"
# IDs recorded before this scheme (ledger recording_version < 4) and their current names.
RENAMED_BEFORE_2026_09_30 = {
    "slab_thickness__mall": "slab_thickness__mall_deprecated_v1",
    "slab_thickness__mall_v2": "slab_thickness__mall",
    "staircase_width_v8": "staircase_width_v8_deprecated_v1",
    "staircase_width_v8_full": "staircase_width_v8",
    "landing_interval_e352__stair_v8": "landing_interval_e352__stair_v8_deprecated_v1",
    "landing_interval_e352__stair_v8_v2": "landing_interval_e352__stair_v8",
    "landing_interval_e352__mall": "landing_interval_e352__mall_deprecated_v1",
    "landing_interval_e352__mall_v2": "landing_interval_e352__mall",
    "landing_interval_e352__scdf_5": "landing_interval_e352__scdf_5_deprecated_v1",
    "landing_interval_e352__scdf_5_v2": "landing_interval_e352__scdf_5",
    "tread_width_e342__mall": "tread_width_e342__mall_deprecated_v1",
    "tread_width_e342__mall_v2": "tread_width_e342__mall",
    "exit_requirements_v0": "exit_requirements__scdf_5_deprecated_v1",
    "exit_requirements__scdf_5_v2": "exit_requirements__scdf_5",
    "exit_requirements__scdf_3_v2": "exit_requirements__scdf_3",
    "planter_box_gfa": "planter_box_gfa_deprecated_v1",
    "planter_box_gfa_v2": "planter_box_gfa",
}


def is_deprecated(case_id: str) -> bool:
    return DEPRECATED_MARK in case_id


# The BCA test-case drops are untracked bulk data: they may sit directly at the
# workspace root or inside the gitignored ``gitignore/`` folder.
MODEL_ROOTS = (WORKSPACE_ROOT, WORKSPACE_ROOT / "gitignore")

DEFAULT_IFC_REL = (
    "bca_tests-main/bca_tests-main/BCATestCases/"
    "Planter boxes/Test models/20240313_URA_Planterbox.ifc"
)
DEFAULT_RULE = (
    "Every door (IfcDoor) in the model must have a clear width of at least 900 mm. "
    "For this first check, use the door's OverallWidth attribute as the width. "
    "Report every door whose width is below 900 mm."
)


def resolve_model_path(rel: str | Path) -> Path:
    """Absolute path to a test model given a workspace-relative path."""
    p = Path(rel)
    if p.is_absolute():
        return p
    for root in MODEL_ROOTS:
        candidate = root / p
        if candidate.exists():
            return candidate
    return MODEL_ROOTS[0] / p


@dataclass
class GroundTruth:
    """A scored case: rule + model + the known set of violating GlobalIds."""

    case_id: str
    rule: str
    ifc_path: str  # relative to the workspace root
    threshold_mm: float | None = None
    tolerance_mm: float | None = None
    violations: list[str] = field(default_factory=list)
    notes: str = ""
    clause: str = ""
    source: str = ""
    # Per-element labelling of the rule's *anchor* elements: every element the
    # rule is about, mapped to PASS / FAIL / ALERT / MANUAL_CHECK / NA (see
    # ``scoring.LABELS``). This is what makes "the agent never looked at it"
    # measurable; ``violations`` is only the FAIL slice of it. Empty for legacy
    # cases, which are then scored on the binary metric alone.
    labels: dict[str, str] = field(default_factory=dict)
    # Solihin & Eastman complexity class of the rule (1-3), when known. Stored on
    # the case rather than inferred from its id, so difficulty can be reported
    # without a lookup table that has to be kept in sync.
    complexity: int | None = None
    reference: dict = field(default_factory=dict)
    provenance: dict[str, dict] = field(default_factory=dict)

    @property
    def unscored_ids(self) -> set[str]:
        """Known IFC anchors without annotations, explicitly excluded from scoring."""
        scope = self.reference.get("evaluation_scope", "full_population")
        if scope == "full_population":
            if self.reference.get("unscored_ids"):
                raise ValueError("Unscored IDs require an explicit annotated_subset policy.")
            return set()
        if scope != "annotated_subset":
            raise ValueError(f"Unsupported reference evaluation scope: {scope}")
        identifiers = self.reference.get("unscored_ids")
        if (not self.labels or not isinstance(identifiers, list)
                or any(not isinstance(guid, str) or not guid.strip() for guid in identifiers)):
            raise ValueError("Annotated subsets require labels and an explicit unscored ID list.")
        excluded = set(identifiers)
        if len(excluded) != len(identifiers) or excluded & (set(self.labels) | set(self.violations)):
            raise ValueError("Unscored IDs must be unique and disjoint from authored references.")
        if self.reference.get("population") != len(self.labels) + len(excluded):
            raise ValueError("Reference population must equal labelled plus unscored anchors.")
        return excluded

    @property
    def violation_set(self) -> set[str]:
        """The FAIL set, taken from the labelling when the case carries one."""
        if self.labels:
            return {guid for guid, label in self.labels.items() if label == "FAIL"}
        return set(self.violations)

    @property
    def anchor_count(self) -> int:
        """Number of authored reference labels, which may cover only a subset."""
        return len(self.labels)

    @property
    def label_counts(self) -> dict[str, int]:
        """Population per label, e.g. ``{"PASS": 27, "FAIL": 22, "ALERT": 3}``."""
        counts: dict[str, int] = {}
        for label in self.labels.values():
            counts[label] = counts.get(label, 0) + 1
        return dict(sorted(counts.items()))

    def resolve_ifc(self) -> Path:
        """Absolute path to the IFC model, resolved against the workspace root."""
        return resolve_model_path(self.ifc_path)

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "rule": self.rule,
            "ifc_path": self.ifc_path,
            "complexity": self.complexity,
            "threshold_mm": self.threshold_mm,
            "tolerance_mm": self.tolerance_mm,
            "violations": self.violations,
            "labels": self.labels,
            "notes": self.notes,
            "clause": self.clause,
            "source": self.source,
            "reference": self.reference,
            "provenance": self.provenance,
        }

    def save(self, path: Path | None = None) -> Path:
        path = path or (GT_DIR / f"{self.case_id}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2), encoding="utf-8")
        return path


def load(path: str | Path) -> GroundTruth:
    """Load a ground-truth case from a JSON file (or a bare case id under GT_DIR)."""
    p = Path(path)
    if not p.exists() and not p.suffix:
        p = GT_DIR / f"{p.name}.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    threshold = data.get("threshold_mm")
    tolerance = data.get("tolerance_mm")
    complexity = data.get("complexity")
    labels = {
        str(guid): str(label) for guid, label in (data.get("labels") or {}).items()
    }
    return GroundTruth(
        case_id=data["case_id"],
        rule=data["rule"],
        ifc_path=data["ifc_path"],
        threshold_mm=float(threshold) if threshold is not None else None,
        tolerance_mm=float(tolerance) if tolerance is not None else None,
        violations=list(data.get("violations", [])),
        labels=labels,
        complexity=int(complexity) if complexity is not None else None,
        notes=data.get("notes", ""),
        clause=data.get("clause", ""),
        source=data.get("source", ""),
        reference=dict(data.get("reference") or {}),
        provenance=dict(data.get("provenance") or {}),
    )


def door_width_ground_truth(
    ifc_path: Path,
    *,
    case_id: str = "door_width_planterbox",
    rule: str = DEFAULT_RULE,
    threshold_mm: float = 900.0,
    tolerance_mm: float = 0.5,
    ifc_rel: str | None = None,
) -> GroundTruth:
    """Derive the door-width ground truth directly from ``IfcDoor.OverallWidth``.

    A door is a violation when its width is more than ``tolerance_mm`` below the
    threshold. A door with no stored width is labelled ALERT: the model is
    incomplete, which is a finding in its own right rather than a silent pass.
    """
    import ifcopenshell

    model = ifcopenshell.open(str(ifc_path))
    cutoff = threshold_mm - tolerance_mm
    labels: dict[str, str] = {}
    for door in model.by_type("IfcDoor"):
        if door.OverallWidth is None:
            labels[door.GlobalId] = "ALERT"
        elif door.OverallWidth < cutoff:
            labels[door.GlobalId] = "FAIL"
        else:
            labels[door.GlobalId] = "PASS"
    violations = sorted(g for g, lab in labels.items() if lab == "FAIL")
    counts: dict[str, int] = {}
    for label in labels.values():
        counts[label] = counts.get(label, 0) + 1
    return GroundTruth(
        case_id=case_id,
        rule=rule,
        ifc_path=ifc_rel or DEFAULT_IFC_REL,
        threshold_mm=threshold_mm,
        tolerance_mm=tolerance_mm,
        violations=violations,
        labels=dict(sorted(labels.items())),
        complexity=1,
        notes=(
            f"Auto-generated from {Path(ifc_path).name}: IfcDoor with "
            f"OverallWidth < {cutoff:g} mm ({threshold_mm:g} mm threshold, "
            f"{tolerance_mm:g} mm float-noise tolerance). "
            f"{len(labels)} anchor elements, {dict(sorted(counts.items()))}."
        ),
    )


def main() -> None:
    ifc_abs = resolve_model_path(DEFAULT_IFC_REL)
    if not ifc_abs.exists():
        raise SystemExit(f"IFC file not found: {ifc_abs}")
    gt = door_width_ground_truth(ifc_abs)
    out = gt.save()
    print(
        f"Wrote {len(gt.violations)} violating GlobalIds "
        f"({gt.anchor_count} anchors, {gt.label_counts}) to {out}"
    )
    for guid in gt.violations:
        print(f"  {guid}")


if __name__ == "__main__":
    main()
