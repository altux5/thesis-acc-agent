import csv
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from experiments import ExperimentStore, describe, export_csv, fingerprint


def configuration(**changes):
    return {"case_id": "test", "model": "offline", "mode": "stateful", "harness": 1,
            "max_iterations": 10, "skills_enabled": False, "audit": {"status": "relations-checked"},
            "rule_hash": "rule", "reference_hash": "v1", "skill_hash": "empty", **changes}


class ExperimentStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ExperimentStore(Path(self.temp.name) / "experiments.sqlite3")

    def test_configuration_identity_includes_every_condition(self):
        base = configuration()
        self.assertEqual(fingerprint(base), fingerprint(dict(reversed(list(base.items())))))
        for key, value in {"mode": "stateless", "reference_hash": "v2", "skill_hash": "new", "max_iterations": 12}.items():
            self.assertNotEqual(fingerprint(base), fingerprint({**base, key: value}))

    def test_identical_configuration_pools_across_separate_sweeps(self):
        for value in (0.5, 1.0):
            sweep = self.store.start_sweep("test", 1)
            run = self.store.start_run(sweep, configuration(), 1)
            self.store.finish_run(run, "complete", {"f1": value})
            self.store.finish_sweep(sweep)
        groups = self.store.summaries()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["attempts"], 2)
        self.assertEqual(groups[0]["f1_mean"], 0.75)

    def test_case_ids_recorded_before_the_renaming_read_as_current_names(self):
        sweep = self.store.start_sweep("test", 3)
        for repeat, config in enumerate((configuration(case_id="staircase_width_v8"),
                                         configuration(case_id="staircase_width_v8_full"),
                                         configuration(case_id="staircase_width_v8", recording_version=4)), 1):
            self.store.start_run(sweep, config, repeat)
        self.assertEqual(sorted(row["case_id"] for row in self.store.list_runs()),
                         ["staircase_width_v8", "staircase_width_v8", "staircase_width_v8_deprecated_v1"])

    def test_record_errors_missing_metrics_and_configuration_means(self):
        sweep = self.store.start_sweep("test", 3)
        for repeat, status, scores in [(1, "complete", {"f1": 1.0, "union_accuracy": 1.0}),
                                       (2, "incomplete", {"f1": 0.0}), (3, "error", None)]:
            run = self.store.start_run(sweep, configuration(), repeat)
            self.store.finish_run(run, status, scores)
        self.store.finish_sweep(sweep)
        summary = self.store.summaries()[0]
        self.assertEqual(summary["attempts"], 3)
        self.assertAlmostEqual(summary["completion_rate"], 1 / 3)
        self.assertEqual(summary["f1_mean"], 0.5)
        self.assertEqual(summary["f1_n"], 2)
        self.assertEqual(summary["union_accuracy_n"], 1)
        self.assertIsNone(summary["union_accuracy_std"])
        self.assertEqual(len(self.store.list_runs(comparison_only=True)), 3)

    def test_duplicate_runs_and_final_overwrite_refused(self):
        sweep = self.store.start_sweep("test", 1)
        run = self.store.start_run(sweep, configuration(), 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.start_run(sweep, configuration(), 1)
        self.store.finish_run(run, "complete", {"f1": 1.0})
        with self.assertRaises(ValueError):
            self.store.finish_run(run, "error")

    def test_error_rates_distinguish_code_failures_from_aborted_runs(self):
        sweep = self.store.start_sweep("test", 5)
        for repeat, status, counts in (
            (1, "complete", {"executions": 2, "error_count": 1}),
            (2, "complete", {"executions": 8, "error_count": 1}),
            (3, "error", {"executions": 0, "error_count": 0}),
            (4, "interrupted", {}),
        ):
            run = self.store.start_run(sweep, configuration(), repeat)
            self.store.finish_run(run, status, {"f1": 0.0} if status == "complete" else None, **counts)
        self.store.start_run(sweep, configuration(), 5)
        rates = {row["repeat"]: row["code_error_rate"] for row in self.store.list_runs()}
        self.assertEqual(rates, {1: 0.5, 2: 0.125, 3: None, 4: None, 5: None})
        summary = self.store.summaries()[0]
        self.assertEqual(summary["aborted_rate"], 0.5)
        self.assertEqual(summary["code_errors"], 2)
        self.assertEqual(summary["code_executions"], 10)
        self.assertEqual(summary["code_error_rate"], 0.2)
        self.assertEqual(summary["code_error_runs_n"], 3)

    def test_error_rates_without_observations_are_unknown(self):
        sweep = self.store.start_sweep("test", 1)
        run = self.store.start_run(sweep, configuration(), 1)
        running = self.store.summaries()[0]
        self.assertIsNone(running["aborted_rate"])
        self.assertIsNone(running["code_error_rate"])
        self.store.finish_run(run, "complete")
        finished = self.store.summaries()[0]
        self.assertEqual(finished["aborted_rate"], 0)
        self.assertIsNone(finished["code_error_rate"])
        self.assertIsNone(finished["code_errors"])

    def test_recovery_is_explicit_and_preserves_other_sweeps(self):
        first = self.store.start_sweep("test", 2)
        second = self.store.start_sweep("test", 1)
        self.store.start_run(first, configuration(), 1)
        self.store.start_run(second, configuration(), 1)
        ExperimentStore(self.store.path)
        self.assertTrue(all(row["status"] == "running" for row in self.store.list_runs()))
        self.store.interrupt_sweep(first)
        statuses = {row["sweep_id"]: row["status"] for row in self.store.list_runs()}
        self.assertEqual(statuses, {first: "interrupted", second: "running"})

    def test_training_skills_and_invalid_references_not_default_comparisons(self):
        sweep = self.store.start_sweep("test", 4)
        for repeat, config in enumerate((configuration(), configuration(harness=3), configuration(skills_enabled=True),
                                         configuration(audit={"status": "invalid-or-incomplete"})), 1):
            run = self.store.start_run(sweep, config, repeat)
            self.store.finish_run(run, "complete", {"f1": 1})
        self.assertEqual(len(self.store.summaries()), 4)
        self.assertEqual(len(self.store.summaries(comparison_only=True)), 1)

    def test_verified_subset_is_comparable_but_legacy_scope_stays_excluded(self):
        sweep = self.store.start_sweep("test", 3)
        for repeat, config in enumerate((
                configuration(case_id="staircase_width_v8", reference_hash="subset-v1",
                              audit={"status": "expert-subset-checked"}),
                configuration(case_id="staircase_width_v8", reference_hash="legacy",
                              audit={"status": "invalid-or-incomplete"}),
                configuration(case_id="staircase_width_v8", harness=3, reference_hash="subset-v1",
                              audit={"status": "expert-subset-checked"})), 1):
            run = self.store.start_run(sweep, config, repeat)
            self.store.finish_run(run, "complete", {"union_accuracy": 1.0})
        self.assertEqual(len(self.store.summaries()), 3)
        eligible = self.store.list_runs(comparison_only=True)
        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0]["audit_status"], "expert-subset-checked")
        self.assertEqual(eligible[0]["harness"], 1)

    def test_runtime_isolation_is_recorded_and_separates_configurations(self):
        sweep = self.store.start_sweep("test", 2)
        kernel = self.store.start_run(sweep, configuration(runtime_isolation="kernel"), 1)
        legacy = self.store.start_run(sweep, configuration(runtime_isolation="inprocess"), 2)
        for run in (kernel, legacy):
            self.store.finish_run(run, "complete", {"f1": 1})
        runtimes = {row["id"]: row["runtime_isolation"] for row in self.store.list_runs()}
        self.assertEqual(runtimes, {kernel: "kernel", legacy: "inprocess"})
        # Same case and model, but the two runtimes must never pool into one mean.
        self.assertEqual(len(self.store.summaries()), 2)
        self.assertEqual({row["runtime_isolation"] for row in self.store.summaries()},
                         {"kernel", "inprocess"})
        self.assertEqual(len(self.store.list_runs(search="kernel")), 1)

    def test_version_one_database_migrates_and_marks_old_rows_legacy(self):
        path = Path(self.temp.name) / "v1.sqlite3"
        legacy = sqlite3.connect(path)
        try:
            with legacy:
                legacy.executescript("""
                CREATE TABLE configurations (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, model TEXT NOT NULL,
                    mode TEXT NOT NULL, harness INTEGER NOT NULL, budget INTEGER NOT NULL,
                    audit_status TEXT NOT NULL, skills_enabled INTEGER NOT NULL,
                    details TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE sweeps (
                    id TEXT PRIMARY KEY, entrypoint TEXT NOT NULL, requested INTEGER NOT NULL,
                    started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
                    owner TEXT NOT NULL, log_path TEXT, error TEXT);
                CREATE TABLE runs (
                    id TEXT PRIMARY KEY, sweep_id TEXT NOT NULL REFERENCES sweeps(id),
                    configuration_id TEXT NOT NULL REFERENCES configurations(id),
                    repeat INTEGER NOT NULL, mode TEXT NOT NULL,
                    started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
                    duration_seconds REAL, verdict TEXT, precision REAL, recall REAL, f1 REAL,
                    union_accuracy REAL, label_coverage REAL, prompt_tokens INTEGER,
                    completion_tokens INTEGER, iterations INTEGER, executions INTEGER,
                    error_count INTEGER, truncations INTEGER, labels_reported INTEGER,
                    labels_expected INTEGER, context_changed INTEGER NOT NULL DEFAULT 0,
                    log_path TEXT, trace_url TEXT, error TEXT, details TEXT,
                    UNIQUE(sweep_id, mode, repeat));
                INSERT INTO configurations VALUES('c','old','offline','stateful',1,10,'relations-checked',0,'{}','t');
                INSERT INTO sweeps VALUES('s','test',1,'t',NULL,'running','owner',NULL,NULL);
                INSERT INTO runs(id,sweep_id,configuration_id,repeat,mode,started_at,status)
                    VALUES('r','s','c',1,'stateful','t','running');
                PRAGMA user_version=1;
            """)
        finally:
            legacy.close()
        store = ExperimentStore(path)
        row = store.list_runs()[0]
        self.assertEqual(row["runtime_isolation"], "inprocess-legacy")
        with store.connection() as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
        ExperimentStore(path)  # migration repeats cleanly

    def test_invalid_metric_and_future_schema_rejected(self):
        sweep = self.store.start_sweep("test", 1)
        run = self.store.start_run(sweep, configuration(), 1)
        with self.assertRaises(ValueError):
            self.store.finish_run(run, "complete", {"f1": float("nan")})
        with self.store.connection() as connection:
            connection.execute("PRAGMA user_version=999")
        with self.assertRaises(ValueError):
            ExperimentStore(self.store.path)

    def test_backup_and_excel_safe_csv(self):
        sweep = self.store.start_sweep("test", 1)
        self.store.start_run(sweep, configuration(model="=formula"), 1)
        backup = Path(self.temp.name) / "backup.sqlite3"
        self.store.backup(backup)
        self.assertEqual(len(ExperimentStore(backup).list_runs()), 1)
        path = Path(self.temp.name) / "results.csv"
        export_csv(path, self.store.list_runs(), ["model", "f1"])
        with path.open(encoding="utf-8-sig", newline="") as stream:
            values = list(csv.reader(stream))
        self.assertEqual(values[1], ["'=formula", ""])

    def test_statistics_use_sample_variation_and_null_for_empty(self):
        self.assertEqual(describe([])["n"], 0)
        self.assertIsNone(describe([])["mean"])
        self.assertAlmostEqual(describe([0, 1])["std"], 2 ** -0.5)


if __name__ == "__main__":
    unittest.main()