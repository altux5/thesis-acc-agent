"""Identify imported module code separately from files currently on disk."""

from __future__ import annotations

import hashlib
import marshal
import sys
from pathlib import Path

_IMPORTED = {}


def _digest(code) -> str:
    return hashlib.sha256(marshal.dumps(code, 2)).hexdigest()


def capture_module() -> None:
    code = sys._getframe(1).f_code
    path = str(Path(code.co_filename).resolve())
    _IMPORTED[path] = (code.co_filename, _digest(code))


def module_snapshot(path: Path) -> dict:
    path = path.resolve()
    imported = _IMPORTED.get(str(path))
    result = {"imported_code_sha256": imported[1] if imported else None}
    try:
        source = path.read_bytes()
        result["disk_sha256"] = hashlib.sha256(source).hexdigest()
        compiled = compile(source, imported[0] if imported else str(path), "exec", dont_inherit=True)
        result["disk_code_sha256"] = _digest(compiled)
        result["status"] = ("matches" if result["disk_code_sha256"] == imported[1] else "mismatch") if imported else "not-captured"
    except (OSError, SyntaxError, ValueError) as exc:
        result.update(status="unverified", error=f"{type(exc).__name__}: {exc}")
    return result


capture_module()