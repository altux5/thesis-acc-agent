"""File tools of the file-system condition: path safety, behaviour, limits and manifest."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import file_tools  # noqa: E402
from file_tools import Workspace, WorkspaceError, manifest, resolve  # noqa: E402


class FileToolsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="acc_workspace_test_"))
        self.outside = Path(tempfile.mkdtemp(prefix="acc_outside_test_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.outside, ignore_errors=True)
        self.workspace = Workspace(self.root, output_limit=6000, call_limit=60)

    def call(self, name, **arguments):
        return self.workspace.run(name, **arguments)

    def test_paths_must_stay_relative_and_inside(self):
        refused = ["C:\\Windows\\x.txt", "/etc/x", "\\\\server\\share\\x", "C:x.txt", "..\\x.txt", "a/../../x",
                   "a:stream", "CON", "con.txt", "Lpt1.log", "name. ", "name.", "bad\x00name", "x" * 300, "", "  ",
                   "~/x", "a<b"]
        for path in refused:
            with self.subTest(path=path), self.assertRaises(WorkspaceError):
                resolve(self.root, path)
        self.assertEqual(resolve(self.root, "lib/helpers.py"), self.root / "lib" / "helpers.py")
        self.assertEqual(resolve(self.root, "lib\\helpers.py"), self.root / "lib" / "helpers.py")
        self.assertEqual(resolve(self.root, "./a.txt"), self.root / "a.txt")

    def test_write_read_edit_and_list(self):
        text, error = self.call("write_file", path="lib/helpers.py", content="def f():\n    return 1\n")
        self.assertFalse(error, text)
        self.assertEqual((self.root / "lib" / "helpers.py").read_text(encoding="utf-8"), "def f():\n    return 1\n")
        text, error = self.call("read_file", path="lib/helpers.py")
        self.assertFalse(error)
        self.assertEqual(text, "[lib/helpers.py: lines 1-2 of 2]\ndef f():\n    return 1")
        self.assertEqual(self.call("read_file", path="lib/helpers.py", offset=1, limit=1)[0],
                         "[lib/helpers.py: lines 2-2 of 2]\n    return 1")
        text, error = self.call("edit_file", path="lib/helpers.py", old_string="return 1", new_string="return 2")
        self.assertFalse(error, text)
        self.assertIn("return 2", (self.root / "lib" / "helpers.py").read_text(encoding="utf-8"))
        self.assertEqual(self.call("ls")[0], "lib/helpers.py  22 bytes")
        self.assertEqual(self.call("ls", path="lib")[0], "lib/helpers.py  22 bytes")
        self.assertEqual({name: item["calls"] for name, item in self.workspace.calls.items()},
                         {"ls": 2, "read_file": 2, "write_file": 1, "edit_file": 1})

    def test_edit_requires_a_unique_non_empty_match(self):
        self.call("write_file", path="a.txt", content="x x")
        for arguments, message in (({"old_string": "y", "new_string": "z"}, "not found"),
                                   ({"old_string": "x", "new_string": "z"}, "occurs 2 times"),
                                   ({"old_string": "", "new_string": "z"}, "must not be empty")):
            text, error = self.call("edit_file", path="a.txt", **arguments)
            self.assertTrue(error)
            self.assertIn(message, text)
        text, error = self.call("edit_file", path="a.txt", old_string="x", new_string="z", replace_all=True)
        self.assertFalse(error)
        self.assertEqual((self.root / "a.txt").read_text(encoding="utf-8"), "z z")
        self.assertEqual(self.workspace.calls["edit_file"], {"calls": 4, "errors": 3})

    def test_errors_are_returned_not_raised(self):
        text, error = self.call("write_file", path="split.txt", content="emoji half \ud83d")
        self.assertTrue(error)
        self.assertIn("not valid Unicode", text)
        self.call("write_file", path="plain.txt", content="x")
        self.assertIn("not valid Unicode", self.call("edit_file", path="plain.txt", old_string="x", new_string="\ud83d")[0])
        self.assertEqual(self.workspace.calls["write_file"]["errors"], 1)
        (self.root / "plain.txt").unlink()
        (self.root / "split.txt").unlink(missing_ok=True)
        self.assertIn("No such file", self.call("read_file", path="missing.txt")[0])
        self.assertIn("No such folder", self.call("ls", path="missing")[0])
        (self.root / "data.bin").write_bytes(b"\xff\xfe\x00")
        self.assertIn("Not a UTF-8 text file", self.call("read_file", path="data.bin")[0])
        self.assertIn("limit is", self.call("write_file", path="big.txt", content="x" * (file_tools.MAX_FILE_BYTES + 1))[0])
        self.assertFalse((self.root / "big.txt").exists())
        self.assertEqual(self.call("ls")[0], "data.bin  3 bytes")

    def test_outputs_are_bounded(self):
        workspace = Workspace(self.root, output_limit=100, call_limit=60)
        workspace.run("write_file", path="long.txt", content="\n".join(f"line {i}" for i in range(500)))
        text, _ = workspace.run("read_file", path="long.txt")
        self.assertLessEqual(len(text.split("\n... [truncated")[0]), 100)
        self.assertIn("read fewer lines with offset and limit", text)
        for index in range(file_tools.MAX_LIST_ENTRIES + 5):
            (self.root / f"f{index:03}.txt").write_text("x", encoding="utf-8")
        listing = Workspace(self.root, output_limit=100_000, call_limit=60).run("ls")[0]
        self.assertIn("... and 6 more files", listing)

    def test_call_limit_counts_every_file_tool(self):
        workspace = Workspace(self.root, output_limit=6000, call_limit=2)
        workspace.run("ls")
        workspace.run("write_file", path="a.txt", content="x")
        text, error = workspace.run("read_file", path="a.txt")
        self.assertTrue(error)
        self.assertIn("limit of 2 file tool calls", text)

    def test_writes_replace_and_never_follow_hard_links(self):
        external = self.outside / "external.txt"
        external.write_text("original", encoding="utf-8")
        os.link(external, self.root / "linked.txt")
        for name, arguments in (("write_file", {"content": "changed"}),
                                ("edit_file", {"old_string": "original", "new_string": "changed"}),
                                ("read_file", {})):
            text, error = self.call(name, path="linked.txt", **arguments)
            self.assertTrue(error, name)
            self.assertIn("hard links", text)
        self.assertEqual(external.read_text(encoding="utf-8"), "original")

    def test_junctions_and_symlinks_are_not_followed(self):
        import _winapi
        _winapi.CreateJunction(str(self.outside), str(self.root / "junction"))
        (self.outside / "secret.txt").write_text("secret", encoding="utf-8")
        for name, arguments in (("write_file", {"content": "x"}), ("read_file", {})):
            text, error = self.call(name, path="junction/secret.txt", **arguments)
            self.assertTrue(error)
            self.assertIn("link", text)
        self.assertEqual((self.outside / "secret.txt").read_text(encoding="utf-8"), "secret")
        self.assertEqual(self.call("ls")[0], "junction  [link, not followed]")
        record = manifest(self.root)
        self.assertEqual((record["files"], record["links"]), ([], ["junction"]))
        try:
            os.symlink(self.outside / "secret.txt", self.root / "symlink.txt")
        except OSError:
            self.skipTest("creating symlinks needs Windows developer mode or admin rights")
        self.assertIn("link", self.call("read_file", path="symlink.txt")[0])

    def test_manifest_records_names_sizes_and_hashes_only(self):
        self.call("write_file", path="lib/a.py", content="print(1)\n")
        (self.root / "results.json").write_text("{}", encoding="utf-8")
        record = manifest(self.root)
        self.assertEqual([item["path"] for item in record["files"]], ["lib/a.py", "results.json"])
        self.assertEqual(set(record["files"][0]), {"path", "bytes", "sha256"})
        self.assertEqual((record["file_count"], record["total_bytes"], record["omitted"]), (2, 11, 0))
        self.assertEqual(manifest(self.root / "missing")["file_count"], 0)


if __name__ == "__main__":
    unittest.main()
