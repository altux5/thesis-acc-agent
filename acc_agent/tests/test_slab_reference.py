import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import ground_truth
from slab_reference import adjudicate, build_case


def source(path, value):
    return {"path": path, "value_mm": value}


class SlabReferenceTests(unittest.TestCase):
    def test_explicit_agreement_records_conflicting_depth(self):
        result = adjudicate([source("Dimensions.Total Thickness", 200), source("Construction.Monolithic Thickness", 200)], source("Qto.Depth", 1175))
        self.assertEqual(result["label"], "PASS")
        self.assertEqual(result["conflicting_sources"][0]["value_mm"], 1175)

    def test_missing_property_is_alert_not_geometry_pass(self):
        self.assertEqual(adjudicate([])["label"], "ALERT")

    def test_conflicting_or_uncorroborated_values_stop_generation(self):
        for sources, depth in [([source("a", 200), source("b", 300)], None), ([source("a", 200)], None), ([], source("Depth", 200))]:
            with self.subTest(sources=sources), self.assertRaises(ValueError):
                adjudicate(sources, depth)

    def test_out_of_range_is_not_forced_to_pass(self):
        self.assertEqual(adjudicate([source("a", 99), source("b", 99)])["label"], "FAIL")

    def test_reference_metadata_round_trips(self):
        case = ground_truth.GroundTruth("test", "rule", "model.ifc", reference={"version": 2}, provenance={"guid": {"label": "PASS"}})
        with TemporaryDirectory() as directory:
            path = case.save(Path(directory) / "case.json")
            loaded = ground_truth.load(path)
        self.assertEqual(loaded.reference, case.reference)
        self.assertEqual(loaded.provenance, case.provenance)

    def test_live_mall_evidence_and_legacy_preservation(self):
        legacy_path = ground_truth.GT_DIR / "slab_thickness__mall.json"
        legacy = ground_truth.load(legacy_path)
        if not legacy.resolve_ifc().exists():
            self.skipTest("Mall IFC is not distributed with the repository")
        original = legacy_path.read_bytes()
        corrected = build_case()
        self.assertEqual(corrected.label_counts, {"ALERT": 12, "PASS": 100})
        self.assertEqual(len(corrected.provenance), 112)
        self.assertEqual(legacy_path.read_bytes(), original)
        self.assertEqual(legacy.label_counts, {"ALERT": 35, "FAIL": 15, "PASS": 62})
        for guid in legacy.violation_set:
            self.assertEqual(corrected.provenance[guid]["value_mm"], 200)
            self.assertTrue(corrected.provenance[guid]["conflicting_sources"])

    def test_catalog_generation_routes_to_version_two(self):
        from unittest.mock import patch
        import simple_rules
        from gui import App, PILOTS, GROUP_SIMPLE_1

        expected = ground_truth.GroundTruth("slab_thickness__mall_v2", "rule", "model.ifc", complexity=1)
        with patch("slab_reference.build_case", return_value=expected):
            actual = simple_rules.build_case(simple_rules.BY_ID["slab_thickness"], "mall")
        self.assertIs(actual, expected)
        self.assertIn(actual.case_id, PILOTS)
        self.assertNotIn("slab_thickness__mall", PILOTS)
        self.assertEqual(App._group_of(actual), GROUP_SIMPLE_1)


if __name__ == "__main__":
    unittest.main()