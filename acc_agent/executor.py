"""Shared reporting helpers and the kernel-only executor factory.

Stateful runs reuse one Python worker; stateless runs restart it between blocks.
Conversation history and external files can still persist. The retired
in-process CodeExecutor is archived in archive/inprocess_runtime.py.
"""

from __future__ import annotations

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
