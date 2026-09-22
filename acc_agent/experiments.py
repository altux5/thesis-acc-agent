"""Local SQLite experiment ledger. No providers, credentials or agent calls."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sqlite3
import statistics
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from code_identity import capture_module
capture_module()

SCHEMA_VERSION = 2
# Rows written before the column existed. The kernel runtime did not exist then,
# so they were in-process, but that is inferred rather than recorded.
LEGACY_RUNTIME = "inprocess-legacy"
FINAL_STATES = {"complete", "incomplete", "abstained", "reported_unverified_scope", "error", "interrupted"}
METRICS = ("precision", "recall", "f1", "union_accuracy", "label_coverage")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def fingerprint(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def default_path() -> Path:
    override = os.environ.get("EXPERIMENT_DB")
    if override:
        return Path(override).expanduser()
    root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "share"))
    return root / "acc_agent" / "experiments.sqlite3"


def describe(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "std": None, "ci95_low": None, "ci95_high": None}
    average = statistics.fmean(values)
    deviation = statistics.stdev(values) if len(values) > 1 else None
    margin = 1.96 * deviation / math.sqrt(len(values)) if deviation is not None else None
    return {"n": len(values), "mean": average, "std": deviation,
            "ci95_low": average - margin if margin is not None else None,
            "ci95_high": average + margin if margin is not None else None}


def _add_column(connection, table: str, column: str, ddl: str) -> None:
    """Idempotent ALTER, so an interrupted migration can simply be repeated."""
    existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


class ExperimentStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, SCHEMA_VERSION):
                raise ValueError(f"Unsupported experiment database version: {version}")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS configurations (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, model TEXT NOT NULL,
                    mode TEXT NOT NULL, harness INTEGER NOT NULL, budget INTEGER NOT NULL,
                    audit_status TEXT NOT NULL, skills_enabled INTEGER NOT NULL,
                    details TEXT NOT NULL, created_at TEXT NOT NULL,
                    runtime_isolation TEXT NOT NULL DEFAULT 'inprocess'
                );
                CREATE TABLE IF NOT EXISTS sweeps (
                    id TEXT PRIMARY KEY, entrypoint TEXT NOT NULL, requested INTEGER NOT NULL,
                    started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
                    owner TEXT NOT NULL, log_path TEXT, error TEXT
                );
                CREATE TABLE IF NOT EXISTS runs (
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
                    runtime_isolation TEXT NOT NULL DEFAULT 'inprocess',
                    UNIQUE(sweep_id, mode, repeat)
                );
                CREATE INDEX IF NOT EXISTS runs_configuration ON runs(configuration_id);
            """)
            for table in ("runs", "configurations"):
                _add_column(connection, table, "runtime_isolation",
                            f"runtime_isolation TEXT NOT NULL DEFAULT '{LEGACY_RUNTIME}'")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def start_sweep(self, entrypoint: str, requested: int, log_path: str = "", owner: str = "") -> str:
        if requested < 1:
            raise ValueError("A sweep must request at least one run.")
        sweep_id = uuid.uuid4().hex
        with self.connection() as connection:
            connection.execute("INSERT INTO sweeps(id,entrypoint,requested,started_at,status,owner,log_path) VALUES(?,?,?,?,?,?,?)",
                               (sweep_id, entrypoint, requested, now(), "running", owner, log_path))
        return sweep_id

    def start_run(self, sweep_id: str, configuration: dict, repeat: int, log_path: str = "") -> str:
        config_id = fingerprint(configuration)
        run_id = uuid.uuid4().hex
        runtime = str(configuration.get("runtime_isolation") or "unrecorded")
        with self.connection() as connection:
            sweep = connection.execute("SELECT status FROM sweeps WHERE id=?", (sweep_id,)).fetchone()
            if sweep is None or sweep["status"] != "running":
                raise ValueError("Cannot add a run to a missing or finished sweep.")
            connection.execute(
                "INSERT OR IGNORE INTO configurations(id,case_id,model,mode,harness,budget,"
                "audit_status,skills_enabled,details,created_at,runtime_isolation) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                    config_id, configuration["case_id"], configuration["model"], configuration["mode"],
                    configuration["harness"], configuration["max_iterations"], configuration["audit"]["status"],
                    int(configuration["skills_enabled"]), canonical(configuration), now(), runtime))
            connection.execute(
                "INSERT INTO runs(id,sweep_id,configuration_id,repeat,mode,started_at,status,log_path,"
                "runtime_isolation) VALUES(?,?,?,?,?,?,?,?,?)",
                (run_id, sweep_id, config_id, repeat, configuration["mode"], now(), "running", log_path, runtime))
        return run_id

    def finish_run(self, run_id: str, status: str, metrics: dict | None = None, **metadata):
        if status not in FINAL_STATES:
            raise ValueError(f"Invalid final run status: {status}")
        scores = metrics or {}
        for name in METRICS:
            value = scores.get(name)
            if value is not None and (not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"Invalid metric {name}: {value}")
        fields = {name: scores.get(name) for name in METRICS}
        for name in ("duration_seconds", "verdict", "prompt_tokens", "completion_tokens", "iterations", "executions",
                     "error_count", "truncations", "labels_reported", "labels_expected", "trace_url", "error"):
            fields[name] = metadata.get(name)
        fields.update(status=status, finished_at=now(), context_changed=int(metadata.get("context_changed", False)),
                      details=canonical({"metrics": scores, **metadata}))
        with self.connection() as connection:
            changed = connection.execute("UPDATE runs SET " + ",".join(f"{name}=?" for name in fields) + " WHERE id=? AND status='running'",
                                         (*fields.values(), run_id)).rowcount
            if changed != 1:
                raise ValueError("Run missing or already finalized; refusing to overwrite results.")

    def finish_sweep(self, sweep_id: str, error: str = ""):
        with self.connection() as connection:
            if connection.execute("SELECT 1 FROM runs WHERE sweep_id=? AND status='running'", (sweep_id,)).fetchone():
                raise ValueError("Cannot finish a sweep with a running attempt.")
            sweep = connection.execute("SELECT requested FROM sweeps WHERE id=?", (sweep_id,)).fetchone()
            if sweep is None:
                raise ValueError("Unknown sweep")
            attempts = connection.execute("SELECT COUNT(*) FROM runs WHERE sweep_id=?", (sweep_id,)).fetchone()[0]
            status = "error" if error else "finished" if attempts == sweep["requested"] else "interrupted"
            connection.execute("UPDATE sweeps SET status=?,finished_at=?,error=? WHERE id=? AND status='running'",
                               (status, now(), error, sweep_id))

    def attach_log(self, run_id: str, path: Path):
        with self.connection() as connection:
            connection.execute("UPDATE runs SET log_path=? WHERE id=?", (str(path.resolve()), run_id))

    def interrupt_sweep(self, sweep_id: str):
        """Explicit recovery only; never assume another GUI's active sweep is stale."""
        with self.connection() as connection:
            connection.execute("UPDATE runs SET status='interrupted',finished_at=?,error=? WHERE sweep_id=? AND status='running'",
                               (now(), "Marked interrupted by user during recovery.", sweep_id))
            connection.execute("UPDATE sweeps SET status='interrupted',finished_at=? WHERE id=? AND status='running'", (now(), sweep_id))

    def list_runs(self, search: str = "", comparison_only: bool = False) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute("""
                SELECT runs.*, configurations.case_id, configurations.model, configurations.harness,
                       configurations.budget, configurations.audit_status, configurations.skills_enabled,
                       configurations.details AS configuration, sweeps.entrypoint
                FROM runs JOIN configurations ON configurations.id=runs.configuration_id
                JOIN sweeps ON sweeps.id=runs.sweep_id ORDER BY runs.started_at DESC, runs.id
            """).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            details = json.loads(item["details"] or "{}")
            item["usage_complete"] = details.get("usage_complete")
            executions, errors = item["executions"], item["error_count"]
            item["code_error_rate"] = (errors / executions if executions is not None and executions > 0
                                       and errors is not None and 0 <= errors <= executions else None)
            item["comparable"] = (item["audit_status"] in ("control-only", "relations-checked", "expert-subset-checked")
                                  and item["harness"] < 3 and not item["skills_enabled"] and not item["context_changed"])
            if comparison_only and not item["comparable"]:
                continue
            if search and search.casefold() not in " ".join(str(item[key]) for key in (
                    "case_id", "model", "mode", "status", "audit_status", "runtime_isolation",
                    "configuration_id", "sweep_id")).casefold():
                continue
            result.append(item)
        return result

    def summaries(self, search: str = "", comparison_only: bool = False) -> list[dict]:
        groups = {}
        for run in self.list_runs(search, comparison_only):
            groups.setdefault(run["configuration_id"], []).append(run)
        result = []
        for config_id, runs in groups.items():
            first = runs[0]
            finished = [run for run in runs if run["status"] != "running"]
            complete = [run for run in finished if run["status"] == "complete"]
            row = {key: first[key] for key in ("case_id", "model", "mode", "harness", "budget", "audit_status", "skills_enabled", "runtime_isolation", "configuration")}
            row.update(configuration_id=config_id, attempts=len(runs), finished=len(finished), complete=len(complete),
                       running=len(runs) - len(finished), completion_rate=len(complete) / len(finished) if finished else None,
                       errors=sum(run["status"] in ("error", "interrupted") for run in runs),
                       context_changed=sum(run["context_changed"] for run in runs))
            row["aborted_rate"] = row["errors"] / len(finished) if finished else None
            measured = [run for run in finished if run["executions"] is not None and run["error_count"] is not None
                        and 0 <= run["error_count"] <= run["executions"]]
            row["code_error_runs_n"] = len(measured)
            row["code_errors"] = sum(run["error_count"] for run in measured) if measured else None
            row["code_executions"] = sum(run["executions"] for run in measured) if measured else None
            row["code_error_rate"] = row["code_errors"] / row["code_executions"] if row["code_executions"] else None
            row["partial_usage_runs"] = sum(run.get("usage_complete") is False for run in finished)
            row["known_input_tokens"] = sum(run["prompt_tokens"] or 0 for run in finished)
            row["known_output_tokens"] = sum(run["completion_tokens"] or 0 for run in finished)
            for name in (*METRICS, "duration_seconds", "prompt_tokens", "completion_tokens"):
                stats = describe([run[name] for run in finished if run[name] is not None
                                  and (name not in ("prompt_tokens", "completion_tokens") or run.get("usage_complete") is not False)])
                row.update({f"{name}_{key}": value for key, value in stats.items()})
            row["complete_union_mean"] = describe([run["union_accuracy"] for run in complete if run["union_accuracy"] is not None])["mean"]
            row["ci_note"] = "95% normal approximation; descriptive only. Independent repeats assumed; small samples and provider defaults limit interpretation."
            result.append(row)
        return result

    def list_sweeps(self) -> list[dict]:
        with self.connection() as connection:
            return [dict(row) for row in connection.execute("""
                SELECT sweeps.*, COUNT(runs.id) AS attempts FROM sweeps
                LEFT JOIN runs ON sweeps.id=runs.sweep_id GROUP BY sweeps.id ORDER BY sweeps.started_at DESC
            """)]

    def backup(self, destination: Path):
        destination = Path(destination)
        if destination.resolve() == self.path.resolve():
            raise ValueError("Backup destination must differ from the live database.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()


def export_csv(path: Path, rows: list[dict], columns: list[str]):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        for row in rows:
            cells = []
            for name in columns:
                value = row.get(name)
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    value = "'" + value
                cells.append("" if value is None else value)
            writer.writerow(cells)