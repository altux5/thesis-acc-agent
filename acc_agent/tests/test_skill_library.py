import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kernel_executor import KernelCodeExecutor
from skill_library import SkillLibrary, source_path


class SkillLibraryTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(TemporaryDirectory()))
        self.stack.enter_context(patch("skill_library.SKILLS_DIR", self.root))
        self.stack.enter_context(patch("skill_library.MANIFEST", self.root / "manifest.json"))
        self.stack.enter_context(patch("skill_library._validate_reuse", return_value=({}, {})))
        self.library = SkillLibrary()
        self.live = {}
        self.save = self.library.make_save_skill(self.live)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def test_real_call_required_and_tests_retained(self):
        code = "def helper(value):\n    return value + 1"
        for test in (None, "", "assert True", "helper(1)"):
            with self.subTest(test=test), self.assertRaises(ValueError):
                self.save("helper", code, test=test)
        self.save("helper", code, test="assert helper(2) == 3")
        self.assertEqual(self.library.skills()["helper"]["test"], "assert helper(2) == 3")

    def test_live_global_dependency_rejected(self):
        self.live["offset"] = 10
        with self.assertRaises(NameError):
            self.save("helper", "def helper(value):\n    return value + offset", test="assert helper(1) == 11")
        self.assertNotIn("helper", self.live)
        self.assertEqual(self.library.skills(), {})

    def test_test_imports_and_local_bindings_are_not_external_fixtures(self):
        import math

        self.live.update(math=math, floor=math.floor, values=math, value=math)
        self.save("helper", "def helper(value):\n    return value", test="""
import math
from math import floor
values = [1, 2]
assert [helper(value) for value in values] == [1, 2]
def check(value):
    assert helper(math.floor(value)) == floor(value)
check(1.9)
""")
        self.assertEqual(self.library.skills()["helper"]["test_fixtures"], [])

    def test_read_before_assignment_still_copies_external_fixture(self):
        self.live["items"] = [1, 2]
        self.save("helper", "def helper(value):\n    return value", test="items = items[1:]\nassert helper(items) == [2]")
        self.assertEqual(self.live["items"], [1, 2])
        self.assertEqual(self.library.skills()["helper"]["test_fixtures"], ["items"])

    def test_fixture_access_inside_test_function_uses_private_copy(self):
        self.live["items"] = [1]
        self.save("helper", "def helper(items):\n    items.append(2)\n    return items", test="""
def check():
    assert helper(items) == [1, 2]
check()
""")
        self.assertEqual(self.live["items"], [1])
        self.assertEqual(self.library.skills()["helper"]["test_fixtures"], ["items"])

    def test_dead_or_caught_failing_assertion_cannot_mark_test_passed(self):
        for test in ("if False:\n    assert helper() == 1\nhelper()",
                     "def unused():\n    assert helper() == 1\nhelper()",
                     "helper()\ntry:\n    assert False\nexcept AssertionError:\n    pass"):
            with self.subTest(test=test), self.assertRaisesRegex(ValueError, "execute an assertion"):
                self.save("helper", "def helper():\n    return 1", test=test)
        self.assertEqual(self.library.skills(), {})

    def test_failed_replacement_preserves_live_and_disk(self):
        self.save("helper", "def helper():\n    return 1", test="assert helper() == 1")
        previous = self.live["helper"]
        files = {path.name: path.read_bytes() for path in self.root.iterdir() if path.is_file()}
        with self.assertRaises(AssertionError):
            self.save("helper", "def helper():\n    return 99", test="assert helper() == 1")
        self.assertIs(self.live["helper"], previous)
        self.assertEqual(self.live["helper"](), 1)
        self.assertEqual(files, {path.name: path.read_bytes() for path in self.root.iterdir() if path.is_file()})

    def test_changed_initialization_cannot_replace_tested_function(self):
        self.save("helper", "def helper():\n    return 10", test="assert helper() == 10")
        previous = self.live["helper"]
        manifest = (self.root / "manifest.json").read_bytes()
        with patch("time.time", side_effect=[1.0, 2.0]), self.assertRaisesRegex(ValueError, "initialization differs"):
            self.save("helper", "import time\nbase = time.time()\ndef helper():\n    return base", test="assert helper() == 1.0")
        self.assertIs(self.live["helper"], previous)
        self.assertEqual((self.root / "manifest.json").read_bytes(), manifest)

    def test_test_mutation_does_not_become_installed_initial_state(self):
        code = "items = []\ndef helper(cache=[]):\n    items.append(1)\n    cache.append(2)\n    return len(items), len(cache)"
        self.save("helper", code, test="assert helper() == (1, 1)\nassert helper() == (2, 2)")
        self.assertEqual(self.live["helper"](), (1, 1))
        loaded = {}
        self.assertEqual(self.library.preload(loaded), [])
        self.assertEqual(loaded["helper"](), (1, 1))

    def test_initialization_drift_on_reload_is_visible_and_skipped(self):
        code = "import time\nbase = time.time()\ndef helper():\n    return base"
        with patch("time.time", return_value=1.0):
            self.save("helper", code, test="assert helper() == 1.0")
        with patch("time.time", return_value=2.0):
            loaded = {}
            issues = self.library.preload(loaded)
        self.assertNotIn("helper", loaded)
        self.assertIn("initialization differs", issues[0])

    def test_unverifiable_top_level_objects_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Cannot verify skill initialization"):
            self.save("helper", "state = object()\ndef helper():\n    return state is not None", test="assert helper()")
        self.assertEqual(self.library.skills(), {})

    def test_reserved_names_cannot_replace_harness_or_builtins(self):
        for name in ("report_labels", "save_skill", "print", "__builtins__", "class"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.save(name, f"def {name}():\n    return 1", test=f"assert {name}() == 1")

    def test_skill_globals_are_separate_from_each_other_and_live_session(self):
        for name, value in (("first", 1), ("second", 2)):
            self.save(name, f"shared_value = {value}\ndef {name}():\n    return shared_value", test=f"assert {name}() == {value}")
        self.live["shared_value"] = 900
        for shared_value in (800, 900):
            namespace = {"shared_value": shared_value}
            self.library.preload(namespace)
            self.assertEqual(namespace["first"](), 1)
            self.assertEqual(namespace["second"](), 2)
        self.assertEqual(self.live["first"](), 1)

    def test_mutable_fixture_is_copied_and_not_installed_in_function_globals(self):
        self.live["items"] = [1]
        self.save("helper", "def helper(items):\n    items.append(2)\n    return len(items)", test="assert helper(items) == 2")
        self.assertEqual(self.live["items"], [1])
        self.assertNotIn("items", self.live["helper"].__globals__)

    def test_ifc_fixture_is_cloned(self):
        import ifcopenshell

        model = ifcopenshell.file(schema="IFC4")
        element = model.create_entity("IfcSlab", GlobalId=ifcopenshell.guid.new(), Name="original")
        self.live["model"] = model
        self.live["element"] = element
        code = "def helper(model, element):\n    element.Name = 'changed'\n    return model.by_guid(element.GlobalId).Name"
        self.save("helper", code, test="assert helper(model, element) == 'changed'")
        self.assertEqual(element.Name, "original")

    def test_disabled_library_cannot_save_or_preload(self):
        disabled = SkillLibrary(enabled=False)
        with self.assertRaises(RuntimeError):
            disabled.make_save_skill({})("helper", "def helper():\n    return 1", test="assert helper() == 1")
        executor = KernelCodeExecutor(skill_library=disabled, timeout=30)
        self.addCleanup(executor.close)
        self.assertEqual(executor.run("print('save_skill' in globals())"), "False")

    def test_versions_keep_old_source_and_executable_tests(self):
        self.save("helper", "def helper():\n    return 1", test="assert helper() == 1")
        previous = self.library.skills()["helper"]
        old_bytes = source_path("helper", previous).read_bytes()
        self.save("helper", "def helper():\n    return 2", test="assert helper() == 2")
        current = self.library.skills()["helper"]
        self.assertEqual(current["version"], 2)
        self.assertEqual(current["history"][0]["test"], "assert helper() == 1")
        self.assertEqual(source_path("helper", previous).read_bytes(), old_bytes)
        self.assertEqual(self.live["helper"](), 2)

    def test_manifest_commit_failure_preserves_previous_function_and_pointer(self):
        self.save("helper", "def helper():\n    return 1", test="assert helper() == 1")
        manifest_bytes = (self.root / "manifest.json").read_bytes()
        with patch("skill_library._save_manifest", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.save("helper", "def helper():\n    return 2", test="assert helper() == 2")
        self.assertEqual(self.live["helper"](), 1)
        self.assertEqual((self.root / "manifest.json").read_bytes(), manifest_bytes)
        namespace = {}
        self.library.preload(namespace)
        self.assertEqual(namespace["helper"](), 1)

    def test_missing_corrupt_or_reserved_skills_are_not_advertised(self):
        self.save("helper", "def helper():\n    return 1", test="assert helper() == 1")
        path = source_path("helper", self.library.skills()["helper"])
        path.unlink()
        loaded = {}
        issues = self.library.preload(loaded)
        self.assertTrue(any("skipped" in issue for issue in issues))
        self.assertNotIn("helper", loaded)
        self.assertNotIn("helper() -", self.library.prompt_section(loaded_only=True))
        self.assertIn("Skill load warning", self.library.prompt_section(loaded_only=True))
        executor = KernelCodeExecutor(skill_library=self.library, timeout=30)
        self.addCleanup(executor.close)
        self.assertEqual(executor.skill_load_issues, [])
        self.assertEqual(executor.run("print('still usable')"), "still usable")
        self.assertFalse(executor.last_error)

    def test_changed_source_hash_is_rejected(self):
        self.save("helper", "def helper():\n    return 1", test="assert helper() == 1")
        path = source_path("helper", self.library.skills()["helper"])
        path.write_text("def helper():\n    return 99\n", encoding="utf-8")
        loaded = {}
        self.assertTrue(self.library.preload(loaded))
        self.assertNotIn("helper", loaded)
        self.assertEqual(self.library.health()["skills"][0]["status"], "unavailable")

    def test_corrupt_manifest_reported_and_never_overwritten(self):
        path = self.root / "manifest.json"
        path.write_text("{bad json", encoding="utf-8")
        self.assertTrue(self.library.preload({}))
        with self.assertRaises(ValueError):
            self.save("helper", "def helper():\n    return 1", test="assert helper() == 1")
        self.assertEqual(path.read_text(encoding="utf-8"), "{bad json")

    def test_legacy_source_preserved_and_not_claimed_as_self_tested(self):
        import json

        source = self.root / "helper.py"
        source.write_text("def helper():\n    return 1\n", encoding="utf-8")
        (self.root / "manifest.json").write_text(json.dumps({"helper": {"signature": "()", "tested": True}}), encoding="utf-8")
        original = source.read_bytes()
        warnings = self.library.preload(self.live)
        self.assertIn("legacy", warnings[0])
        self.save("helper", "def helper():\n    return 2", test="assert helper() == 2")
        self.assertEqual(source.read_bytes(), original)
        history = self.library.skills()["helper"]["history"]
        self.assertEqual(history[0]["version"], "legacy")
        self.assertIsNone(history[0]["test"])

    def test_stale_writer_cannot_overwrite_another_sessions_revision(self):
        self.save("helper", "def helper():\n    return 1", test="assert helper() == 1")
        other = SkillLibrary()
        other.preload({})
        other.make_save_skill({})("helper", "def helper():\n    return 2", test="assert helper() == 2")
        self.save("unrelated", "def unrelated():\n    return 10", test="assert unrelated() == 10")
        with self.assertRaisesRegex(RuntimeError, "revision changed"):
            self.save("helper", "def helper():\n    return 3", test="assert helper() == 3")
        self.assertEqual(self.live["helper"](), 1)

    def test_imported_function_cannot_claim_private_globals(self):
        with self.assertRaisesRegex(ValueError, "own source"):
            self.save("helper", "from json import dumps as helper", test="assert helper(1) == '1'")

    def test_retained_test_can_be_rerun_without_writing_or_mutating_fixtures(self):
        self.live["items"] = [1]
        self.save("helper", "def helper(items):\n    items.append(2)\n    return items", test="assert helper(items) == [1, 2]")
        before = (self.root / "manifest.json").read_bytes()
        items = [1]
        result = self.library.retest("helper", {"items": items})
        self.assertEqual(result["version"], 1)
        self.assertEqual(items, [1])
        self.assertEqual((self.root / "manifest.json").read_bytes(), before)

    def test_experiment_fingerprint_reads_committed_revision(self):
        from experiment_recorder import skills_snapshot
        from experiments import fingerprint

        self.save("helper", "def helper():\n    return 1", test="assert helper() == 1")
        first = skills_snapshot(self.library)
        self.assertEqual(first["files"]["helper"], self.library.skills()["helper"]["sha256"])
        self.save("helper", "def helper():\n    return 2", test="assert helper() == 2")
        self.assertNotEqual(fingerprint(first), fingerprint(skills_snapshot(self.library)))

    def test_subprocess_writer_cannot_modify_locked_manifest(self):
        import subprocess
        import sys
        from skill_library import _manifest_lock

        script = (
            "from pathlib import Path\nimport skill_library\n"
            f"skill_library.SKILLS_DIR = Path({str(self.root)!r})\n"
            "try:\n    with skill_library._manifest_lock():\n        print('incorrectly acquired')\n"
            "except RuntimeError:\n    print('locked')\n"
        )
        with _manifest_lock():
            result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
                                    capture_output=True, text=True, timeout=15, check=True)
        self.assertEqual(result.stdout.strip(), "locked")

    def test_outside_path_and_reserved_legacy_names_skipped(self):
        import json

        data = {"helper": {"code_path": "../outside.py"}, "report_labels": {}}
        (self.root / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
        builtin = object()
        namespace = {"report_labels": builtin}
        issues = self.library.preload(namespace)
        self.assertEqual(len(issues), 2)
        self.assertIs(namespace["report_labels"], builtin)

    def test_metadata_inspection_does_not_execute_skill_code(self):
        import json

        (self.root / "broken.py").write_text("raise RuntimeError('must not run')\n", encoding="utf-8")
        (self.root / "manifest.json").write_text(json.dumps({"broken": {}}), encoding="utf-8")
        health = self.library.health()
        self.assertEqual(health["skills"][0]["status"], "source checked")
        self.assertIn("Catalogued helpers", self.library.prompt_section())
        self.assertIn("RuntimeError", " ".join(self.library.preload({})))
        executor = KernelCodeExecutor(skill_library=self.library, timeout=30)
        self.addCleanup(executor.close)
        self.assertEqual(executor.run("print('broken' in globals())"), "False")
        self.assertEqual(executor.skill_load_issues, [])
        self.assertEqual(executor.skill_prompt_section(), "")


if __name__ == "__main__":
    unittest.main()