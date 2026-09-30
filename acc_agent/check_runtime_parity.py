"""Offline kernel contract check; the historical command name is retained.

Checks expected output, reporting, interpreter persistence/reset and a real IFC
classification against the stored reference. Legacy two-runtime comparisons are
preserved below as comments; they are not executed.

    python acc_agent/check_runtime_parity.py

No model calls, no writes outside a temporary directory.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ground_truth
# from executor import CodeExecutor
from kernel_executor import KernelCodeExecutor

OBSERVED = ("last_error", "labels_valid", "label_reports", "reported_labels")
STATUS = ("error", "truncated", "output_dropped_chars", "labels_valid")

BLOCKS = [
    ("no output", "pass"),
    ("print", "print('hello')"),
    ("unicode", "print('\\u00e4\\u00df \\u2192 900\\u00a0mm')"),
    ("builtins available", "print(sorted(dir(__builtins__))[:3] if isinstance(__builtins__, dict) else 'module')"),
    ("harness names", "print(sorted(n for n in dir() if not n.startswith('_')))"),
    ("stdout then error", "print('partial')\nraise ValueError('boom')"),
    ("stderr write", "import sys; sys.stderr.write('warned\\n')"),
    ("nameerror", "print(undefined_name)"),
    ("systemexit", "raise SystemExit(2)"),
    ("labels valid", "print(report_labels({'a': 'pass', 'b': 'Fail', 'c': 'n/a'}))"),
    ("labels then failure", "report_labels({'d': 'PASS'})\nraise RuntimeError('late')"),
    ("labels invalid", "report_labels({'e': 'probably'})"),
    ("empty labels", "print(report_labels({}))"),
    ("long output", "print('x' * 200)"),
    ("nested exception", "try:\n    1/0\nexcept ZeroDivisionError as exc:\n    raise RuntimeError('wrapped') from exc"),
]


def observe(executor) -> dict:
    return {
        **{name: getattr(executor, name) for name in OBSERVED},
        "status": {key: executor.last_execution.get(key) for key in STATUS},
    }


# def compare_blocks(stateful: bool, limit: int) -> list[str]:
#     problems = []
#     inproc = CodeExecutor(stateful=stateful, output_char_limit=limit)
#     kernel = KernelCodeExecutor(stateful=stateful, output_char_limit=limit, timeout=60)
#     try:
#         for name, code in BLOCKS:
#             left, right = inproc.run(code), kernel.run(code)
#             if left != right:
#                 problems.append(f"[{name}] output differs\n  in-process: {left!r}\n  kernel:     {right!r}")
#             if observe(inproc) != observe(kernel):
#                 problems.append(f"[{name}] state differs\n  in-process: {observe(inproc)}\n  kernel:     {observe(kernel)}")
#     finally:
#         inproc.close()
#         kernel.close()
#     return problems


def check_blocks(stateful: bool, limit: int) -> list[str]:
    problems = []
    error_cases = {"stdout then error", "nameerror", "systemexit", "labels then failure", "labels invalid", "nested exception"}
    markers = {
        "no output": "(code ran with no output)", "print": "hello",
        "unicode": "\u00e4\u00df \u2192 900\u00a0mm", "harness names": "['report_labels']",
        "stdout then error": "ValueError: boom", "stderr write": "warned",
        "nameerror": "NameError", "systemexit": "SystemExit: 2",
        "labels valid": "staged 3 element labels", "labels then failure": "RuntimeError: late",
        "labels invalid": "ValueError", "empty labels": "staged 0 element labels",
        "long output": "x" * min(limit, 200), "nested exception": "RuntimeError: wrapped",
    }
    expected_labels = {}
    expected_reports = 0
    expected_valid = False
    executor = KernelCodeExecutor(stateful=stateful, output_char_limit=limit, timeout=60)
    try:
        for name, code in BLOCKS:
            output = executor.run(code)
            expected_error = name in error_cases
            if expected_error:
                expected_labels, expected_valid = {}, False
            elif name in ("labels valid", "empty labels"):
                expected_labels = {"a": "PASS", "b": "FAIL", "c": "NA"} if name == "labels valid" else {}
                expected_reports += 1
                expected_valid = True
            expected = {"last_error": expected_error, "reported_labels": expected_labels,
                        "label_reports": expected_reports, "labels_valid": expected_valid}
            actual = observe(executor)
            for field, value in expected.items():
                if actual[field] != value:
                    problems.append(f"[{name}] {field}: expected {value!r}, got {actual[field]!r}")
            if actual["status"]["error"] != expected_error or actual["status"]["labels_valid"] != expected_valid:
                problems.append(f"[{name}] structured status disagrees with expected outcome")
            if name in markers and markers[name] not in output:
                problems.append(f"[{name}] missing expected output {markers[name]!r}")
            if name == "long output":
                dropped = max(0, 201 - limit)
                if actual["status"]["output_dropped_chars"] != dropped or actual["status"]["truncated"] != bool(dropped):
                    problems.append(f"[{name}] incorrect truncation accounting")
    finally:
        executor.close()
    return problems


def check_statefulness(stateful: bool) -> list[str]:
    executor = KernelCodeExecutor(stateful=stateful, timeout=60)
    try:
        executor.run(
            "import os, sys\nvalue = 7\n"
            "os.environ['ACC_RUNTIME_PROBE'] = 'present'\n"
            "sys.modules['acc_runtime_probe'] = object()\n"
            "with open('probe.txt', 'w') as stream:\n    stream.write('present')\n"
        )
        if executor.last_error:
            return ["Statefulness probe setup failed"]
        output = executor.run(
            "import os, sys, json\n"
            "print(json.dumps({'variable': 'value' in globals(), "
            "'environment': os.environ.get('ACC_RUNTIME_PROBE') == 'present', "
            "'module': 'acc_runtime_probe' in sys.modules, "
            "'scratch_file': os.path.exists('probe.txt')}))"
        )
        expected = dict.fromkeys(("variable", "environment", "module", "scratch_file"), stateful)
        if executor.last_error or json.loads(output) != expected:
            return [f"Statefulness probe disagrees with expected persistence={stateful}: {output}"]
        return []
    finally:
        executor.close()


CLASSIFY = """
import ifcopenshell
from ifcopenshell.util.element import get_psets

model = ifcopenshell.open(r"{ifc}")
KEYS = ("Thickness", "Default Thickness", "Total Thickness", "Monolithic Thickness")
labels = {{}}
for slab in model.by_type("IfcSlab"):
    found = []
    for pset in get_psets(slab, psets_only=True).values():
        for key, value in pset.items():
            if key in KEYS and isinstance(value, (int, float)):
                found.append(float(value))
    if len(found) >= 2 and max(found) - min(found) < 1e-6:
        labels[slab.GlobalId] = "PASS" if 100 <= found[0] <= 1000 else "FAIL"
    else:
        labels[slab.GlobalId] = "ALERT"
report_labels(labels)
print("classified", len(labels))
"""


# def compare_real_model() -> list[str]:
#     problems = []
#     case = ground_truth.load(
#         Path(__file__).resolve().parent / "ground_truth" / "slab_thickness__mall_v2.json")
#     ifc = case.resolve_ifc()
#     code = CLASSIFY.format(ifc=ifc)
#     results = {}
#     for name, executor in (("in-process", CodeExecutor(stateful=True)),
#                            ("kernel", KernelCodeExecutor(stateful=True, timeout=600))):
#         try:
#             output = executor.run(code)
#             if executor.last_error:
#                 problems.append(f"[{name}] classification raised:\n{output[-800:]}")
#             results[name] = dict(executor.reported_labels)
#         finally:
#             executor.close()
#     if results.get("in-process") != results.get("kernel"):
#         left, right = results.get("in-process", {}), results.get("kernel", {})
#         differing = [k for k in set(left) | set(right) if left.get(k) != right.get(k)]
#         problems.append(f"label maps differ on {len(differing)} elements, e.g. {differing[:5]}")
#     reference = case.labels
#     produced = results.get("kernel", {})
#     if set(produced) != set(reference):
#         problems.append(f"anchor set differs from reference: produced {len(produced)}, reference {len(reference)}")
#     counts: dict[str, int] = {}
#     for value in produced.values():
#         counts[value] = counts.get(value, 0) + 1
#     agree = sum(1 for k, v in produced.items() if reference.get(k) == v)
#     print(f"  mall slabs: {len(produced)} labels {counts}, {agree} agree with the reference")
#     return problems


def check_real_model() -> list[str]:
    problems = []
    case = ground_truth.load(Path(__file__).resolve().parent / "ground_truth" / "slab_thickness__mall.json")
    code = CLASSIFY.format(ifc=case.resolve_ifc())
    for stateful in (True, False):
        executor = KernelCodeExecutor(stateful=stateful, timeout=600)
        try:
            output = executor.run(code)
            produced = executor.reported_labels
            if executor.last_error:
                problems.append(f"[stateful={stateful}] classification raised:\n{output[-800:]}")
            if produced != case.labels:
                problems.append(f"[stateful={stateful}] slab labels differ from the reference")
            counts: dict[str, int] = {}
            for value in produced.values():
                counts[value] = counts.get(value, 0) + 1
            print(f"  stateful={stateful}: {len(produced)} slab labels {counts}; exact reference match={produced == case.labels}")
        finally:
            executor.close()
    return problems


# def main() -> int:
#     failures = []
#     for stateful in (True, False):
#         label = "stateful" if stateful else "stateless"
#         print(f"Comparing {len(BLOCKS)} blocks, {label} ...")
#         found = compare_blocks(stateful, 6000)
#         print(f"  {'OK' if not found else str(len(found)) + ' DIFFERENCES'}")
#         failures += found
#     print("Comparing truncation behaviour at a 60-character cap ...")
#     found = compare_blocks(True, 60)
#     print(f"  {'OK' if not found else str(len(found)) + ' DIFFERENCES'}")
#     failures += found
#     print("Replaying a real classification over the mall IFC ...")
#     found = compare_real_model()
#     print(f"  {'OK' if not found else str(len(found)) + ' DIFFERENCES'}")
#     failures += found
#     if failures:
#         print("\nDIFFERENCES FOUND:\n" + "\n".join(failures))
#         return 1
#     print("\nThe two runtimes agree on every checked observable.")
#     return 0


def main() -> int:
    failures = []
    for stateful in (True, False):
        for limit in (6000, 60):
            print(f"Checking {len(BLOCKS)} kernel blocks, stateful={stateful}, output cap={limit} ...")
            found = check_blocks(stateful, limit)
            print("  FAILED" if found else "  OK")
            failures.extend(found)
        print(f"Checking interpreter and scratch-state persistence, stateful={stateful} ...")
        found = check_statefulness(stateful)
        print("  FAILED" if found else "  OK")
        failures.extend(found)
    print("Checking real mall slab classification against the reference ...")
    failures.extend(check_real_model())
    if failures:
        print("\nCHECKS FAILED:\n" + "\n".join(failures))
        return 1
    print("\nAll kernel contract checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
