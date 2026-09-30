import unittest
from unittest.mock import patch

from benchmark_audit import audit_case, structural_issues
from ground_truth import GroundTruth, load


class BenchmarkAuditTests(unittest.TestCase):
    def test_unparseable_unknown_is_not_deliberate_abstention(self):
        from scoring import ParsedVerdict, score

        unfinished = score(ParsedVerdict("UNKNOWN", set(), False), {"one"})
        abstained = score(ParsedVerdict("UNKNOWN", set(), True, reason="Missing data"), {"one"})
        self.assertFalse(unfinished.abstained)
        self.assertTrue(abstained.abstained)

    def test_label_and_violation_inconsistency_detected(self):
        case = GroundTruth("test", "rule", "none", labels={"one": "FAIL"})
        self.assertTrue(structural_issues(case))

    def test_explicit_unscored_stairs_do_not_reduce_reference_agreement(self):
        from scoring import ParsedVerdict, score

        labels = {"labelled": "FAIL", "unlabelled": "FAIL"}
        parsed = ParsedVerdict("NON_COMPLIANT", set(labels), True, labels=labels)
        result = score(parsed, {"labelled"}, {"labelled": "FAIL"},
                       unscored_ids={"unlabelled"})
        self.assertEqual(result.f1, 1.0)
        self.assertEqual(result.union_accuracy, 1.0)
        self.assertEqual(result.labels_reported, 2)
        self.assertEqual(parsed.labels, labels)
        self.assertEqual(parsed.violations, set(labels))

    def test_subset_scoring_still_penalises_unknown_and_missing_ids(self):
        from scoring import ParsedVerdict, score

        labels = {"labelled": "FAIL", "invented": "FAIL", "unlabelled": "FAIL"}
        parsed = ParsedVerdict("NON_COMPLIANT", set(labels), True, labels=labels)
        result = score(parsed, {"labelled"}, {"labelled": "FAIL", "missing": "PASS"},
                       unscored_ids={"unlabelled"})
        self.assertEqual(result.fp, 1)
        self.assertEqual(result.union_accuracy, 1 / 3)
        self.assertEqual(result.label_coverage, 0.5)
        self.assertEqual(result.confusion["(not-anchor)->FAIL"], 1)
        self.assertEqual(result.confusion["PASS->(missing)"], 1)

    def test_condo_independent_relations_match(self):
        case = load("doors_windows_storey__condo")
        if not case.resolve_ifc().exists():
            self.skipTest("Local IFC unavailable")
        result = audit_case(case)
        self.assertEqual(result["status"], "relations-checked", result)
        self.assertEqual(result["independent_counts"], {"PASS": 208, "FAIL": 4})
        self.assertEqual(result["ifc_anchors"], 212)

    def test_staircase_subset_metadata_is_explicit_and_reproducible(self):
        from import_bca_gt import CASES, GT_COMPARISON_DIR, extract

        case = load("staircase_width_v8_deprecated_v1")
        self.assertEqual(len(case.unscored_ids), 10)
        self.assertEqual(case.reference["population"], 59)
        self.assertFalse(case.unscored_ids & set(case.labels))
        self.assertFalse(load("doors_windows_storey__condo").unscored_ids)
        specification = next(item for item in CASES if item.case_id == case.case_id)
        if not case.resolve_ifc().exists() or not (GT_COMPARISON_DIR / specification.rule_file).exists():
            self.skipTest("Local IFC or expert workbook unavailable")
        rebuilt, _ = extract(specification)
        self.assertEqual(rebuilt.labels, case.labels)
        self.assertEqual(rebuilt.reference, case.reference)

    def test_subset_metadata_cannot_exclude_authored_labels(self):
        case = load("staircase_width_v8_deprecated_v1")
        case.reference["unscored_ids"][0] = next(iter(case.labels))
        with self.assertRaises(ValueError):
            _ = case.unscored_ids

    def test_staircase_declared_subset_passes_workbook_and_ifc_audit(self):
        case = load("staircase_width_v8_deprecated_v1")
        if not case.resolve_ifc().exists():
            self.skipTest("Local IFC unavailable")
        result = audit_case(case)
        self.assertEqual(result["status"], "expert-subset-checked", result)
        self.assertEqual(len(result["missing_reference_ids"]), 10)
        self.assertEqual(set(result["missing_reference_ids"]), case.unscored_ids)
        self.assertTrue(result["workbook_matches"])
        self.assertEqual(result["issues"], [])

    def test_undeclared_or_stale_staircase_subsets_remain_invalid(self):
        original = load("staircase_width_v8_deprecated_v1")
        if not original.resolve_ifc().exists():
            self.skipTest("Local IFC unavailable")
        for defect in ("undeclared", "fingerprint", "wrong_id", "wrong_label"):
            with self.subTest(defect=defect):
                case = load("staircase_width_v8_deprecated_v1")
                if defect == "undeclared":
                    case.reference = {}
                elif defect == "fingerprint":
                    case.reference["ifc_sha256"] = "stale"
                elif defect == "wrong_id":
                    case.reference["unscored_ids"][0] = "invented"
                else:
                    guid = next(guid for guid, label in case.labels.items() if label == "PASS")
                    case.labels[guid] = "FAIL"
                    case.violations.append(guid)
                with patch("import_bca_gt.extract", return_value=(original, {})):
                    result = audit_case(case)
                self.assertEqual(result["status"], "invalid-or-incomplete", result)
                self.assertTrue(result["issues"])

    def test_all_59_stairs_can_match_the_49_authored_reference_labels(self):
        from completion import validate_final
        from scoring import ParsedVerdict, score
        import json

        case = load("staircase_width_v8_deprecated_v1")
        for outcome in ("PASS", "FAIL", "ALERT", "MANUAL_CHECK", "NA"):
            with self.subTest(unannotated_outcome=outcome):
                labels = {**case.labels, **dict.fromkeys(case.unscored_ids, outcome)}
                violations = {guid for guid, label in labels.items() if label == "FAIL"}
                parsed = ParsedVerdict("NON_COMPLIANT", violations, True, labels=labels)
                metrics = score(parsed, case.violation_set, case.labels, unscored_ids=case.unscored_ids)
                self.assertEqual(metrics.union_accuracy, 1.0)
                self.assertEqual(metrics.f1, 1.0)
                self.assertEqual(metrics.labels_reported, 59)
                self.assertEqual(metrics.labels_expected, 49)
                text = "FINAL: " + json.dumps({"verdict": parsed.verdict, "violations": sorted(violations)})
                self.assertEqual(validate_final(text, labels, 1, False, set(labels))[1], [])
                partial = "FINAL: " + json.dumps({"verdict": parsed.verdict, "violations": sorted(case.violation_set)})
                self.assertIsNone(validate_final(partial, case.labels, 1, False, set(labels))[0])

    def test_legacy_scoring_and_missing_reference_penalties_are_preserved(self):
        from scoring import ParsedVerdict, score

        case = load("staircase_width_v8_deprecated_v1")
        labels = {**case.labels, **dict.fromkeys(case.unscored_ids, "PASS")}
        parsed = ParsedVerdict("NON_COMPLIANT", case.violation_set, True, labels=labels)
        self.assertEqual(score(parsed, case.violation_set, case.labels).union_accuracy, 49 / 59)
        missing = ParsedVerdict("COMPLIANT", set(), True, labels=dict.fromkeys(case.unscored_ids, "PASS"))
        result = score(missing, case.violation_set, case.labels, unscored_ids=case.unscored_ids)
        self.assertEqual(result.fn, 22)
        self.assertEqual(result.union_accuracy, 0.0)
        self.assertEqual(result.label_coverage, 0.0)


if __name__ == "__main__":
    unittest.main()