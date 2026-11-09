import contextlib
import json
import tkinter as tk
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import ground_truth
from agent import AgentResult
from ground_truth import GroundTruth
from gui import (App, CUSTOM_CHOICE, HEALTH_SUITE_CASES, HELDOUT_SUITE_CASES, MAX_MODEL_CALLS,
                 PROVIDER_RETRY_DELAYS, USABLE_CASES, case_assessment, is_provider_error)
from kernel_executor import KernelCodeExecutor
from gui_widgets import METRIC_GUIDE, GREEN, ORANGE, RED, bind_wrapping, result_presentation
from scoring import ParsedVerdict, aggregate, score

# Raises from a frame that belongs to the provider client, like langchain_anthropic on a reply without content.
_PROVIDER_CLIENT = {"__name__": "langchain_anthropic.chat_models"}
exec("def provider_failure():\n    raise TypeError(\"'NoneType' object is not iterable\")\n", _PROVIDER_CLIENT)
provider_failure = _PROVIDER_CLIENT["provider_failure"]


def local_failure():
    raise TypeError("agent bug")



class ImmediateThread:
    def __init__(self, target, daemon):
        self.target = target

    def start(self):
        self.target()

    def is_alive(self):
        return False


class GuiPresentationTests(unittest.TestCase):
    def payload(self):
        metrics = score(ParsedVerdict("NON_COMPLIANT", {"one"}, True, labels={"one": "FAIL"}), {"one"}, {"one": "FAIL"})
        return {"scores": metrics, "case_id": "sample", "mode": "stateful", "rep": 1,
                "gt_n": 1, "iterations": 3, "prompt_tokens": 100, "completion_tokens": 50}

    def test_scores_go_to_separate_view_but_still_log(self):
        app = Mock()
        payload = self.payload()
        App._render_score(app, payload)
        app.score_view.add_score.assert_called_once_with(payload)
        app._write.assert_not_called()
        saved = app._log.call_args.args[0]
        self.assertIn("**Score** (sample):", saved)
        self.assertIn("union_acc=1.000 coverage=1.000 labels=1/1", saved)

    def test_aggregate_goes_to_scores_view_and_original_log(self):
        app = Mock()
        payload = {"mode": "stateful", "n": 2, "agg": aggregate([self.payload()["scores"]] * 2)}
        App._render_aggregate(app, payload)
        app.score_view.add_aggregate.assert_called_once_with(payload)
        app._write.assert_not_called()
        self.assertIn("## stateful mean over 2", app._log.call_args.args[0])

    def test_metric_guide_covers_metrics_and_vacuous_scores(self):
        for metric in ("Recall:", "Precision:", "F1:", "Union accuracy:", "Coverage:", "No reference violations:"):
            self.assertIn(metric, METRIC_GUIDE)

    def test_verdict_is_structured_not_a_keyword_in_a_reason(self):
        payload = {"verdict": 'FINAL: {"verdict":"UNKNOWN","violations":[],"reason":"Cannot claim COMPLIANT"}', "completion_status": "abstained"}
        display = result_presentation(payload)
        self.assertEqual(display["title"], "Unable to conclude")
        self.assertEqual(display["color"], ORANGE)

    def test_incomplete_and_unverified_are_never_green(self):
        final = 'FINAL: {"verdict":"COMPLIANT","violations":[]}'
        self.assertEqual(result_presentation({"verdict": final, "completion_status": "incomplete"})["color"], RED)
        self.assertEqual(result_presentation({"verdict": final, "completion_status": "reported_unverified_scope"})["color"], ORANGE)
        self.assertEqual(result_presentation({"verdict": final, "completion_status": "complete"})["color"], GREEN)

    def test_result_display_changes_do_not_change_saved_verdict(self):
        app = Mock()
        final = 'FINAL: {"verdict":"NON_COMPLIANT","violations":["one"]}'
        payload = {"verdict": final, "completion_status": "complete", "iterations": 3, "prompt_tokens": 12345, "completion_tokens": 700}
        App._finish(app, payload)
        app.result_view.show_result.assert_called_once_with(payload)
        self.assertIn(final, app._log.call_args.args[0])
        self.assertIn("- tokens: 12345 in / 700 out", app._log.call_args.args[0])

    def test_wrap_width_accounts_for_display_scaling(self):
        label = Mock()
        label._get_widget_scaling.return_value = 1.25
        label.cget.return_value = 0
        with patch("gui_widgets.tk.Misc.bind") as bind:
            bind_wrapping(label)
        resize = bind.call_args.args[2]
        resize(Mock(width=750))
        label.configure.assert_called_once_with(wraplength=588)
        label.bind.assert_not_called()


class GuiWorkflowTests(unittest.TestCase):
    def setUp(self):
        try:
            self.app = App()
            self.app.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Desktop Tk unavailable: {exc}")

    def tearDown(self):
        for callback in self.app.tk.call("after", "info"):
            self.app.tk.call("after", "cancel", callback)
        self.app.destroy()

    def test_case_filters_retain_catalog_custom_and_numeric_controls(self):
        app = self.app
        self.assertFalse(hasattr(app, "skills_control"))
        self.assertFalse(hasattr(app, "skills_var"))
        self.assertFalse(hasattr(app, "skill_details_btn"))
        self.assertFalse(hasattr(app, "runtime_var"))
        self.assertFalse(hasattr(app, "runtime_control"))
        self.assertFalse(hasattr(app, "runtime_note"))
        self.assertFalse(hasattr(App, "_runtime_choice"))
        self.assertFalse(hasattr(App, "_on_runtime"))
        for group in ("Pilots", "All cases", "Class 1", "Class 2", "Class 3", "Controls", "Custom"):
            app._filter_cases(group)
            self.assertTrue(app.case_menu.cget("values"))
        self.assertEqual(app.case_var.get(), CUSTOM_CHOICE)
        self.assertIsNone(app.current_gt)
        app._filter_cases("All cases")
        self.assertEqual(set(app.case_menu.cget("values")), set(app.case_labels) | {CUSTOM_CHOICE})
        self.assertEqual(len(app.harness_control.cget("values")), 2)
        app._on_harness(app.harness_control.cget("values")[1])
        self.assertEqual(app.harness_var.get(), 2)
        app._set_settings_enabled(False)
        self.assertEqual(app.rule_box.cget("state"), "disabled")
        app._set_settings_enabled(True)
        self.assertEqual(app.repeats_slider.cget("state"), "normal")

    def test_archived_skill_controls_and_callbacks_are_absent(self):
        self.assertFalse(hasattr(self.app, "skill_health_label"))
        self.assertFalse(hasattr(App, "_refresh_skill_health"))
        self.assertFalse(hasattr(App, "_show_skill_health"))

    def test_sidebar_offers_only_single_run_health_suite_and_stop(self):
        app = self.app
        footer = app.run_btn.master
        buttons = [child.cget("text") for child in footer.winfo_children() if hasattr(child, "invoke")]
        self.assertEqual(buttons, ["Run checks", "Run 8-case health suite", "Stop after current run"])
        for name in ("usable_2_suite_btn", "heldout_pilot_btns", "heldout_chain_btns", "_chain"):
            self.assertFalse(hasattr(app, name))
        for name in ("_on_heldout_pilot", "_on_heldout_chain", "_continue_chain", "_pilot_finished_cases"):
            self.assertFalse(hasattr(App, name))

    def test_reference_tiers_cover_catalogue_and_health_suite(self):
        app = self.app
        self.assertGreaterEqual(len(HELDOUT_SUITE_CASES), 3)
        self.assertEqual(len(app.case_labels), 46 + len(HELDOUT_SUITE_CASES))
        self.assertFalse(any(ground_truth.is_deprecated(metadata["case_id"]) for metadata in app.case_labels.values()))
        self.assertEqual(len(USABLE_CASES), 6)
        self.assertEqual(len(set(HEALTH_SUITE_CASES)), 8)
        self.assertEqual(case_assessment("future_case")[0], "Unreviewed")
        self.assertTrue(all(metadata["assessment"] != "Unreviewed" for metadata in app.case_labels.values()))
        for group, count in (("Health suite", 8), ("Usable", 6), ("usable_2", 10), ("Held-out", len(HELDOUT_SUITE_CASES)),
                             ("Retired", 9), ("Controls", 20), ("Provisional", 1)):
            with self.subTest(group=group):
                app._filter_cases(group)
                self.assertEqual(len(app.case_menu.cget("values")), count)
        app._filter_cases("Retired")
        self.assertIn("Retired", app.case_summary.cget("text"))
        app._filter_cases("usable_2")
        self.assertIn("usable_2", app.case_summary.cget("text"))
        self.assertEqual(case_assessment("headroom_condo_c32")[0], "Retired")
        app._filter_cases("Provisional")
        self.assertIn("all 59 stairs", app.case_summary.cget("text"))
        self.assertEqual(case_assessment("staircase_width_v8")[0], "Provisional")
        self.assertEqual(case_assessment("staircase_width_v8_deprecated_v1")[0], "Deprecated")

    @contextlib.contextmanager
    def suite_fixture(self, *, approve=True, stop=False, fail=False, provider_fail_calls=(), budget=MAX_MODEL_CALLS,
                      file_system=False, script_mode=False):
        app = self.app
        with TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            model = root / "fixture.ifc"
            model.touch()
            cases = {}
            for case_id in HEALTH_SUITE_CASES:
                labels = {case_id + "-one": "FAIL", case_id + "-two": "PASS"}
                if case_id == "slab_thickness__mall":
                    labels = {case_id + "-one": "PASS", case_id + "-two": "ALERT"}
                cases[case_id] = GroundTruth(case_id, "Rule for " + case_id, str(model), labels=labels,
                    violations=[guid for guid, label in labels.items() if label == "FAIL"])
            seen = []
            executors = []

            def make_executor(**settings):
                self.assertEqual(settings.get("file_system", False), file_system or script_mode)
                executor = Mock(stateful=settings["stateful"])
                executors.append(executor)
                return executor

            def make_agent(client, executor, **settings):
                self.assertEqual(settings["max_iterations"], budget)
                if script_mode:
                    self.assertNotIn("harness", settings)
                    self.assertFalse(executor.stateful)
                else:
                    self.assertEqual(settings["harness"], 2)
                    self.assertEqual(settings.get("file_system", False), file_system)

                def check(rule, ifc, on_event, trace_attrs):
                    case_id = trace_attrs["metadata"]["case_id"]
                    case = cases[case_id]
                    self.assertEqual(rule, case.rule)
                    self.assertEqual(ifc, str(model))
                    self.assertTrue(trace_attrs["metadata"]["health_suite_id"].startswith("health-"))
                    call = len(seen)
                    seen.append((case_id, executor.stateful))
                    if fail:
                        raise RuntimeError("Offline provider failure")
                    if call in provider_fail_calls:
                        provider_failure()
                    labels = {**case.labels, **dict.fromkeys(case.unscored_ids, "FAIL")}
                    failures = [guid for guid, label in labels.items() if label == "FAIL"]
                    verdict = "NON_COMPLIANT" if failures else "COMPLIANT"
                    final = "FINAL: " + json.dumps({"verdict": verdict, "violations": failures})
                    on_event("completion", {"status": "complete", "issues": [], "expected_anchors": len(labels), "labels_submitted": len(labels)})
                    on_event("done", {"verdict": final, "completion_status": "complete", "iterations": 2,
                                      "prompt_tokens": 100, "completion_tokens": 20, "usage_complete": True})
                    if stop:
                        app._on_stop()
                    return AgentResult(final, 2, verdict_label=verdict, violations=failures,
                        parse_ok=True, labels=labels, completion_status="complete", expected_anchors=len(labels),
                        prompt_tokens=100, completion_tokens=20, usage_complete=True)

                return Mock(check=check, partial_result=None)

            stack.enter_context(patch.dict("os.environ", {"EXPERIMENT_DB": str(root / "test.sqlite3"), "EXPERIMENTS": "1"}))
            stack.enter_context(patch("gui.LOG_DIR", root))
            stack.enter_context(patch("gui.ground_truth.load", side_effect=cases.__getitem__))
            stack.enter_context(patch("experiment_recorder.audit_case", return_value={"status": "unverified"}))
            client = stack.enter_context(patch("gui.llm.load_llm", return_value=Mock(model="offline", provider="offline")))
            confirm = stack.enter_context(patch("gui.messagebox.askyesno", return_value=approve))
            errors = stack.enter_context(patch("gui.messagebox.showerror"))
            stack.enter_context(patch("gui.make_executor", side_effect=make_executor))
            stack.enter_context(patch("gui.CodeActAgent", side_effect=make_agent if not script_mode else
                                      AssertionError("script mode must not build the frozen agent")))
            stack.enter_context(patch("gui.ScriptAgent", side_effect=make_agent if script_mode else
                                      AssertionError("only script mode builds the script agent")))
            stack.enter_context(patch("gui.threading.Thread", ImmediateThread))
            for name in ("score_run", "score_sweep", "flush"):
                stack.enter_context(patch("gui.tracing." + name))
            stack.enter_context(patch("gui.tracing.trace_url", return_value=""))
            stack.enter_context(patch.object(app, "after"))
            app.mode_var.set("both")
            app.repeats_var.set(1)
            app.harness_var.set(2)
            yield root, cases, seen, executors, client, confirm, errors

    def test_health_suite_runs_all_eight_cases_in_both_modes_without_pooling(self):
        app = self.app
        with self.suite_fixture() as (root, cases, seen, executors, client, confirm, errors):
            app._on_suite()
            for _ in range(9):
                if app._suite is None:
                    break
                app._poll()
            self.assertIsNone(app._suite)
            self.assertEqual(seen, [(case_id, stateful) for case_id in HEALTH_SUITE_CASES for stateful in (True, False)])
            self.assertEqual(len(app.score_view.table.get_children()), 16)
            self.assertEqual({entry["case_id"] for entry in app.score_view.entries.values()}, set(HEALTH_SUITE_CASES))
            self.assertTrue(all(entry["scores"].union_accuracy == 1.0 for entry in app.score_view.entries.values()))
            client.assert_called_once()
            confirm.assert_called_once()
            self.assertIn("16 runs", confirm.call_args.args[1])
            self.assertIn(f"{16 * MAX_MODEL_CALLS} model calls", confirm.call_args.args[1])
            self.assertEqual(confirm.call_args.kwargs["default"], "no")
            errors.assert_not_called()
            self.assertTrue(all(executor.close.called for executor in executors))
            manifest = json.loads(app._suite_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "finished")
            self.assertEqual(manifest["finished_runs"], 16)
            self.assertEqual(manifest["complete_runs"], 16)
            self.assertEqual(manifest["known_input_tokens"], 1600)
            self.assertEqual(manifest["known_output_tokens"], 320)
            self.assertTrue(manifest["usage_complete"])
            self.assertEqual(len(manifest["cases"]), 8)
            for entry in manifest["cases"]:
                self.assertTrue(Path(entry["log_path"]).exists())
                self.assertTrue(Path(entry["report_path"]).exists())
                self.assertIn(manifest["suite_id"], Path(entry["log_path"]).read_text(encoding="utf-8"))
            self.assertEqual(app.views.get(), "Scores")
            self.assertEqual(app.suite_btn.cget("state"), "normal")
            self.assertEqual(app.stop_btn.cget("state"), "disabled")
            from experiments import ExperimentStore

            stored = ExperimentStore(root / "test.sqlite3").list_runs()
            self.assertEqual(len(stored), 16)
            self.assertEqual({row["case_id"] for row in stored}, set(HEALTH_SUITE_CASES))
            self.assertEqual(len({row["sweep_id"] for row in stored}), 8)

    def test_file_system_suite_passes_the_flag_to_executor_agent_and_records(self):
        app = self.app
        with self.suite_fixture(file_system=True) as (root, _, seen, executors, _, confirm, _):
            app._on_suite(HEALTH_SUITE_CASES[:1], kind="files_test", file_system=True)
            app._poll()
            self.assertIsNone(app._suite)
            self.assertEqual(seen, [(HEALTH_SUITE_CASES[0], True), (HEALTH_SUITE_CASES[0], False)])
            self.assertIn("File system: on", confirm.call_args.args[1])
            manifest = json.loads(app._suite_path.read_text(encoding="utf-8"))
            self.assertEqual((manifest["status"], manifest["settings"]["file_system"]), ("finished", True))
            self.assertIn("- **File system:** on", Path(manifest["cases"][0]["log_path"]).read_text(encoding="utf-8"))
            from experiments import ExperimentStore

            stored = ExperimentStore(root / "test.sqlite3").list_runs()
            self.assertEqual({json.loads(row["configuration"])["agent_protocol"] for row in stored},
                             {"langchain-codeact-v5-files-guided"})

    def test_script_mode_suite_builds_the_script_agent_and_records_its_protocol(self):
        app = self.app
        with self.suite_fixture(script_mode=True) as (root, _, seen, executors, _, confirm, _):
            app.mode_var.set("stateless")
            app.harness_var.set(1)
            app._on_suite(HEALTH_SUITE_CASES[:1], kind="script_test", script_mode=True)
            app._poll()
            self.assertIsNone(app._suite)
            self.assertEqual(seen, [(HEALTH_SUITE_CASES[0], False)])
            self.assertIn("Script mode: code runs only from workspace files", confirm.call_args.args[1])
            manifest = json.loads(app._suite_path.read_text(encoding="utf-8"))
            self.assertEqual((manifest["status"], manifest["settings"]["script_mode"]), ("finished", True))
            log = Path(manifest["cases"][0]["log_path"]).read_text(encoding="utf-8")
            self.assertIn("- **Agent protocol:** langchain-codeact-v5-script-v2", log)
            self.assertIn("- **Script mode:**", log)
            from experiments import ExperimentStore

            stored = ExperimentStore(root / "test.sqlite3").list_runs()
            configurations = [json.loads(row["configuration"]) for row in stored]
            self.assertEqual({item["agent_protocol"] for item in configurations}, {"langchain-codeact-v5-script-v2"})
            self.assertTrue(all(item["core_files"]["script_agent.py"]["status"] == "matches" for item in configurations))
            self.assertTrue(all(item["runtime_code_verified"] for item in configurations))

    def test_file_tool_events_are_shown_and_logged(self):
        app = Mock()
        App._handle(app, "file_tool", {"name": "write_file", "arguments": {"path": "lib/a.py", "content": "x = 1\n"},
                                       "result": "Wrote 6 bytes to lib/a.py.", "error": False})
        shown = "".join(call.args[0] for call in app._write.call_args_list)
        self.assertIn("File tool: write_file(path='lib/a.py', content=<6 chars>)", shown)
        logged = app._log.call_args.args[0]
        self.assertIn("### File tool: write_file(path='lib/a.py', content=<6 chars>)", logged)
        self.assertIn("x = 1", logged)
        self.assertIn("Wrote 6 bytes to lib/a.py.", logged)

    def test_suite_budget_override_reaches_agent_and_records(self):
        app = self.app
        with self.suite_fixture(budget=MAX_MODEL_CALLS + 1) as (root, _, seen, _, _, confirm, _):
            app.mode_var.set("stateful")
            app._on_suite(HEALTH_SUITE_CASES[:1], kind="budget_test", budget=MAX_MODEL_CALLS + 1)
            app._poll()
            self.assertIsNone(app._suite)
            self.assertEqual(seen, [(HEALTH_SUITE_CASES[0], True)])
            self.assertIn(f"Fixed {MAX_MODEL_CALLS + 1} model calls per run", confirm.call_args.args[1])
            manifest = json.loads(app._suite_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "finished")
            self.assertEqual(manifest["settings"]["max_model_calls"], MAX_MODEL_CALLS + 1)
            from experiments import ExperimentStore

            stored = ExperimentStore(root / "test.sqlite3").list_runs()
            self.assertEqual([json.loads(row["configuration"])["max_iterations"] for row in stored], [MAX_MODEL_CALLS + 1])

    def test_suite_reasoning_override_is_recorded(self):
        app = self.app
        with self.suite_fixture() as (root, cases, seen, executors, client, confirm, errors), \
                patch.dict("os.environ", {"REASONING": "0"}):
            app._on_suite(reasoning=True)
            self.assertIn("Reasoning: on", confirm.call_args.args[1])
            manifest = json.loads(app._suite_path.read_text(encoding="utf-8"))
            self.assertIs(manifest["settings"]["reasoning"], True)
            app._stop_requested.set()
            for _ in range(3):
                if app._suite is None:
                    break
                app._poll()

    def test_declining_health_suite_makes_no_provider_or_worker_calls(self):
        with self.suite_fixture(approve=False) as (_, _, seen, executors, client, confirm, _):
            self.app._on_suite()
            self.assertIsNone(self.app._suite)
            self.assertEqual(seen, [])
            self.assertEqual(executors, [])
            client.assert_not_called()
            confirm.assert_called_once()

    def test_suite_missing_model_is_rejected_before_confirmation(self):
        with self.suite_fixture() as (_, cases, seen, _, client, confirm, errors):
            Path(next(iter(cases.values())).ifc_path).unlink()
            self.app._on_suite()
            self.assertEqual(seen, [])
            client.assert_not_called()
            confirm.assert_not_called()
            errors.assert_called_once()

    def test_health_suite_stop_and_non_provider_error_do_not_start_later_runs(self):
        for stop, fail, status in ((True, False, "stopped"), (False, True, "error")):
            with self.subTest(status=status), self.suite_fixture(stop=stop, fail=fail) as (_, _, seen, executors, _, _, _):
                self.app._on_suite()
                self.app._poll()
                self.assertIsNone(self.app._suite)
                self.assertEqual(seen, [(HEALTH_SUITE_CASES[0], True)])
                self.assertTrue(all(executor.close.called for executor in executors))
                manifest = json.loads(self.app._suite_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["status"], status)
                self.assertEqual(len(manifest["cases"]), 1)
                self.assertEqual(manifest["cases"][0]["status"], status)
                self.assertEqual(self.app.run_btn.cget("state"), "normal")

    def scheduled_retry(self, delay):
        calls = [c for c in self.app.after.call_args_list if c.args and c.args[0] == delay * 1000]
        self.assertEqual(len(calls), 1)
        return calls[0].args[1]

    def test_provider_error_reruns_the_whole_case_after_a_pause(self):
        app = self.app
        # Call 1 is the stateless run of the first case, after its stateful run finished.
        with self.suite_fixture(provider_fail_calls={1}) as (root, _, seen, _, _, confirm, _):
            app._on_suite()
            self.assertIn("A provider error reruns the whole case", confirm.call_args.args[1])
            app._poll()
            self.assertIsNotNone(app._suite)
            manifest = json.loads(app._suite_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "running")
            self.assertEqual(manifest["finished_runs"], 0)
            self.assertEqual(manifest["cases"][0]["status"], "error")
            self.assertTrue(manifest["cases"][0]["provider_error"])
            self.assertEqual(manifest["cases"][0]["discarded_runs"], 1)
            self.assertEqual(manifest["settings"]["provider_retry_delays"], list(PROVIDER_RETRY_DELAYS))
            self.assertEqual(app.stop_btn.cget("state"), "normal")
            self.assertEqual(app.run_btn.cget("state"), "disabled")
            self.scheduled_retry(PROVIDER_RETRY_DELAYS[0])()
            for _ in range(9):
                if app._suite is None:
                    break
                app._poll()
            self.assertIsNone(app._suite)
            first = HEALTH_SUITE_CASES[0]
            self.assertEqual(seen[:4], [(first, True), (first, False), (first, True), (first, False)])
            self.assertEqual(len(seen), 18)
            manifest = json.loads(app._suite_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "finished")
            self.assertEqual(manifest["finished_runs"], 16)
            self.assertEqual(manifest["complete_runs"], 16)
            self.assertEqual([e["case_id"] for e in manifest["cases"]], [first, *HEALTH_SUITE_CASES])
            self.assertEqual([e["status"] for e in manifest["cases"]], ["error"] + ["finished"] * 8)
            from experiments import ExperimentStore

            sweeps = {row["sweep_id"] for row in ExperimentStore(root / "test.sqlite3").list_runs()}
            self.assertEqual(len(sweeps), 9)

    def test_a_case_failing_all_retries_is_skipped_and_the_suite_continues(self):
        app = self.app
        attempts = len(PROVIDER_RETRY_DELAYS) + 1
        with self.suite_fixture(provider_fail_calls=set(range(attempts))) as (_, _, seen, _, _, _, _):
            app._on_suite()
            app._poll()
            for delay in PROVIDER_RETRY_DELAYS:
                self.scheduled_retry(delay)()
                app._poll()
            for _ in range(10):
                if app._suite is None:
                    break
                app._poll()
            self.assertIsNone(app._suite)
            first = HEALTH_SUITE_CASES[0]
            self.assertEqual(seen[:attempts], [(first, True)] * attempts)
            self.assertEqual(seen[attempts:], [(case, stateful) for case in HEALTH_SUITE_CASES[1:] for stateful in (True, False)])
            manifest = json.loads(app._suite_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "finished")
            self.assertEqual(manifest["skipped_cases"], [first])
            self.assertEqual([e["status"] for e in manifest["cases"]],
                             ["error"] * attempts + ["finished"] * (len(HEALTH_SUITE_CASES) - 1))
            self.assertTrue(manifest["cases"][attempts - 1]["skipped"])
            self.assertEqual(manifest["cases"][attempts - 1]["discarded_runs"], 0)
            self.assertEqual(manifest["finished_runs"], 2 * (len(HEALTH_SUITE_CASES) - 1))
            self.assertIn("1 case(s) skipped after provider errors", app.suite_status.cget("text"))
            self.assertEqual(app.run_btn.cget("state"), "normal")

    def test_stop_during_provider_retry_pause_ends_the_suite_now(self):
        app = self.app
        with self.suite_fixture(provider_fail_calls={0}) as (_, _, seen, _, _, _, _), \
                patch.object(app, "after_cancel") as cancel:
            app._on_suite()
            app._poll()
            pending = app._suite_retry
            app._on_stop()
            cancel.assert_called_once_with(pending)
            self.assertIsNone(app._suite)
            self.assertEqual(seen, [(HEALTH_SUITE_CASES[0], True)])
            manifest = json.loads(app._suite_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "stopped")
            self.assertEqual(app.stop_btn.cget("state"), "disabled")

    def test_only_errors_raised_inside_provider_clients_count_as_provider_errors(self):
        for raiser, expected in ((provider_failure, True), (local_failure, False)):
            try:
                raiser()
            except TypeError as exc:
                self.assertIs(is_provider_error(exc), expected)
        self.assertFalse(is_provider_error(TypeError("never raised")))
        for status, expected in ((529, True), (500, True), (429, True), (400, False), (401, False), (404, False)):
            exc = TypeError("status")
            exc.status_code = status
            try:
                provider_failure()
            except TypeError as raised:
                exc = exc.with_traceback(raised.__traceback__)
            self.assertIs(is_provider_error(exc), expected, status)

    def test_health_suite_start_failure_restores_controls(self):
        with self.suite_fixture() as (_, _, seen, _, _, _, _):
            with patch.object(self.app, "_on_run", side_effect=OSError("Cannot open log")):
                self.app._on_suite()
            self.assertIsNone(self.app._suite)
            self.assertEqual(seen, [])
            manifest = json.loads(self.app._suite_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "error")
            self.assertEqual(manifest["cases"][0]["error"], "Cannot open log")
            self.assertEqual(self.app.run_btn.cget("state"), "normal")

    def test_suite_aggregates_stay_separate_and_show_only_selected_case(self):
        view = self.app.score_view
        for case_id in HEALTH_SUITE_CASES:
            for mode in ("stateful", "stateless"):
                payload = GuiPresentationTests().payload()
                payload.update(case_id=case_id, mode=mode)
                view.add_score(payload)
                view.add_aggregate({"case_id": case_id, "mode": mode, "n": 3, "agg": aggregate([payload["scores"]] * 3)})
        self.assertEqual(len(view.summaries), 16)
        self.assertEqual(len(view.aggregate_label.cget("text").splitlines()), 2)
        selected_case = HEALTH_SUITE_CASES[0]
        view.table.selection_set(selected_case + ":stateful:1")
        view._select()
        self.assertTrue(all(selected_case in line for line in view.aggregate_label.cget("text").splitlines()))

    def test_offline_sweep_preserves_both_modes_logs_scores_and_report(self):
        app = self.app
        seen_modes = []
        labels = {"door-a": "FAIL", "door-b": "PASS"}
        final = 'FINAL: {"verdict":"NON_COMPLIANT","violations":["door-a"]}'

        def make_agent(client, executor, **settings):
            self.assertEqual(settings["max_iterations"], MAX_MODEL_CALLS)
            self.assertEqual(settings["harness"], 2)
            self.assertIsInstance(executor, KernelCodeExecutor)
            self.assertIsNone(executor.skill_library)
            self.assertEqual(executor.skill_prompt_section(), "")
            seen_modes.append(executor.stateful)

            def check(rule, ifc, on_event, trace_attrs):
                on_event("iteration_start", {"n": 1, "total": 4})
                on_event("code", {"code": "report_labels(labels)"})
                on_event("output", {"output": "Recorded two element labels"})
                on_event("completion", {"status": "complete", "issues": [], "expected_anchors": 2, "labels_submitted": 2})
                on_event("done", {"verdict": final, "completion_status": "complete", "labels": 2, "iterations": 2, "prompt_tokens": 1000, "completion_tokens": 200})
                return AgentResult(verdict=final, iterations=2, verdict_label="NON_COMPLIANT", violations=["door-a"],
                    parse_ok=True, labels=labels, label_reports=1, completion_status="complete", harness=2,
                    prompt_tokens=1000, completion_tokens=200)

            return Mock(check=check)

        with TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            stack.enter_context(patch.dict("os.environ", {"EXPERIMENT_DB": str(root / "test.sqlite3"), "EXPERIMENTS": "1", "SKILLS": "1", "EXECUTION_RUNTIME": "inprocess"}))
            stack.enter_context(patch("experiment_recorder.audit_case", return_value={"status": "unverified", "issues": ["Synthetic UI fixture"]}))
            model = root / "unused.ifc"
            model.touch()
            app.ifc_var.set(str(model))
            app.mode_var.set("both")
            app.repeats_var.set(1)
            app.harness_var.set(2)
            app.current_case = "offline"
            app.current_gt = GroundTruth("offline", "rule", str(model), labels=labels)
            stack.enter_context(patch("gui.LOG_DIR", root))
            stack.enter_context(patch("gui.llm.load_llm", return_value=Mock(model="offline", provider="offline")))
            stack.enter_context(patch("gui.CodeActAgent", side_effect=make_agent))
            stack.enter_context(patch("gui.threading.Thread", ImmediateThread))
            for name in ("score_run", "score_sweep", "flush"):
                stack.enter_context(patch("gui.tracing." + name))
            stack.enter_context(patch("gui.tracing.trace_url", return_value=""))
            stack.enter_context(patch.object(app, "after"))
            app._on_run()
            app._poll()
            self.assertEqual(seen_modes, [True, False])
            self.assertEqual(len(app.score_view.table.get_children()), 2)
            self.assertEqual(app.result_view.title_label.cget("text"), "Violations reported")
            self.assertEqual(app.result_view.figures["input"].cget("text"), "1,000")
            self.assertEqual(app.run_btn.cget("state"), "normal")
            self.assertEqual(app.model_entry.cget("state"), "normal")
            self.assertEqual(app.views.get(), "Factual Report")
            self.assertTrue(app.current_report_path.exists())
            log = app.current_log_path.read_text(encoding="utf-8")
            self.assertIn("**Skills enabled:** False", log)
            self.assertIn("**Execution runtime:** kernel", log)
            self.assertEqual(log.count("**Score** (offline):"), 2)
            self.assertEqual(log.count(final), 2)
            self.assertNotIn("Score vs ground truth", app.console.get("1.0", "end"))
            from experiments import ExperimentStore

            stored = ExperimentStore(root / "test.sqlite3").list_runs()
            self.assertEqual(len(stored), 2)
            self.assertEqual({row["mode"] for row in stored}, {"stateful", "stateless"})
            self.assertTrue(all(row["status"] == "complete" for row in stored))
            self.assertTrue(all(not row["skills_enabled"] for row in stored))
            self.assertTrue(all(row["runtime_isolation"] == "kernel" for row in stored))


if __name__ == "__main__":
    unittest.main()