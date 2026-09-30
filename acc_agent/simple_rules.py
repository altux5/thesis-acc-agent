"""Low-complexity BCA rules (Solihin & Eastman class 1-2) as ground-truth cases.

Why this module exists
----------------------
The advisors' EC3-2026 paper ("Assessing the viability of LLM agents for generating
reusable compliance checking functions") groups 16 rules by the Solihin and Eastman
(2015) complexity classes. Its headline result: **class 1 and class 2 rules are
tractable** (test F1_agg 0.24 and 0.40) while **class 3 rules that need auxiliary
geometric constructions collapse** (0.20 overall, near zero on 4 of 6 rules).

Our existing ``staircase_width_v8`` case (clause E.3.3.1, clear width) is squarely a
class-3 rule - which is why the agent struggles with it. This module adds the cheap
end of that ladder so the stateful-vs-stateless comparison has rules the agent can
actually solve, and so results can be reported per complexity class the way the
paper does.

The rules come from the **same BCA Approved Document (Acceptable Solutions V7.08)**
as the staircase-width case, so the thesis stays on one regulatory corpus:

===========================  ===  ==========================================
Clause                       Cls  Requirement
===========================  ===  ==========================================
E.3.4.1                      1    Riser height not more than 175 mm
E.3.4.2                      1    Tread width not less than 275/250/225 mm
E.3.5.2                      2    Max. 18 risers between landings
(BIM validation)             1    Slab thickness within a plausible range
(BIM validation)             2    Door/window on the same storey as its wall
===========================  ===  ==========================================

Difference from ``import_bca_gt.py``
------------------------------------
The four existing BCA cases carry *expert* ground truth shipped in the advisors'
comparison workbooks. No such labelling exists for these clauses, so the ground
truth is produced by a **coded reference implementation** instead. The paper
explicitly allows this ("These can be produced manually, through coded reference
implementations, or using existing rule-checking tools"), and it is what
``ground_truth.door_width_ground_truth`` already does for the door case.

The reference implementations below are deliberately *literal*: they read the value
the IFC stores and compare it against the threshold. They define the truth for a
case; they are never shown to the agent, which only ever sees ``rule_text()``.

Convention (same as the door-width case): an element whose value is **absent** is
*indeterminate*, not a violation. Float noise is absorbed by ``TOL_MM``.

Usage
-----
    python simple_rules.py --list                     # the rule catalogue
    python simple_rules.py --survey                   # violations per rule x model
    python simple_rules.py --generate                 # write ground_truth/*.json
    python simple_rules.py --generate --rule tread_width_e342
    python evaluate.py --case tread_width_e342__mall --repeats 3
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ground_truth import GroundTruth, resolve_model_path

BCA_ROOT = "bca_tests-main/bca_tests-main/BCATestCases"
TOL_MM = 0.5  # absorbs IFC float noise (a nominal 275 mm tread stored as 274.999...)


@dataclass(frozen=True)
class Model:
    """One IFC model plus the context a checker legitimately needs."""

    model_id: str
    ifc_rel: str
    building_type: str  # "industrial" | "residential" | "other" (drives E.3.4.2)
    split: str  # paper-style data split

    @property
    def building_phrase(self) -> str:
        return {
            "industrial": "an industrial building",
            "residential": "a residential building",
            "other": "a building that is neither industrial nor residential",
        }[self.building_type]


MODELS: dict[str, Model] = {
    m.model_id: m
    for m in (
        Model(
            "condo",
            f"{BCA_ROOT}/Headroom/Test Models/beta condo_uat1_v1.ifc",
            "residential",
            "train",
        ),
        Model(
            "stair_v8",
            f"{BCA_ROOT}/Staircase width/Test models/BCA_[E-3-3]_v8.ifc",
            "other",
            "train",
        ),
        Model(
            "planterbox",
            f"{BCA_ROOT}/Planter boxes/Test models/20240313_URA_Planterbox.ifc",
            "other",
            "train",
        ),
        Model(
            "mall",
            f"{BCA_ROOT}/Headroom/Test Models/beta mall_UAT1_v6.4.ifc",
            "other",
            "val",
        ),
        Model(
            "stair_obos",
            f"{BCA_ROOT}/Staircase width/Test models/BCA_[E-3-3]_v5-OBOS.ifc",
            "other",
            "val",
        ),
        Model(
            "scdf_5",
            f"{BCA_ROOT}/Location of exits & access to exits (EIB related)"
            "/Test Models/uat2_scdf_2.2.12_5_v0.ifc",
            "other",
            "test",
        ),
        Model(
            "scdf_3",
            f"{BCA_ROOT}/Location of exits & access to exits (EIB related)"
            "/Test Models/uat2_scdf_2.2.12_3_v1.ifc",
            "other",
            "test",
        ),
        Model(
            "stair_industrial",
            f"{BCA_ROOT}/Staircase width/Test models/E3.3 INDUSTRIAL.V2.ifc",
            "industrial",
            "test",
        ),
    )
}


# --------------------------------------------------------------------------- #
# IFC helpers used by the reference implementations
# --------------------------------------------------------------------------- #
def _psets(element) -> dict[str, dict]:
    import ifcopenshell.util.element as ue

    try:
        return ue.get_psets(element)
    except Exception:
        return {}


def _lookup(element, keys: tuple[str, ...], scale: float = 1.0) -> float | None:
    """First numeric property matching *keys* (``"Pset.Prop"`` or a bare ``"Prop"``).

    ``keys`` is tried in order, so the most trustworthy source wins. The result is
    multiplied by *scale* (used to normalise lengths to millimetres).
    """
    psets = _psets(element)
    for key in keys:
        pset_name, _, prop_name = key.rpartition(".")
        for pname, props in psets.items():
            if pset_name and pname != pset_name:
                continue
            value = props.get(prop_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            return float(value) * scale
    return None


def _mm_scale(model) -> float:
    """Millimetres per file length unit (1.0 for mm models, 1000.0 for metre models)."""
    import ifcopenshell.util.unit as uu

    return float(uu.calculate_unit_scale(model)) * 1000.0


def _host_element(filling_element):
    """The wall/slab an ``IfcDoor``/``IfcWindow`` fills, or ``None`` if it is orphaned."""
    for fills in getattr(filling_element, "FillsVoids", None) or ():
        opening = getattr(fills, "RelatingOpeningElement", None)
        for voids in getattr(opening, "VoidsElements", None) or ():
            host = getattr(voids, "RelatingBuildingElement", None)
            if host is not None:
                return host
    return None


def _storey(element):
    """The ``IfcBuildingStorey`` containing *element*, walking up aggregations."""
    import ifcopenshell.util.element as ue

    container = ue.get_container(element)
    while container is not None and not container.is_a("IfcBuildingStorey"):
        decomposes = getattr(container, "Decomposes", None) or ()
        container = decomposes[0].RelatingObject if decomposes else None
    return container


# --------------------------------------------------------------------------- #
# Element outcome labels
# --------------------------------------------------------------------------- #
# Every reference implementation labels the *whole* anchor population, not just
# the violations. The distinction that matters is ALERT: a flight whose riser
# height is recorded nowhere is not compliant, it is unjudgeable, and the fix is
# to correct the model. Collapsing it into "not a violation" is precisely what
# lets a checker score well by staying quiet, so it gets its own label.
PASS, FAIL, ALERT, MANUAL_CHECK, NA = "PASS", "FAIL", "ALERT", "MANUAL_CHECK", "NA"


def _threshold_label(
    value: float | None,
    *,
    ok: bool,
) -> str:
    """PASS/FAIL for a measured value, ALERT when the model never recorded one."""
    if value is None:
        return ALERT
    return PASS if ok else FAIL


# --------------------------------------------------------------------------- #
# Rule definition
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SimpleRule:
    """One low-complexity rule: the agent's prompt + the reference implementation."""

    rule_id: str
    complexity: int  # Solihin & Eastman class
    clause: str  # BCA paragraph, or "BIM validation"
    entity: str  # the IFC class violations are reported on
    summary: str  # the requirement in one or two sentences
    regulation: str = ""  # verbatim clause text, quoted for the agent
    guidance: str = ""  # modelling context the agent legitimately needs
    threshold_mm: float | None = None
    # Labels every anchor element of the rule: {GlobalId: PASS|FAIL|ALERT|NA|...}.
    reference: Callable[[object, Model], dict[str, str]] = None  # type: ignore[assignment]
    models: tuple[str, ...] = field(default_factory=lambda: tuple(MODELS))

    def rule_text(self, model: Model) -> str:
        parts = [self.summary.strip()]
        if self.regulation:
            parts.append(
                "\nRegulatory text (the authoritative clause - use it to interpret "
                "the requirement; you must still work out how to read it out of the "
                "IFC):\n" + self.regulation.strip()
            )
        if self.guidance:
            parts.append("\n" + self.guidance.strip().format(model=model))
        parts.append(
            f"\nReport the GlobalId of every element (modelled as {self.entity}) "
            "that does NOT satisfy this requirement."
        )
        return "\n".join(parts)


# --------------------------------------------------------------------------- #
# class 1 - E.3.4.1 riser height
# --------------------------------------------------------------------------- #
RISER_MAX_MM = 175.0
RISER_KEYS = (
    "Pset_StairFlightCommon.RiserHeight",
    "Qto_StairFlightBaseQuantities.RiserHeight",
    "Dimensions.Actual Riser Height",
)


def _riser_height_violations(model, _ctx: Model) -> dict[str, str]:
    scale = _mm_scale(model)
    out: dict[str, str] = {}
    for flight in model.by_type("IfcStairFlight"):
        height = _lookup(flight, RISER_KEYS, scale)
        out[flight.GlobalId] = _threshold_label(
            height, ok=height is not None and height <= RISER_MAX_MM + TOL_MM
        )
    return out


# --------------------------------------------------------------------------- #
# class 1 - E.3.4.2 tread width (threshold depends on the building type)
# --------------------------------------------------------------------------- #
TREAD_MIN_MM = {"residential": 275.0, "industrial": 250.0, "other": 275.0}
TREAD_KEYS = (
    "Pset_StairFlightCommon.TreadLength",
    "Qto_StairFlightBaseQuantities.TreadLength",
    "Dimensions.Actual Tread Depth",
)


def _tread_width_violations(model, ctx: Model) -> dict[str, str]:
    scale = _mm_scale(model)
    minimum = TREAD_MIN_MM[ctx.building_type]
    out: dict[str, str] = {}
    for flight in model.by_type("IfcStairFlight"):
        width = _lookup(flight, TREAD_KEYS, scale)
        out[flight.GlobalId] = _threshold_label(
            width, ok=width is not None and width >= minimum - TOL_MM
        )
    return out


# --------------------------------------------------------------------------- #
# class 2 - E.3.5.2 intermediate landing every 18 risers
# --------------------------------------------------------------------------- #
RISERS_PER_FLIGHT_MAX = 18
RISER_COUNT_KEYS = (
    "Pset_StairFlightCommon.NumberOfRiser",
    "Pset_StairFlightCommon.NumberOfRisers",
    "Dimensions.Actual Number of Risers",
)


def _landing_interval_violations(model, _ctx: Model) -> dict[str, str]:
    out: dict[str, str] = {}
    for flight in model.by_type("IfcStairFlight"):
        count = _lookup(flight, RISER_COUNT_KEYS)
        if count is None:
            count = getattr(flight, "NumberOfRisers", None) or getattr(
                flight, "NumberOfRiser", None
            )
        if count is None:
            out[flight.GlobalId] = ALERT  # riser count recorded nowhere
            continue
        out[flight.GlobalId] = (
            FAIL if int(count) > RISERS_PER_FLIGHT_MAX else PASS
        )
    return out


# --------------------------------------------------------------------------- #
# class 1 - slab thickness (generic BIM validation)
# --------------------------------------------------------------------------- #
SLAB_MIN_MM, SLAB_MAX_MM = 100.0, 1000.0
SLAB_KEYS = (
    "Qto_SlabBaseQuantities.Depth",
    "SGPset_SlabDimension.Thickness",
    "Dimensions.Thickness",
    "Construction.Thickness",
    "Pset_SlabCommon.Thickness",
)


def _slab_thickness_violations(model, _ctx: Model) -> dict[str, str]:
    scale = _mm_scale(model)
    out: dict[str, str] = {}
    for slab in model.by_type("IfcSlab"):
        thickness = _lookup(slab, SLAB_KEYS, scale)
        out[slab.GlobalId] = _threshold_label(
            thickness,
            ok=(
                thickness is not None
                and SLAB_MIN_MM - TOL_MM <= thickness <= SLAB_MAX_MM + TOL_MM
            ),
        )
    return out


# --------------------------------------------------------------------------- #
# class 2 - doors/windows must sit in their host wall's storey
# --------------------------------------------------------------------------- #
def _doors_windows_storey_violations(model, _ctx: Model) -> dict[str, str]:
    out: dict[str, str] = {}
    for element in model.by_type("IfcDoor") + model.by_type("IfcWindow"):
        host = _host_element(element)
        if host is None:
            out[element.GlobalId] = FAIL  # orphan: no host element at all
            continue
        own, host_storey = _storey(element), _storey(host)
        if own is None or host_storey is None:
            out[element.GlobalId] = ALERT  # a storey assignment is missing
            continue
        out[element.GlobalId] = (
            PASS if own.GlobalId == host_storey.GlobalId else FAIL
        )
    return out


RULES: tuple[SimpleRule, ...] = (
    SimpleRule(
        rule_id="riser_height_e341",
        complexity=1,
        clause="e.3.4.1",
        entity="IfcStairFlight",
        summary=f"The height of a riser must not be more than {RISER_MAX_MM:g} mm.",
        regulation=(
            "BCA Approved Document (Acceptable Solutions V7.08) - E.3.4 Risers and "
            "treads:\n"
            "E.3.4.1 The height of a riser shall not be more than 175 mm. (see "
            "Figure E.3.4.2(a) for measurement of \u201criser\u201d)"
        ),
        guidance=(
            "The riser height is the vertical rise of one step of a stair flight. A "
            "flight whose riser height is not recorded anywhere in the model cannot "
            "be judged: label it ALERT, and do NOT report it as a violation."
        ),
        threshold_mm=RISER_MAX_MM,
        reference=_riser_height_violations,
    ),
    SimpleRule(
        rule_id="tread_width_e342",
        complexity=1,
        clause="e.3.4.2",
        entity="IfcStairFlight",
        summary=(
            "The width of a tread must not be less than the minimum required for "
            "this type of building."
        ),
        regulation=(
            "BCA Approved Document (Acceptable Solutions V7.08) - E.3.4 Risers and "
            "treads:\n"
            "E.3.4.2 The width of a tread of a staircase (see Figure E.3.4.2(a) for "
            "measurement of \u201ctread\u201d) shall not be less than:\n"
            "  a) 225 mm, if the staircase is in a residential unit within a "
            "residential building;\n"
            "  b) 250 mm, if the staircase is in an industrial building; or\n"
            "  c) 275 mm, if the staircase is in any other type of building, "
            "including common staircases in a residential building."
        ),
        guidance=(
            "This model is {model.building_phrase}, and all of its staircases are "
            "common staircases - none of them sits inside a residential unit. A "
            "flight whose tread width is not recorded anywhere in the model cannot "
            "be judged: label it ALERT, and do NOT report it as a violation."
        ),
        reference=_tread_width_violations,
    ),
    SimpleRule(
        rule_id="landing_interval_e352",
        complexity=2,
        clause="e.3.5.2",
        entity="IfcStairFlight",
        summary=(
            f"Except for spiral staircases, no run of more than "
            f"{RISERS_PER_FLIGHT_MAX} risers may occur without an intermediate "
            f"landing."
        ),
        regulation=(
            "BCA Approved Document (Acceptable Solutions V7.08) - E.3.5 Landing:\n"
            "E.3.5.1 A landing shall be provided at every floor level and door "
            "opening.\n"
            "E.3.5.2 Except for spiral staircases, an intermediate landing shall be "
            "provided in between floor levels at intervals of not more than 18 "
            "risers."
        ),
        guidance=(
            "A landing separates one stair flight from the next, so a flight that "
            "itself contains more than 18 risers runs past the required landing "
            "interval. A flight whose riser count is not recorded cannot be judged: "
            "label it ALERT, and do NOT report it as a violation."
        ),
        reference=_landing_interval_violations,
    ),
    SimpleRule(
        rule_id="slab_thickness",
        complexity=1,
        clause="BIM validation",
        entity="IfcSlab",
        summary=(
            f"Every slab must have a thickness between {SLAB_MIN_MM:g} mm and "
            f"{SLAB_MAX_MM:g} mm inclusive."
        ),
        guidance=(
            "Slab thickness is stored under different names depending on the "
            "authoring tool: a base-quantity depth, a dimension property, or a "
            "vendor-specific property set. A slab with no recorded thickness cannot "
            "be judged: label it ALERT, and do NOT report it as a violation."
        ),
        threshold_mm=SLAB_MAX_MM,
        reference=_slab_thickness_violations,
    ),
    SimpleRule(
        rule_id="doors_windows_storey",
        complexity=2,
        clause="BIM validation",
        entity="IfcDoor or IfcWindow",
        summary=(
            "Every door and window must be assigned to the same building storey as "
            "the wall it is placed in, and must not be an orphan (a door or window "
            "with no host element at all)."
        ),
        guidance=(
            "A door or window fills an opening that voids a host element - its wall. "
            "It violates the rule when (a) it has no host element, or (b) the storey "
            "containing it differs from the storey containing its host. If either "
            "storey cannot be determined the element cannot be judged: label it "
            "ALERT, and do NOT report it as a violation."
        ),
        reference=_doors_windows_storey_violations,
    ),
)

BY_ID: dict[str, SimpleRule] = {r.rule_id: r for r in RULES}


# --------------------------------------------------------------------------- #
# Case generation
# --------------------------------------------------------------------------- #
# Coded references replaced by reference_v2.py, which owns the plain case IDs.
SUPERSEDED = {"landing_interval_e352__mall", "landing_interval_e352__scdf_5", "landing_interval_e352__stair_v8",
              "tread_width_e342__mall"}


def case_id(rule_id: str, model_id: str) -> str:
    name = f"{rule_id}__{model_id}"
    return f"{name}_deprecated_v1" if name in SUPERSEDED else name


def _population(model, rule: SimpleRule) -> int:
    if rule.entity.startswith("IfcDoor"):
        return len(model.by_type("IfcDoor")) + len(model.by_type("IfcWindow"))
    return len(model.by_type(rule.entity))


def build_case(rule: SimpleRule, model_id: str) -> GroundTruth:
    """Run *rule*'s reference implementation on *model_id* and wrap it as ground truth."""
    if rule.rule_id == "slab_thickness" and model_id == "mall":
        from slab_reference import build_case as build_mall_reference

        return build_mall_reference()
    import ifcopenshell

    ctx = MODELS[model_id]
    ifc_abs = resolve_model_path(ctx.ifc_rel)
    if not ifc_abs.exists():
        raise FileNotFoundError(ifc_abs)
    model = ifcopenshell.open(str(ifc_abs))
    labels = dict(sorted(rule.reference(model, ctx).items()))
    violations = sorted(g for g, label in labels.items() if label == FAIL)
    total = _population(model, rule)
    if total == 0:
        raise ValueError(
            f"{rule.rule_id} is degenerate on {model_id}: the model contains no "
            f"{rule.entity} elements."
        )
    counts: dict[str, int] = {}
    for label in labels.values():
        counts[label] = counts.get(label, 0) + 1
    return GroundTruth(
        case_id=case_id(rule.rule_id, model_id),
        rule=rule.rule_text(ctx),
        ifc_path=ctx.ifc_rel,
        threshold_mm=rule.threshold_mm,
        tolerance_mm=TOL_MM,
        violations=violations,
        labels=labels,
        complexity=rule.complexity,
        clause=rule.clause,
        source=f"simple_rules.py::{rule.rule_id}::{model_id}",
        notes=(
            f"Solihin & Eastman class {rule.complexity}. Reference implementation on "
            f"{Path(ctx.ifc_rel).name} ({ctx.building_type}, split={ctx.split}): "
            f"{len(labels)} anchor {rule.entity} elements labelled "
            f"{dict(sorted(counts.items()))}."
        ),
    )


def survey() -> list[dict]:
    """Label breakdown for every (rule, model) pair."""
    import ifcopenshell

    rows = []
    for rule in RULES:
        for model_id in rule.models:
            ctx = MODELS[model_id]
            ifc_abs = resolve_model_path(ctx.ifc_rel)
            if not ifc_abs.exists():
                rows.append({"rule": rule.rule_id, "model": model_id, "missing": True})
                continue
            model = ifcopenshell.open(str(ifc_abs))
            population = _population(model, rule)
            if population == 0:
                continue  # degenerate: nothing of this entity type in the model
            labels = (
                build_case(rule, model_id).labels
                if rule.rule_id == "slab_thickness" and model_id == "mall"
                else rule.reference(model, ctx)
            )
            counts: dict[str, int] = {}
            for label in labels.values():
                counts[label] = counts.get(label, 0) + 1
            rows.append(
                {
                    "rule": rule.rule_id,
                    "class": rule.complexity,
                    "model": model_id,
                    "split": ctx.split,
                    "violations": counts.get(FAIL, 0),
                    "alerts": counts.get(ALERT, 0),
                    "population": population,
                    "labels": dict(sorted(counts.items())),
                    "missing": False,
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List the rule catalogue.")
    parser.add_argument(
        "--survey", action="store_true", help="Violation counts per rule x model."
    )
    parser.add_argument(
        "--generate", action="store_true", help="Write ground_truth/*.json cases."
    )
    parser.add_argument("--rule", type=str, default=None, help="Restrict to one rule.")
    parser.add_argument(
        "--model", type=str, default=None, help="Restrict to one model id."
    )
    parser.add_argument(
        "--skip-empty",
        action="store_true",
        help="Only write cases that have something to find. Without this flag the "
        "fully compliant models are written too, as false-positive controls.",
    )
    args = parser.parse_args()

    if args.list:
        for rule in RULES:
            print(
                f"{rule.rule_id:<24} class {rule.complexity}  {rule.clause:<16}"
                f"{rule.entity}"
            )
            print(f"    {rule.summary}")
        return

    if args.survey:
        print(
            f"{'rule':<24}{'cls':<5}{'model':<18}{'split':<7}"
            f"{'fail':>6}{'alert':>7}{'pop':>7}"
        )
        for row in survey():
            if row["missing"]:
                print(f"{row['rule']:<24}{'':<5}{row['model']:<18}MISSING")
                continue
            print(
                f"{row['rule']:<24}{row['class']:<5}{row['model']:<18}"
                f"{row['split']:<7}{row['violations']:>6}{row['alerts']:>7}"
                f"{row['population']:>7}"
            )
        return

    if not args.generate:
        parser.error("choose one of --list / --survey / --generate")

    rules = [r for r in RULES if args.rule in (None, r.rule_id)]
    if not rules:
        raise SystemExit(f"No rule matches --rule {args.rule!r}")
    written = 0
    for rule in rules:
        for model_id in rule.models:
            if args.model not in (None, model_id):
                continue
            try:
                gt = build_case(rule, model_id)
            except ValueError as exc:
                print(f"skip   {case_id(rule.rule_id, model_id)} ({exc})")
                continue
            if args.skip_empty and not gt.violations:
                print(f"skip   {gt.case_id} (no violations)")
                continue
            out = gt.save()
            written += 1
            print(
                f"wrote  {gt.case_id:<38}{len(gt.violations):>4} fail / "
                f"{gt.anchor_count:>4} anchors  {gt.label_counts}"
            )
    print(f"\n{written} case(s) written. Run e.g.:")
    print("  python evaluate.py --case tread_width_e342__mall --repeats 3")


if __name__ == "__main__":
    main()
