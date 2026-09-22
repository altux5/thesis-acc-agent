import tkinter as tk
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import customtkinter as ctk

from experiment_view import ExperimentsView, cell, sorted_rows
from experiments import ExperimentStore
from .test_experiments import configuration


class TableSortingTests(unittest.TestCase):
    def test_rate_cells_are_percentages_and_missing_is_not_zero(self):
        self.assertEqual(cell(0.2, "code_error_rate"), "20.0%")
        self.assertEqual(cell(0.0, "aborted_rate"), "0.0%")
        self.assertEqual(cell(None, "code_error_rate"), "n/a")

    def test_numeric_sort_not_lexicographic_and_missing_last(self):
        rows = [{"value": value} for value in (100, None, 9, 20)]
        self.assertEqual([row["value"] for row in sorted_rows(rows, "value")], [9, 20, 100, None])
        self.assertEqual([row["value"] for row in sorted_rows(rows, "value", True)], [100, 20, 9, None])


class ExperimentViewTests(unittest.TestCase):
    def test_skills_enabled_runs_visible_by_default_and_filter_is_explicit(self):
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"EXPERIMENT_DB": str(Path(directory) / "test.sqlite3")}):
            store = ExperimentStore()
            sweep = store.start_sweep("fixture", 2)
            settings = configuration()
            settings["skills_enabled"] = True
            for repeat, f1 in ((1, 1.0), (2, 0.0)):
                run = store.start_run(sweep, settings, repeat)
                store.finish_run(run, "complete", {"f1": f1}, executions=2 if repeat == 1 else 8, error_count=1)
            store.finish_sweep(sweep)
            try:
                root = ctk.CTk()
            except tk.TclError as exc:
                self.skipTest(str(exc))
            try:
                root.withdraw()
                view = ExperimentsView(root)
                view.pack(fill="both", expand=True)
                view.refresh()
                self.assertFalse(view.comparable.get())
                self.assertEqual(len(view.table.get_children()), 1)
                self.assertEqual(view.rows[0]["f1_mean"], 0.5)
                self.assertEqual(view.rows[0]["code_error_rate"], 0.2)
                self.assertEqual(view.table.set("0", "code_error_rate"), "20.0%")
                self.assertEqual(view.table.set("0", "aborted_rate"), "0.0%")
                view.mode.set("Runs")
                view.refresh()
                self.assertEqual(len(view.table.get_children()), 2)
                self.assertEqual(sorted(row["code_error_rate"] for row in view.rows), [0.125, 0.5])
                view.comparable.set(True)
                view.refresh()
                self.assertEqual(view.rows, [])
                self.assertIn("No matches with comparison filter enabled", view.status.cget("text"))
                view.mode.set("Sweeps")
                view.refresh()
                self.assertEqual(len(view.table.get_children()), 1)
                self.assertEqual(view.comparison_filter.cget("state"), "disabled")
                view.mode.set("Configurations")
                view.comparable.set(False)
                view.refresh()
                self.assertEqual(len(view.table.get_children()), 1)
                self.assertEqual(view.comparison_filter.cget("state"), "normal")
            finally:
                for timer in root.tk.call("after", "info"):
                    root.tk.call("after", "cancel", timer)
                root.destroy()

    def test_tables_filters_selection_and_clipboard(self):
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"EXPERIMENT_DB": str(Path(directory) / "test.sqlite3")}):
            store = ExperimentStore()
            sweep = store.start_sweep("fixture", 2)
            for repeat, f1 in ((1, 1.0), (2, 0.0)):
                run = store.start_run(sweep, configuration(), repeat)
                store.finish_run(run, "complete" if f1 else "incomplete", {"f1": f1})
            store.finish_sweep(sweep)
            try:
                root = ctk.CTk()
            except tk.TclError as exc:
                self.skipTest(str(exc))
            try:
                root.withdraw()
                view = ExperimentsView(root)
                view.pack(fill="both", expand=True)
                view.refresh()
                self.assertEqual(len(view.rows), 1)
                self.assertEqual(view.rows[0]["f1_mean"], 0.5)
                view.mode.set("Runs")
                view.refresh()
                self.assertEqual(len(view.rows), 2)
                view.sort("f1")
                self.assertEqual(view.rows[0]["f1"], 0.0)
                view.table.selection_set("0")
                view.select()
                view.copy()
                self.assertIn("Started UTC\tCase", root.clipboard_get())
                view.search.set("not found")
                view.refresh()
                self.assertEqual(view.rows, [])
                view.mode.set("Sweeps")
                view.search.set("")
                view.refresh()
                self.assertEqual(view.rows[0]["attempts"], 2)
            finally:
                for timer in root.tk.call("after", "info"):
                    root.tk.call("after", "cancel", timer)
                root.destroy()


if __name__ == "__main__":
    unittest.main()