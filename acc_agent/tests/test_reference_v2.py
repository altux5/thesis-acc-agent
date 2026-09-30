import unittest
from types import SimpleNamespace

import numpy as np

import ground_truth
from benchmark_audit import audit_case
from completion import scope_classes
from reference_v2 import (BUILDERS, LANDING_MAX_RISERS, _flight_count_decision, _tapered_width_at_500, expected_rule,
                          flight_steps, geometric_riser_count)


def flight(guid):
    return SimpleNamespace(GlobalId=guid)


def box_steps(risers, riser_mm=170.0, tread_mm=250.0, width_mm=1200.0, arrival_mm=None):
    """Closed boxes (metres) for a straight flight's steps; optional deeper arrival edge."""
    vertices, faces = [], []
    depths = [tread_mm] * risers
    if arrival_mm:
        depths[-1] = arrival_mm
    for index, depth in enumerate(depths):
        x0, z1 = sum(depths[:index]), riser_mm * (index + 1)
        corners = [(x, y, z) for z in (0.0, z1) for y in (0.0, width_mm) for x in (x0, x0 + depth)]
        base = len(vertices)
        vertices += [tuple(c / 1000 for c in corner) for corner in corners]
        faces += [[base + a, base + b, base + c] for a, b, c in (
            (4, 5, 7), (4, 7, 6), (0, 2, 3), (0, 3, 1), (0, 1, 5), (0, 5, 4),
            (2, 6, 7), (2, 7, 3), (0, 4, 6), (0, 6, 2), (1, 3, 7), (1, 7, 5))]
    return np.array(vertices), np.array(faces)


class StepGeometryTests(unittest.TestCase):
    def test_rectangular_treads_and_riser_bounds(self):
        geometry = flight_steps(*box_steps(5))
        self.assertEqual([round(s["depth_mm"]) for s in geometry["steps"]], [250] * 5)
        self.assertFalse(geometry["top_is_arrival"])
        self.assertEqual(geometric_riser_count(geometry, 170.0), (5, 6))

    def test_deeper_top_face_is_the_arrival_level(self):
        geometry = flight_steps(*box_steps(5, arrival_mm=400.0))
        self.assertTrue(geometry["top_is_arrival"])
        self.assertEqual(geometric_riser_count(geometry, 170.0), (5, 5))

    def test_tapered_tread_is_measured_500_mm_from_the_narrow_end(self):
        from shapely.geometry import Polygon

        wedge = Polygon([(0, 0), (1000, 0), (1000, 400), (0, 100)])
        self.assertAlmostEqual(_tapered_width_at_500(wedge), 250.0, delta=1.0)


class RiserDecisionTests(unittest.TestCase):
    def test_repeated_staircase_total_uses_flight_geometry(self):
        flights = [flight("a"), flight("b")]
        decisions = _flight_count_decision(flights, {"a": 21.0, "b": 21.0}, {"a": (9, 10), "b": (10, 11)})
        self.assertEqual({g: d["count"] for g, d in decisions.items()}, {"a": 10, "b": 11})
        self.assertTrue(all(d["source"].startswith("geometry") for d in decisions.values()))

    def test_per_flight_counts_within_bounds_are_kept(self):
        flights = [flight("a"), flight("b")]
        decisions = _flight_count_decision(flights, {"a": 9.0, "b": 9.0}, {"a": (9, 10), "b": (9, 10)})
        self.assertEqual({g: d["count"] for g, d in decisions.items()}, {"a": 9, "b": 9})

    def test_conflicting_outcomes_stop_generation(self):
        with self.assertRaisesRegex(ValueError, "Adjudicate"):
            _flight_count_decision([flight("a")], {"a": float(LANDING_MAX_RISERS)}, {"a": (20, 21)})


class StoredCaseTests(unittest.TestCase):
    def test_usable_2_cases_are_consistent_with_their_builders(self):
        for case_id in BUILDERS:
            with self.subTest(case=case_id):
                case = ground_truth.load(case_id)
                self.assertEqual(case.reference["tier"], "usable_2")
                self.assertTrue(scope_classes(case.rule))
                try:
                    expected = expected_rule(case_id)
                except FileNotFoundError:
                    self.skipTest("Authority template unavailable")
                self.assertEqual(case.rule, expected)
                if not case.resolve_ifc().is_file():
                    self.skipTest("IFC fixture unavailable")
                audit = audit_case(case)
                self.assertEqual(audit["issues"], [])
                self.assertEqual(audit["status"], "evidence-checked")


if __name__ == "__main__":
    unittest.main()
