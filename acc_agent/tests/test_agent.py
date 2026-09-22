import unittest
from unittest.mock import patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from agent import CodeActAgent, build_system_prompt
from kernel_executor import KernelCodeExecutor


def python_call(code, call_id="execute"):
    return {"name": "run_python", "args": {"code": code}, "id": call_id}


def final_call(verdict="COMPLIANT", violations=None, reason="", call_id="final"):
    return {"name": "FinalReport", "args": {"verdict": verdict, "violations": violations or [], "reason": reason}, "id": call_id}


def reply(*calls, text=""):
    return AIMessage(content=text, tool_calls=list(calls), usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})


class ScriptedClient(BaseChatModel):
    replies: list = Field(default_factory=list)
    requests: list = Field(default_factory=list)
    bindings: list = Field(default_factory=list)
    index: int = 0

    def __init__(self, replies=None, **kwargs):
        super().__init__(replies=list(replies or []), **kwargs)

    @property
    def _llm_type(self):
        return "offline-tool-calling"

    def bind_tools(self, tools, **kwargs):
        self.bindings.append(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.requests.append(messages)
        response = self.replies[self.index]
        self.index += 1
        if isinstance(response, BaseException):
            raise response
        return ChatResult(generations=[ChatGeneration(message=response)])


class AgentRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tracing = patch("tracing.get_client", return_value=None)
        self.tracing.start()
        self.addCleanup(self.tracing.stop)

    def run_script(self, replies, stateful=True, budget=None, anchors=None, harness=1):
        executor = KernelCodeExecutor(stateful=stateful, timeout=30)
        self.addCleanup(executor.close)
        model = ScriptedClient(replies)
        agent = CodeActAgent(model, executor, max_iterations=budget or len(replies), env_primer=False, harness=harness)
        with patch("agent.discover_scope", return_value=({"anchor"} if anchors is None else anchors, "public test scope")):
            return agent.check("Judge anchor", "not-opened.ifc")

    def test_committed_result_in_both_modes(self):
        for stateful in (True, False):
            with self.subTest(stateful=stateful):
                result = self.run_script([reply(python_call('report_labels({"anchor":"FAIL"})')),
                                          reply(final_call("NON_COMPLIANT", ["anchor"]))], stateful)
                self.assertEqual(result.completion_status, "complete")
                self.assertEqual(result.labels, {"anchor": "FAIL"})
                self.assertEqual(result.violations, ["anchor"])
                self.assertEqual(result.executions, 1)
                self.assertEqual(result.iterations, 2)
                self.assertEqual(result.prompt_tokens, 200)
                self.assertEqual(len(result.tool_schemas), 2)
                self.assertTrue(any(entry["role"] == "tool" for entry in result.transcript))

    def test_inconsistent_final_is_rejected_then_corrected(self):
        result = self.run_script([reply(python_call('report_labels({"anchor":"FAIL"})')),
                                  reply(final_call()), reply(final_call("NON_COMPLIANT", ["anchor"]))])
        self.assertEqual(result.completion_status, "complete")
        self.assertEqual(result.finalization_attempts, 2)
        self.assertTrue(any("must equal" in str(entry["content"]) for entry in result.transcript))

    def test_missing_labels_and_scope_are_repaired(self):
        result = self.run_script([reply(final_call()), reply(python_call('report_labels({"anchor":"PASS"})')),
                                  reply(final_call()), reply(python_call('report_labels({"anchor":"PASS","second":"ALERT"})')),
                                  reply(final_call())], anchors={"anchor", "second"})
        self.assertEqual(result.completion_status, "complete")
        self.assertEqual(result.expected_anchors, 2)

    def test_failed_execution_invalidates_labels_until_resubmission(self):
        for stateful in (True, False):
            with self.subTest(stateful=stateful):
                result = self.run_script([reply(python_call('report_labels({"anchor":"PASS"})')),
                                          reply(python_call('raise ValueError("failed")')),
                                          reply(python_call('print("continuing")')), reply(final_call()),
                                          reply(python_call('report_labels({"anchor":"PASS"})')), reply(final_call())], stateful)
                self.assertEqual(result.completion_status, "complete")
                self.assertEqual(result.label_reports, 2)
                self.assertTrue(any("No report_labels" in str(entry["content"]) for entry in result.transcript))

    def test_budget_does_not_add_finalization_turns(self):
        result = self.run_script([reply(python_call('print(123)')), reply(final_call())], budget=2)
        self.assertEqual(result.iterations, 2)
        self.assertEqual(result.completion_status, "incomplete")
        self.assertFalse(result.parse_ok)
        self.assertTrue(result.usage_complete)
        self.assertIn("Budget", result.reason)

    def test_bundled_final_cannot_accept_prior_labels_after_mutation(self):
        result = self.run_script([reply(python_call('report_labels({"anchor":"PASS"})')),
                                  reply(python_call('report_labels({"anchor":"FAIL"})'), final_call()),
                                  reply(python_call('report_labels({"anchor":"FAIL"})')),
                                  reply(final_call("NON_COMPLIANT", ["anchor"]))])
        self.assertEqual(result.executions, 2)
        self.assertEqual(result.verdict_label, "NON_COMPLIANT")
        self.assertEqual(result.iterations, 4)
        first_tool = next(entry for entry in result.transcript if entry["role"] == "tool")
        self.assertEqual(first_tool["status"], "success")

    def test_last_call_with_code_and_final_is_incomplete(self):
        result = self.run_script([reply(python_call('report_labels({"anchor":"PASS"})'), final_call())])
        self.assertEqual(result.labels, {})
        self.assertEqual(result.executions, 0)
        self.assertFalse(result.parse_ok)

    def test_multiple_python_calls_are_ordered_and_modes_remain_distinct(self):
        for stateful in (True, False):
            with self.subTest(stateful=stateful):
                result = self.run_script([reply(python_call('value = 7', "first"), python_call('print(value)', "second")),
                                          reply(final_call("UNKNOWN", reason="No supported judgment was completed."))], stateful)
                second = result.execution_records[1]
                self.assertEqual(second["error"], not stateful)
                self.assertIn("7" if stateful else "NameError", second["output"])

    def test_invalid_tool_arguments_never_execute(self):
        malformed = {"name": "run_python", "args": {"wrong": "print(1)"}, "id": "bad"}
        result = self.run_script([reply(malformed), reply(final_call("UNKNOWN", reason="No measurements obtained."))])
        self.assertEqual(result.executions, 0)
        self.assertEqual(result.completion_status, "abstained")

    def test_planning_uses_same_agent_and_budget(self):
        result = self.run_script([reply(text="Inspect scope, measure, label, verify."),
                                  reply(python_call('report_labels({"anchor":"PASS"})')), reply(final_call())], harness=2)
        self.assertEqual(result.plan, "Inspect scope, measure, label, verify.")
        self.assertEqual(result.iterations, 3)
        self.assertEqual(result.llm_calls[0]["phase"], "plan")
        self.assertEqual(result.completion_status, "complete")

    def test_reference_feedback_is_retired(self):
        with self.assertRaisesRegex(ValueError, "H3"):
            CodeActAgent(ScriptedClient(), None, harness=3)

    def test_primer_is_optional_and_describes_geometry_units(self):
        for stateful in (True, False):
            prompt = " ".join(build_system_prompt("model.ifc", stateful).split())
            self.assertIn("are in metres by default", prompt)
            self.assertIn("Do NOT apply the model unit scale", prompt)
            self.assertNotIn("Mesh vertices", build_system_prompt("model.ifc", stateful, False))


if __name__ == "__main__":
    unittest.main()