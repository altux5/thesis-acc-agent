import hashlib
import json
import unittest

import ground_truth


class ModelFilesTests(unittest.TestCase):
    def test_every_reference_model_is_distributed_and_unchanged(self):
        manifest = json.loads((ground_truth.MODELS_DIR / "MODELS.json").read_text(encoding="utf-8"))["models"]
        digests = {}
        for path in sorted(ground_truth.GT_DIR.glob("*.json")):
            case = json.loads(path.read_text(encoding="utf-8"))
            rel = case.get("ifc_path")
            if not rel:
                continue
            with self.subTest(case=path.stem):
                self.assertIn(rel, manifest)
                resolved = ground_truth.resolve_model_path(rel)
                self.assertEqual(resolved, ground_truth.MODELS_DIR / manifest[rel]["file"])
                if manifest[rel].get("distributed", True) is False and not resolved.is_file():
                    continue
                self.assertTrue(resolved.is_file())
                if resolved not in digests:
                    digests[resolved] = hashlib.sha256(resolved.read_bytes()).hexdigest()
                self.assertEqual(digests[resolved], manifest[rel]["sha256"])
                recorded = (case.get("reference") or {}).get("ifc_sha256") if isinstance(case.get("reference"), dict) else None
                if recorded:
                    self.assertEqual(digests[resolved], recorded)

    def test_default_model_resolves_into_models_folder(self):
        manifest = json.loads((ground_truth.MODELS_DIR / "MODELS.json").read_text(encoding="utf-8"))["models"]
        resolved = ground_truth.resolve_model_path(ground_truth.DEFAULT_IFC_REL)
        self.assertEqual(resolved.parent.parent, ground_truth.MODELS_DIR)
        if manifest[ground_truth.DEFAULT_IFC_REL].get("distributed", True) is False and not resolved.is_file():
            self.skipTest("Default BCA model is local only and not distributed")
        self.assertTrue(resolved.is_file())

    def test_gui_and_cli_default_model_is_distributed(self):
        manifest = json.loads((ground_truth.MODELS_DIR / "MODELS.json").read_text(encoding="utf-8"))["models"]
        entry = manifest[ground_truth.DEFAULT_DISTRIBUTED_IFC_REL]
        self.assertTrue(entry.get("distributed", True))
        self.assertTrue(ground_truth.resolve_model_path(ground_truth.DEFAULT_DISTRIBUTED_IFC_REL).is_file())


if __name__ == "__main__":
    unittest.main()
