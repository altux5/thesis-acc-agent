"""Workspace file tools for the file-system condition (protocol ``langchain-codeact-v5-files-guided``).

The tools run in the host process, outside the worker's write confinement, so every path is
validated here: relative only, inside the run workspace, no links or junctions, no Windows
device names or alternate data streams. Writes go to a fresh temporary file that then
replaces the target, so a write never follows a link out of the workspace. This is
containment for model-written code, not a security sandbox.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path, PureWindowsPath

from code_identity import capture_module
capture_module()

FILE_TOOL_NAMES = ("ls", "read_file", "write_file", "edit_file")
MAX_FILE_BYTES = 1_000_000
MAX_PATH_CHARS = 200
MAX_LIST_ENTRIES = 200
DEFAULT_READ_LINES = 200
MANIFEST_MAX_ENTRIES = 500
_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])(\..*)?$", re.IGNORECASE)
_INVALID_CHARS = set('<>:"|?*') | {chr(code) for code in range(32)}


class WorkspaceError(ValueError):
    """A request the workspace refuses; the message is returned to the model."""


def _is_link(path: Path) -> bool:
    info = os.lstat(path)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & reparse)


def _parts(relative: str) -> list[str]:
    if not isinstance(relative, str) or not relative.strip():
        raise WorkspaceError("Give a relative path inside the working folder.")
    if len(relative) > MAX_PATH_CHARS:
        raise WorkspaceError(f"Path longer than {MAX_PATH_CHARS} characters.")
    pure = PureWindowsPath(relative)
    if pure.drive or pure.root or relative.startswith(("/", "\\", "~")):
        raise WorkspaceError("Absolute paths are not allowed; use a path relative to the working folder.")
    parts = [part for part in re.split(r"[\\/]+", relative) if part not in ("", ".")]
    for part in parts:
        if part == "..":
            raise WorkspaceError("'..' is not allowed; stay inside the working folder.")
        if set(part) & _INVALID_CHARS:
            raise WorkspaceError(f"Invalid character in {part!r} (no < > : \" | ? * or control characters).")
        if part.endswith((" ", ".")) or _RESERVED.match(part):
            raise WorkspaceError(f"{part!r} is not a valid file name on Windows.")
    return parts


def resolve(root: Path, relative: str) -> Path:
    """Map *relative* to a path inside *root* without following any link."""
    root = Path(root)
    path = root
    for part in _parts(relative):
        path = path / part
        if os.path.lexists(path) and _is_link(path):
            raise WorkspaceError(f"{relative!r} goes through a link; links are not followed.")
    real_root = os.path.normcase(os.path.realpath(root))
    real = os.path.normcase(os.path.realpath(path))
    if real != real_root and not real.startswith(real_root + os.sep):
        raise WorkspaceError(f"{relative!r} is outside the working folder.")
    return path


def _check_single_link(path: Path) -> None:
    if path.exists() and os.lstat(path).st_nlink > 1:
        raise WorkspaceError("This file has several hard links; it is refused.")


def _encode(text: str) -> bytes:
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise WorkspaceError("Content is not valid Unicode text (unpaired surrogate).") from exc


def _atomic_write(path: Path, data: bytes) -> None:
    if len(data) > MAX_FILE_BYTES:
        raise WorkspaceError(f"Content is {len(data)} bytes; the limit is {MAX_FILE_BYTES} bytes.")
    if path.exists() and not path.is_file():
        raise WorkspaceError("A folder with this name exists.")
    _check_single_link(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{os.urandom(4).hex()}.tmp")
    try:
        with open(temp, "xb") as handle:
            handle.write(data)
        os.replace(temp, path)
    finally:
        if os.path.lexists(temp):
            os.remove(temp)


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise WorkspaceError("No such file.")
    _check_single_link(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise WorkspaceError(f"File larger than {MAX_FILE_BYTES} bytes; read it from Python instead.")
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceError("Not a UTF-8 text file.") from exc


class Workspace:
    """The four file tools over one run workspace, with per-run call accounting."""

    def __init__(self, root: Path, *, output_limit: int, call_limit: int):
        self.root = Path(root)
        self.output_limit = output_limit
        self.call_limit = call_limit
        self.calls = {name: {"calls": 0, "errors": 0} for name in FILE_TOOL_NAMES}

    def run(self, name: str, **arguments) -> tuple[str, bool]:
        """Execute one tool call; returns (text for the model, error flag)."""
        record = self.calls[name]
        record["calls"] += 1
        if sum(item["calls"] for item in self.calls.values()) > self.call_limit:
            record["errors"] += 1
            return f"Error: the limit of {self.call_limit} file tool calls for this check is reached.", True
        try:
            return getattr(self, "_" + name)(**arguments), False
        except WorkspaceError as exc:
            record["errors"] += 1
            return f"Error: {exc}", True
        except OSError as exc:
            record["errors"] += 1
            return f"Error: {type(exc).__name__}: {exc.strerror or exc}", True
        except (ValueError, TypeError) as exc:  # a bad argument must not end the check
            record["errors"] += 1
            return f"Error: {type(exc).__name__}: {exc}", True

    def _bounded(self, text: str, hint: str) -> str:
        if len(text) <= self.output_limit:
            return text
        return text[:self.output_limit] + f"\n... [truncated {len(text) - self.output_limit} characters; {hint}]"

    def _ls(self, path: str = ".") -> str:
        base = self.root if path in ("", ".") else resolve(self.root, path)
        if not base.is_dir():
            raise WorkspaceError("No such folder.")
        lines, more = [], 0
        for current, folders, files in os.walk(base):
            current_path = Path(current)
            for folder in list(folders):
                if _is_link(current_path / folder):
                    folders.remove(folder)
                    files.append(folder)
            folders.sort()
            for name in sorted(files):
                entry = current_path / name
                relative = entry.relative_to(self.root).as_posix()
                if len(lines) >= MAX_LIST_ENTRIES:
                    more += 1
                elif _is_link(entry):
                    lines.append(f"{relative}  [link, not followed]")
                else:
                    lines.append(f"{relative}  {os.lstat(entry).st_size} bytes")
        if not lines:
            return "(no files)"
        return self._bounded("\n".join(lines) + (f"\n... and {more} more files" if more else ""), "list a subfolder")

    def _read_file(self, path: str, offset: int = 0, limit: int = DEFAULT_READ_LINES) -> str:
        lines = _read_text(resolve(self.root, path)).splitlines()
        offset, limit = max(0, int(offset)), max(1, int(limit))
        chunk = lines[offset:offset + limit]
        header = f"[{path}: lines {offset + 1}-{offset + len(chunk)} of {len(lines)}]" if lines else f"[{path}: empty file]"
        return self._bounded(header + ("\n" + "\n".join(chunk) if chunk else ""), "read fewer lines with offset and limit")

    def _write_file(self, path: str, content: str) -> str:
        target = resolve(self.root, path)
        data = _encode(content)
        _atomic_write(target, data)
        return f"Wrote {len(data)} bytes to {path}."

    def _edit_file(self, path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
        target = resolve(self.root, path)
        text = _read_text(target)
        if not old_string:
            raise WorkspaceError("old_string must not be empty.")
        count = text.count(old_string)
        if count == 0:
            raise WorkspaceError("old_string was not found; read the file and copy the exact text.")
        if count > 1 and not replace_all:
            raise WorkspaceError(f"old_string occurs {count} times; give more context or set replace_all.")
        updated = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
        _atomic_write(target, _encode(updated))
        return f"Replaced {count if replace_all else 1} occurrence(s) in {path}."


def manifest(root: Path) -> dict:
    """Names, sizes and SHA-256 of the workspace files; contents are never recorded."""
    root = Path(root)
    entries, links, total, omitted = [], [], 0, 0
    if not root.is_dir():
        return {"files": [], "links": [], "file_count": 0, "total_bytes": 0, "omitted": 0}
    for current, folders, files in os.walk(root):
        current_path = Path(current)
        for folder in list(folders):
            if _is_link(current_path / folder):
                folders.remove(folder)
                links.append((current_path / folder).relative_to(root).as_posix())
        for name in sorted(files):
            entry = current_path / name
            relative = entry.relative_to(root).as_posix()
            if _is_link(entry):
                links.append(relative)
                continue
            size = os.lstat(entry).st_size
            total += size
            if len(entries) >= MANIFEST_MAX_ENTRIES:
                omitted += 1
                continue
            digest = hashlib.sha256()
            try:
                with open(entry, "rb") as handle:
                    for block in iter(lambda: handle.read(1 << 20), b""):
                        digest.update(block)
                sha = digest.hexdigest()
            except OSError as exc:
                sha = f"unreadable: {type(exc).__name__}"
            entries.append({"path": relative, "bytes": size, "sha256": sha})
    return {"files": sorted(entries, key=lambda item: item["path"]), "links": sorted(links),
            "file_count": len(entries) + omitted, "total_bytes": total, "omitted": omitted}
