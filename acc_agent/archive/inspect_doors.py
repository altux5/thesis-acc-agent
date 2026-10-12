# Archived 2026-10-01, file otherwise unchanged. Early helper from the door-width warm-up;
# nothing imports it. ground_truth.door_width_ground_truth() now builds that reference.
# To run it again, copy it back to acc_agent/ (it imports ground_truth from there).
"""Ground-truth helper: list every IfcDoor and its OverallWidth.

Reads the width directly from each IfcDoor, independent of the agent, so it can
serve as a reference for the door-width check.

Usage:
    python acc_agent/inspect_doors.py [path-to-ifc] [threshold_mm]
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import ifcopenshell

from ground_truth import resolve_model_path

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_IFC = resolve_model_path(
    "bca_tests-main/bca_tests-main/BCATestCases/"
    "Planter boxes/Test models/20240313_URA_Planterbox.ifc"
)

# Treat anything within this many mm of the threshold as "at the threshold"
# (the stored widths carry floating-point noise, e.g. 899.999999999 == 900).
TOL = 0.5


def main() -> None:
    ifc_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_IFC
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 900.0

    model = ifcopenshell.open(str(ifc_path))
    doors = model.by_type("IfcDoor")

    rows = []
    for d in doors:
        w = d.OverallWidth
        rows.append((w if w is not None else float("nan"), d.GlobalId, d.Name or ""))
    rows.sort(key=lambda r: (r[0] != r[0], r[0]))  # NaN sorts last

    print(f"{'width_mm':>9}  {'verdict':<5}  guid                       name")
    print("-" * 90)
    fails = []
    strict_below = 0
    for w, guid, name in rows:
        is_nan = w != w
        if is_nan:
            verdict = "N/A"
        elif w < threshold - TOL:
            verdict = "FAIL"
            fails.append((w, guid, name))
        else:
            verdict = "PASS"
        if not is_nan and w < threshold:
            strict_below += 1
        wtxt = "n/a" if is_nan else f"{w:.1f}"
        print(f"{wtxt:>9}  {verdict:<5}  {guid}  {name}")

    dist = Counter(round(w) for w, _, _ in rows if w == w)
    print("-" * 90)
    print("Width distribution (nominal mm -> count):")
    for w in sorted(dist):
        print(f"  {w:>5} mm : {dist[w]}")

    print("-" * 90)
    print(f"Total doors:                         {len(doors)}")
    print(f"Threshold:                           {threshold:.0f} mm")
    print(f"NON-COMPLIANT (> {TOL:.1f} mm below):       {len(fails)}")
    print(f"  strictly < {threshold:.0f} (incl. ~900 noise): {strict_below}")
    print(f"  borderline ~{threshold:.0f} (float noise):     {strict_below - len(fails)}")
    print("\nNon-compliant GUIDs:")
    for w, guid, name in fails:
        print(f"  {guid}  ({w:.1f} mm)  {name}")


if __name__ == "__main__":
    main()
