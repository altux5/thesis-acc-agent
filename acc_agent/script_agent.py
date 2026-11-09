"""Script mode (protocol ``langchain-codeact-v5-script-v2``): code runs only from files of the run workspace.

The model writes scripts with the workspace file tools; ``write_file`` and ``edit_file`` with ``run=true``
also execute the saved ``.py`` file, and ``run_file`` re-runs one unchanged, like ``python name.py``.
Every run starts a fresh interpreter (the stateless kernel), files persist. There is no
``run_python``, so code has one path: written once, corrected with ``edit_file``, run from the file,
and saving plus running is one tool call (M3 sends one tool call per reply). Design: NOTES.md 2026-11-04.

The frozen agent (agent.py, kernel_executor.py, kernel_worker.py, file_tools.py) is reused
unchanged: completion checks, label protocol, budget rules, workspace confinement and recording
all come from it. This module only replaces the tool set, the prompt and the loop wiring.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Callable, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.types import hook_config
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, ConfigDict, model_validator

from code_identity import capture_module
capture_module()

from agent import (BUDGET_NOTE, ENVIRONMENT_PRIMER, FILE_TOOL_CALLS_PER_MODEL_CALL, FILES_LAST_CALL, LABEL_PROTOCOL,
                   NO_TOOL_CALL, AgentResult, CodeActAgent, RunEvents)
from completion import discover_scope, validate_submission
import file_tools
import tracing

# v1 (langchain-codeact-v5-script: separate write and run_file calls) ran only as the 4-run pilot of 2026-11-04.
SCRIPT_PROTOCOL = "langchain-codeact-v5-script-v2"
SCRIPT_TOOL_NAMES = ("run_file", *file_tools.FILE_TOOL_NAMES)
SCRIPT_NOTE = """
Scripts: write_file creates a file and edit_file replaces exact text in it. With run=true they
also run the saved .py file in a fresh Python process, like `python name.py`, and return its
output, so saving and running is one tool call. run_file runs a .py file without changing it;
read_file and ls show the working folder. Variables and imports do not survive between runs,
files do. A script can import other .py files of the folder and can save slow intermediate
results (for example JSON) for later scripts. Correct a script with edit_file(run=true) instead
of writing it again. Only report_labels in a script that runs commits labels.
"""
SCRIPT_LAST_CALL = ("This is the last model call and only FinalReport is accepted: file tools and run_file "
                    "sent now are rejected and do not run. Submit FinalReport from your committed labels, or "
                    "UNKNOWN naming what is unresolved.")
SCRIPT_NO_TOOL_CALL = ("No tool call received. Text alone does not end the check: write a script and run it "
                       "(write_file with run=true), or submit FinalReport.")
# Frozen-agent messages that name run_python, replaced by their script-mode wording.
_REWORDED = {FILES_LAST_CALL: SCRIPT_LAST_CALL, NO_TOOL_CALL: SCRIPT_NO_TOOL_CALL}
# The worker execs this wrapper: the script runs as __main__ in its own globals, can import files of the
# workspace (the worker's cwd), writes no bytecode there, and its tracebacks name the file and line.
_RUNNER = """import os as _os, sys as _sys
_sys.dont_write_bytecode = True
_sys.path.insert(0, _os.getcwd())
exec(compile({source!r}, {path!r}, "exec"), {{"__name__": "__main__", "__file__": {path!r}, "report_labels": report_labels}})
"""
RECORDING = {
    "tools": list(SCRIPT_TOOL_NAMES), "execution": "workspace .py files only, each run in a fresh interpreter "
    "(stateless kernel): write_file/edit_file with run=true save then run; run_file re-runs; no run_python",
    "execution_cap": "executions per run capped at the model-call budget; further runs are refused",
    "workspace": "one folder per run, shared by every worker of the run",
    "max_file_bytes": file_tools.MAX_FILE_BYTES, "file_tool_calls_per_model_call": FILE_TOOL_CALLS_PER_MODEL_CALL,
    "tool_order": "tool calls of one response run sequentially in the order sent (max_concurrency 1)",
    "recorded": "each executed script's source, sha256 and triggering tool in execution_records; workspace manifest",
}


def build_script_prompt(ifc_path: str, env_primer: bool = True, max_calls: int | None = None) -> str:
    """Script-mode system prompt: the frozen prompt's primer, label protocol and budget, with run_file for run_python."""
    return f"""You are an automated building-code compliance checker.
Write Python scripts in the working folder and run them with run_file to inspect the IFC
and evaluate the supplied rule.
ifcopenshell is installed; import what you need. IFC path: {ifc_path}
{SCRIPT_NOTE}
Only real tool results are execution evidence. Wait for the result before deciding
what it means. Print compact results; the executor bounds output length.
Files can be written only inside the current working folder: use relative paths.
{ENVIRONMENT_PRIMER if env_primer else ''}{LABEL_PROTOCOL}{BUDGET_NOTE.format(calls=max_calls) if max_calls else ''}
Finish using the FinalReport structured response, separately from the other tool calls.
Its violations must exactly match committed FAIL labels. Use NON_COMPLIANT if there
are failures, COMPLIANT if supported completed judgments contain no failures, or
UNKNOWN with a concrete reason if you cannot reach a supported judgment. UNKNOWN
is accepted only on the final model call and cannot conceal known failures.
Never claim compliance merely because time ran out.
Coverage and successful execution are checked independently before acceptance.
Inspect data before concluding; do not guess values that you could read or measure.
"""


def _reword(update: dict | None) -> dict | None:
    if not update:
        return update
    messages = [message.model_copy(update={"content": _REWORDED[message.content]})
                if isinstance(message, (HumanMessage, ToolMessage)) and isinstance(message.content, str)
                and message.content in _REWORDED else message for message in update.get("messages", [])]
    return {**update, "messages": messages} if "messages" in update else update


class ScriptRunEvents(RunEvents):
    """The frozen event bridge and rejection rules, with run_file named instead of run_python."""

    def __init__(self, owner, result, system, emit):
        def reworded_emit(event, **payload):
            if isinstance(payload.get("message"), str):
                payload["message"] = _REWORDED.get(payload["message"], payload["message"])
            emit(event, **payload)
        super().__init__(owner, result, system, reworded_emit)

    def before_model(self, state, runtime):
        return _reword(super().before_model(state, runtime))

    @hook_config(can_jump_to=["model"])
    def after_model(self, state, runtime):
        return _reword(super().after_model(state, runtime))


class ScriptAgent(CodeActAgent):
    """CodeAct whose only execution path is a workspace file run in a fresh interpreter."""

    def __init__(self, llm, executor, max_iterations: int = 12, reasoning_enabled: bool = True,
                 env_primer: bool = True):
        if getattr(executor, "stateful", True):
            raise ValueError("Script mode runs every file in a fresh interpreter: use a stateless executor.")
        super().__init__(llm, executor, max_iterations=max_iterations, reasoning_enabled=reasoning_enabled,
                         env_primer=env_primer, harness=1, file_system=True)
        self.protocol = SCRIPT_PROTOCOL
        self.work_tools = set(SCRIPT_TOOL_NAMES)

    def _run_loop(self, rule, ifc_path, on_event: Callable | None = None) -> AgentResult:
        # Same loop as CodeActAgent._run_loop (frozen); only the tools, prompt and event bridge differ.
        def emit(event, **payload):
            if on_event:
                on_event(event, payload)

        system = build_script_prompt(ifc_path, self.env_primer, self.max_iterations)
        result = AgentResult(harness=self.harness, protocol=self.protocol)
        self.partial_result = result
        anchors, result.scope_note = discover_scope(rule, ifc_path)
        result.expected_anchors = len(anchors) if anchors is not None else None

        class FinalReport(BaseModel):
            """Submit a supported verdict after committing labels through Python."""
            model_config = ConfigDict(extra="forbid", strict=True)
            verdict: Literal["COMPLIANT", "NON_COMPLIANT", "UNKNOWN"]
            violations: list[str]
            reason: str = ""

            @model_validator(mode="after")
            def validate_evidence(report):
                _, issues = validate_submission(report.model_dump(), self.executor.reported_labels,
                                               self.executor.label_reports if self.executor.labels_valid else 0,
                                               self.executor.last_error, anchors,
                                               self.max_iterations - len(result.llm_calls))
                if issues:
                    result.completion_issues = issues
                    emit("notice", message="Completion rejected: " + " ".join(issues))
                    raise ValueError(" ".join(issues))
                return report

        def budget_note() -> str:
            used = len(result.llm_calls)
            return f"\n[Model call {used} of {self.max_iterations} used; {self.max_iterations - used} remain.]"

        root = Path(self.executor.workspace)
        workspace = file_tools.Workspace(root, output_limit=self.executor.output_char_limit,
                                         call_limit=FILE_TOOL_CALLS_PER_MODEL_CALL * self.max_iterations)
        result.file_tool_calls = workspace.calls

        def execute(path: str, trigger: str) -> tuple[str, dict]:
            """Run one saved .py file in a fresh interpreter; refusals run nothing and change no labels."""
            try:
                if not isinstance(path, str) or not path.endswith(".py"):
                    raise file_tools.WorkspaceError("Only .py files can be run.")
                if result.executions >= self.max_iterations:
                    raise file_tools.WorkspaceError(f"The limit of {self.max_iterations} script runs for this check is reached.")
                source = file_tools._read_text(file_tools.resolve(root, path))
            except (file_tools.WorkspaceError, OSError) as exc:
                text = f"Error: {exc} Nothing ran."
                result.execution_records.append({"path": path, "trigger": trigger, "status": "not_run", "error_text": text})
                emit("notice", message=f"{trigger} {path}: {text}")
                return text, {"error": True, "not_run": True}
            result.executions += 1
            record = {"path": path, "trigger": trigger, "code": source,
                      "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(), "status": "started"}
            result.execution_records.append(record)
            emit("code", code=f"# {trigger} {path}\n{source}")
            started = time.perf_counter()
            try:
                output = self.executor.run(_RUNNER.format(source=source, path=path))
            except BaseException as exc:
                record.update(status="interrupted", error_text=f"{type(exc).__name__}: {exc}",
                              seconds=round(time.perf_counter() - started, 3))
                self._capture_progress(result)
                raise
            # Includes the worker restart and any IFC reload: every run starts a fresh interpreter.
            record.update(status="returned", output=output, seconds=round(time.perf_counter() - started, 3),
                          **self.executor.last_execution)
            self._capture_progress(result)
            emit("output", output=output, **self.executor.last_execution)
            return output, dict(self.executor.last_execution)

        def file_call(name: str, run: bool = False, **arguments) -> tuple[str, dict]:
            text, error = workspace.run(name, **arguments)
            emit("file_tool", name=name, arguments={**arguments, "run": run} if name in ("write_file", "edit_file")
                 else arguments, result=text, error=error)
            if not run:
                return text + budget_note(), {}
            if error:
                return text + " Nothing ran." + budget_note(), {"error": True, "not_run": True}
            output, artifact = execute(arguments["path"], name)
            return f"{text}\n{output}" + budget_note(), artifact

        @tool(response_format="content_and_artifact")
        def run_file(path: str) -> tuple[str, dict]:
            """Run a .py file of the working folder unchanged in a fresh Python process, like `python path`, and return its output.

            Commit the full label map with report_labels(mapping) inside the script.
            """
            output, artifact = execute(path, "run_file")
            return output + budget_note(), artifact

        @tool(response_format="content_and_artifact")
        def ls(path: str = ".") -> tuple[str, dict]:
            """List the files in the working folder, or under one of its subfolders, with their sizes."""
            return file_call("ls", path=path)

        @tool(response_format="content_and_artifact")
        def read_file(path: str, offset: int = 0, limit: int = file_tools.DEFAULT_READ_LINES) -> tuple[str, dict]:
            """Read a UTF-8 text file from the working folder, starting at line offset (0-based), at most limit lines."""
            return file_call("read_file", path=path, offset=offset, limit=limit)

        @tool(response_format="content_and_artifact")
        def write_file(path: str, content: str, run: bool = False) -> tuple[str, dict]:
            """Create or overwrite a UTF-8 text file in the working folder.

            With run=true, then run the saved .py file in a fresh Python process and return its output.
            """
            return file_call("write_file", run=run, path=path, content=content)

        @tool(response_format="content_and_artifact")
        def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False,
                      run: bool = False) -> tuple[str, dict]:
            """Replace exact text in a file of the working folder. old_string must occur exactly once unless replace_all is true.

            With run=true, then run the edited .py file in a fresh Python process and return its output.
            """
            return file_call("edit_file", run=run, path=path, old_string=old_string, new_string=new_string,
                             replace_all=replace_all)

        tools = [run_file, ls, read_file, write_file, edit_file]
        bridge = ScriptRunEvents(self, result, system, emit)
        # Executions are capped inside execute(), whichever tool triggers them.
        graph = create_agent(self.llm, tools=tools, system_prompt=system,
                             response_format=ToolStrategy(FinalReport), middleware=[
                                 bridge,
                                 ModelCallLimitMiddleware(run_limit=self.max_iterations, exit_behavior="error"),
                             ])
        from langchain_core.utils.function_calling import convert_to_openai_tool
        result.tool_schemas = [convert_to_openai_tool(item) for item in tools] + [convert_to_openai_tool(FinalReport)]
        callbacks = tracing.langchain_callbacks()
        try:
            # max_concurrency 1 also makes the tool calls of one response run one at a time, in the order sent.
            state = graph.invoke({"messages": [HumanMessage(f"Rule to check:\n{rule}")]},
                                 {"max_concurrency": 1, "recursion_limit": self.max_iterations * 8 + 10, "callbacks": callbacks})
            bridge.capture(state["messages"])
            report = state.get("structured_response")
            if report is not None:
                payload, issues = validate_submission(report.model_dump(), self.executor.reported_labels,
                                                     self.executor.label_reports if self.executor.labels_valid else 0,
                                                     self.executor.last_error, anchors,
                                                     self.max_iterations - len(result.llm_calls))
                self._accept(result, payload, issues, anchors, emit)
        except (ModelCallLimitExceededError, GraphRecursionError) as exc:
            result.completion_issues.append(f"Budget exhausted: {exc}")
        return self._finish(result, emit, "No supported FinalReport submitted within the model-call budget.")
