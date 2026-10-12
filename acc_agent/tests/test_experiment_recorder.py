import unittest
import contextlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from agent import AgentResult
from experiment_recorder import RunTicket, SweepRecorder
from experiments import ExperimentStore
from ground_truth import GroundTruth
from .test_agent import ScriptedClient, reply, python_call


class RecorderTests(unittest.TestCase):
    def test_retired_library_cannot_change_new_run_metadata_or_prompt(self):
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"EXPERIMENTS": "1", "SKILLS": "1"}):
            path = Path(directory) / "fixture.ifc"
            path.write_text("fixture", encoding="utf-8")
            store = ExperimentStore(Path(directory) / "test.sqlite3")
            library = Mock(enabled=True)
            recorder = SweepRecorder(
                entrypoint="test", requested=1, case=None, rule="rule", ifc_path=path,
                client=Mock(provider="offline", model="offline", max_tokens=8000),
                max_iterations=3, reasoning=False, env_primer=False, library=library,
                output_limit=6000, store=store,
            )
            ticket = recorder.start_run("stateful", 1, 1)
            self.assertIsNotNone(ticket, recorder.last_error)
            self.assertIsNone(recorder.library)
            self.assertFalse(ticket.configuration["skills_enabled"])
            self.assertEqual(ticket.initial_skills, {"enabled": False, "manifest": {}, "files": {}})
            self.assertNotIn("skill_library.py", ticket.configuration["core_files"])
            ticket.observe("output", {"output": "[skill saved]"})
            self.assertEqual(ticket.skill_saves, 0)
            recorder.finish_run(ticket, AgentResult("FINAL: {}", 1, completion_status="incomplete"))
            recorder.finish()
            self.assertFalse(store.list_runs()[0]["skills_enabled"])
            self.assertEqual(library.mock_calls, [])

    def test_effective_kernel_settings_recorded_despite_legacy_runtime_argument(self):
        settings = [
            (600.0, 60.0, "0"),
            (1.0, 60.0, "0"),
            (600.0, 120.0, "0"),
            (600.0, 60.0, "123"),
            (600.0, 60.0, "0"),
        ]
        with TemporaryDirectory() as directory, patch.dict("os.environ", {
            "EXPERIMENTS": "1", "EXEC_TIMEOUT": "999",
            "EXEC_STARTUP_TIMEOUT": "999", "EXEC_HASH_SEED": "999", "EXECUTION_RUNTIME": "inprocess",
        }):
            path = Path(directory) / "fixture.ifc"
            path.write_text("fixture", encoding="utf-8")
            store = ExperimentStore(Path(directory) / "test.sqlite3")
            for runtime in ("kernel", "inprocess"):
                configurations = []
                for timeout, startup_timeout, hash_seed in settings:
                    with self.subTest(runtime=runtime, timeout=timeout,
                                      startup_timeout=startup_timeout, hash_seed=hash_seed), patch.multiple(
                        "kernel_executor", DEFAULT_TIMEOUT=timeout,
                        STARTUP_TIMEOUT=startup_timeout, HASH_SEED=hash_seed,
                    ):
                        recorder = SweepRecorder(
                            entrypoint="test", requested=1, case=None, rule="rule", ifc_path=path,
                            client=Mock(provider="offline", model="offline", max_tokens=8000),
                            max_iterations=3, reasoning=False, env_primer=False, library=None,
                            output_limit=6000, store=store, runtime=runtime,
                        )
                        ticket = recorder.start_run("stateful", 1, 1)
                        self.assertIsNotNone(ticket, recorder.last_error)
                        expected = {
                            "execution_timeout_seconds": timeout,
                            "startup_timeout_seconds": startup_timeout,
                            "python_hash_seed": hash_seed,
                        }
                        self.assertEqual(ticket.configuration["runtime_isolation"], "kernel")
                        self.assertEqual(ticket.configuration["kernel_settings"], expected)
                        recorder.finish_run(ticket, AgentResult("FINAL: {}", 1, completion_status="incomplete"))
                        recorder.finish()
                        row = next(row for row in store.list_runs() if row["id"] == ticket.id)
                        configurations.append(row["configuration_id"])
                self.assertEqual(len(set(configurations)), 4)
                self.assertEqual(configurations[0], configurations[-1])

    def test_unreported_usage_is_null_not_a_measured_zero(self):
        import io
        from agent import CodeActAgent
        from kernel_executor import KernelCodeExecutor
        unreported = reply(python_call("print(1)"))
        unreported.usage_metadata = None
        for turns in ([RuntimeError("first request failed")],
                  [unreported, RuntimeError("later request failed")]):
            with self.subTest(turns=len(turns)), TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
                root = Path(directory)
                model = root / "fixture.ifc"
                model.write_text("fixture", encoding="utf-8")
                store = ExperimentStore(root / "fixture.sqlite3")
                stack.enter_context(patch.dict("os.environ", {"EXPERIMENTS": "1"}))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                stack.enter_context(patch("tracing.get_client", return_value=None))
                stack.enter_context(patch("agent.discover_scope", return_value=({"anchor"}, "fixture scope")))
                client = ScriptedClient(turns, metadata={"provider": "offline", "model": "fixture"})
                recorder = SweepRecorder(entrypoint="test", requested=1, case=None, rule="fixture", ifc_path=model,
                    client=client, max_iterations=3, reasoning=False, env_primer=False, library=None, output_limit=6000, store=store)
                ticket = recorder.start_run("stateful", 1, 1)
                executor = KernelCodeExecutor(timeout=30)
                stack.callback(executor.close)
                agent = CodeActAgent(client, executor)
                with self.assertRaises(RuntimeError):
                    agent.check("fixture", str(model))
                recorder.finish_run(ticket, agent.partial_result, error="request failed")
                row = store.list_runs()[0]
                self.assertIsNone(row["prompt_tokens"])
                self.assertIsNone(row["completion_tokens"])
                self.assertFalse(row["usage_complete"])

    def test_failure_after_returned_call_preserves_tokens_and_partial_transcript(self):
        import json
        from evaluate import _run_once
        first = reply(python_call('print("executed first step")'))
        first.usage_metadata = {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100,
                                "input_token_details": {"cache_read": 900}}

        with TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            model = root / "fixture.ifc"
            model.write_text("fixture", encoding="utf-8")
            store = ExperimentStore(root / "fixture.sqlite3")
            stack.enter_context(patch.dict("os.environ", {"EXPERIMENTS": "1"}))
            stack.enter_context(patch("evaluate.PROJECT_DIR", root))
            stack.enter_context(patch("tracing.get_client", return_value=None))
            stack.enter_context(patch("agent.discover_scope", return_value=({"anchor"}, "fixture scope")))
            client = ScriptedClient([first, RuntimeError("second call failed")], metadata={"provider": "offline", "model": "fixture"})
            recorder = SweepRecorder(entrypoint="test", requested=1, case=None, rule="fixture", ifc_path=model,
                client=client, max_iterations=3, reasoning=False, env_primer=False, library=None, output_limit=6000, store=store)
            with self.assertRaisesRegex(RuntimeError, "second call failed"):
                _run_once(client, "fixture", model, "stateful", 3, False, set(), recorder=recorder)
            row = store.list_runs()[0]
            self.assertEqual(row["status"], "error")
            self.assertEqual(row["prompt_tokens"], 1000)
            self.assertEqual(row["completion_tokens"], 100)
            self.assertFalse(row["usage_complete"])
            saved = json.loads(Path(row["log_path"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["llm_calls"][1]["status"], "error")
            self.assertIn("executed first step", saved["execution_records"][0]["output"])
            summary = store.summaries()[0]
            self.assertEqual(summary["known_input_tokens"], 1000)
            self.assertEqual(summary["prompt_tokens_n"], 0)
            self.assertEqual(summary["partial_usage_runs"], 1)

    def test_structured_error_flags_override_printed_traceback_text(self):
        ticket = RunTicket("fixture", 0, {})
        ticket.observe("output", {"output": "traceback omitted", "error": True, "truncated": True})
        ticket.observe("output", {"output": "Traceback (most recent call last):\n... [truncated 3 characters]", "error": False, "truncated": False})
        self.assertEqual(ticket.errors, 1)
        self.assertEqual(ticket.truncations, 1)

    def test_successful_evaluation_persists_transcript_link_and_metrics(self):
        import json
        from evaluate import _run_once

        with TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            path = root / "fixture.ifc"
            path.write_text("fixture", encoding="utf-8")
            store = ExperimentStore(root / "test.sqlite3")
            stack.enter_context(patch.dict("os.environ", {"EXPERIMENTS": "1"}))
            stack.enter_context(patch("evaluate.PROJECT_DIR", root))
            stack.enter_context(patch("evaluate.tracing.score_run"))
            stack.enter_context(patch("evaluate.tracing.trace_url", return_value=""))
            result = AgentResult('FINAL: {"verdict":"COMPLIANT","violations":[]}', 2,
                verdict_label="COMPLIANT", parse_ok=True, labels={"one": "PASS"}, expected_anchors=1,
                completion_status="complete", transcript=[{"role": "user", "content": "fixture evidence"}])
            agent = stack.enter_context(patch("evaluate.CodeActAgent"))
            agent.return_value.check.return_value = result
            recorder = SweepRecorder(entrypoint="eval", requested=1, case=None, rule="rule", ifc_path=path,
                client=Mock(provider="offline", model="offline", max_tokens=8000), max_iterations=3,
                reasoning=False, env_primer=False, library=None, output_limit=6000, store=store)
            _, metadata = _run_once(Mock(), "rule", path, "stateful", 3, False, set(), gt_labels={"one": "PASS"}, recorder=recorder)
            recorder.finish()
            row = store.list_runs()[0]
            self.assertEqual(row["id"], metadata["experiment_run_id"])
            self.assertEqual(row["union_accuracy"], 1.0)
            with store.connection() as connection:
                details = json.loads(connection.execute("SELECT details FROM runs WHERE id=?", (row["id"],)).fetchone()["details"])
            self.assertEqual(details["messages"], result.transcript)
            self.assertEqual(details["agent_protocol"], "langchain-codeact-v5")
            transcript = json.loads(Path(row["log_path"]).read_text(encoding="utf-8"))
            self.assertEqual(transcript["completion_status"], "complete")
            self.assertEqual(transcript["messages"], result.transcript)

    def test_ending_fingerprint_failure_preserves_result(self):
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"EXPERIMENTS": "1"}):
            path = Path(directory) / "model.ifc"
            path.write_text("fixture", encoding="utf-8")
            store = ExperimentStore(Path(directory) / "test.sqlite3")
            recorder = SweepRecorder(entrypoint="test", requested=1, case=None, rule="rule", ifc_path=path,
                client=Mock(provider="offline", model="offline", max_tokens=8000), max_iterations=3,
                reasoning=False, env_primer=False, library=None, output_limit=6000, store=store, warning=Mock())
            ticket = recorder.start_run("stateful", 1, 1)
            with patch("experiment_recorder.skills_snapshot", side_effect=OSError("snapshot unavailable")):
                recorder.finish_run(ticket, AgentResult("FINAL: {}", 1, completion_status="incomplete"))
            recorder.finish()
            row = store.list_runs()[0]
            self.assertEqual(row["status"], "incomplete")
            self.assertEqual(row["context_changed"], 1)
            self.assertIn("snapshot unavailable", row["details"])

    def test_skill_mutation_splits_later_configuration(self):
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"EXPERIMENTS": "1"}):
            path = Path(directory) / "model.ifc"
            path.write_text("fixture", encoding="utf-8")
            store = ExperimentStore(Path(directory) / "test.sqlite3")
            recorder = SweepRecorder(entrypoint="test", requested=2, case=None, rule="rule", ifc_path=path,
                client=Mock(provider="offline", model="offline", max_tokens=8000), max_iterations=3,
                reasoning=True, env_primer=False, library=None, output_limit=6000, store=store)
            snapshots = [{"enabled": True, "files": {}}, {"enabled": True, "files": {"helper": "hash"}}]
            with patch("experiment_recorder.skills_snapshot", side_effect=[snapshots[0], snapshots[1], snapshots[1], snapshots[1]]):
                first = recorder.start_run("stateful", 1, 1)
                recorder.finish_run(first, AgentResult("FINAL: {}", 1, completion_status="incomplete"))
                second = recorder.start_run("stateful", 2, 1)
                recorder.finish_run(second, AgentResult("FINAL: {}", 1, completion_status="incomplete"))
            rows = store.list_runs()
            self.assertEqual(len({row["configuration_id"] for row in rows}), 2)
            self.assertEqual(sum(row["context_changed"] for row in rows), 1)

    def test_api_error_closes_evaluation_run_and_sweep(self):
        from evaluate import _run_once

        with TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            path = Path(directory) / "fixture.ifc"
            path.write_text("fixture", encoding="utf-8")
            store = ExperimentStore(Path(directory) / "test.sqlite3")
            stack.enter_context(patch.dict("os.environ", {"EXPERIMENTS": "1"}))
            recorder = SweepRecorder(entrypoint="test", requested=1, case=None, rule="rule", ifc_path=path,
                client=Mock(provider="offline", model="offline", max_tokens=8000), max_iterations=3,
                reasoning=False, env_primer=False, library=None, output_limit=6000, store=store)
            agent = stack.enter_context(patch("evaluate.CodeActAgent"))
            agent.return_value.check.side_effect = RuntimeError("provider failed")
            with self.assertRaises(RuntimeError):
                _run_once(Mock(), "rule", path, "stateless", 3, False, set(), recorder=recorder)
            self.assertEqual(store.list_runs()[0]["status"], "error")
            self.assertEqual(store.list_sweeps()[0]["status"], "error")
            self.assertIsNone(store.list_runs()[0]["f1"])

    def test_snapshot_events_lifecycle_and_skill_changes(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "model.ifc"
            path.write_text("fixture", encoding="utf-8")
            store = ExperimentStore(Path(directory) / "test.sqlite3")
            case = GroundTruth("test", "rule", str(path), labels={"one": "PASS"})
            with patch("experiment_recorder.audit_case", return_value={"status": "relations-checked"}), patch.dict("os.environ", {"EXPERIMENTS": "1"}):
                recorder = SweepRecorder(entrypoint="test", requested=1, case=case, rule="rule", ifc_path=path,
                    client=Mock(provider="offline", model="offline", max_tokens=8000), max_iterations=3,
                    reasoning=True, env_primer=True, library=None, output_limit=6000, store=store)
                ticket = recorder.start_run("stateful", 1, 1)
                self.assertEqual(store.list_runs()[0]["status"], "running")
                ticket.observe("code", {"code": "irrelevant"})
                ticket.observe("output", {"output": "Traceback (most recent call last):\nValueError: x\n... [truncated 2 characters]"})
                result = AgentResult("FINAL: {}", 2, completion_status="incomplete", labels={"one": "PASS"})
                recorder.finish_run(ticket, result)
                recorder.finish()
            row = store.list_runs()[0]
            self.assertEqual(row["status"], "incomplete")
            self.assertEqual(row["error_count"], 1)
            self.assertEqual(row["truncations"], 1)
            self.assertIsNone(row["f1"])
            self.assertNotIn("API_KEY", row["configuration"])

    def test_initialization_failure_does_not_break_check(self):
        warning = Mock()
        with patch("experiment_recorder.ExperimentStore", side_effect=OSError("disk unavailable")):
            recorder = SweepRecorder(entrypoint="test", requested=1, case=None, rule="rule", ifc_path="none",
                client=Mock(), max_iterations=3, reasoning=False, env_primer=False, library=None,
                output_limit=6000, warning=warning)
        self.assertIsNone(recorder.start_run("stateful", 1, 1))
        warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()