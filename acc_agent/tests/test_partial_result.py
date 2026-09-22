import contextlib
import io
import unittest
from unittest.mock import patch

from agent import CodeActAgent
from kernel_executor import KernelCodeExecutor
from .test_agent import ScriptedClient, reply, python_call


class PartialResultTests(unittest.TestCase):
    def executor(self, **settings):
        executor = KernelCodeExecutor(timeout=30, **settings)
        self.addCleanup(executor.close)
        return executor

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("tracing.get_client", return_value=None))
        self.stack.enter_context(patch("agent.discover_scope", return_value=({"anchor"}, "fixture scope")))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def client(self, first_reply, error):
        first_reply.usage_metadata = {"input_tokens": 1050, "output_tokens": 100, "total_tokens": 1150,
                                      "input_token_details": {"cache_read": 900, "cache_creation": 50}}
        return ScriptedClient([first_reply, error])

    def test_later_request_failure_keeps_prefix_usage_and_execution_evidence(self):
        failure = RuntimeError("second request failed")
        for stateful in (True, False):
            with self.subTest(stateful=stateful):
                client = self.client(reply(python_call('report_labels({"anchor":"PASS"})\nprint("measured")')), failure)
                agent = CodeActAgent(client, self.executor(stateful=stateful), max_iterations=3, env_primer=False)
                with self.assertRaises(RuntimeError) as raised:
                    agent.check("fixture", "unused.ifc")
                self.assertIs(raised.exception, failure)
                partial = agent.partial_result
                self.assertEqual(partial.prompt_tokens, 1050)
                self.assertEqual(partial.completion_tokens, 100)
                self.assertEqual(partial.cache_read_input_tokens, 900)
                self.assertFalse(partial.usage_complete)
                self.assertEqual(partial.executions, 1)
                self.assertEqual(partial.labels, {"anchor": "PASS"})
                self.assertEqual(partial.llm_calls[1]["status"], "error")
                self.assertFalse(partial.llm_calls[1]["usage_reported"])
                self.assertIn("measured", partial.execution_records[0]["output"])
                self.assertTrue(any(entry["role"] == "tool" and "measured" in entry["content"] for entry in partial.transcript))
                self.assertFalse(partial.parse_ok)

    def test_planning_usage_is_kept_when_first_iteration_request_fails(self):
        agent = CodeActAgent(self.client(reply(text="Inspect, then report."), RuntimeError("failed")), self.executor(), harness=2)
        with self.assertRaises(RuntimeError):
            agent.check("fixture", "unused.ifc")
        self.assertEqual(agent.partial_result.llm_calls[0]["phase"], "plan")
        self.assertEqual(agent.partial_result.prompt_tokens, 1050)
        self.assertEqual(agent.partial_result.executions, 0)

    def test_interruption_keeps_progress_without_suppressing_interrupt(self):
        agent = CodeActAgent(self.client(reply(python_call('print(1)')), KeyboardInterrupt()), self.executor())
        with self.assertRaises(KeyboardInterrupt):
            agent.check("fixture", "unused.ifc")
        self.assertEqual(agent.partial_result.prompt_tokens, 1050)
        self.assertEqual(agent.partial_result.completion_status, "incomplete")

    def test_finalization_failure_retains_main_iteration_usage(self):
        failure = RuntimeError("finalization failed")
        agent = CodeActAgent(self.client(reply(python_call('print(1)')), failure), self.executor(), max_iterations=2)
        with self.assertRaises(RuntimeError) as raised:
            agent.check("fixture", "unused.ifc")
        self.assertIs(raised.exception, failure)
        partial = agent.partial_result
        self.assertEqual(partial.finalization_attempts, 0)
        self.assertEqual(partial.llm_calls[1]["phase"], "iteration 2")
        self.assertFalse(partial.usage_complete)
        self.assertEqual(partial.prompt_tokens, 1050)


if __name__ == "__main__":
    unittest.main()