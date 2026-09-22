"""Shared reporting helpers and the kernel-only executor factory.

Stateful runs reuse one Python worker; stateless runs restart it between blocks.
Conversation history and external files can still persist. The retired
in-process CodeExecutor is preserved below as comments, not an active runtime.
"""

from __future__ import annotations

# import contextlib  # Retired in-process executor.
import io
import os
import traceback

from code_identity import capture_module
capture_module()

# Eager, not lazy: kernel_executor binds threading.Thread at import time and has
# to do that before any caller patches it.
from kernel_executor import KernelCodeExecutor

# Element outcomes the agent may report. Mirrors ``scoring.LABELS``; kept as a
# literal here so the executor has no import-time dependency on the scorer.
REPORT_LABELS = ("PASS", "FAIL", "ALERT", "MANUAL_CHECK", "NA")

# Frames from these harness files are stripped from tracebacks shown to the model.
HARNESS_FILES = frozenset({"executor.py", "kernel_executor.py", "kernel_worker.py"})

# RUNTIME_ISOLATION = os.environ.get("EXECUTION_RUNTIME", "kernel").strip().lower()
RUNTIME_ISOLATION = "kernel"


def normalise_label_map(mapping: dict) -> dict[str, str]:
    """Validate and canonicalise a ``{GlobalId: label}`` submission.

    Used by the kernel worker to validate labels before committing a submission.
    """
    if not isinstance(mapping, dict):
        raise TypeError(
            "report_labels expects a dict of {GlobalId: label}, got "
            f"{type(mapping).__name__}"
        )
    cleaned: dict[str, str] = {}
    bad: list[str] = []
    for guid, label in mapping.items():
        text = str(label or "").strip().upper()
        for ch in "-/ ":
            text = text.replace(ch, "_")
        if text == "N_A":
            text = "NA"
        if text in REPORT_LABELS:
            cleaned[str(guid).strip()] = text
        else:
            bad.append(f"{guid}={label!r}")
    if bad:
        raise ValueError(
            f"{len(bad)} entr(y/ies) use a label outside "
            f"{REPORT_LABELS}: {', '.join(bad[:5])}"
            + (" ..." if len(bad) > 5 else "")
        )
    return cleaned


def format_label_receipt(cleaned: dict[str, str]) -> str:
    counts: dict[str, int] = {}
    for label in cleaned.values():
        counts[label] = counts.get(label, 0) + 1
    return (
        f"staged {len(cleaned)} element labels {dict(sorted(counts.items()))}; "
        "committed only if this code block succeeds"
    )


def assemble_output(text: str, dropped_chars: int, error_text: str) -> str:
    """Build the execution output string fed back to the model."""
    output = text.strip() or "(code ran with no output)"
    if dropped_chars:
        output += f"\n... [truncated {dropped_chars} characters]"
    if error_text:
        output += "\n\n" + error_text
    return output


def format_agent_traceback(exc: BaseException, limit: int = 6000) -> str:
    """Format *exc* with the harness's own frames removed.

    Keep agent-code frames while hiding host/worker implementation details.
    """
    report = traceback.TracebackException(type(exc), exc, exc.__traceback__)
    node, seen = report, set()
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        node.stack = traceback.StackSummary(
            frame for frame in node.stack
            if os.path.basename(frame.filename) not in HARNESS_FILES
        )
        node = node.__cause__ or node.__context__
    return "".join(report.format())[-limit:]


class _BoundedOutput(io.StringIO):
    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit
        self.dropped_chars = 0

    def write(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("Execution output must be text")
        remaining = max(0, self.limit - self.tell())
        kept = text[:remaining]
        super().write(kept)
        self.dropped_chars += len(text) - len(kept)
        return len(text)

    def writelines(self, lines) -> None:
        for line in lines:
            self.write(line)


# Retired 2026-09-16: namespace resets retain process state. Kept for history only.
# class CodeExecutor:
#     """Executes Python code blocks and captures their printed output.
#
#     Parameters
#     ----------
#     stateful:
#         When True, variables persist across calls (the thesis contribution).
#         When False, every call starts from a fresh namespace (the baseline).
#     output_char_limit:
#         Execution output longer than this is truncated before being returned,
#         so the model's context window does not blow up.
#     skill_library:
#         Archived compatibility argument, ignored. Cross-run skills are excluded
#         from the thesis evaluation; ordinary within-run functions still work.
#
#     Attributes
#     ----------
#     reported_labels:
#         The most recent successfully committed ``{GlobalId: label}`` mapping.
#         A code failure invalidates it. A successful block without a new report
#         cannot restore it. Valid submissions survive stateless namespace resets.
#     """
#
#     def __init__(
#         self,
#         stateful: bool = True,
#         output_char_limit: int = 6000,
#         skill_library: object | None = None,
#     ) -> None:
#         if not isinstance(output_char_limit, int) or output_char_limit < 1:
#             raise ValueError("output_char_limit must be a positive integer")
#         self.stateful = stateful
#         self.output_char_limit = output_char_limit
#         # self.skill_library = skill_library
#         self.skill_library = None
#         # Whether the last executed block raised (used to flag it in the trace).
#         self.last_error = False
#         self.last_execution: dict = {}
#         # The agent's latest per-element labelling, via report_labels(). Survives
#         # a namespace reset, so a stateless run can still report one.
#         self.reported_labels: dict[str, str] = {}
#         self.label_reports = 0
#         self.labels_valid = False
#         self._pending_labels: dict[str, str] | None = None
#         self._pending_label_reports = 0
#         self.skill_load_issues: list[str] = []
#         self._pending_skill_warnings: list[str] = []
#         self._namespace: dict[str, object] = {}
#         self._prime_namespace()
#
#     def _make_report_labels(self):
#         """Build the ``report_labels`` builtin bound to this executor."""
#
#         def report_labels(mapping: dict) -> str:
#             """Record the outcome of every anchor element the rule judges.
#
#             Each call *replaces* the previous labelling, so the agent always has
#             one authoritative answer rather than an accumulation of stale ones.
#             """
#             cleaned = normalise_label_map(mapping)
#             self._pending_labels = cleaned
#             self._pending_label_reports += 1
#             return format_label_receipt(cleaned)
#
#         return report_labels
#
#     def _prime_namespace(self) -> None:
#         """Inject the reporting builtin; cross-run skills are retired."""
#         self._namespace["report_labels"] = self._make_report_labels()
#         self.skill_load_issues = []
#         # lib = self.skill_library
#         # if lib is not None and getattr(lib, "enabled", False):
#         #     self._namespace["save_skill"] = lib.make_save_skill(self._namespace)
#         #     self.skill_load_issues = lib.preload(self._namespace) or []
#         #     self._pending_skill_warnings = list(self.skill_load_issues)
#
#     def skill_prompt_section(self) -> str:
#         # lib = self.skill_library
#         # return lib.prompt_section(loaded_only=True) if lib is not None else ""
#         return ""
#
#     def run(self, code: str) -> str:
#         """Execute *code*, returning captured stdout+stderr (or a traceback)."""
#         self._pending_labels = None
#         self._pending_label_reports = 0
#         self.last_error = False
#         self.last_execution = {}
#         buffer = _BoundedOutput(self.output_char_limit)
#         error_text = ""
#         try:
#             with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
#                 if not self.stateful:
#                     self._namespace = {}
#                     self._prime_namespace()
#                 for warning in self._pending_skill_warnings:
#                     buffer.write(f"[skill load warning] {warning}\n")
#                 self._pending_skill_warnings = []
#                 exec(code, self._namespace)  # noqa: S102 - intentional: this is the REPL
#         except BaseException as exc:
#             self.last_error = True
#             self.reported_labels = {}
#             self.labels_valid = False
#             error_text = format_agent_traceback(exc)
#             if not isinstance(exc, (Exception, SystemExit)):
#                 raise
#         else:
#             if self._pending_labels is not None:
#                 self.reported_labels = self._pending_labels
#                 self.label_reports += self._pending_label_reports
#                 self.labels_valid = True
#         finally:
#             self._pending_labels = None
#             self._pending_label_reports = 0
#             self.last_execution = {
#                 "error": self.last_error, "error_text": error_text,
#                 "truncated": buffer.dropped_chars > 0,
#                 "output_dropped_chars": buffer.dropped_chars,
#                 "labels_valid": self.labels_valid,
#             }
#
#         output = buffer.getvalue().strip() or "(code ran with no output)"
#         if buffer.dropped_chars:
#             output += f"\n... [truncated {buffer.dropped_chars} characters]"
#         if error_text:
#             output += "\n\n" + error_text
#         return output
#
#     def close(self) -> None:
#         """No-op; present so callers can treat both runtimes the same way."""


def make_executor(
    *,
    stateful: bool = True,
    output_char_limit: int = 6000,
    skill_library: object | None = None,
    runtime: str | None = None,
):
    """Build the kernel runtime; explicit legacy runtime selections are rejected.

    EXECUTION_RUNTIME is retired. Stateful runs keep their worker, while
    stateless runs restart it between blocks. External files can still persist.
    """
    # choice = (runtime or RUNTIME_ISOLATION).strip().lower()
    # if choice in ("kernel", "subprocess", "worker"):
    #     return KernelCodeExecutor(
    #         stateful=stateful,
    #         output_char_limit=output_char_limit,
    #         skill_library=skill_library,
    #     )
    # if choice not in ("inprocess", "in-process", ""):
    #     raise ValueError(
    #         f"Unknown EXECUTION_RUNTIME {choice!r}; expected 'inprocess' or 'kernel'"
    #     )
    # return CodeExecutor(
    #     stateful=stateful,
    #     output_char_limit=output_char_limit,
    #     skill_library=skill_library,
    # )
    choice = (runtime or RUNTIME_ISOLATION).strip().lower()
    if choice not in ("kernel", "subprocess", "worker"):
        raise ValueError(
            f"Only the kernel runtime is supported; requested {choice!r}. "
            "The in-process runtime is retired."
        )
    return KernelCodeExecutor(
        stateful=stateful,
        output_char_limit=output_char_limit,
        skill_library=skill_library,
    )
