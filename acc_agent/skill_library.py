"""Agent-authored helpers with isolated globals, self-tests and durable revisions.

Archived exploratory implementation since 2026-09-16. The application no longer
imports, loads, saves or advertises skills. Standalone tests retain this code for
historical reference; SKILLS cannot re-enable the commented-out integration.

This is not a security sandbox or independent correctness certification. Candidate
code and tests run in-process; imported modules and external side effects are not
isolated. Skills are only installed after testing and a successful manifest commit.
"""

from __future__ import annotations

import datetime as _dt
import ast
import builtins
import copy
import hashlib
import inspect
import json
import keyword
import marshal
import os
import re
import tempfile
import threading
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from types import FunctionType, ModuleType

from code_identity import capture_module
capture_module()

PROJECT_DIR = Path(__file__).resolve().parent
# Overridable because the kernel worker is a separate process and cannot inherit
# a monkeypatched module attribute.
SKILLS_DIR = Path(os.environ.get("SKILLS_DIR") or (PROJECT_DIR / "skills"))
MANIFEST = SKILLS_DIR / "manifest.json"

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RESERVED_NAMES = frozenset(dir(builtins)) | {"report_labels", "save_skill"}
_WRITE_LOCK = threading.RLock()
CONTRACT_FIELDS = ("summary", "inputs", "returns", "assumptions", "failure_behavior")
TRANSFER_CASES = ("normal", "edge", "changed_input")


def _contract(value: dict | None) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) != set(CONTRACT_FIELDS):
        raise ValueError("contract must contain summary, inputs, returns, assumptions and failure_behavior")
    if any(not isinstance(text, str) or not text.strip() or "\n" in text or len(text) > 1000 for text in value.values()):
        raise ValueError("Contract fields must be nonempty single-line strings, at most 1000 characters each")
    return {key: value[key].strip() for key in CONTRACT_FIELDS}


def _validate_reuse(name: str, code: str, contract: dict | None, transfer_tests: dict | None) -> tuple[dict, dict]:
    public = _contract(contract)
    if not public:
        raise ValueError("A functional contract is required before saving a reusable skill")
    if not isinstance(transfer_tests, dict) or set(transfer_tests) != set(TRANSFER_CASES):
        raise ValueError("transfer_tests must contain normal, edge and changed_input test programs")
    if any(not isinstance(test, str) or not test.strip() for test in transfer_tests.values()):
        raise ValueError("Each transfer test must be a nonempty Python program")
    programs = [ast.dump(ast.parse(test)) for test in transfer_tests.values()]
    if len(set(programs)) != len(TRANSFER_CASES):
        raise ValueError("Transfer tests must differ; use varied constructed inputs and expected results")
    tree = ast.parse(code)
    function = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name), None)
    if function is not None and not (function.args.posonlyargs or function.args.args or function.args.kwonlyargs or function.args.vararg or function.args.kwarg):
        raise ValueError("Reusable skills must accept inputs; pass model data and task-specific settings as parameters")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if re.search(r"(?:[A-Za-z]:[\\/]|(?:^|\s)/[^\s]+\.ifc|\.ifc\b)", node.value, re.IGNORECASE):
                raise ValueError("Do not embed IFC file paths in skills; accept a model or path argument")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("by_guid", "by_id"):
            arguments = [*node.args, *(item.value for item in node.keywords)]
            if any(isinstance(argument, ast.Constant) for argument in arguments):
                raise ValueError("Do not embed entity lookup IDs in skills; pass identifiers as arguments")
    return public, {key: transfer_tests[key].strip() for key in TRANSFER_CASES}


def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not _IDENT.fullmatch(name) or keyword.iskeyword(name):
        raise ValueError(f"skill name must be a valid Python identifier, got {name!r}")
    if name in RESERVED_NAMES or name.startswith("__"):
        raise ValueError(f"skill name {name!r} is reserved for Python or the harness")


def _candidate(name: str, code: str, filename: str) -> tuple[Callable, dict]:
    _validate_name(name)
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code must be nonempty Python source")
    namespace = {"__builtins__": vars(builtins).copy(), "__name__": f"skill_{name}"}
    exec(compile(code, filename, "exec", optimize=0), namespace)
    function = namespace.get(name)
    if not isinstance(function, FunctionType) or inspect.iscoroutinefunction(function) or inspect.isgeneratorfunction(function):
        raise ValueError(f"code must define a regular synchronous function named {name!r}")
    if function.__globals__ is not namespace:
        raise ValueError("Skill function must be defined in its own source, not imported from another module")
    return function, namespace


def _copy_fixture(value, memo: dict):
    if type(value).__module__.startswith("ifcopenshell"):
        import ifcopenshell

        if isinstance(value, ifcopenshell.file):
            if id(value) not in memo:
                memo[id(value)] = ifcopenshell.file.from_string(value.to_string())
            return memo[id(value)]
        if isinstance(value, ifcopenshell.entity_instance):
            if not value.id():
                raise ValueError("Inline IFC values need explicit setup in the test")
            return _copy_fixture(value.file, memo).by_id(value.id())
    if isinstance(value, list):
        if id(value) not in memo:
            memo[id(value)] = []
            memo[id(value)].extend(_copy_fixture(item, memo) for item in value)
        return memo[id(value)]
    if isinstance(value, dict):
        if id(value) not in memo:
            memo[id(value)] = {}
            memo[id(value)].update((_copy_fixture(key, memo), _copy_fixture(item, memo)) for key, item in value.items())
        return memo[id(value)]
    if isinstance(value, tuple):
        return tuple(_copy_fixture(item, memo) for item in value)
    return copy.deepcopy(value, memo)


def _initial_state(namespace: dict) -> str:
    seen = {}

    def describe(value):
        if value is None or type(value) in (bool, int, float, complex, str, bytes):
            return [type(value).__name__, repr(value)]
        if id(value) in seen:
            return ["ref", seen[id(value)]]
        seen[id(value)] = len(seen)
        if isinstance(value, ModuleType):
            return ["import", value.__name__]
        if isinstance(value, FunctionType):
            if value.__globals__ is not namespace:
                return ["import", value.__module__, value.__qualname__]
            return ["function", marshal.dumps(value.__code__.replace(co_filename="<skill>"), 2).hex(),
                    describe(value.__defaults__), describe(value.__kwdefaults__), describe(value.__annotations__),
                    describe(value.__dict__), describe(tuple(cell.cell_contents for cell in value.__closure__)) if value.__closure__ else None]
        if inspect.isbuiltin(value) or (isinstance(value, type) and value.__module__ != namespace["__name__"]):
            return ["import", value.__module__, value.__qualname__]
        if type(value) in (list, tuple):
            return [type(value).__name__, [describe(item) for item in value]]
        if type(value) is dict:
            return ["dict", [[describe(key), describe(item)] for key, item in value.items()]]
        if type(value) in (set, frozenset) and all(type(item) in (bool, int, float, complex, str, bytes) or item is None for item in value):
            return [type(value).__name__, sorted((type(item).__name__, repr(item)) for item in value)]
        raise ValueError(f"Cannot verify skill initialization state of type {type(value).__name__}; create runtime objects inside the helper")

    state = [[key, describe(value)] for key, value in namespace.items() if key != "__builtins__"]
    return hashlib.sha256(json.dumps(state, ensure_ascii=True).encode("utf-8")).hexdigest()


def _test_candidate(name: str, code: str, test: str, live: dict, filename: str) -> tuple[str, list[str], str]:
    if not isinstance(test, str) or not test.strip():
        raise ValueError("A nonempty test containing assertions and a call to the skill is required")
    tree = ast.parse(test, filename="<skill-test>")
    if not any(isinstance(node, ast.Assert) for node in ast.walk(tree)):
        raise ValueError("The skill test must contain an assertion")
    function, private = _candidate(name, code, filename)
    initial_state = _initial_state(private)
    fixtures = []
    memo = {}

    class TestNamespace(dict):
        def __missing__(self, key):
            if key not in live or key in private or key in RESERVED_NAMES:
                raise KeyError(key)
            try:
                value = _copy_fixture(live[key], memo)
            except Exception as exc:
                raise ValueError(f"Cannot copy fixture {key!r}; create it or import it in the test: {exc}") from exc
            self[key] = value
            fixtures.append(key)
            return value

    test_namespace = TestNamespace(__builtins__=vars(builtins).copy())
    calls = 0
    assertions = 0

    def assertion_passed():
        nonlocal assertions
        assertions += 1

    assertion_hook = "_skill_assertion_" + uuid.uuid4().hex

    class CountAssertions(ast.NodeTransformer):
        def visit_Assert(self, node):
            return [node, ast.copy_location(ast.Expr(value=ast.Call(
                func=ast.Name(id=assertion_hook, ctx=ast.Load()), args=[], keywords=[])), node)]

    tree = ast.fix_missing_locations(CountAssertions().visit(tree))
    test_namespace[assertion_hook] = assertion_passed

    def tested_function(*args, **kwargs):
        nonlocal calls
        result = function(*args, **kwargs)
        calls += 1
        return result

    test_namespace[name] = tested_function
    exec(compile(tree, "<skill-test>", "exec", optimize=0), test_namespace)
    if not calls:
        raise ValueError("The test must successfully call the candidate skill")
    if not assertions:
        raise ValueError("The skill test must execute an assertion successfully")
    return str(inspect.signature(function)), sorted(fixtures), initial_state


def _load_manifest() -> dict:
    if MANIFEST.exists():
        try:
            data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"Skill manifest cannot be read: {exc}") from exc
        if not isinstance(data, dict) or any(not isinstance(meta, dict) for meta in data.values()):
            raise ValueError("Skill manifest must map skill names to metadata objects")
        return data
    return {}


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".skill-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _save_manifest(data: dict) -> None:
    _atomic_write(MANIFEST, json.dumps(data, indent=2, sort_keys=True))


@contextmanager
def _manifest_lock():
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    with _WRITE_LOCK, (SKILLS_DIR / ".write.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Skill library is being updated by another process; retry the save") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def source_path(name: str, metadata: dict) -> Path:
    _validate_name(name)
    relative = Path(metadata.get("code_path", f"{name}.py"))
    if relative.is_absolute() or relative.drive:
        raise ValueError("Skill source path must be relative to the library")
    path = (SKILLS_DIR / relative).resolve()
    if not path.is_relative_to(SKILLS_DIR.resolve()):
        raise ValueError("Skill source path escapes the library")
    return path


def _source(name: str, metadata: dict) -> tuple[Path, str]:
    path = source_path(name, metadata)
    data = path.read_bytes()
    if metadata.get("format_version") == 2:
        if hashlib.sha256(data).hexdigest() != metadata.get("sha256"):
            raise ValueError("Saved skill source hash does not match its committed revision")
        if not isinstance(metadata.get("test"), str) or not metadata["test"].strip():
            raise ValueError("Self-tested revision has no retained test")
        if metadata.get("reuse_checks_version"):
            _validate_reuse(name, data.decode("utf-8"), metadata.get("contract"), metadata.get("transfer_tests"))
    return path, data.decode("utf-8")


class SkillLibrary:
    """Disk-backed self-tested helpers; namespace isolation is not a sandbox."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.loaded: dict[str, dict] = {}
        self.load_issues: list[str] = []
        self._load_snapshot: dict | None = None

    # ---- reading -----------------------------------------------------------
    def skills(self) -> dict:
        return _load_manifest() if self.enabled else {}

    def prompt_section(self, *, loaded_only: bool = False) -> str:
        """Text for the system prompt describing the library + how to extend it."""
        if not self.enabled:
            return ""
        lines = [
            "\nAvailable Python helpers (applicability must be checked against the current task).",
            "Passing self-tests does not establish general correctness. Inspect assumptions before use.",
            "- Persist a useful synchronous helper with:",
            '    save_skill("name", code, test="<assertion using it>",',
            '        contract={"summary": ..., "inputs": ..., "returns": ...,',
            '                  "assumptions": ..., "failure_behavior": ...},',
            '        transfer_tests={"normal": ..., "edge": ..., "changed_input": ...})',
            "  An executed passing assertion and an actual successful call are REQUIRED.",
            "  Before saving, extract the reusable operation. Parameterize task thresholds,",
            "  source-selection policies and units; do not bake in an answer, filename or entity ID.",
            "  Document accepted types, units, ambiguity and missing-data behavior. Do not",
            "  silently choose a conflicting measurement or assume one export layout is universal.",
            "  Describe function behavior only: no originating case, model name, score or success story",
            "  in the contract, docstrings or comments. Optional provenance={} is audit metadata only.",
            "  Each transfer test is a separate program with no session fixtures. Construct",
            "  fresh inputs for normal, edge/missing/conflicting, and changed-input scenarios.",
            "  Vary values, IDs, order, units or settings as relevant and assert expected results.",
            "  Test programs must call the candidate and execute assertions. They are retained.",
            "  Each helper has private globals; import dependencies in its source.",
            "  Initialization must repeat unchanged: use plain values, containers,",
            "  functions and imports. Create runtime objects inside the helper.",
            "  Tests may reference named session inputs such as model or slabs; these",
            "  are copied as fixtures, not injected into the helper's globals. Imports",
            "  and setup can also be written in the test. Do not depend on other skills",
            "  or session globals. Test normal, missing-data and boundary cases.",
            "  A failed test/save does not replace the live helper. Python/harness",
            "  names (including report_labels and save_skill) are reserved.",
        ]
        issues = list(self.load_issues)
        skills = self.loaded
        if not loaded_only:
            skills = {}
            issues = []
            try:
                for name, metadata in self.skills().items():
                    try:
                        path, code = _source(name, metadata)
                        ast.parse(code, filename=str(path))
                        skills[name] = metadata
                    except Exception as exc:
                        issues.append(f"{name}: unavailable ({type(exc).__name__}: {exc})")
            except (OSError, ValueError) as exc:
                issues.append(str(exc))
        if skills:
            lines.append("- Successfully loaded helpers; call them directly by name:" if loaded_only else "- Catalogued helpers (load outcome not yet established):")
            for name, meta in skills.items():
                state = "self-tested" if meta.get("format_version") == 2 else "legacy: test unavailable; validate before relying on it"
                lines.append(f"    {name}{meta.get('signature', '(...)')} [{state}; generalization unverified]")
                if not meta.get("reuse_checks_version"):
                    lines.append("      Transfer-test checks unavailable; validate applicability before use.")
                contract = meta.get("contract") or {}
                if contract:
                    for key in CONTRACT_FIELDS:
                        lines.append(f"      {key}: {contract.get(key, 'unspecified')}")
                else:
                    lines.append("      Applicability contract unavailable; inspect and validate before use.")
        else:
            lines.append("- No saved helpers are loaded.")
        for issue in issues:
            lines.append("- Skill load warning: " + issue)
        return "\n".join(lines) + "\n"

    # ---- loading into a REPL namespace -------------------------------------
    def preload(self, namespace: dict) -> list[str]:
        """Install only each helper's public function; report skipped entries."""
        self.loaded = {}
        self.load_issues = []
        if not self.enabled:
            return []
        try:
            manifest = self.skills()
        except (OSError, ValueError) as exc:
            self.load_issues.append(str(exc))
            return list(self.load_issues)
        self._load_snapshot = manifest
        for name, metadata in manifest.items():
            try:
                path, code = _source(name, metadata)
                if name in namespace:
                    raise ValueError("Name is already used by the session; refusing to replace it during preload")
                function, private = _candidate(name, code, str(path))
                if metadata.get("initial_state_sha256") and _initial_state(private) != metadata["initial_state_sha256"]:
                    raise ValueError("Skill initialization differs from the self-tested revision")
                namespace[name] = function
                self.loaded[name] = metadata
                if metadata.get("format_version") != 2:
                    self.load_issues.append(f"{name}: legacy helper loaded; original test was not retained and was not rerun")
            except Exception as exc:
                self.load_issues.append(f"{name}: skipped ({type(exc).__name__}: {exc})")
        return list(self.load_issues)

    def health(self) -> dict:
        """Inspect metadata and parse code without executing it or changing files."""
        if not self.enabled:
            return {"enabled": False, "skills": [], "issues": []}
        try:
            manifest = self.skills()
        except (OSError, ValueError) as exc:
            return {"enabled": True, "skills": [], "issues": [str(exc)]}
        entries = []
        for name, metadata in manifest.items():
            entry = {"name": name, "version": metadata.get("version", "legacy"),
                     "validation": metadata.get("validation", "legacy: test unavailable"), "status": "source checked"}
            try:
                path, code = _source(name, metadata)
                ast.parse(code, filename=str(path))
                entry["path"] = str(path)
            except Exception as exc:
                entry.update(status="unavailable", issue=f"{type(exc).__name__}: {exc}")
            entries.append(entry)
        return {"enabled": True, "skills": entries, "issues": []}

    def make_save_skill(self, namespace: dict) -> Callable:
        """Return a ``save_skill`` bound to the live *namespace*."""

        def save_skill(
            name: str, code: str, description: str = "", test: str | None = None,
            *, contract: dict | None = None, provenance: dict | None = None,
            transfer_tests: dict | None = None,
        ) -> str:
            if not self.enabled:
                raise RuntimeError("Skills are disabled")
            _validate_name(name)
            public_contract, transfer_programs = _validate_reuse(name, code, contract, transfer_tests)
            provenance = json.loads(json.dumps(provenance or {}, allow_nan=False))
            if not isinstance(provenance, dict):
                raise ValueError("provenance must be a JSON object")
            code = code.strip() + "\n"
            revision = uuid.uuid4().hex
            path = SKILLS_DIR / "versions" / name / f"{revision}.py"
            signature, fixtures, initial_state = _test_candidate(name, code, test, namespace, str(path))
            for kind, program in transfer_programs.items():
                try:
                    _, _, transfer_state = _test_candidate(name, code, program, {}, str(path))
                    if transfer_state != initial_state:
                        raise ValueError("Skill initialization differs between test cases")
                except Exception as exc:
                    raise ValueError(f"Transfer test {kind!r} failed: {type(exc).__name__}: {exc}") from exc
            with _manifest_lock():
                manifest = _load_manifest()
                previous = manifest.get(name)
                if self._load_snapshot is not None and self._load_snapshot.get(name) != previous:
                    raise RuntimeError("Skill revision changed since this session loaded it; reload before replacing it")
                function, private = _candidate(name, code, str(path))
                if _initial_state(private) != initial_state:
                    raise ValueError("Skill initialization differs from the tested candidate; move runtime setup inside the helper")
                history = list(previous.get("history", [])) if previous else []
                if previous:
                    archived = {key: value for key, value in previous.items() if key != "history"}
                    if previous.get("format_version") != 2:
                        _, old_code = _source(name, previous)
                        old_relative = Path("versions") / name / f"legacy-{uuid.uuid4().hex}.py"
                        _atomic_write(SKILLS_DIR / old_relative, old_code)
                        archived.update(code_path=old_relative.as_posix(), version="legacy", test=None,
                                        sha256=hashlib.sha256(old_code.encode("utf-8")).hexdigest())
                    history.append(archived)
                metadata = {
                    "format_version": 2, "version": int(previous.get("version", 0)) + 1 if previous and previous.get("format_version") == 2 else 1,
                    "revision": revision, "code_path": path.relative_to(SKILLS_DIR).as_posix(),
                    "sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
                    "signature": signature, "description": str(description),
                    "contract": public_contract, "provenance": provenance,
                    "reuse_checks_version": 1, "transfer_tests": transfer_programs,
                    "saved": _dt.datetime.now().isoformat(timespec="seconds"),
                    "tested": True, "test": test, "test_fixtures": fixtures,
                    "initial_state_sha256": initial_state,
                    "fixture_policy": "Referenced live inputs copied into a test-only namespace; IFC models cloned. Fixture values are not persisted; supply equivalent inputs to rerun.",
                    "validation": "self-tested on supplied examples; generalization unverified", "history": history,
                }
                _atomic_write(path, code)
                manifest[name] = metadata
                _save_manifest(manifest)
            namespace[name] = function
            self.loaded[name] = metadata
            if self._load_snapshot is None:
                self._load_snapshot = {}
            self._load_snapshot[name] = metadata
            self.load_issues = [issue for issue in self.load_issues if not issue.startswith(name + ":")]

            msg = (
                f"[skill saved] {name}{signature} v{metadata['version']} - self-tested, not independently verified."
            )
            print(msg)
            return msg

        return save_skill

    def retest(self, name: str, fixtures: dict | None = None) -> dict:
        """Rerun a retained test with caller-supplied fixtures; do not install or save."""
        if not self.enabled:
            raise RuntimeError("Skills are disabled")
        metadata = self.skills().get(name)
        if metadata is None:
            raise ValueError(f"Unknown skill {name!r}")
        path, code = _source(name, metadata)
        test = metadata.get("test")
        if not test:
            raise ValueError("Legacy helper has no retained test; resave it with a new test")
        signature, inputs, initial_state = _test_candidate(name, code, test, fixtures or {}, str(path))
        if metadata.get("initial_state_sha256") and initial_state != metadata["initial_state_sha256"]:
            raise ValueError("Skill initialization differs from the self-tested revision")
        for kind, program in metadata.get("transfer_tests", {}).items():
            _, _, transfer_state = _test_candidate(name, code, program, {}, str(path))
            if transfer_state != initial_state:
                raise ValueError(f"Skill initialization differs during transfer test {kind!r}")
        return {"name": name, "version": metadata.get("version"), "signature": signature,
                "fixtures": inputs, "transfer_tests": list(metadata.get("transfer_tests", {})),
                "validation": "self-test passed; not independently verified"}
