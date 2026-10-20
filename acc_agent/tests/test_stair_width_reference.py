import unittest

import ground_truth
from benchmark_audit import audit_case
from stair_width_reference import (ADJUDICATIONS, CASE_ID, RULE, SUBSET_CASE_ID, applicability_finding,
                                   expert_label, lane_widths, reconcile, verify_recorded)
from completion import scope_classes


def solid(lo, hi):
    return {"lo": lo, "hi": hi, "kind": "solid", "low": None}


def rail(lo, hi, low=None):
    return {"lo": lo, "hi": hi, "kind": "rail", "low": low}


def evidence(**overrides):
    base = {"predefined_type": "STRAIGHT_RUN_STAIR", "storey": "1st Storey", "spaces": [],
            "modelled_rise_mm": 3000, "riser_height_mm": 166.7}
    return {**base, **overrides}


def space(name, area=30.0, occupancy=None):
    return {"name": name, "area_m2": area, "occupancy": occupancy}


class LaneWidthTests(unittest.TestCase):
    def assertWidths(self, intervals, half, edge, balustrade):
        result = lane_widths(intervals, half)
        self.assertAlmostEqual(result["edge"], edge, places=6)
        self.assertAlmostEqual(result["balustrade"], balustrade, places=6)

    def test_open_flight_uses_its_edges(self):
        self.assertWidths([], 0.5, 1.0, 1.0)

    def test_walls_inside_the_flight_bound_the_width(self):
        self.assertWidths([solid(-0.5, -0.45), solid(0.45, 0.5)], 0.5, 0.9, 0.9)

    def test_wall_handrail_counts_only_beyond_80_mm(self):
        self.assertWidths([solid(-0.5, -0.45), rail(-0.45, -0.38), solid(0.45, 0.5)], 0.5, 0.9, 0.9)
        self.assertWidths([solid(-0.5, -0.45), rail(-0.45, -0.35), solid(0.45, 0.5)], 0.5, 0.8, 0.8)

    def test_balustrade_inset_differs_only_in_the_strict_reading(self):
        balustrade = rail(-0.5, -0.45, low=(-0.47, -0.462))
        self.assertWidths([balustrade], 0.5, 1.0, 0.962)

    def test_railing_within_the_flight_divides_it(self):
        self.assertWidths([rail(-1.45, -1.4), rail(-0.5, -0.45)], 1.5, 0.9, 0.9)

    def test_gaps_behind_a_railing_are_not_lanes(self):
        self.assertWidths([rail(-0.4, -0.35)], 0.5, 0.85, 0.85)


class ApplicabilityTests(unittest.TestCase):
    def test_exemptions_and_manual_checks(self):
        cases = [
            (evidence(spaces=[space("PLANT ROOM 4")]), "NA"),
            (evidence(spaces=[space("PRODUCTION AREA 5")]), "NA"),
            (evidence(spaces=[space("CINEMA 1")]), "MANUAL_CHECK"),
            (evidence(predefined_type="NOTDEFINED"), "MANUAL_CHECK"),
            (evidence(storey="3rd Storey Attic", spaces=[space("KITCHEN 7", 9.4, "single dwelling residential")]), "NA"),
            (evidence(storey="3rd Storey Attic", spaces=[space("Living Room 6", 32.6, "multi-unit residential")]), None),
            (evidence(storey="2nd Storey", spaces=[space("Living Room 8", 9.7, "multi-unit residential")]), None),
            (evidence(modelled_rise_mm=167), "NA"),
            (evidence(), None),
        ]
        for record, expected in cases:
            with self.subTest(record=record):
                self.assertEqual(applicability_finding(record)[0], expected)

    def test_expert_rows_map_to_labels_or_stop(self):
        self.assertEqual(expert_label("e.3.3.1", "fail", ""), "FAIL")
        self.assertEqual(expert_label("e.2.4", "exempt", ""), "NA")
        self.assertEqual(expert_label("e.2.4", "alert", "Requires manual checking."), "MANUAL_CHECK")
        for row in (("e.2.4", "alert", "Unreadable"), ("e.3.3.1", "exempt", ""), ("e.9", "pass", "")):
            with self.subTest(row=row), self.assertRaises(ValueError):
                expert_label(*row)

    def test_conflicts_need_an_adjudication(self):
        expert = {"clause": "e.3.3.1", "bucket": "pass", "message": "", "width_mm": 1000, "label": "PASS"}
        width = {"edge_reading_mm": 875, "balustrade_reading_mm": 875}
        with self.assertRaises(ValueError):
            reconcile("unreviewed-stair", expert, evidence(), width)
        record = reconcile("35pIuS$v94_8nIIWR7TtCO", expert, evidence(), width)
        self.assertEqual(record["label"], "FAIL")
        self.assertEqual(record["width_agreement"], "outcome conflict")


class StoredCaseTests(unittest.TestCase):
    def test_full_case_covers_every_stair_and_preserves_the_subset(self):
        case = ground_truth.load(CASE_ID)
        subset = ground_truth.load(SUBSET_CASE_ID)
        self.assertEqual(case.rule, RULE)
        self.assertEqual(scope_classes(case.rule), ["IfcStair"])
        self.assertEqual(case.unscored_ids, set())
        self.assertEqual(case.label_counts, {"FAIL": 23, "MANUAL_CHECK": 4, "NA": 6, "PASS": 26})
        self.assertEqual(set(case.labels), set(subset.labels) | subset.unscored_ids)
        changed = {guid for guid, label in subset.labels.items() if case.labels[guid] != label}
        self.assertEqual(changed, {guid for guid in ADJUDICATIONS if guid in subset.labels})
        self.assertEqual(subset.label_counts, {"FAIL": 22, "PASS": 27})
        self.assertEqual(case.reference["population"], 59)

    def test_recorded_evidence_matches_workbook_and_audit(self):
        from import_bca_gt import GT_COMPARISON_DIR
        from stair_width_reference import WORKBOOK

        case = ground_truth.load(CASE_ID)
        if not case.resolve_ifc().exists() or not (GT_COMPARISON_DIR / WORKBOOK).exists():
            self.skipTest("v8 IFC or expert workbook unavailable (the workbook is not distributed)")
        self.assertEqual(verify_recorded(case), [])
        result = audit_case(case)
        self.assertEqual(result["status"], "evidence-checked", result)
        self.assertEqual(result["ifc_anchors"], 59)


if __name__ == "__main__":
    unittest.main()
