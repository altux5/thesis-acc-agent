import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from agent import AgentResult
from code_identity import module_snapshot
from experiment_recorder import SweepRecorder
from experiments import ExperimentStore


class CodeIdentityTests(unittest.TestCase):
    def test_old_import_is_not_misidentified_as_edited_source(self):
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"EXPERIMENTS": "1"}):
            root = Path(directory)
            path = root / "fixture.py"
            source = "from code_identity import capture_module\ncapture_module()\ndef answer():\n    return 1\n"
            path.write_text(source, encoding="utf-8")
            spec = importlib.util.spec_from_file_location("identity_fixture", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            before = module_snapshot(path)
            self.assertEqual(before["status"], "matches")
            path.write_text(source.replace("return 1", "return 200"), encoding="utf-8")
            after = module_snapshot(path)
            self.assertEqual(module.answer(), 1)
            self.assertEqual(after["status"], "mismatch")
            self.assertEqual(after["imported_code_sha256"], before["imported_code_sha256"])
            self.assertNotEqual(after["disk_code_sha256"], before["disk_code_sha256"])
            store = ExperimentStore(root / "test.sqlite3")
            with patch("experiment_recorder.code_snapshot", return_value={"fixture.py": after}):
                recorder = SweepRecorder(entrypoint="test", requested=1, case=None, rule="fixture", ifc_path=path,
                    client=Mock(provider="offline", model="fixture", max_tokens=8000), max_iterations=1,
                    reasoning=False, env_primer=False, library=None, output_limit=1000, store=store, warning=Mock())
                ticket = recorder.start_run("stateful", 1, 1)
                recorder.finish_run(ticket, AgentResult("", 1))
            row = store.list_runs()[0]
            self.assertEqual(row["context_changed"], 1)
            self.assertFalse(ticket.configuration["runtime_code_verified"])
            recorder.warning.assert_called_once()

    def test_uninstrumented_source_is_not_claimed_as_verified(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.py"
            path.write_text("value = 1\n", encoding="utf-8")
            self.assertEqual(module_snapshot(path)["status"], "not-captured")

    def test_captured_identity_module_matches_its_source(self):
        import code_identity
        self.assertEqual(module_snapshot(Path(code_identity.__file__))["status"], "matches")


if __name__ == "__main__":
    unittest.main()