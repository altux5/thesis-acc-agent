import unittest
from unittest.mock import patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
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

    def test_model_sees_plain_output_with_one_traceback(self):
        executor = KernelCodeExecutor(timeout=30)
        self.addCleanup(executor.close)
        model = ScriptedClient([reply(python_call('print("line one\\nline two")\nraise ValueError("boom")')),
                                reply(final_call("UNKNOWN", reason="Execution failed."))])
        with patch("agent.discover_scope", return_value=({"anchor"}, "public test scope")):
            CodeActAgent(model, executor, max_iterations=2, env_primer=False).check("Judge anchor", "not-opened.ifc")
        tool_message = next(message for message in model.requests[1] if isinstance(message, ToolMessage))
        self.assertTrue(tool_message.content.startswith("line one\nline two"))
        self.assertEqual(tool_message.content.count("ValueError: boom"), 1)
        self.assertTrue(tool_message.artifact["error"])
        self.assertIn("ValueError: boom", tool_message.artifact["error_text"])

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

    def test_early_abstention_is_rejected_while_calls_remain(self):
        result = self.run_script([reply(python_call('print("schema")')),
                                  reply(final_call("UNKNOWN", reason="Reading the IFC.")),
                                  reply(python_call('report_labels({"anchor":"PASS"})')), reply(final_call())])
        self.assertEqual(result.completion_status, "complete")
        self.assertEqual(result.finalization_attempts, 2)
        self.assertTrue(any("only on the final model call" in str(entry["content"]) for entry in result.transcript))

    def test_planning_uses_same_agent_and_budget(self):
        result = self.run_script([reply(text="Inspect scope, measure, label, verify."),
                                  reply(python_call('report_labels({"anchor":"PASS"})')), reply(final_call())], harness=2)
        self.assertEqual(result.plan, "Inspect scope, measure, label, verify.")
        self.assertEqual(result.iterations, 3)
        self.assertEqual(result.llm_calls[0]["phase"], "plan")
        self.assertEqual(result.completion_status, "complete")

    def test_planning_with_one_extra_call_leaves_the_full_working_budget(self):
        # heldout_h2_minimax_21: the plan is call 1 of 21, so 20 calls remain for code and FinalReport.
        work = [reply(python_call(f"print({index})", call_id=f"execute{index}")) for index in range(18)]
        result = self.run_script([reply(text="Plan."), *work,
                                  reply(python_call('report_labels({"anchor":"PASS"})', call_id="label")),
                                  reply(final_call())], budget=21, harness=2)
        self.assertEqual(result.completion_status, "complete")
        self.assertEqual(result.iterations, 21)
        self.assertEqual(result.executions, 19)
        self.assertEqual([call["phase"] for call in result.llm_calls][:2], ["plan", "iteration 2"])
        self.assertIn("You have 21 model calls in total", " ".join(str(result.transcript[0]["content"]).split()))

    def test_reference_feedback_is_retired(self):
        with self.assertRaisesRegex(ValueError, "H3"):
            CodeActAgent(ScriptedClient(), None, harness=3)


    def test_primer_is_optional_and_describes_geometry_units(self):
        for stateful in (True, False):
            prompt = " ".join(build_system_prompt("model.ifc", stateful).split())
            self.assertIn("are in metres by default", prompt)
            self.assertIn("Do NOT apply the model unit scale", prompt)
            self.assertIn("import ifcopenshell.util.element, ifcopenshell.util.unit", prompt)
            self.assertNotIn("Mesh vertices", build_system_prompt("model.ifc", stateful, False))

    def test_budget_is_stated_counted_and_announced_before_the_end(self):
        executor = KernelCodeExecutor(timeout=30)
        self.addCleanup(executor.close)
        model = ScriptedClient([reply(python_call('print("first")')), reply(python_call('print("second")')),
                                reply(python_call('report_labels({"anchor":"PASS"})')), reply(final_call()), reply(final_call())])
        with patch("agent.discover_scope", return_value=({"anchor"}, "public test scope")):
            result = CodeActAgent(model, executor, max_iterations=6, env_primer=False).check("Judge anchor", "not-opened.ifc")
        self.assertEqual(result.completion_status, "complete")
        self.assertIn("You have 6 model calls in total", " ".join(model.requests[0][0].content.split()))
        tool_message = next(message for message in model.requests[1] if isinstance(message, ToolMessage))
        self.assertTrue(tool_message.content.endswith("[Model call 1 of 6 used; 5 remain.]"))
        self.assertEqual(result.execution_records[0]["output"], "first")
        self.assertTrue(all(record["seconds"] >= 0 for record in result.execution_records + result.llm_calls))
        wrap_up = [message.content for message in model.requests[2] if "4 calls remain" in str(message.content)]
        self.assertEqual(len(wrap_up), 1)
        self.assertIn("Model call 3 of 6", wrap_up[0])
        self.assertFalse(any("calls remain" in str(message.content) for message in model.requests[1] if message.type == "human"))

    def test_text_without_a_tool_call_returns_to_the_model(self):
        result = self.run_script([reply(text="All doors pass."), reply(python_call('report_labels({"anchor":"PASS"})')),
                                  reply(final_call())])
        self.assertEqual(result.completion_status, "complete")
        self.assertEqual(result.iterations, 3)
        self.assertTrue(any("No tool call received" in str(entry["content"]) for entry in result.transcript))

    def test_malformed_tool_call_is_removed_and_the_model_asked_to_resend(self):
        broken = AIMessage(content="", invalid_tool_calls=[{"name": "run_python", "args": '{"code": "print(', "id": "bad",
                                                            "error": "invalid JSON", "type": "invalid_tool_call"}],
                           usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
        model = ScriptedClient([broken, reply(python_call('report_labels({"anchor":"PASS"})')), reply(final_call())])
        executor = KernelCodeExecutor(timeout=30)
        self.addCleanup(executor.close)
        with patch("agent.discover_scope", return_value=({"anchor"}, "public test scope")):
            result = CodeActAgent(model, executor, max_iterations=3, env_primer=False).check("Judge anchor", "not-opened.ifc")
        self.assertEqual(result.completion_status, "complete")
        self.assertEqual(result.llm_calls[0]["malformed_tool_calls"], 1)
        resent = model.requests[1]
        self.assertFalse(any(getattr(message, "invalid_tool_calls", None) for message in resent))
        self.assertIn("could not be parsed", str(resent[-1].content))
        self.assertNotIn("No tool call received", " ".join(str(message.content) for message in resent))

    def test_text_on_the_last_call_leaves_the_run_incomplete(self):
        result = self.run_script([reply(python_call('report_labels({"anchor":"PASS"})')), reply(text="Done: compliant.")])
        self.assertEqual(result.completion_status, "incomplete")
        self.assertFalse(result.parse_ok)
        self.assertIn("Budget", result.reason)

    def test_last_call_accepts_only_final_report_and_runs_no_code(self):
        model = ScriptedClient([reply(python_call('report_labels({"anchor":"PASS"})')),
                                reply(python_call('report_labels({"anchor":"FAIL"})'))])
        executor = KernelCodeExecutor(timeout=30)
        self.addCleanup(executor.close)
        with patch("agent.discover_scope", return_value=({"anchor"}, "public test scope")):
            result = CodeActAgent(model, executor, max_iterations=2, env_primer=False).check("Judge anchor", "not-opened.ifc")
        from langchain_core.utils.function_calling import convert_to_openai_tool

        def names(tools):
            return [convert_to_openai_tool(tool)["function"]["name"] for tool in tools]

        self.assertEqual(names(model.bindings[0]), ["run_python", "FinalReport"])
        self.assertEqual(names(model.bindings[-1]), ["run_python", "FinalReport"])
        self.assertEqual(result.executions, 1)
        self.assertEqual(result.labels, {"anchor": "PASS"})
        self.assertEqual(result.completion_status, "incomplete")
        self.assertTrue(any("only FinalReport is accepted" in str(entry["content"]) for entry in result.transcript))

    def test_pending_labels_block_a_decided_verdict_but_allow_final_unknown(self):
        result = self.run_script([reply(python_call('report_labels({"anchor":"PASS","second":"pending"})')),
                                  reply(final_call()),
                                  reply(final_call("UNKNOWN", reason="Element second is unresolved."))],
                                 anchors={"anchor", "second"})
        self.assertEqual(result.labels, {"anchor": "PASS", "second": "PENDING"})
        self.assertEqual(result.completion_status, "abstained")
        self.assertTrue(any("still PENDING" in str(entry["content"]) for entry in result.transcript))

    def test_resolved_pending_labels_complete_normally(self):
        result = self.run_script([reply(python_call('report_labels({"anchor":"PENDING"})')),
                                  reply(python_call('report_labels({"anchor":"FAIL"})')),
                                  reply(final_call("NON_COMPLIANT", ["anchor"]))])
        self.assertEqual(result.completion_status, "complete")


class FileSystemConditionTests(unittest.TestCase):
    """The file-system condition, and the guard that the frozen agent is unchanged without it."""

    # Fingerprints of the frozen v5 prompt and tool schemas, taken before the condition was added.
    FROZEN_PROMPTS = {(True, True): "9b7f678a478bb146e60823667e7a4de74879071464bd40b7c526e3941871156d",
                      (True, False): "9f60884980b3748551dcee004a389556d48237a933454c1b5fc10f7e30630c3f",
                      (False, True): "514935a191fe404f4d92fc6ebfd0b475af642b3243a0e3ff0e960e70c9c4c08c",
                      (False, False): "c618965b654465da744b5c1840d9d817ad8afa1fc8e330537e4b40a5cc7e4866"}
    FROZEN_SCHEMAS = "e6a9e1cf12d98414ab95cc6217daed8da14c799f66c14b714dab56f75d97d86e"

    def setUp(self):
        self.tracing = patch("tracing.get_client", return_value=None)
        self.tracing.start()
        self.addCleanup(self.tracing.stop)

    def run_script(self, replies, *, stateful=False, budget=None, file_system=True):
        executor = KernelCodeExecutor(stateful=stateful, timeout=30, file_system=file_system)
        self.addCleanup(executor.close)
        model = ScriptedClient(replies)
        agent = CodeActAgent(model, executor, max_iterations=budget or len(replies), env_primer=False,
                             file_system=file_system)
        with patch("agent.discover_scope", return_value=({"anchor"}, "public test scope")):
            return agent.check("Judge anchor", "not-opened.ifc"), model

    def test_frozen_prompt_and_tool_schemas_are_unchanged_without_the_file_system(self):
        import hashlib
        import json
        for (stateful, primer), digest in self.FROZEN_PROMPTS.items():
            with self.subTest(stateful=stateful, primer=primer):
                prompt = build_system_prompt("model.ifc", stateful, primer, 20)
                self.assertEqual(hashlib.sha256(prompt.encode()).hexdigest(), digest)
                self.assertEqual(prompt, build_system_prompt("model.ifc", stateful, primer, 20, file_system=False))
        result, _ = self.run_script([reply(python_call('report_labels({"anchor":"PASS"})')), reply(final_call())],
                                    file_system=False)
        self.assertEqual(hashlib.sha256(json.dumps(result.tool_schemas, sort_keys=True).encode()).hexdigest(),
                         self.FROZEN_SCHEMAS)
        self.assertEqual((result.protocol, result.file_tool_calls, result.workspace), ("langchain-codeact-v5", {}, {}))

    def test_prompt_describes_the_tools_and_what_persists(self):
        stateless = build_system_prompt("model.ifc", False, False, 20, file_system=True)
        stateful = build_system_prompt("model.ifc", True, False, 20, file_system=True)
        self.assertIn("Python is RESET before each call: variables and imports do not survive", stateless)
        self.assertIn("stay available for the\nrest of this check, also after Python is reset.", stateless)
        self.assertIn("Python is PERSISTENT", stateful)
        self.assertIn("stay available for the\nrest of this check. Use them to avoid repeating work:", stateful)
        for prompt in (stateless, stateful):
            self.assertIn("ls, read_file, write_file and edit_file", prompt)
            self.assertIn('exec(open("name.py").read())', prompt)
            self.assertIn("load them in later calls instead\n  of recomputing them", prompt)
            self.assertIn("only report_labels in executed Python\ncommits labels", prompt)

    def test_recommended_exec_pattern_picks_up_edits_in_a_persistent_session(self):
        script = [reply({"name": "write_file", "args": {"path": "check.py", "content": "LABEL = 'FAIL'\n"}, "id": "w"}),
                  reply(python_call('exec(open("check.py").read())\nprint(LABEL)', "first")),
                  reply({"name": "edit_file", "args": {"path": "check.py", "old_string": "FAIL", "new_string": "PASS"},
                         "id": "e"}),
                  reply(python_call('exec(open("check.py").read())\nreport_labels({"anchor": LABEL})\nprint(LABEL)', "second")),
                  reply(final_call())]
        result, _ = self.run_script(script, stateful=True)
        self.assertEqual(result.completion_status, "complete")
        self.assertEqual([record["output"] for record in result.execution_records][-2:], ["FAIL", "PASS"])
        self.assertEqual(result.labels, {"anchor": "PASS"})

    def test_stateless_code_reuses_files_written_by_tools_and_python(self):
        script = [reply({"name": "write_file", "args": {"path": "lib/helpers.py",
                         "content": "def labels():\n    return {'anchor': 'PASS'}\n"}, "id": "write"}),
                  reply(python_call("import sys\nsys.path.insert(0, 'lib')\nfrom helpers import labels\n"
                                    "report_labels(labels())\nopen('saved.json', 'w').write('{}')")),
                  reply({"name": "ls", "args": {}, "id": "list"}),
                  reply(final_call())]
        result, model = self.run_script(script)
        self.assertEqual(result.completion_status, "complete")
        self.assertEqual(result.protocol, "langchain-codeact-v5-files-guided")
        self.assertEqual([schema["function"]["name"] for schema in result.tool_schemas],
                         ["run_python", "ls", "read_file", "write_file", "edit_file", "FinalReport"])
        self.assertEqual({name: item["calls"] for name, item in result.file_tool_calls.items()},
                         {"ls": 1, "read_file": 0, "write_file": 1, "edit_file": 0})
        self.assertEqual([item["path"] for item in result.workspace["files"]], ["lib/helpers.py", "saved.json"])
        self.assertEqual(result.workspace["cleanup_error"], "")
        tools = [message for message in model.requests[3] if isinstance(message, ToolMessage)]
        self.assertTrue(tools[0].content.endswith("[Model call 1 of 4 used; 3 remain.]"))
        self.assertIn("lib/helpers.py  ", tools[-1].content)

    def test_file_tools_are_rejected_on_the_last_call(self):
        result, model = self.run_script([reply(python_call('report_labels({"anchor":"PASS"})')),
                                         reply({"name": "write_file", "args": {"path": "late.txt", "content": "x"},
                                                "id": "late"})], budget=2)
        self.assertEqual(result.completion_status, "incomplete")
        self.assertEqual(result.file_tool_calls["write_file"]["calls"], 0)
        self.assertNotIn("late.txt", [item["path"] for item in result.workspace["files"]])
        self.assertTrue(any("run_python and file tools sent now are rejected" in str(entry["content"])
                            for entry in result.transcript))

    def test_file_tools_mixed_with_final_report_are_rejected(self):
        result, _ = self.run_script([reply(python_call('report_labels({"anchor":"PASS"})')),
                                     reply({"name": "write_file", "args": {"path": "mixed.txt", "content": "x"},
                                            "id": "mixed"}, final_call()),
                                     reply(final_call())])
        self.assertEqual(result.completion_status, "complete")
        self.assertEqual(result.file_tool_calls["write_file"]["calls"], 0)
        self.assertTrue(any("Mixed tool calls and FinalReport rejected" in str(entry["content"])
                            for entry in result.transcript))

    def test_malformed_call_cannot_smuggle_a_file_tool_into_the_last_call(self):
        broken = AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": "late.txt", "content": "x"},
                                                    "id": "late"}],
                           invalid_tool_calls=[{"name": "FinalReport", "args": "{broken", "id": "bad", "error": None}],
                           usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
        result, _ = self.run_script([reply(python_call('report_labels({"anchor":"PASS"})')), broken], budget=2)
        self.assertEqual(result.completion_status, "incomplete")
        self.assertEqual(result.llm_calls[-1]["malformed_tool_calls"], 1)
        self.assertEqual(result.file_tool_calls["write_file"]["calls"], 0)
        self.assertNotIn("late.txt", [item["path"] for item in result.workspace["files"]])

    def test_the_condition_needs_an_executor_with_a_workspace(self):
        executor = KernelCodeExecutor(timeout=30)
        self.addCleanup(executor.close)
        with self.assertRaisesRegex(ValueError, "run workspace"):
            CodeActAgent(ScriptedClient(), executor, file_system=True)


class SingleShotBaselineTests(unittest.TestCase):
    """One model call, one script run once, no output shown; the verdict follows from the committed labels."""

    def setUp(self):
        self.tracing = patch("tracing.get_client", return_value=None)
        self.tracing.start()
        self.addCleanup(self.tracing.stop)

    def run_single(self, message, anchors=None):
        executor = KernelCodeExecutor(stateful=False, timeout=30)
        self.addCleanup(executor.close)
        model = ScriptedClient([message])
        agent = CodeActAgent(model, executor, max_iterations=1, env_primer=False, single_shot=True)
        events = []
        with patch("agent.discover_scope", return_value=({"a", "b"} if anchors is None else anchors, "public test scope")):
            result = agent.check("Judge a and b", "not-opened.ifc", on_event=lambda event, payload: events.append(event))
        return result, model, events

    def test_complete_labels_give_a_derived_verdict_after_one_call_and_one_execution(self):
        result, model, events = self.run_single(reply(python_call('print("hidden")\nreport_labels({"a":"FAIL","b":"PASS"})')))
        self.assertEqual((result.completion_status, result.verdict_label, result.violations), ("complete", "NON_COMPLIANT", ["a"]))
        self.assertEqual((result.iterations, result.executions, len(model.requests)), (1, 1, 1))
        self.assertEqual(result.protocol, "langchain-codeact-v5-single-shot")
        self.assertEqual(result.prompt_tokens, 100)
        self.assertEqual(result.execution_records[0]["output"].strip(), "hidden")
        self.assertEqual([entry["role"] for entry in result.transcript], ["system", "user", "assistant", "tool"])
        self.assertIn("you will not see its output", result.transcript[0]["content"])
        self.assertEqual([tool["function"]["name"] for tool in result.tool_schemas], ["run_python"])
        self.assertEqual(model.bindings[0][0].name, "run_python")
        self.assertIn("done", events)
        compliant, _, _ = self.run_single(reply(python_call('report_labels({"a":"PASS","b":"PASS"})')))
        self.assertEqual((compliant.completion_status, compliant.verdict_label), ("complete", "COMPLIANT"))

    def test_runs_without_a_valid_labelling_are_incomplete(self):
        cases = {
            "error": reply(python_call('report_labels({"a":"PASS","b":"PASS"})\nraise ValueError("late")')),
            "coverage": reply(python_call('report_labels({"a":"PASS"})')),
            "pending": reply(python_call('report_labels({"a":"PASS","b":"PENDING"})')),
            "no labels": reply(python_call('print(1)')),
            "only alert": reply(python_call('report_labels({"a":"ALERT","b":"ALERT"})')),
        }
        for name, message in cases.items():
            with self.subTest(name):
                result, _, _ = self.run_single(message)
                self.assertEqual(result.completion_status, "incomplete")
                self.assertEqual(result.executions, 1)
                self.assertTrue(result.completion_issues)
                self.assertEqual(result.reason, " ".join(result.completion_issues))

    def test_no_tool_call_runs_nothing_and_only_the_first_call_runs(self):
        result, _, _ = self.run_single(reply(text="import ifcopenshell ..."))
        self.assertEqual((result.completion_status, result.executions), ("incomplete", 0))
        self.assertIn("no run_python call", result.reason)
        result, _, _ = self.run_single(reply(python_call('report_labels({"a":"PASS","b":"PASS"})', "one"),
                                             python_call('report_labels({"a":"FAIL","b":"FAIL"})', "two")))
        self.assertEqual((result.completion_status, result.verdict_label, result.executions), ("complete", "COMPLIANT", 1))
        self.assertEqual(result.llm_calls[0]["ignored_tool_calls"], 1)

    def test_settings_other_than_the_baseline_are_rejected(self):
        for settings in ({"max_iterations": 20}, {"max_iterations": 2, "harness": 2}):
            with self.subTest(settings), self.assertRaisesRegex(ValueError, "single-shot"):
                CodeActAgent(ScriptedClient(), None, single_shot=True, **settings)

    def test_prompt_keeps_primer_and_label_protocol_without_iteration_or_final_report(self):
        from agent import ENVIRONMENT_PRIMER, LABEL_PROTOCOL, build_single_shot_prompt
        prompt = build_single_shot_prompt("model.ifc")
        self.assertIn(ENVIRONMENT_PRIMER, prompt)
        self.assertIn(LABEL_PROTOCOL, prompt)
        for absent in ("FinalReport", "model calls", "PERSISTENT", "RESET"):
            self.assertNotIn(absent, prompt)


if __name__ == "__main__":
    unittest.main()