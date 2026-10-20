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
                self.assertTrue(resolved.is_file())
                if resolved not in digests:
                    digests[resolved] = hashlib.sha256(resolved.read_bytes()).hexdigest()
                self.assertEqual(digests[resolved], manifest[rel]["sha256"])
                recorded = (case.get("reference") or {}).get("ifc_sha256") if isinstance(case.get("reference"), dict) else None
                if recorded:
                    self.assertEqual(digests[resolved], recorded)

    def test_default_model_resolves_into_models_folder(self):
        resolved = ground_truth.resolve_model_path(ground_truth.DEFAULT_IFC_REL)
        self.assertEqual(resolved.parent.parent, ground_truth.MODELS_DIR)
        self.assertTrue(resolved.is_file())


if __name__ == "__main__":
    unittest.main()
