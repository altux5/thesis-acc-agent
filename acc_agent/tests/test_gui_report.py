import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from gui import App


class GuiReportTests(unittest.TestCase):
    def test_partial_result_event_preserves_usage_without_claiming_verdict(self):
        import io
        from factual_report import parse_log

        app = Mock()
        app._suite = None
        log = io.StringIO()
        log.write("# Compliance check sweep\n# stateful - run 1/1\n")
        app._log.side_effect = log.write
        payload = {"prompt_tokens": 1000, "completion_tokens": 100, "iterations": 2,
                   "usage_complete": False, "completion_status": "incomplete", "labels": 0,
                   "verdict": "(no verdict reached)", "reason": "API failed"}
        App._handle(app, "partial_result", payload)
        app.result_view.show_result.assert_called_once_with(payload)
        run = parse_log(log.getvalue(), Path("fixture.md")).runs[0]
        self.assertEqual(run.tokens, (1000, 100))
        self.assertFalse(run.usage_complete)
        self.assertFalse(run.verdict_recorded)

    def test_failed_report_is_incomplete_in_log_report_and_database(self):
        import contextlib
        import io
        from agent import CodeActAgent
        from kernel_executor import KernelCodeExecutor
        from experiment_recorder import SweepRecorder
        from experiments import ExperimentStore
        from factual_report import parse_log
        from ground_truth import GroundTruth
        from scoring import ParsedVerdict, score
        from .test_agent import ScriptedClient, reply, python_call, final_call

        with TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            ifc = root / "fixture.ifc"
            ifc.write_text("unused fixture", encoding="utf-8")
            store = ExperimentStore(root / "experiments.sqlite3")
            case = GroundTruth("fixture", "Judge anchor", str(ifc), labels={"anchor": "FAIL"}, violations=["anchor"])
            stack.enter_context(patch.dict("os.environ", {"EXPERIMENTS": "1"}))
            stack.enter_context(patch("experiment_recorder.audit_case", return_value={"status": "unverified"}))
            stack.enter_context(patch("agent.discover_scope", return_value=({"anchor"}, "fixture scope")))
            stack.enter_context(patch("tracing.get_client", return_value=None))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            for mode in ("stateful", "stateless"):
                with self.subTest(mode=mode):
                    final = reply(final_call())
                    client = ScriptedClient([
                        reply(python_call('print("x" * 500)\nreport_labels({"anchor":"PASS"})\nraise ValueError("failed measurement")')),
                        reply(python_call('print("continuing")')), final,
                    ])
                    recorder = SweepRecorder(entrypoint="test", requested=1, case=case, rule=case.rule,
                        ifc_path=ifc, client=client, max_iterations=3, reasoning=False, env_primer=False,
                        library=None, output_limit=60, store=store)
                    ticket = recorder.start_run(mode, 1, 1)
                    log = io.StringIO()
                    log.write(f"# Compliance check sweep\n- **Case:** fixture\n- **Modes:** {mode} x 1\n# {mode} - run 1/1\n")
                    app = Mock()
                    app._suite = None
                    app._log.side_effect = log.write
                    app._finish.side_effect = lambda payload: App._finish(app, payload)

                    def event(name, payload):
                        ticket.observe(name, payload)
                        App._handle(app, name, payload)

                    executor = KernelCodeExecutor(stateful=mode == "stateful", output_char_limit=60, timeout=30)
                    stack.callback(executor.close)
                    result = CodeActAgent(client, executor,
                        max_iterations=3, reasoning_enabled=False, env_primer=False)._run_loop(case.rule, str(ifc), event)
                    metrics = score(ParsedVerdict(result.verdict_label, set(result.violations), result.parse_ok, labels=result.labels), case.violation_set, case.labels)
                    recorder.finish_run(ticket, result, metrics)
                    recorder.finish()
                    report = parse_log(log.getvalue(), root / "fixture.md")
                    self.assertEqual(result.completion_status, "incomplete")
                    self.assertEqual(report.runs[0].completion["status"], "incomplete")
                    self.assertEqual(report.runs[0].errors, 1)
                    self.assertEqual(report.runs[0].truncations, 1)
                    row = next(row for row in store.list_runs() if row["id"] == ticket.id)
                    self.assertEqual(row["status"], "incomplete")
                    self.assertEqual(row["error_count"], 1)
                    self.assertEqual(row["labels_reported"], 0)

    def test_structured_execution_status_is_saved_without_changing_output(self):
        import json

        app = Mock()
        App._handle(app, "output", {"output": "text", "error": True, "error_text": "ValueError: failed", "truncated": False, "labels_valid": False})
        self.assertIn("### Output\n\n```\ntext\n```", app._log.call_args_list[0].args[0])
        recorded = app._log.call_args_list[1].args[0].split("```json\n")[1].split("\n```")[0]
        self.assertTrue(json.loads(recorded)["error"])

    def test_kernel_restart_reaches_the_logged_execution_status(self):
        import json

        app = Mock()
        App._handle(app, "output", {
            "output": "The execution kernel was restarted.", "error": True,
            "error_text": "ExecutionTimeout: the code block was still running after 600 seconds.",
            "truncated": False, "output_dropped_chars": 0, "labels_valid": False,
            "kernel_restarted": True, "restart_reason": "timeout"})
        recorded = json.loads(app._log.call_args_list[1].args[0].split("```json\n")[1].split("\n```")[0])
        self.assertTrue(recorded["kernel_restarted"])
        self.assertEqual(recorded["restart_reason"], "timeout")

    def test_in_process_status_carries_no_restart_keys(self):
        import json

        app = Mock()
        App._handle(app, "output", {"output": "text", "error": True,
                                    "error_text": "ValueError: failed",
                                    "truncated": False, "labels_valid": False})
        recorded = json.loads(app._log.call_args_list[1].args[0].split("```json\n")[1].split("\n```")[0])
        self.assertNotIn("kernel_restarted", recorded)

    def test_completion_event_is_logged_as_structured_data(self):
        import json

        app = Mock()
        payload = {"status": "incomplete", "issues": ["No report_labels submission"]}
        App._handle(app, "completion", payload)
        logged = app._log.call_args.args[0]
        data = logged.split("```json\n")[1].split("\n```")[0]
        self.assertEqual(json.loads(data), payload)
        app._show_factual_report.assert_not_called()

    def test_sweep_end_closes_log_before_generating_report(self):
        app = Mock()
        app._suite = None
        app._sweep_caption = "sample | offline"
        app.current_log_path = Path("sweep.md")
        log_handle = app.log_fh

        def show_report(source):
            log_handle.close.assert_called_once()
            self.assertIsNone(app.log_fh)
            self.assertEqual(source, Path("sweep.md"))

        app._show_factual_report.side_effect = show_report
        App._handle(app, "__threaddone__", {})
        app._show_factual_report.assert_called_once_with(Path("sweep.md"))
        app.report_load_btn.configure.assert_called_once_with(state="normal")
        app.run_btn.configure.assert_called_once()

    def test_step_events_do_not_generate_reports(self):
        app = Mock()
        for event, payload in [
            ("code", {"code": "print(1)"}),
            ("output", {"output": "1"}),
            ("done", {"verdict": "COMPLIANT"}),
            ("score", {}),
        ]:
            App._handle(app, event, payload)
        app._show_factual_report.assert_not_called()

    def test_generation_failure_is_visible_and_does_not_escape_to_gui(self):
        app = Mock()
        with patch("gui.factual_report.generate_report", side_effect=OSError("read-only directory")):
            App._show_factual_report(app, Path("sweep.md"))
        self.assertIsNone(app.current_report_path)
        self.assertIn("read-only directory", app._set_report_text.call_args.args[0])
        app.views.set.assert_called_once_with("Factual Report")

    def test_report_view_contains_results_and_enables_open_button(self):
        app = Mock()
        with TemporaryDirectory() as directory:
            source = Path(directory) / "sweep.md"
            source.write_text('''# Compliance check sweep
- **Case:** example
# stateful - run 1/1
## Iteration 1 / 1
### Verdict
FINAL: {"verdict": "COMPLIANT", "violations": []}
**Score** (example): F1=1.00 labels=2/2 coverage=1.000 union_acc=1.000
''', encoding="utf-8")
            App._show_factual_report(app, source)
            self.assertTrue(app.current_report_path.exists())
            self.assertIn("F1: 1.00", app._set_report_text.call_args.args[0])
            self.assertEqual(app.report_open_btn.configure.call_args.kwargs, {"state": "normal"})
            app.views.set.assert_called_once_with("Factual Report")


if __name__ == "__main__":
    unittest.main()