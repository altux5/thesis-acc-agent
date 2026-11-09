"""Script mode: code runs only from workspace files, each run in a fresh interpreter."""

import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage

from kernel_executor import KernelCodeExecutor
from script_agent import SCRIPT_PROTOCOL, ScriptAgent, build_script_prompt
from tests.test_agent import ScriptedClient, final_call, reply


def write(path, content, call_id=None, run=False):
    args = {"path": path, "content": content, **({"run": True} if run else {})}
    return {"name": "write_file", "args": args, "id": call_id or f"write {path}"}


def edit(path, old, new, call_id=None, run=False):
    args = {"path": path, "old_string": old, "new_string": new, **({"run": True} if run else {})}
    return {"name": "edit_file", "args": args, "id": call_id or f"edit {path} {old}"}


def run(path, call_id=None):
    return {"name": "run_file", "args": {"path": path}, "id": call_id or f"run {path}"}


class ScriptModeTests(unittest.TestCase):
    def setUp(self):
        self.tracing = patch("tracing.get_client", return_value=None)
        self.tracing.start()
        self.addCleanup(self.tracing.stop)

    def check(self, replies, budget=None):
        executor = KernelCodeExecutor(stateful=False, timeout=30, file_system=True)
        self.addCleanup(executor.close)
        model = ScriptedClient(replies)
        agent = ScriptAgent(model, executor, max_iterations=budget or len(replies), env_primer=False)
        with patch("script_agent.discover_scope", return_value=({"anchor"}, "public test scope")):
            return agent.check("Judge anchor", "not-opened.ifc"), model

    def outputs(self, result):
        return [record.get("output", "").split("\n[")[0] for record in result.execution_records]

    def test_saving_and_running_is_one_tool_call(self):
        source = 'report_labels({"anchor": "FAIL"})\nprint("checked")\n'
        result, model = self.check([reply(write("check.py", source, run=True)),
                                    reply(edit("check.py", "checked", "rechecked", run=True)),
                                    reply(final_call("NON_COMPLIANT", ["anchor"]))])
        self.assertEqual(result.completion_status, "complete")
        self.assertEqual(result.executions, 2)
        self.assertEqual([(record["trigger"], record["path"]) for record in result.execution_records],
                         [("write_file", "check.py"), ("edit_file", "check.py")])
        self.assertEqual(self.outputs(result), ["checked", "rechecked"])
        tools = [message for message in model.requests[2] if isinstance(message, ToolMessage)]
        self.assertTrue(tools[0].content.startswith(f"Wrote {len(source)} bytes to check.py.\nchecked"))
        self.assertTrue(tools[1].content.startswith("Replaced 1 occurrence(s) in check.py.\nrechecked"))
        self.assertTrue(tools[1].content.endswith("[Model call 2 of 3 used; 1 remain.]"))
        self.assertEqual({name: item["calls"] for name, item in result.file_tool_calls.items()},
                         {"ls": 0, "read_file": 0, "write_file": 1, "edit_file": 1})

    def test_run_needs_a_saved_python_file(self):
        result, model = self.check([reply(write("notes.txt", "x", run=True)),
                                    reply(edit("missing.py", "a", "b", run=True)),
                                    reply(final_call("UNKNOWN", reason="nothing ran"))])
        self.assertEqual(result.executions, 0)
        self.assertEqual([item["path"] for item in result.workspace["files"]], ["notes.txt"])
        tools = [message.content for message in model.requests[2] if isinstance(message, ToolMessage)]
        self.assertIn("Wrote 1 bytes to notes.txt.\nError: Only .py files can be run. Nothing ran.", tools[0])
        self.assertIn("Error: No such file. Nothing ran.", tools[1])

    def test_write_and_run_in_one_response_completes(self):
        source = 'report_labels({"anchor": "FAIL"})\nprint("done")\n'
        result, _ = self.check([reply(write("check.py", source), run("check.py")),
                                reply(final_call("NON_COMPLIANT", ["anchor"]))])
        self.assertEqual(result.completion_status, "complete")
        self.assertEqual(result.protocol, SCRIPT_PROTOCOL)
        self.assertEqual(result.executions, 1)
        record = result.execution_records[0]
        self.assertEqual((record["path"], record["code"], record["status"]), ("check.py", source, "returned"))
        self.assertEqual([schema["function"]["name"] for schema in result.tool_schemas],
                         ["run_file", "ls", "read_file", "write_file", "edit_file", "FinalReport"])
        self.assertEqual([item["path"] for item in result.workspace["files"]], ["check.py"])

    def test_tool_calls_of_one_response_run_in_the_order_sent(self):
        calls = [write("a.py", 'print("v0")\nreport_labels({"anchor": "PASS"})\n'), run("a.py", "r0")]
        for step in range(1, 5):
            calls += [edit("a.py", f"v{step - 1}", f"v{step}"), run("a.py", f"r{step}")]
        result, _ = self.check([reply(*calls), reply(final_call())], budget=10)
        self.assertEqual(self.outputs(result), ["v0", "v1", "v2", "v3", "v4"])
        self.assertEqual(result.completion_status, "complete")

    def test_each_run_is_a_fresh_interpreter_and_files_persist(self):
        first = 'import json\nVALUE = 7\njson.dump({"value": VALUE}, open("data.json", "w"))\n'
        second = ('import json\ntry:\n    VALUE\nexcept NameError:\n    print("fresh")\n'
                  'print(json.load(open("data.json"))["value"])\n')
        result, _ = self.check([reply(write("first.py", first), run("first.py"), write("second.py", second),
                                      run("second.py")), reply(final_call("UNKNOWN", reason="state only"))])
        self.assertEqual(self.outputs(result), ["(code ran with no output)", "fresh\n7"])

    def test_scripts_import_workspace_modules_without_bytecode(self):
        result, _ = self.check([reply(write("helpers.py", "def label():\n    return 'PASS'\n"),
                                      write("check.py", "from helpers import label\nreport_labels({'anchor': label()})\n"),
                                      run("check.py")), reply(final_call())])
        self.assertEqual(result.completion_status, "complete")
        self.assertEqual([item["path"] for item in result.workspace["files"]], ["check.py", "helpers.py"])

    def test_traceback_names_the_file_and_line(self):
        result, _ = self.check([reply(write("check.py", "x = 1\n\nraise ValueError('boom')\n"), run("check.py")),
                                reply(final_call("UNKNOWN", reason="failed"))])
        record = result.execution_records[0]
        self.assertTrue(record["error"])
        self.assertIn('File "check.py", line 3, in <module>', record["output"])
        self.assertIn("raise ValueError('boom')", record["output"])

    def test_run_file_refuses_missing_and_non_python_files(self):
        result, _ = self.check([reply(run("missing.py"), write("notes.txt", "x"), run("notes.txt")),
                                reply(run("../outside.py")),
                                reply(final_call("UNKNOWN", reason="nothing ran"))])
        self.assertEqual(result.executions, 0)
        self.assertEqual([record["status"] for record in result.execution_records], ["not_run"] * 3)
        self.assertTrue(all("Nothing ran." in record["error_text"] for record in result.execution_records))

    def test_executions_are_capped_by_the_budget_whichever_tool_runs_them(self):
        calls = [write("a.py", 'print("x")\n', run=True), edit("a.py", "x", "y", run=True), run("a.py")]
        result, model = self.check([reply(*calls), reply(final_call("UNKNOWN", reason="cap only"))])
        self.assertEqual(result.executions, 2)
        self.assertEqual([record["status"] for record in result.execution_records], ["returned", "returned", "not_run"])
        tools = [message.content for message in model.requests[1] if isinstance(message, ToolMessage)]
        self.assertIn("The limit of 2 script runs for this check is reached. Nothing ran.", tools[2])
        self.assertEqual(result.completion_status, "abstained")

    def test_last_call_rejects_run_file_with_script_wording(self):
        result, _ = self.check([reply(write("check.py", 'report_labels({"anchor": "PASS"})\n'), run("check.py")),
                                reply(run("check.py", "late"))], budget=2)
        self.assertEqual(result.completion_status, "incomplete")
        self.assertEqual(result.executions, 1)
        texts = [str(entry["content"]) for entry in result.transcript]
        self.assertTrue(any("file tools and run_file sent now are rejected" in text for text in texts))
        self.assertFalse(any("run_python" in text for text in texts))

    def test_text_only_reply_is_answered_with_script_wording(self):
        result, model = self.check([AIMessage(content="thinking", usage_metadata={"input_tokens": 1, "output_tokens": 1,
                                                                                   "total_tokens": 2}),
                                    reply(write("check.py", 'report_labels({"anchor": "PASS"})\n'), run("check.py")),
                                    reply(final_call())])
        self.assertEqual(result.completion_status, "complete")
        self.assertTrue(any("write a script and run it (write_file with run=true)" in str(entry["content"])
                            for entry in result.transcript))

    def test_prompt_names_only_script_execution(self):
        prompt = build_script_prompt("model.ifc", env_primer=True, max_calls=20)
        self.assertNotIn("run_python", prompt)
        self.assertIn("With run=true they\nalso run the saved .py file", prompt)
        self.assertIn("You have 20 model calls", prompt)

    def test_script_mode_needs_a_stateless_executor_with_a_workspace(self):
        for stateful, files, message in ((True, True, "stateless executor"), (False, False, "run workspace")):
            with self.subTest(stateful=stateful, files=files):
                executor = KernelCodeExecutor(stateful=stateful, timeout=30, file_system=files)
                self.addCleanup(executor.close)
                with self.assertRaisesRegex(ValueError, message):
                    ScriptAgent(ScriptedClient(), executor)


if __name__ == "__main__":
    unittest.main()
