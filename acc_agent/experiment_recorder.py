"""Record surrounding run lifecycle without changing LLM requests or execution."""

from __future__ import annotations

import importlib.metadata
import os
import platform
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from code_identity import capture_module, module_snapshot
capture_module()

from agent import AGENT_PROTOCOL, build_system_prompt, save_transcript
from benchmark_audit import audit_case, file_hash
from completion import COMPLETION_CHECKS_VERSION
from executor import RUNTIME_ISOLATION
from experiments import ExperimentStore, fingerprint
import kernel_executor
from llm import model_identity

PROJECT_DIR = Path(__file__).resolve().parent
CORE_FILES = ("agent.py", "completion.py", "executor.py", "llm.py", "scoring.py",
              "experiment_recorder.py", "experiments.py", "code_identity.py")


def code_snapshot() -> dict:
    return {name: module_snapshot(PROJECT_DIR / name) for name in CORE_FILES}


def code_verified(snapshot: dict) -> bool:
    return all(item.get("status") == "matches" for item in snapshot.values())


def skills_snapshot(library) -> dict:
    """Archived inspection helper; new sweeps always pass None."""
    if library is None or not getattr(library, "enabled", False):
        return {"enabled": False, "manifest": {}, "files": {}}
    from skill_library import source_path

    manifest = library.skills()
    files = {}
    for name in manifest:
        if not re.fullmatch(r"[A-Za-z_]\w*", name):
            raise ValueError("Skill manifest contains an invalid identifier.")
        path = source_path(name, manifest[name])
        files[name] = file_hash(path) if path.exists() else None
    return {"enabled": True, "manifest": manifest, "files": files}


def runtime_snapshot() -> dict:
    packages = {}
    for name in ("ifcopenshell", "numpy", "shapely", "anthropic", "openai", "langchain", "langchain-core",
                 "langgraph", "langchain-anthropic", "langchain-openrouter", "pydantic", "langfuse"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"python": platform.python_version(), "platform": platform.platform(), "packages": packages}


@dataclass
class RunTicket:
    id: str
    started: float
    initial_skills: dict
    errors: int = 0
    truncations: int = 0
    executions: int = 0
    steps: int = 0
    skill_saves: int = 0
    configuration: dict = field(default_factory=dict)
    usage_records: list[dict] = field(default_factory=list)

    def observe(self, event: str, payload: dict):
        if event == "usage":
            self.usage_records.append(dict(payload))
        elif event == "code":
            self.executions += 1
        elif event == "iteration_start":
            self.steps = int(payload.get("n", self.steps))
        elif event == "output":
            output = str(payload.get("output", ""))
            self.errors += int(payload["error"] if isinstance(payload.get("error"), bool) else "Traceback (most recent call last):" in output)
            self.truncations += int(payload["truncated"] if isinstance(payload.get("truncated"), bool) else bool(re.search(r"\[truncated \d+ characters\]", output)))


class SweepRecorder:
    def __init__(self, *, entrypoint, requested, case, rule, ifc_path, client,
                 max_iterations, reasoning, env_primer, library, output_limit,
                 log_path="", warning=print, store=None, runtime=None):
        """Record kernel-only runs; library and runtime are ignored legacy inputs."""
        self.warning = warning
        self.store = None
        self.sweep_id = None
        self.library = None
        self.ifc_path = Path(ifc_path).resolve()
        self.log_path = str(Path(log_path).resolve()) if log_path else ""
        self.base = {}
        self.last_error = ""
        self.entry_file = {"gui": "gui.py", "eval": "evaluate.py", "cli": "run.py"}.get(entrypoint)
        if os.environ.get("EXPERIMENTS", "1").lower() in ("0", "false", "no"):
            return
        try:
            self.store = store or ExperimentStore()
            self.sweep_id = self.store.start_sweep(entrypoint, requested, self.log_path, owner=f"pid:{os.getpid()}")
            audit = audit_case(case, self.ifc_path) if case else {"status": "unscored", "issues": ["No reference case."]}
            if case and (rule != case.rule or self.ifc_path != case.resolve_ifc().resolve()):
                audit = {**audit, "status": "overridden-unverified", "issues": [*audit.get("issues", []), "Rule or IFC override differs from the case."]}
            max_tokens = getattr(client, "max_tokens", None)
            if not isinstance(max_tokens, int):
                max_tokens = None
            self.base = {
                "recording_version": 4, "entrypoint": entrypoint, "agent_protocol": AGENT_PROTOCOL,
                "code_identity_scope": "imported module code, not mutable runtime state; config uses effective settings below",
                "config_file_disk_hash": file_hash(PROJECT_DIR / "config.py"),
                "case_id": case.case_id if case else "custom",
                **model_identity(client), "rule": rule,
                "rule_hash": fingerprint(rule), "reference": case.as_dict() if case else None,
                "reference_hash": fingerprint(case.as_dict()) if case else None,
                "reference_version": case.reference.get("version", "unversioned") if case else None,
                "reference_failures": len(case.violation_set) if case else None,
                "ifc_path": str(self.ifc_path), "ifc_hash": file_hash(self.ifc_path),
                "max_iterations": max_iterations, "finalization_limit": 0,
                "budget_policy": "model calls include planning, schema repairs and finalization; Python tool calls also capped at max_iterations",
                "model_retries": 0, "max_concurrency": 1,
                "completion_checks": COMPLETION_CHECKS_VERSION,
                "reasoning": reasoning, "env_primer": env_primer, "output_limit": output_limit,
                "runtime_isolation": RUNTIME_ISOLATION,
                "runtime_isolation_note": "kernel only: stateful keeps one worker; stateless restarts it per block. Conversation history and external files can persist. Historical in-process runs remain separate.",
                "kernel_settings": {
                    "execution_timeout_seconds": kernel_executor.DEFAULT_TIMEOUT,
                    "startup_timeout_seconds": kernel_executor.STARTUP_TIMEOUT,
                    "python_hash_seed": kernel_executor.HASH_SEED,
                },
                "kernel_files_disk_hash": {name: file_hash(PROJECT_DIR / name)
                                           for name in ("kernel_executor.py", "kernel_worker.py")},
                "kernel_files_scope": "disk hashes only; the worker compiles its own copy in a separate process, so the host's imported-code check cannot attest what it ran",
                "sampling": {"temperature": "provider-default", "seed": "unset",
                             "max_tokens": max_tokens},
                "core_files": code_snapshot(), "runtime": runtime_snapshot(), "audit": audit,
                "order": "mode-blocks", "token_accounting": "v2: input includes reported cache reads/writes once; partial usage is a known lower bound, not full request cost",
            }
        except Exception as exc:
            self._warn(exc)

    def _warn(self, exc):
        self.last_error = f"Experiment recording warning: {type(exc).__name__}: {exc}"
        self.warning(self.last_error)

    def start_run(self, mode: str, repeat: int, harness: int) -> RunTicket | None:
        if self.store is None or self.sweep_id is None or not self.base:
            return None
        try:
            skills = skills_snapshot(self.library)
            system = build_system_prompt(str(self.ifc_path), mode == "stateful", self.base["env_primer"])
            current = {**self.base, "mode": mode, "harness": harness, "feedback_leakage": False,
                       "skills_enabled": skills["enabled"], "skill_snapshot": skills,
                       "skill_hash": fingerprint(skills), "system_prompt_hash": fingerprint(system),
                       "system_prompt_hash_kind": "skills-disabled; actual prompt hash retained on run"}
            current["core_files"] = code_snapshot()
            if self.entry_file:
                current["core_files"][self.entry_file] = module_snapshot(PROJECT_DIR / self.entry_file)
            current["runtime_code_verified"] = code_verified(current["core_files"])
            if not current["runtime_code_verified"]:
                self.warning("Imported code differs from disk or is unverified; this run is excluded from comparable results. Restart the application after edits.")
            current_hash = file_hash(self.ifc_path)
            if current_hash != self.base["ifc_hash"]:
                current["ifc_hash"] = current_hash
                current["audit"] = {"status": "changed-unverified", "issues": ["IFC changed after sweep audit."]}
            run_id = self.store.start_run(self.sweep_id, current, repeat, self.log_path)
            return RunTicket(run_id, time.perf_counter(), skills, configuration=current)
        except Exception as exc:
            self._warn(exc)
            return None

    def finish_run(self, ticket: RunTicket | None, result=None, scores=None, error: str = ""):
        if ticket is None:
            return
        try:
            integrity_error = ""
            try:
                after = skills_snapshot(self.library)
                ending_code = code_snapshot()
                if self.entry_file:
                    ending_code[self.entry_file] = module_snapshot(PROJECT_DIR / self.entry_file)
                changed = (fingerprint(after) != fingerprint(ticket.initial_skills)
                           or not ticket.configuration["runtime_code_verified"]
                           or ending_code != ticket.configuration["core_files"]
                           or file_hash(self.ifc_path) != ticket.configuration["ifc_hash"])
            except Exception as exc:
                after, changed = None, True
                integrity_error = f"Could not verify ending context: {type(exc).__name__}: {exc}"
                self.warning(integrity_error)
            metadata = {
                "duration_seconds": time.perf_counter() - ticket.started,
                "error_count": ticket.errors, "truncations": ticket.truncations,
                "skill_saves": ticket.skill_saves, "skills_after": after, "context_changed": changed,
                "iterations": ticket.steps, "executions": ticket.executions, "error": error,
                "integrity_error": integrity_error,
                "runtime_code_verified": ticket.configuration["runtime_code_verified"],
                "usage_complete": not error and bool(ticket.usage_records) and all(item.get("usage_reported") for item in ticket.usage_records),
                "llm_calls": ticket.usage_records,
            }
            measured = [item for item in ticket.usage_records if item.get("usage_reported")]
            if measured:
                metadata.update(prompt_tokens=sum(item["prompt_tokens"] for item in measured),
                                completion_tokens=sum(item["completion_tokens"] for item in measured))
            if result is not None:
                has_usage = not result.llm_calls or any(item.get("usage_reported") for item in result.llm_calls)
                metadata.update(
                    verdict=result.verdict_label, raw_verdict=result.verdict, labels=result.labels,
                    violations=result.violations, labels_reported=len(result.labels),
                    labels_expected=result.expected_anchors, prompt_tokens=result.prompt_tokens if has_usage else None,
                    completion_tokens=result.completion_tokens if has_usage else None, iterations=result.iterations, executions=result.executions,
                    completion_issues=result.completion_issues, reason=result.reason,
                    finalization_attempts=result.finalization_attempts, trace_id=result.trace_id,
                    usage_complete=result.usage_complete, llm_calls=result.llm_calls,
                    cache_read_input_tokens=result.cache_read_input_tokens,
                    cache_creation_input_tokens=result.cache_creation_input_tokens,
                    agent_protocol=result.protocol, tool_schemas=result.tool_schemas,
                    messages=result.transcript, execution_records=result.execution_records, plan=result.plan,
                    actual_system_prompt_hash=fingerprint(result.transcript[0]["content"]) if result.transcript and result.transcript[0].get("role") == "system" else None,
                )
            status = "error" if error else result.completion_status if result is not None else "interrupted"
            self.store.finish_run(ticket.id, status, scores.as_dict() if scores is not None else None, **metadata)
        except Exception as exc:
            self._warn(exc)

    def save_evidence(self, ticket: RunTicket | None, result, out_dir: Path, *, force: bool = False):
        if result is None or (self.log_path and not force):
            return
        try:
            path = save_transcript(result, out_dir, ticket.id if ticket else uuid.uuid4().hex)
            if self.store is not None and ticket is not None:
                self.store.attach_log(ticket.id, path)
            return path
        except Exception as exc:
            self._warn(exc)

    def attach_log(self, ticket: RunTicket | None, path: Path):
        if ticket is not None:
            try:
                self.store.attach_log(ticket.id, path)
            except Exception as exc:
                self._warn(exc)

    def finish(self, error: str = ""):
        if self.store is not None and self.sweep_id is not None:
            try:
                self.store.finish_sweep(self.sweep_id, error or self.last_error)
            except Exception as exc:
                self._warn(exc)