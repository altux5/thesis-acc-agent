import contextlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from completion import discover_scope, scope_classes, validate_final
from .test_agent import ScriptedClient, reply, python_call, final_call


class CompletionTests(unittest.TestCase):
    def setUp(self):
        tracing = patch("tracing.get_client", return_value=None)
        tracing.start()
        self.addCleanup(tracing.stop)

    def check(self, verdict="COMPLIANT", violations=None, labels=None, reports=1, error=False, anchors=None, **extra):
        text = "FINAL: " + json.dumps({"verdict": verdict, "violations": violations or [], **extra})
        return validate_final(text, labels or {}, reports, error, anchors)

    def test_missing_submission_and_partial_coverage_rejected(self):
        payload, issues = self.check(reports=0, anchors={"one", "two"})
        self.assertIsNone(payload)
        self.assertTrue(any("No report_labels" in issue for issue in issues))
        payload, issues = self.check(labels={"one": "PASS"}, anchors={"one", "two"})
        self.assertIsNone(payload)
        self.assertIn("1 missing", " ".join(issues))

    def test_count_alone_does_not_prove_coverage(self):
        payload, issues = self.check(labels={"wrong": "PASS"}, anchors={"one"})
        self.assertIsNone(payload)
        self.assertIn("1 unexpected", " ".join(issues))

    def test_contradictory_final_and_failed_execution_rejected(self):
        self.assertIsNone(self.check(labels={"one": "FAIL"}, anchors={"one"})[0])
        self.assertIsNone(self.check(labels={"one": "PASS"}, error=True, anchors={"one"})[0])

    def test_valid_failure_and_missing_data_mix(self):
        payload, issues = self.check("NON_COMPLIANT", ["one"], {"one": "FAIL", "two": "ALERT"}, anchors={"one", "two"})
        self.assertEqual(payload["verdict"], "NON_COMPLIANT")
        self.assertEqual(issues, [])

    def test_empty_verified_population_and_all_alerts(self):
        self.assertIsNotNone(self.check(anchors=set())[0])
        self.assertIsNone(self.check(labels={"one": "ALERT"}, anchors={"one"})[0])
        self.assertIsNotNone(self.check(labels={"one": "NA"}, anchors={"one"})[0])

    def test_abstention_is_allowed_but_reason_required(self):
        self.assertIsNone(self.check("UNKNOWN", reports=0)[0])
        self.assertIsNotNone(self.check("UNKNOWN", reports=0, reason="Model could not be read.")[0])

    def test_prose_and_malformed_json_do_not_bypass_validation(self):
        for text in ['COMPLIANT', 'FINAL: {}', 'FINAL: {"verdict":[],"violations":[]}', 'FINAL: {"verdict":"COMPLIANT","violations":"guid"}', 'FINAL: {bad', 'FINAL: {"verdict":"COMPLIANT","violations":[]} extra']:
            with self.subTest(text=text):
                self.assertIsNone(validate_final(text, {"one": "PASS"}, 1, False, {"one"})[0])

    def test_scope_uses_explicit_public_class_not_other_mentions(self):
        self.assertEqual(scope_classes("A host is IfcWall. Report elements (modelled as IfcDoor or IfcWindow)."), ["IfcDoor", "IfcWindow"])
        self.assertEqual(scope_classes("Every door (IfcDoor) needs checking."), ["IfcDoor"])
        self.assertEqual(scope_classes("Inspect some IfcWall and IfcSlab."), [])
        with patch("ifcopenshell.open") as open_model:
            open_model.return_value.by_type.return_value = [type("Element", (), {"GlobalId": "public-id"})()]
            anchors, note = discover_scope("Check elements (modelled as IfcSlab).", "model.ifc")
        self.assertEqual(anchors, {"public-id"})
        self.assertIn("no reference labels", note)

    def test_evaluation_exports_completion_for_real_ifc_scope_in_both_modes(self):
        import ifcopenshell
        from evaluate import _run_once
        from .test_agent import ScriptedClient

        model = ifcopenshell.file(schema="IFC4")
        first = model.create_entity("IfcSlab", GlobalId=ifcopenshell.guid.new())
        second = model.create_entity("IfcSlab", GlobalId=ifcopenshell.guid.new())
        labels = {first.GlobalId: "PASS", second.GlobalId: "ALERT"}
        replies = [reply(python_call(f"report_labels({labels!r})")), reply(final_call())]
        with TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            path = Path(directory) / "scope.ifc"
            model.write(str(path))
            for name in ("check_run", "step", "tool"):
                stack.enter_context(patch("tracing." + name, side_effect=lambda *args, **kwargs: contextlib.nullcontext(None)))
            for name in ("finish", "finish_trace", "score_run"):
                stack.enter_context(patch("tracing." + name))
            stack.enter_context(patch("tracing.current_trace_id", return_value=""))
            stack.enter_context(patch("tracing.trace_url", return_value=""))
            for mode in ("stateful", "stateless"):
                with self.subTest(mode=mode):
                    scores, meta = _run_once(
                        ScriptedClient(replies), "Report every element (modelled as IfcSlab).",
                        path, mode, 2, False, set(), env_primer=False, gt_labels=labels,
                    )
                    self.assertEqual(meta["completion_status"], "complete")
                    self.assertEqual(meta["expected_anchors"], 2)
                    self.assertEqual(scores.union_accuracy, 1.0)
                    self.assertIn("no reference labels", meta["scope_note"])

    def test_unknown_custom_scope_is_not_claimed_as_complete(self):
        from agent import CodeActAgent
        from kernel_executor import KernelCodeExecutor
        from .test_agent import ScriptedClient

        replies = [reply(python_call('report_labels({"anchor":"PASS"})')), reply(final_call())]
        executor = KernelCodeExecutor(timeout=30)
        self.addCleanup(executor.close)
        agent = CodeActAgent(ScriptedClient(replies), executor, max_iterations=2, env_primer=False)
        with contextlib.ExitStack() as stack:
            import io
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            for name in ("step", "tool"):
                stack.enter_context(patch("tracing." + name, side_effect=lambda *args, **kwargs: contextlib.nullcontext(None)))
            stack.enter_context(patch("tracing.finish"))
            result = agent._run_loop("Some custom rule", "not-read.ifc")
        self.assertEqual(result.completion_status, "reported_unverified_scope")
        self.assertIsNone(result.expected_anchors)
        self.assertTrue(result.parse_ok)

    def test_staircase_subset_scores_full_submission_and_rejects_partial_scope(self):
        import ifcopenshell
        from evaluate import _run_once
        from .test_agent import ScriptedClient

        model = ifcopenshell.file(schema="IFC4")
        labelled = model.create_entity("IfcStair", GlobalId=ifcopenshell.guid.new())
        unlabelled = model.create_entity("IfcStair", GlobalId=ifcopenshell.guid.new())
        truth = {labelled.GlobalId: "FAIL"}
        full = {**truth, unlabelled.GlobalId: "FAIL"}
        with TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            path = Path(directory) / "stairs.ifc"
            model.write(str(path))
            for name in ("check_run", "step", "tool"):
                stack.enter_context(patch("tracing." + name, side_effect=lambda *args, **kwargs: contextlib.nullcontext(None)))
            for name in ("finish", "finish_trace", "score_run"):
                stack.enter_context(patch("tracing." + name))
            stack.enter_context(patch("tracing.current_trace_id", return_value=""))
            stack.enter_context(patch("tracing.trace_url", return_value=""))
            for harness in (1, 2):
                for mode in ("stateful", "stateless"):
                    with self.subTest(harness=harness, mode=mode):
                        replies = [reply(text="Inspect all stairs.")] if harness == 2 else []
                        replies += [
                            reply(python_call(f"report_labels({truth!r})")),
                            reply(final_call("NON_COMPLIANT", list(truth))),
                            reply(python_call(f"report_labels({full!r})")),
                            reply(final_call("NON_COMPLIANT", list(full))),
                        ]
                        client = ScriptedClient(replies)
                        scores, meta = _run_once(
                            client, "Report every element (modelled as IfcStair).",
                            path, mode, len(replies), False, set(truth), env_primer=False,
                            harness=harness, gt_labels=truth, unscored_ids={unlabelled.GlobalId},
                        )
                        self.assertEqual(meta["completion_status"], "complete")
                        self.assertEqual(meta["expected_anchors"], 2)
                        self.assertEqual(meta["predicted_violations"], sorted(full))
                        self.assertEqual(meta["executions"], 2)
                        self.assertEqual(scores.union_accuracy, 1.0)
                        self.assertEqual(scores.f1, 1.0)

if __name__ == "__main__":
    unittest.main()