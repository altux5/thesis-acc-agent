"""CodeAct using LangChain's agent loop and the existing Python worker."""

from __future__ import annotations

import datetime as _dt
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
from langchain.agents.middleware.types import hook_config
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, ConfigDict, model_validator

from code_identity import capture_module
capture_module()

from completion import COMPLETION_CHECKS_VERSION, discover_scope, validate_submission
from kernel_executor import KernelCodeExecutor
from llm import LLMClient, model_identity, with_reasoning
import tracing

AGENT_PROTOCOL = "langchain-codeact-v5"
# Remaining model calls (including the current one) at which the agent is told to commit labels.
WRAP_UP_CALLS = 4
ENVIRONMENT_PRIMER = """
Working with this IFC environment (general reference, not a checking algorithm):
- Import the helper modules you use explicitly; `import ifcopenshell` alone does not
  load them: import ifcopenshell.util.element, ifcopenshell.util.unit,
  ifcopenshell.util.shape, ifcopenshell.geom
- ifcopenshell.util.element.get_psets(entity) returns property and quantity sets,
  including inherited properties. Dimensions may be stored in Qto_* sets.
- Use ifcopenshell.util.element.get_decomposition(entity) for assembly parts and
  get_container(entity) for the containing storey.
- Raw IFC lengths use model units unless the property or quantity overrides them.
  ifcopenshell.util.unit.calculate_unit_scale(model) gives metres per model unit.
- Mesh vertices from ifcopenshell.geom.create_shape are in metres by default,
  including millimetre-based models. Do NOT apply the model unit scale to these
  vertices again. convert-back-units=True changes units; use-world-coords changes
  the coordinate frame, not units.
- Geometry can be inspected with ifcopenshell.geom and ifcopenshell.util.shape:
  settings = ifcopenshell.geom.settings(); settings.set("use-world-coords", True)
  shape = ifcopenshell.geom.create_shape(settings, entity)
  vertices = ifcopenshell.util.shape.get_vertices(shape.geometry)
  mins, maxs = ifcopenshell.util.shape.get_bbox(vertices)
  Geometry creation may fail; a bounding box is not necessarily a clear dimension.
- numpy and shapely are installed. trimesh, networkx and scipy are not provided.
"""
LABEL_PROTOCOL = """
Call report_labels({"<GlobalId>": "<LABEL>", ...}) from executed Python to commit
the full population, not just failures. report_labels is already defined in the
Python session; do not import it. Each submission replaces the last mapping.
Labels: PASS meets the rule; FAIL violates it; ALERT required model data is absent
or unreadable; MANUAL_CHECK a person must resolve a genuinely non-deterministic
judgment; NA the rule does not apply. Missing data is not a violation.
PENDING is a provisional placeholder for an element you have not resolved yet;
COMPLIANT and NON_COMPLIANT are rejected while any PENDING remains.
Recorded IFC lengths carry floating-point export noise: a value within 0.5 mm of a
numeric limit meets that limit.
Do not invent PASS labels to fill coverage gaps. Submit only supported judgments.
"""
PLAN_REQUEST = """Before executing code, provide a short plan covering the element
scope, candidate measurement sources and units, PASS/FAIL condition, missing data
and exemptions, and how you will verify coverage. Plan only in this first response."""
BUDGET_NOTE = """
You have {calls} model calls in total. Every response counts, including FinalReport;
tool results show how many remain. As soon as you can list every element in scope,
commit a complete provisional labelling with report_labels, using PENDING for
elements you have not resolved yet, then resolve them while calls remain. Use ALERT
and MANUAL_CHECK only in their defined meaning. The last call accepts only
FinalReport: submit your committed labels, or UNKNOWN naming what is unresolved.
"""
NO_TOOL_CALL = ("No tool call received. Text alone does not end the check: call run_python "
                "to execute code, or submit FinalReport.")
LAST_CALL = ("This is the last model call and only FinalReport is accepted: run_python sent now is "
             "rejected and does not run. Submit FinalReport from your committed labels, or UNKNOWN "
             "naming what is unresolved.")


def build_system_prompt(ifc_path: str, stateful: bool, env_primer: bool = True, max_calls: int | None = None) -> str:
    persistence = (
        "Python is PERSISTENT: variables, imports, functions and the model survive between calls."
        if stateful else
        "Python is RESET before each call: every code argument must be a self-contained script."
    )
    return f"""You are an automated building-code compliance checker.
Use run_python with Python code to inspect the IFC and evaluate the supplied rule.
ifcopenshell is installed; import what you need. IFC path: {ifc_path}
{persistence}
Only real tool results are execution evidence. Wait for the result before deciding
what it means. Print compact results; the executor bounds output length.
Files can be written only inside the current working folder: use relative paths.
{ENVIRONMENT_PRIMER if env_primer else ''}{LABEL_PROTOCOL}{BUDGET_NOTE.format(calls=max_calls) if max_calls else ''}
Finish using the FinalReport structured response, separately from Python tool calls.
Its violations must exactly match committed FAIL labels. Use NON_COMPLIANT if there
are failures, COMPLIANT if supported completed judgments contain no failures, or
UNKNOWN with a concrete reason if you cannot reach a supported judgment. UNKNOWN
is accepted only on the final model call and cannot conceal known failures.
Never claim compliance merely because time ran out.
Coverage and successful execution are checked independently before acceptance.
Inspect data before concluding; do not guess values that you could read or measure.
"""


@dataclass
class AgentResult:
    verdict: str = "(no verdict reached)"
    iterations: int = 0
    transcript: list[dict] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    verdict_label: str = "UNKNOWN"
    violations: list[str] = field(default_factory=list)
    parse_ok: bool = False
    reason: str = ""
    executions: int = 0
    trace_id: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    label_reports: int = 0
    harness: int = 1
    plan: str = ""
    evaluations: int = 0
    early_stop: bool = False
    feedback_leakage: bool = False
    completion_status: str = "incomplete"
    completion_issues: list[str] = field(default_factory=list)
    expected_anchors: int | None = None
    scope_note: str = ""
    finalization_attempts: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    usage_complete: bool = True
    llm_calls: list[dict] = field(default_factory=list)
    execution_records: list[dict] = field(default_factory=list)
    protocol: str = AGENT_PROTOCOL
    tool_schemas: list[dict] = field(default_factory=list)


def message_record(message) -> dict:
    role = {"human": "user", "ai": "assistant"}.get(message.type, message.type)
    record = {"role": role, "content": message.content}
    if isinstance(message, AIMessage):
        record.update(tool_calls=message.tool_calls, invalid_tool_calls=message.invalid_tool_calls,
                      additional_kwargs=message.additional_kwargs, response_metadata=message.response_metadata)
    elif message.type == "tool":
        record.update(tool_call_id=message.tool_call_id, name=message.name, status=message.status,
                      artifact=message.artifact)
    return record


def usage_record(message: AIMessage) -> dict:
    usage = message.usage_metadata
    details = (usage or {}).get("input_token_details", {})
    stop = message.response_metadata.get("stop_reason") or message.response_metadata.get("finish_reason")
    return dict(usage_reported=usage is not None,
                prompt_tokens=usage["input_tokens"] if usage else None,
                completion_tokens=usage["output_tokens"] if usage else None,
                cache_read_input_tokens=details.get("cache_read", 0) if usage else None,
                cache_creation_input_tokens=details.get("cache_creation", 0) if usage else None,
                stop_reason=stop, truncated=stop in ("length", "max_tokens"))


class RunEvents(AgentMiddleware):
    """Per-run event/usage bridge; LangChain owns routing and structured-output repair."""

    def __init__(self, owner, result, system, emit):
        self.owner, self.result, self.system, self.emit = owner, result, system, emit

    def capture(self, messages):
        self.result.transcript = [{"role": "system", "content": self.system}] + [message_record(message) for message in messages]
        self.owner._capture_progress(self.result)

    def before_model(self, state, runtime):
        self.capture(state["messages"])
        number = len(self.result.llm_calls) + 1
        total = self.owner.max_iterations
        if self.owner.harness == 2 and number == 1:
            return {"messages": [HumanMessage(PLAN_REQUEST)]}
        if number == total:
            return {"messages": [HumanMessage(LAST_CALL)]}
        if number > 1 and total - number + 1 == WRAP_UP_CALLS:
            return {"messages": [HumanMessage(
                f"Model call {number} of {total}: {WRAP_UP_CALLS} calls remain, including this one. Commit your complete "
                "labelling with report_labels now (PENDING where unresolved); the last call accepts only FinalReport.")]}
        return None

    def wrap_model_call(self, request, handler):
        result = self.result
        number = len(result.llm_calls) + 1
        planning = self.owner.harness == 2 and number == 1
        phase = "plan" if planning else f"iteration {number}"
        record = dict(phase=phase, status="requested", usage_reported=False)
        result.llm_calls.append(record)
        result.iterations = number
        self.emit("iteration_start", n=number, total=self.owner.max_iterations)
        self.capture(request.messages)
        if planning:
            request = request.override(tools=[], response_format=None)
        started = time.perf_counter()
        try:
            response = handler(request)
        except BaseException as exc:
            record.update(status="error", error=f"{type(exc).__name__}: {exc}", seconds=round(time.perf_counter() - started, 3))
            result.usage_complete = False
            self.emit("usage", **record)
            raise
        message = next(item for item in response.result if isinstance(item, AIMessage))
        record.update(status="returned", seconds=round(time.perf_counter() - started, 3), **usage_record(message))
        result.usage_complete = result.usage_complete and record["usage_reported"]
        for name in ("prompt_tokens", "completion_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            setattr(result, name, getattr(result, name) + (record[name] or 0))
        self.emit("usage", **record)
        reasoning = "\n".join(block.get("reasoning", "") for block in message.content_blocks if block.get("type") == "reasoning")
        self.emit("assistant", content=message.text, reasoning=reasoning)
        if planning:
            result.plan = message.text
            self.emit("plan", content=result.plan, reasoning=reasoning)
        result.finalization_attempts += sum(call["name"] == "FinalReport" for call in message.tool_calls)
        self.capture([*request.messages, *response.result])
        return response

    @hook_config(can_jump_to=["model"])
    def after_model(self, state, runtime):
        self.capture(state["messages"])
        last_index = next(index for index in range(len(state["messages"]) - 1, -1, -1)
                          if isinstance(state["messages"][index], AIMessage))
        last_ai = state["messages"][last_index]
        if self.owner.harness == 2 and len(self.result.llm_calls) == 1:
            return {"messages": [HumanMessage("Now execute your plan with run_python, then submit FinalReport.")], "jump_to": "model"}
        if not last_ai.tool_calls:
            self.emit("notice", message=NO_TOOL_CALL)
            return {"messages": [HumanMessage(NO_TOOL_CALL)], "jump_to": "model"}
        names = {call["name"] for call in last_ai.tool_calls}
        last_call = len(self.result.llm_calls) == self.owner.max_iterations
        if "run_python" in names and ("FinalReport" in names or last_call):
            # The tool list stays unchanged on the last call so the provider's prompt cache still applies.
            issue = LAST_CALL if last_call else "Mixed execution and FinalReport rejected. No code from this response ran. Submit Python first, then a separate FinalReport after inspecting its output."
            self.emit("notice", message=issue)
            existing = {message.tool_call_id: message.id for message in state["messages"][last_index + 1:] if isinstance(message, ToolMessage)}
            responses = [ToolMessage(content=issue, tool_call_id=call["id"], name=call["name"],
                                     id=existing.get(call["id"]), status="error") for call in last_ai.tool_calls]
            return {"messages": responses, "structured_response": None, "jump_to": "model"}
        return None


class CodeActAgent:
    def __init__(self, llm: LLMClient, executor: KernelCodeExecutor, max_iterations: int = 12,
                 reasoning_enabled: bool = True, env_primer: bool = True, harness: int = 1):
        if harness not in (1, 2):
            raise ValueError("Only H1/basic and H2/planning are supported. H3 reference feedback is retired.")
        if max_iterations < (2 if harness == 2 else 1):
            raise ValueError("The model-call budget must allow the selected harness to run.")
        self.llm = with_reasoning(llm, reasoning_enabled)
        self.executor = executor
        self.max_iterations = max_iterations
        self.reasoning_enabled = reasoning_enabled
        self.env_primer = env_primer
        self.harness = harness
        self.partial_result: AgentResult | None = None

    def _capture_progress(self, result):
        result.labels = dict(self.executor.reported_labels)
        result.label_reports = self.executor.label_reports

    def _trace_config(self, ifc_path, trace_attrs):
        extra = trace_attrs or {}
        metadata = {"case_id": "adhoc", **(extra.get("metadata") or {}), **model_identity(self.llm),
                    "mode": "stateful" if self.executor.stateful else "stateless", "harness": self.harness,
                    "skills": False, "protocol": AGENT_PROTOCOL, "ifc_path": ifc_path,
                    "max_iterations": self.max_iterations, "reasoning": self.reasoning_enabled,
                    "env_primer": self.env_primer, "completion_checks": COMPLETION_CHECKS_VERSION}
        return dict(name=extra.get("name") or f"check {metadata['case_id']} h{self.harness} {metadata['mode']}",
                    metadata=metadata, tags=[f"{name}:{metadata[name]}" for name in ("mode", "case_id", "harness", "provider", "model")]
                    + list(extra.get("tags") or []), session_id=extra.get("session_id"))

    def check(self, rule, ifc_path, on_event=None, trace_attrs=None) -> AgentResult:
        self.partial_result = None
        ifc_path = str(Path(ifc_path).resolve())
        with tracing.check_run(input=rule, **self._trace_config(ifc_path, trace_attrs)) as span:
            trace_id = tracing.current_trace_id() or ""
            try:
                result = self._run_loop(rule, ifc_path, on_event)
            except BaseException as exc:
                if self.partial_result is not None:
                    partial = self.partial_result
                    self._capture_progress(partial)
                    partial.trace_id = trace_id
                    partial.completion_status = "incomplete"
                    partial.parse_ok = False
                    partial.reason = f"{type(exc).__name__}: {exc}"
                    partial.completion_issues = [partial.reason]
                tracing.finish_trace(span, output=str(exc), level="ERROR")
                raise
            result.trace_id = trace_id
            tracing.finish_trace(span, output={"verdict": result.verdict_label, "violations": result.violations, "reason": result.reason},
                                 metadata={"completion_status": result.completion_status, "iterations": result.iterations,
                                           "prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens,
                                           "usage_complete": result.usage_complete},
                                 level="WARNING" if result.completion_status == "incomplete" else None)
        return result

    def _run_loop(self, rule, ifc_path, on_event: Callable | None = None) -> AgentResult:
        def emit(event, **payload):
            if on_event:
                on_event(event, payload)

        system = build_system_prompt(ifc_path, self.executor.stateful, self.env_primer, self.max_iterations)
        result = AgentResult(harness=self.harness)
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

        @tool(response_format="content_and_artifact")
        def run_python(code: str) -> tuple[str, dict]:
            """Execute Python against the IFC. Wait for real output before concluding.

            Commit the full label map with report_labels(mapping) inside the code.
            """
            result.executions += 1
            record = {"code": code, "status": "started"}
            result.execution_records.append(record)
            emit("code", code=code)
            started = time.perf_counter()
            try:
                output = self.executor.run(code)
            except BaseException as exc:
                record.update(status="interrupted", error_text=f"{type(exc).__name__}: {exc}",
                              seconds=round(time.perf_counter() - started, 3))
                self._capture_progress(result)
                raise
            # Includes the worker restart and any IFC reload in stateless mode.
            record.update(status="returned", output=output, seconds=round(time.perf_counter() - started, 3),
                          **self.executor.last_execution)
            self._capture_progress(result)
            emit("output", output=output, **self.executor.last_execution)
            used = len(result.llm_calls)
            budget = f"\n[Model call {used} of {self.max_iterations} used; {self.max_iterations - used} remain.]"
            return output + budget, dict(self.executor.last_execution)

        bridge = RunEvents(self, result, system, emit)
        graph = create_agent(self.llm, tools=[run_python], system_prompt=system,
                             response_format=ToolStrategy(FinalReport), middleware=[
                                 bridge,
                                 ModelCallLimitMiddleware(run_limit=self.max_iterations, exit_behavior="error"),
                                 ToolCallLimitMiddleware(tool_name="run_python", run_limit=self.max_iterations, exit_behavior="error"),
                             ])
        from langchain_core.utils.function_calling import convert_to_openai_tool
        result.tool_schemas = [convert_to_openai_tool(run_python), convert_to_openai_tool(FinalReport)]
        callbacks = tracing.langchain_callbacks()
        try:
            state = graph.invoke({"messages": [HumanMessage(f"Rule to check:\n{rule}")]},
                                 {"max_concurrency": 1, "recursion_limit": self.max_iterations * 8 + 10, "callbacks": callbacks})
            bridge.capture(state["messages"])
            report = state.get("structured_response")
            if report is not None:
                payload, issues = validate_submission(report.model_dump(), self.executor.reported_labels,
                                                     self.executor.label_reports if self.executor.labels_valid else 0,
                                                     self.executor.last_error, anchors,
                                                     self.max_iterations - len(result.llm_calls))
                if payload is not None:
                    result.verdict_label = payload["verdict"]
                    result.violations = sorted(payload["violations"])
                    result.reason = payload.get("reason", "")
                    result.verdict = "FINAL: " + json.dumps(payload)
                    result.parse_ok = True
                    result.completion_status = "abstained" if payload["verdict"] == "UNKNOWN" else "complete" if anchors is not None else "reported_unverified_scope"
                    result.completion_issues = [result.reason] if result.completion_status == "abstained" else [result.scope_note] if anchors is None else []
                    emit("final", verdict=result.verdict)
                else:
                    result.completion_issues = issues
        except (ModelCallLimitExceededError, ToolCallLimitExceededError, GraphRecursionError) as exc:
            result.completion_issues.append(f"Budget exhausted: {exc}")
        if result.completion_status == "incomplete":
            result.completion_issues = result.completion_issues or ["No supported FinalReport submitted within the model-call budget."]
            result.reason = " ".join(result.completion_issues)
        self._capture_progress(result)
        emit("completion", status=result.completion_status, issues=result.completion_issues,
             version=COMPLETION_CHECKS_VERSION, expected_anchors=result.expected_anchors,
             labels_submitted=len(result.labels), scope_note=result.scope_note,
             finalization_attempts=result.finalization_attempts)
        emit("done", verdict=result.verdict, reason=result.reason, iterations=result.iterations,
             prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
             usage_complete=result.usage_complete, cache_read_input_tokens=result.cache_read_input_tokens,
             cache_creation_input_tokens=result.cache_creation_input_tokens, labels=len(result.labels),
             completion_status=result.completion_status, completion_issues=result.completion_issues)
        return result


def save_transcript(result: AgentResult, out_dir: Path, label: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{_dt.datetime.now():%Y%m%d-%H%M%S}_{label}.json"
    payload = asdict(result)
    payload["messages"] = payload.pop("transcript")
    payload["completion_checks"] = COMPLETION_CHECKS_VERSION
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    return path
