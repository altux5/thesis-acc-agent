import contextlib
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from skill_library import SkillLibrary


def contract():
    return {"summary": "Return the supplied value.", "inputs": "value: any Python value",
            "returns": "The value unchanged.", "assumptions": "No conversion or validation is performed.",
            "failure_behavior": "Missing arguments raise TypeError."}


def transfer_tests():
    return {"normal": "assert helper(7) == 7", "edge": "assert helper(None) is None",
            "changed_input": "assert helper({'new_id': 42}) == {'new_id': 42}"}


class SkillContractTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(TemporaryDirectory()))
        self.stack.enter_context(patch("skill_library.SKILLS_DIR", self.root))
        self.stack.enter_context(patch("skill_library.MANIFEST", self.root / "manifest.json"))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.library = SkillLibrary()
        self.live = {}

    def test_prompt_uses_contract_not_origin_or_validation_fixture(self):
        self.library.make_save_skill(self.live)("helper", "def helper(value):\n    return value",
            "Learned on secret_mall_case; expected count 112.", test="assert helper(1) == 1",
            contract=contract(), transfer_tests=transfer_tests(),
            provenance={"case_id": "secret_mall_case", "expected_count": 112})
        for loaded_only in (False, True):
            prompt = self.library.prompt_section(loaded_only=loaded_only)
            self.assertNotIn("secret_mall_case", prompt)
            self.assertNotIn("112", prompt)
            self.assertIn("No conversion or validation", prompt)
            self.assertIn("generalization unverified", prompt)
        self.assertEqual(self.library.skills()["helper"]["provenance"]["case_id"], "secret_mall_case")

    def test_unstructured_legacy_description_is_not_sent_to_model(self):
        import json

        (self.root / "helper.py").write_text("def helper(value):\n    return value", encoding="utf-8")
        (self.root / "manifest.json").write_text(json.dumps({"helper": {"description": "Origin: private_condo"}}), encoding="utf-8")
        self.library.preload(self.live)
        prompt = self.library.prompt_section(loaded_only=True)
        self.assertNotIn("private_condo", prompt)
        self.assertIn("contract unavailable", prompt)

    def test_incomplete_contract_rejected_before_install(self):
        with self.assertRaisesRegex(ValueError, "contract must contain"):
            self.library.make_save_skill(self.live)("helper", "def helper(value):\n    return value",
                test="assert helper(1) == 1", contract={"summary": "Works everywhere"})
        self.assertNotIn("helper", self.live)
        self.assertEqual(self.library.skills(), {})

    def test_one_case_only_or_duplicate_tests_cannot_be_saved(self):
        for tests in (None, {"normal": "assert helper(1)==1"},
                      dict.fromkeys(("normal", "edge", "changed_input"), "assert helper(1)==1")):
            with self.subTest(tests=tests), self.assertRaises(ValueError):
                self.library.make_save_skill(self.live)("helper", "def helper(value):\n    return value",
                    test="assert helper(1)==1", contract=contract(), transfer_tests=tests)
        self.assertEqual(self.library.skills(), {})

    def test_transfer_tests_cannot_borrow_live_fixtures(self):
        self.live["items"] = [1, 2]
        tests = {**transfer_tests(), "edge": "assert helper(items) == [1, 2]"}
        with self.assertRaisesRegex(ValueError, "Transfer test 'edge' failed: NameError"):
            self.library.make_save_skill(self.live)("helper", "def helper(value):\n    return value",
                test="assert helper(items) == [1, 2]", contract=contract(), transfer_tests=tests)
        self.assertNotIn("helper", self.live)

    def test_failed_changed_input_preserves_previous_revision(self):
        save = self.library.make_save_skill(self.live)
        save("helper", "def helper(value):\n    return value", test="assert helper(1)==1",
             contract=contract(), transfer_tests=transfer_tests())
        previous = self.live["helper"]
        manifest = (self.root / "manifest.json").read_bytes()
        tests = {"normal": "assert helper(1)==1", "edge": "assert helper(2)==2", "changed_input": "assert helper(3)==3"}
        with self.assertRaisesRegex(ValueError, "Transfer test 'changed_input' failed"):
            save("helper", "def helper(value):\n    return value if value < 3 else 1", test="assert helper(1)==1",
                 contract=contract(), transfer_tests=tests)
        self.assertIs(self.live["helper"], previous)
        self.assertEqual(manifest, (self.root / "manifest.json").read_bytes())

    def test_fixed_model_paths_or_ids_are_rejected(self):
        for code in ("def helper(model):\n    return model.by_guid('some_fixed_guid')",
                     "def helper(model):\n    return model.by_id(12)",
                     "def helper(model):\n    return 'known_model.ifc'",
                     "def helper():\n    return 112"):
            with self.subTest(code=code), self.assertRaises(ValueError):
                self.library.make_save_skill(self.live)("helper", code, test="assert helper(1)==1",
                    contract=contract(), transfer_tests=transfer_tests())

    def test_retained_transfer_programs_replay_without_live_state(self):
        self.library.make_save_skill(self.live)("helper", "def helper(value):\n    return value",
            test="assert helper(1)==1", contract=contract(), transfer_tests=transfer_tests())
        metadata = self.library.skills()["helper"]
        self.assertEqual(metadata["reuse_checks_version"], 1)
        self.assertEqual(set(self.library.retest("helper")["transfer_tests"]), set(transfer_tests()))

    def test_strict_revision_with_missing_tests_is_not_loaded(self):
        import json

        self.library.make_save_skill(self.live)("helper", "def helper(value):\n    return value",
            test="assert helper(1)==1", contract=contract(), transfer_tests=transfer_tests())
        metadata = self.library.skills()
        del metadata["helper"]["transfer_tests"]
        (self.root / "manifest.json").write_text(json.dumps(metadata), encoding="utf-8")
        loaded = {}
        issues = self.library.preload(loaded)
        self.assertNotIn("helper", loaded)
        self.assertIn("transfer_tests must contain", issues[0])

    def test_agent_recovers_from_retired_save_with_local_function_in_both_modes(self):
        from agent import CodeActAgent
        from kernel_executor import KernelCodeExecutor
        from .test_agent import ScriptedClient, reply, python_call, final_call

        code = "def helper(value):\n    return value"
        rejected = f"save_skill('helper', {code!r}, test='assert helper(1)==1')"
        accepted = (f"save_skill('helper', {code!r}, test='assert helper(1)==1', "
                    f"contract={contract()!r}, transfer_tests={transfer_tests()!r})")
        for stateful in (True, False):
            with self.subTest(stateful=stateful), patch("tracing.get_client", return_value=None), patch(
                "agent.discover_scope", return_value=({"anchor"}, "synthetic scope")
            ):
                client = ScriptedClient([
                    reply(python_call(rejected)), reply(python_call(accepted)),
                    reply(python_call(f"{code}\nreport_labels({{'anchor': helper('PASS')}})")),
                    reply(final_call()),
                ])
                executor = KernelCodeExecutor(stateful=stateful, skill_library=SkillLibrary(), timeout=30)
                self.addCleanup(executor.close)
                result = CodeActAgent(client, executor,
                    max_iterations=4, env_primer=False).check("synthetic rule", "unused.ifc")
                self.assertEqual(result.completion_status, "complete")
                self.assertEqual(result.labels, {"anchor": "PASS"})
                self.assertTrue(result.execution_records[0]["error"])
                self.assertIn("NameError", result.execution_records[0]["error_text"])
                self.assertTrue(result.execution_records[1]["error"])
                self.assertIn("NameError", result.execution_records[1]["error_text"])
                self.assertFalse(result.execution_records[2]["error"])
                self.assertEqual(self.library.skills(), {})


if __name__ == "__main__":
    unittest.main()