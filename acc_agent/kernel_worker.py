"""Child process that executes the agent's code blocks. Not imported by the host.

Started by ``kernel_executor.KernelCodeExecutor``. One JSON request per line
arrives on the control channel, one JSON response goes back.

The control channel is deliberately *not* stdin/stdout as the agent sees them.
At startup fds 0 and 1 are duplicated to private descriptors and then replaced,
so code running inside this process cannot read the protocol, and cannot forge a
response by printing one. ``print()`` output is captured separately per block.

That closes the obvious protocol holes. It is NOT a sandbox: the code still runs
with this user's permissions and can read the filesystem.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import traceback

TRACEBACK_LIMIT = 6000


def _split_control_channel():
    """Take private copies of fd 0/1, then point the public ones elsewhere."""
    control_in = os.fdopen(os.dup(0), "r", encoding="utf-8", newline="\n")
    control_out = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    devnull = os.open(os.devnull, os.O_RDONLY)
    try:
        os.dup2(devnull, 0)
    finally:
        os.close(devnull)
    # Native-level writes to fd 1 land on stderr, which the host leaves inherited.
    os.dup2(2, 1)
    sys.stdin = io.StringIO("")
    return control_in, control_out


CONTROL_IN, CONTROL_OUT = _split_control_channel()

SCRATCH = os.path.normcase(os.path.abspath(os.getcwd()))
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
# os.* / shutil.* audit events whose path arguments are modified on disk.
_MUTATING_EVENTS = {"os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.symlink", "os.link",
                    "os.truncate", "os.chmod", "os.utime", "shutil.rmtree", "shutil.move", "shutil.copyfile",
                    "shutil.copytree", "shutil.chown"}


def _outside_scratch(path) -> bool:
    if isinstance(path, int) or path is None:
        return False  # an already-open descriptor or no path argument
    full = os.path.normcase(os.path.abspath(os.fsdecode(path)))
    return full != SCRATCH and not full.startswith(SCRATCH + os.sep) and full != os.path.normcase(os.devnull)


def _confine_writes(event: str, args: tuple) -> None:
    """Refuse Python-level writes outside the worker's private scratch directory."""
    if event == "open":
        path, mode, flags = args
        writing = any(c in mode for c in "wax+") if isinstance(mode, str) else bool((flags or 0) & _WRITE_FLAGS)
        targets = [path] if writing else []
    elif event in _MUTATING_EVENTS:
        paths = [arg for arg in args if isinstance(arg, (str, bytes, os.PathLike))]
        # Copies and links only create their destination; the source is merely read.
        targets = paths[1:] if event in ("shutil.copyfile", "shutil.copytree", "os.link", "os.symlink") else paths
    else:
        return
    for target in targets:
        if _outside_scratch(target):
            raise PermissionError(f"Writing outside the working folder is not allowed: {os.fsdecode(target)}. "
                                  "Use a relative path.")


sys.addaudithook(_confine_writes)

sys.path.insert(0, sys.argv[1])

from executor import (  # noqa: E402  - path must be set first
    _BoundedOutput,
    assemble_output,
    format_agent_traceback,
    format_label_receipt,
    normalise_label_map,
)

# Module cache only: the agent still writes its own imports, but `import ifcopenshell`
# then exposes these submodules as attributes. Nothing is added to the namespace.
import ifcopenshell.geom  # noqa: E402,F401
import ifcopenshell.util.element  # noqa: E402,F401
import ifcopenshell.util.shape  # noqa: E402,F401
import ifcopenshell.util.unit  # noqa: E402,F401

NAMESPACE: dict[str, object] = {}
STATE: dict[str, object] = {"pending": None, "reports": 0, "warnings": []}


def _report_labels(mapping: dict) -> str:
    cleaned = normalise_label_map(mapping)
    STATE["pending"] = cleaned
    STATE["reports"] = int(STATE["reports"]) + 1
    return format_label_receipt(cleaned)


def _prime(request: dict) -> dict:
    """Inject reporting only, even if an old host requests skills."""
    NAMESPACE.clear()
    NAMESPACE["report_labels"] = _report_labels
    loaded: dict = {}
    issues: list[str] = []
    STATE["warnings"] = list(issues)
    return {"ok": True, "skill_loaded": loaded, "skill_issues": issues}


def _execute(request: dict) -> dict:
    STATE["pending"] = None
    STATE["reports"] = 0
    buffer = _BoundedOutput(int(request["limit"]))
    error = False
    error_text = ""
    fatal = False
    try:
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            for warning in STATE["warnings"] or []:
                buffer.write(f"[skill load warning] {warning}\n")
            STATE["warnings"] = []
            exec(request["code"], NAMESPACE)  # noqa: S102 - intentional: this is the REPL
    except BaseException as exc:
        error = True
        error_text = format_agent_traceback(exc, TRACEBACK_LIMIT)
        # Anything outside Exception/SystemExit leaves the interpreter suspect.
        fatal = not isinstance(exc, (Exception, SystemExit))
    labels = STATE["pending"] if not error else None
    return {
        "ok": True,
        "output": assemble_output(buffer.getvalue(), buffer.dropped_chars, error_text),
        "error": error,
        "error_text": error_text,
        "truncated": buffer.dropped_chars > 0,
        "output_dropped_chars": buffer.dropped_chars,
        "labels": labels,
        "label_reports": int(STATE["reports"]) if labels is not None else 0,
        "fatal": fatal,
    }


def main() -> int:
    handlers = {"prime": _prime, "execute": _execute}
    while True:
        line = CONTROL_IN.readline()
        if not line:
            return 0
        try:
            request = json.loads(line)
        except ValueError:
            continue
        operation = request.get("op")
        if operation == "shutdown":
            return 0
        try:
            response = handlers[operation](request)
        except BaseException as exc:  # protocol-level failure, not agent code
            response = {
                "ok": False,
                "detail": f"{type(exc).__name__}: {exc}",
                "fatal": True,
            }
        CONTROL_OUT.write(json.dumps(response) + "\n")
        CONTROL_OUT.flush()
        if response.get("fatal"):
            return 1


if __name__ == "__main__":
    sys.exit(main())
