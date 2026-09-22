"""Out-of-process execution for the CodeAct loop, in the style of a Jupyter kernel.

The retired ``CodeExecutor`` reset a stateless run by swapping a namespace dict, leaving
``sys.modules``, ``os.environ``, the cwd and files on disk untouched -- so
``import ifcopenshell`` is a cache hit rather than a real reload, and the system
prompt's "nothing persists" is not true. This runtime resets by restarting a
worker process instead, clearing interpreter state. It is the only active runtime.
Conversation history and external files are not reset by this mechanism.

Mapping from experimental condition to worker lifetime:

- stateful  (C) -> one worker for the whole run
- stateless (B) -> the worker is restarted before every block after the first
- single-shot (A, not implemented) -> one worker, one block, then discard

It also gives the harness what an in-process ``exec`` cannot: a per-block
deadline, and containment when native code in ifcopenshell takes the interpreter
down. Each worker also gets a private scratch directory as its working directory,
so a relative write neither lands in the source tree nor outlives the worker.

It is **not** a security boundary: the worker runs as the same user with the same
filesystem access, so a write to an *absolute* path still persists, and known API
keys are merely dropped from its environment rather than made unreachable.

Reporting helpers remain in executor.py; the old in-process class is commented
out there. The public execution interface is unchanged.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import weakref
from pathlib import Path
# Bound at import: the reader must be a real background thread, and callers
# patch threading.Thread globally.
from threading import Thread

from code_identity import capture_module
capture_module()

PROJECT_DIR = Path(__file__).resolve().parent
WORKER = PROJECT_DIR / "kernel_worker.py"

# Wall-clock budget for one code block. Generous by default: a full-model
# traversal on the mall IFC legitimately takes minutes.
DEFAULT_TIMEOUT = float(os.environ.get("EXEC_TIMEOUT", "600"))
STARTUP_TIMEOUT = float(os.environ.get("EXEC_STARTUP_TIMEOUT", "60"))
# Pinned so set iteration order is the same in every worker. Left free, each
# worker gets its own seed and repeats vary for reasons that are not the model.
HASH_SEED = os.environ.get("EXEC_HASH_SEED", "0")
_SECRET_MARKERS = ("API_KEY", "SECRET", "TOKEN", "PASSWORD")

# Why a request produced no usable reply. Distinguished here rather than by
# polling the child, which races: a crashed worker is often not yet reaped.
TIMED_OUT = object()
DIED = object()


def _child_environment() -> dict[str, str]:
    """A sanitised environment: no PYTHON* inheritance, no obvious credentials.

    Done here rather than with ``-I`` because that also discards the settings we
    want to pin, including the hash seed and the output encoding.
    """
    env = {k: v for k, v in os.environ.items()
           if not k.upper().startswith("PYTHON")
           and not any(marker in k.upper() for marker in _SECRET_MARKERS)}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONHASHSEED"] = HASH_SEED
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class KernelError(RuntimeError):
    """The worker could not be started or spoke an unusable protocol."""


class _Worker:
    """One child process plus the reader thread draining its control channel."""

    def __init__(self, skills: bool) -> None:
        # A private cwd, so a relative write neither lands in the source tree nor
        # outlives the worker. Absolute paths are still reachable.
        self.scratch = tempfile.mkdtemp(prefix="acc_kernel_")
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-s", str(WORKER), str(PROJECT_DIR)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,  # inherited, so native-level noise stays visible
                cwd=self.scratch,
                env=_child_environment(),
                text=True,
                encoding="utf-8",
                errors="backslashreplace",
                bufsize=1,
            )
        except OSError as exc:
            shutil.rmtree(self.scratch, ignore_errors=True)
            raise KernelError(f"could not start the execution kernel: {exc}") from exc
        self._replies: queue.Queue = queue.Queue()
        self._reader = Thread(target=self._drain, daemon=True)
        self._reader.start()
        self.skill_loaded: dict = {}
        self.skill_issues: list[str] = []
        self.blocks = 0
        # reply = self.request({"op": "prime", "skills": bool(skills)}, STARTUP_TIMEOUT)
        reply = self.request({"op": "prime"}, STARTUP_TIMEOUT)
        if not isinstance(reply, dict) or not reply.get("ok"):
            self.kill()
            detail = reply.get("detail", "no response") if isinstance(reply, dict) else "no response"
            raise KernelError(f"execution kernel failed to start: {detail}")
        self.skill_loaded = reply.get("skill_loaded") or {}
        self.skill_issues = list(reply.get("skill_issues") or [])

    def _drain(self) -> None:
        try:
            for line in self._proc.stdout:
                self._replies.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self._replies.put(None)  # EOF sentinel: the worker is gone

    def request(self, message: dict, timeout: float):
        """Send *message* and wait for one reply, or return TIMED_OUT / DIED."""
        try:
            self._proc.stdin.write(json.dumps(message) + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError):
            return DIED
        try:
            line = self._replies.get(timeout=timeout)
        except queue.Empty:
            return TIMED_OUT
        if line is None:
            return DIED
        try:
            return json.loads(line)
        except ValueError:
            return DIED

    @property
    def alive(self) -> bool:
        return self._proc.poll() is None

    def kill(self) -> None:
        proc = self._proc
        if proc.poll() is None:
            proc.kill()
        for stream in (proc.stdin, proc.stdout):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        shutil.rmtree(self.scratch, ignore_errors=True)

    def shutdown(self) -> None:
        try:
            self._proc.stdin.write(json.dumps({"op": "shutdown"}) + "\n")
            self._proc.stdin.flush()
            self._proc.wait(timeout=5)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        self.kill()


class KernelCodeExecutor:
    """Executes code blocks in the application's sole worker-based runtime.

    Parameters
    ----------
    stateful:
        When True one worker serves the whole run. When False the worker is
        restarted before every block after the first. Variables, imported modules
        and worker environment changes do not carry over; external files can.
    output_char_limit:
        Execution output longer than this is truncated before being returned.
    skill_library:
        Archived compatibility argument, ignored. Cross-run skill loading,
        saving and prompt instructions are disabled in the host and worker.
    timeout:
        Seconds one code block may run before the worker is killed.
    """

    def __init__(
        self,
        stateful: bool = True,
        output_char_limit: int = 6000,
        skill_library: object | None = None,
        timeout: float | None = None,
    ) -> None:
        if not isinstance(output_char_limit, int) or output_char_limit < 1:
            raise ValueError("output_char_limit must be a positive integer")
        self.stateful = stateful
        self.output_char_limit = output_char_limit
        # self.skill_library = skill_library
        self.skill_library = None
        self.timeout = DEFAULT_TIMEOUT if timeout is None else float(timeout)
        self.last_error = False
        self.last_execution: dict = {}
        self.reported_labels: dict[str, str] = {}
        self.label_reports = 0
        self.labels_valid = False
        self.skill_load_issues: list[str] = []
        self.restarts = 0
        # The finalizer must not close over ``self`` or the executor could never
        # be collected, so the worker lives in a slot the callback can reach.
        self._slot: dict = {"worker": None}
        self._finalizer = weakref.finalize(self, _shutdown_slot, self._slot)
        self._start()

    @property
    def _worker(self) -> "_Worker | None":
        return self._slot["worker"]

    # ---- worker lifetime ---------------------------------------------------
    def _skills_enabled(self) -> bool:
        # return getattr(self.skill_library, "enabled", False) is True
        return False

    def _start(self) -> None:
        worker = _Worker(self._skills_enabled())
        self._slot["worker"] = worker
        self.skill_load_issues = list(worker.skill_issues)
        # library = self.skill_library
        # if library is not None and self._skills_enabled():
        #     library.loaded = dict(worker.skill_loaded)
        #     library.load_issues = list(worker.skill_issues)

    def _replace_worker(self) -> None:
        worker = self._slot["worker"]
        if worker is not None:
            self._slot["worker"] = None
            worker.kill()
        self.restarts += 1
        self._start()

    def close(self) -> None:
        self._finalizer.detach()
        _shutdown_slot(self._slot)

    def skill_prompt_section(self) -> str:
        # lib = self.skill_library
        # return lib.prompt_section(loaded_only=True) if lib is not None else ""
        return ""

    # ---- execution ---------------------------------------------------------
    def _fail(self, detail: str, note: str, *, reason: str) -> str:
        """Record a harness-level failure and rebuild the worker for the next block."""
        self.last_error = True
        self.reported_labels = {}
        self.labels_valid = False
        self.last_execution = {
            "error": True, "error_text": detail, "truncated": False,
            "output_dropped_chars": 0, "labels_valid": False,
            "kernel_restarted": False, "restart_reason": reason,
        }
        self._replace_worker()
        self.last_execution["kernel_restarted"] = True
        return f"{note}\n\n{detail}"

    def run(self, code: str) -> str:
        """Execute *code* in the worker, returning its captured output."""
        self.last_error = False
        self.last_execution = {}
        worker = self._worker
        if not self.stateful and worker is not None and worker.blocks:
            self._replace_worker()
            worker = self._worker
        if worker is None or not worker.alive:
            return self._fail(
                "ExecutionKernelDied: the interpreter was unavailable before this "
                "code block started. This block was not executed.",
                "The execution kernel was restarted. Everything defined earlier "
                "in the session is gone; the next block starts from a fresh "
                "interpreter. Rebuild the required state before continuing.",
                reason="worker_unavailable_before_block",
            )

        worker.blocks += 1
        reply = worker.request(
            {"op": "execute", "code": code, "limit": self.output_char_limit},
            self.timeout,
        )

        if reply is TIMED_OUT:
            return self._fail(
                f"ExecutionTimeout: the code block was still running after "
                f"{self.timeout:g} seconds and the session was terminated.",
                "The execution kernel was restarted because this block exceeded "
                "its time budget. Everything defined earlier in the session is "
                "gone; the next block starts from a fresh interpreter. Reduce the "
                "work per block instead of repeating it.",
                reason="timeout",
            )
        if reply is DIED:
            return self._fail(
                "ExecutionKernelDied: the interpreter running this block exited "
                "before returning a result (a native crash or a process exit).",
                "The execution kernel was restarted after it died. Everything "
                "defined earlier in the session is gone; the next block starts from "
                "a fresh interpreter.",
                reason="worker_died",
            )
        if not reply.get("ok"):
            return self._fail(
                f"ExecutionKernelError: {reply.get('detail', 'unknown failure')}",
                "The execution kernel hit an internal error and was restarted. "
                "Everything defined earlier in the session is gone.",
                reason="protocol_error",
            )

        self.last_error = bool(reply.get("error"))
        labels = reply.get("labels")
        if self.last_error:
            self.reported_labels = {}
            self.labels_valid = False
        elif labels is not None:
            self.reported_labels = dict(labels)
            self.label_reports += int(reply.get("label_reports") or 0)
            self.labels_valid = True
        self.last_execution = {
            "error": self.last_error,
            "error_text": reply.get("error_text", ""),
            "truncated": bool(reply.get("truncated")),
            "output_dropped_chars": int(reply.get("output_dropped_chars") or 0),
            "labels_valid": self.labels_valid,
        }
        output = reply.get("output", "(code ran with no output)")
        if reply.get("fatal"):
            # The worker is exiting on its own; do not reuse it.
            self._replace_worker()
            self.last_execution.update(
                kernel_restarted=True, restart_reason="fatal_exception",
            )
            output += (
                "\n\nThe execution kernel was restarted after a fatal exception. "
                "Everything defined earlier in the session is gone; the next "
                "block starts from a fresh interpreter."
            )
        return output


def _shutdown_slot(slot: dict) -> None:
    worker = slot.get("worker")
    if worker is not None:
        slot["worker"] = None
        worker.shutdown()
