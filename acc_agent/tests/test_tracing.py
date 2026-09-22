import contextlib
import sys
import types
import unittest
from unittest.mock import MagicMock, Mock, patch

import tracing


class TracingIsolationTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.propagate = Mock(side_effect=lambda **kwargs: contextlib.nullcontext())
        self.stack.enter_context(patch.dict(sys.modules, {"langfuse": types.SimpleNamespace(propagate_attributes=self.propagate)}))
        self.client = Mock()
        self.stack.enter_context(patch("tracing.get_client", return_value=self.client))

    def contexts(self):
        return (
            lambda: tracing.check_run("fixture", input="rule", metadata={"case": "test"}),
            lambda: tracing.step("fixture"),
            lambda: tracing.tool("fixture"),
            lambda: tracing.generation("fixture", model="offline", input="request"),
        )

    def test_factory_and_entry_failures_do_not_prevent_or_repeat_work(self):
        for factory in self.contexts():
            for phase in ("factory", "enter"):
                with self.subTest(factory=factory, phase=phase):
                    self.client.reset_mock(side_effect=True)
                    manager = MagicMock()
                    self.client.start_as_current_observation.return_value = manager
                    if phase == "factory":
                        self.client.start_as_current_observation.side_effect = RuntimeError("offline tracing")
                    else:
                        manager.__enter__.side_effect = RuntimeError("broken context entry")
                    calls = []
                    with factory() as observation:
                        calls.append("agent ran")
                        tracing.finish(observation, output="result")
                    self.assertEqual(calls, ["agent ran"])

    def test_exit_failures_do_not_discard_success(self):
        manager = MagicMock()
        manager.__exit__.side_effect = RuntimeError("broken context exit")
        self.client.start_as_current_observation.return_value = manager
        for factory in self.contexts():
            with self.subTest(factory=factory):
                with factory():
                    result = "valid result"
                self.assertEqual(result, "valid result")

    def test_agent_error_is_not_suppressed_or_replaced_by_telemetry(self):
        for factory in self.contexts():
            for exit_failure in (False, True):
                with self.subTest(factory=factory, exit_failure=exit_failure):
                    manager = MagicMock()
                    manager.__exit__.return_value = True
                    if exit_failure:
                        manager.__exit__.side_effect = RuntimeError("telemetry exit failed")
                    self.client.start_as_current_observation.return_value = manager
                    original = ValueError("actual agent failure")
                    with self.assertRaises(ValueError) as raised:
                        with factory():
                            raise original
                    self.assertIs(raised.exception, original)
                    self.assertIs(manager.__exit__.call_args.args[1], original)

    def test_propagation_context_is_also_optional(self):
        manager = MagicMock()
        manager.__exit__.side_effect = RuntimeError("propagation exit failed")
        self.propagate.side_effect = None
        self.propagate.return_value = manager
        self.client.start_as_current_observation.return_value = contextlib.nullcontext(tracing._Noop())
        with tracing.check_run():
            pass
        self.propagate.side_effect = RuntimeError("propagation unavailable")
        with tracing.check_run():
            pass

    def test_fallback_never_swallows_body_error(self):
        self.client.start_as_current_observation.side_effect = RuntimeError("trace unavailable")
        for factory in self.contexts():
            with self.subTest(factory=factory), self.assertRaisesRegex(ValueError, "agent"):
                with factory():
                    raise ValueError("agent failed")

    def test_interrupt_propagates_unchanged(self):
        self.client.start_as_current_observation.return_value = MagicMock()
        with self.assertRaises(KeyboardInterrupt):
            with tracing.step("fixture"):
                raise KeyboardInterrupt()

    def test_disabled_tracing_stays_noop(self):
        with patch("tracing.get_client", return_value=None):
            for factory in self.contexts():
                with factory() as observation:
                    self.assertIsInstance(observation, tracing._Noop)


if __name__ == "__main__":
    unittest.main()