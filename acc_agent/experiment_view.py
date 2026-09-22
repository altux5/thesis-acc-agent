"""Sortable spreadsheet-style desktop view over the local experiment ledger."""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from experiments import ExperimentStore, default_path, export_csv
from gui_widgets import BACKGROUND, BORDER, HOVER, MUTED, ORANGE, PANEL, PRIMARY, SURFACE, TEXT, bind_wrapping, dark_text

RUN_COLUMNS = [
    ("started_at", "Started UTC", 178), ("case_id", "Case", 220), ("model", "Model", 150),
    ("mode", "Mode", 95), ("harness", "Harness", 65), ("budget", "Budget", 65), ("status", "Completion", 165),
    ("f1", "F1", 65), ("precision", "Precision", 80), ("recall", "Recall", 70),
    ("union_accuracy", "Union acc.", 85), ("label_coverage", "Coverage", 85),
    ("labels_reported", "Labels", 65), ("duration_seconds", "Seconds", 85),
    ("prompt_tokens", "Input tokens*", 105), ("completion_tokens", "Output tokens", 105),
    ("usage_complete", "Usage complete", 110),
    ("iterations", "Iterations", 75), ("executions", "Code blocks", 85), ("error_count", "Code errors", 85),
    ("code_error_rate", "Code error rate", 115), ("truncations", "Truncations", 90),
    ("audit_status", "Reference audit", 180), ("skills_enabled", "Skills", 65),
    ("runtime_isolation", "Execution runtime", 130),
    ("context_changed", "Context changed", 115), ("configuration_id", "Configuration", 160), ("id", "Run ID", 170),
]
CONFIG_COLUMNS = [
    ("case_id", "Case", 220), ("model", "Model", 150), ("mode", "Mode", 95), ("harness", "Harness", 65),
    ("budget", "Budget", 65), ("attempts", "Attempts", 75), ("complete", "Complete", 80),
    ("completion_rate", "Completion rate", 115), ("running", "Running", 70), ("errors", "Error/interrupted", 125),
    ("aborted_rate", "Aborted run rate", 120), ("code_errors", "Code errors", 85),
    ("code_executions", "Code blocks", 85), ("code_error_rate", "Code error rate", 115),
    ("f1_mean", "Mean F1", 80), ("f1_std", "F1 SD", 75), ("f1_n", "F1 N", 65),
    ("precision_mean", "Mean precision", 110), ("recall_mean", "Mean recall", 100),
    ("union_accuracy_mean", "Mean union", 95), ("union_accuracy_std", "Union SD", 85), ("union_accuracy_n", "Union N", 75),
    ("label_coverage_mean", "Mean coverage", 110), ("duration_seconds_mean", "Mean seconds", 110),
    ("prompt_tokens_mean", "Mean input*", 105), ("completion_tokens_mean", "Mean output", 105),
    ("partial_usage_runs", "Partial usage", 105), ("known_input_tokens", "Known input total", 125),
    ("known_output_tokens", "Known output total", 130),
    ("audit_status", "Reference audit", 180), ("skills_enabled", "Skills", 65),
    ("runtime_isolation", "Execution runtime", 130), ("configuration_id", "Configuration", 160),
]
SWEEP_COLUMNS = [
    ("started_at", "Started UTC", 190), ("entrypoint", "Entry point", 100), ("status", "Sweep status", 120),
    ("requested", "Requested", 90), ("attempts", "Attempted", 90), ("owner", "Process", 100),
    ("finished_at", "Finished UTC", 190), ("id", "Sweep ID", 230), ("error", "Error", 300),
]


def sorted_rows(rows: list[dict], column: str, descending: bool = False) -> list[dict]:
    present = [row for row in rows if row.get(column) is not None]
    absent = [row for row in rows if row.get(column) is None]
    return sorted(present, key=lambda row: row[column] if isinstance(row[column], (int, float)) else str(row[column]).casefold(),
                  reverse=descending) + absent


def cell(value, column: str = "") -> str:
    if value is None:
        return "n/a"
    if column in ("completion_rate", "aborted_rate", "code_error_rate"):
        return f"{value:.1%}"
    if isinstance(value, float):
        return f"{value:,.3f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


class ExperimentsView(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=BACKGROUND, corner_radius=0)
        self.store = None
        self.rows = []
        self.columns = CONFIG_COLUMNS
        self.order_column = "case_id"
        self.descending = False
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1, minsize=120)
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        self.mode = ctk.StringVar(value="Configurations")
        ctk.CTkSegmentedButton(controls, values=["Configurations", "Runs", "Sweeps"], variable=self.mode,
            command=lambda choice: self.refresh(), selected_color=PRIMARY, unselected_color=SURFACE,
            selected_hover_color=HOVER, unselected_hover_color=HOVER, text_color=TEXT, corner_radius=4,
        ).pack(side="left")
        self.comparable = ctk.BooleanVar(value=False)
        self.comparison_filter = ctk.CTkCheckBox(controls, text="Audited / skills off / H1-2", variable=self.comparable,
            command=self.refresh, font=("Segoe UI", 11), text_color=MUTED, checkbox_width=16, checkbox_height=16,
            fg_color=PRIMARY, border_color=BORDER, border_width=1,
        )
        self.comparison_filter.pack(side="left", padx=12)

        tools = ctk.CTkFrame(self, fg_color="transparent")
        tools.grid(row=1, column=0, sticky="ew", padx=10)
        tools.grid_columnconfigure(0, weight=1)
        self.search = ctk.StringVar(value="")
        self.search_entry = ctk.CTkEntry(tools, textvariable=self.search, placeholder_text="Case, model, mode or ID",
            fg_color=PANEL, border_color=BORDER, text_color=TEXT, corner_radius=4)
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search_entry.bind("<Return>", lambda event: self.refresh())
        for column, (label, command) in enumerate((("Refresh", self.refresh), ("Export CSV", self.export),
                                                  ("Backup", self.backup)), 1):
            ctk.CTkButton(tools, text=label, command=command, width=88, height=28, fg_color=SURFACE,
                hover_color=HOVER, text_color=TEXT, corner_radius=4).grid(row=0, column=column, padx=3)
        self.status = ctk.CTkLabel(self, text="No experiment records loaded.", anchor="w", justify="left", width=1,
                                 text_color=MUTED, font=("Segoe UI", 11))
        self.status.grid(row=2, column=0, sticky="ew", padx=10, pady=6)
        bind_wrapping(self.status)
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=3, column=0, sticky="nsew", padx=10)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        self.table = ttk.Treeview(frame, show="headings", style="Scores.Treeview", selectmode="extended", height=5)
        self.table.grid(row=0, column=0, sticky="nsew")
        self.table.tag_configure("even", background=PANEL)
        self.table.tag_configure("odd", background=SURFACE)
        vertical = ctk.CTkScrollbar(frame, command=self.table.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ctk.CTkScrollbar(frame, orientation="horizontal", command=self.table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.bind("<<TreeviewSelect>>", self.select)
        self.table.bind("<Control-c>", lambda event: self.copy())
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=4, column=0, sticky="ew", padx=10, pady=6)
        self.open_button = ctk.CTkButton(bottom, text="Open log", width=90, height=26, command=self.open_log,
            fg_color=SURFACE, hover_color=HOVER, text_color=TEXT, corner_radius=4, state="disabled")
        self.open_button.pack(side="left", padx=(0, 6))
        ctk.CTkButton(bottom, text="Copy rows", width=90, height=26, command=self.copy,
            fg_color=SURFACE, hover_color=HOVER, text_color=TEXT, corner_radius=4).pack(side="left")
        self.recover_button = ctk.CTkButton(bottom, text="Mark interrupted", width=125, height=26, command=self.recover,
            fg_color=SURFACE, hover_color=HOVER, text_color=ORANGE, corner_radius=4, state="disabled")
        self.recover_button.pack(side="right")
        self.details = dark_text(self, height=4)
        self.details.grid(row=5, column=0, sticky="ew", padx=4)
        self.details.configure(state="disabled")

    def refresh(self):
        try:
            if self.store is None or self.store.path != default_path():
                self.store = ExperimentStore()
            mode = self.mode.get()
            self.comparison_filter.configure(state="disabled" if mode == "Sweeps" else "normal")
            self.columns = CONFIG_COLUMNS if mode == "Configurations" else RUN_COLUMNS if mode == "Runs" else SWEEP_COLUMNS
            if mode == "Sweeps":
                self.rows = [row for row in self.store.list_sweeps() if self.search.get().casefold() in str(row).casefold()]
            else:
                query = self.store.summaries if mode == "Configurations" else self.store.list_runs
                self.rows = query(self.search.get(), self.comparable.get())
            self.table.configure(columns=[name for name, _, _ in self.columns])
            for name, label, width in self.columns:
                self.table.heading(name, text=label, command=lambda selected=name: self.sort(selected))
                self.table.column(name, width=width, minwidth=45, stretch=False, anchor="w")
            self.order_column = self.order_column if self.order_column in {name for name, _, _ in self.columns} else self.columns[0][0]
            self._render()
            total = len(self.store.list_runs())
            eligible = len(self.store.list_runs(comparison_only=True))
            status = f"{total} attempts stored | {eligible} pass the comparison filter | {len(self.rows)} {mode.lower()} shown"
            filtered_empty = mode != "Sweeps" and self.comparable.get() and not self.rows and total > 0
            if filtered_empty:
                status += " | No matches with comparison filter enabled"
            self.status.configure(text=f"{status} | {self.store.path}", text_color=ORANGE if filtered_empty else MUTED)
            self._details("Exact configurations are never merged across cases or changed inputs. Means use available scores with N shown; errors remain in completion-rate denominators. Partial usage is a known lower bound and is excluded from full-run token means, but included in known totals. New input totals include cache; historical values are unchanged. Sweep recovery is manual; do not interrupt an active run.")
        except Exception as exc:
            self.status.configure(text=f"Database unavailable: {type(exc).__name__}: {exc}", text_color=ORANGE)

    def _render(self):
        self.rows = sorted_rows(self.rows, self.order_column, self.descending)
        self.table.delete(*self.table.get_children())
        for index, row in enumerate(self.rows):
            self.table.insert("", "end", iid=str(index), values=[cell(row.get(name), name) for name, _, _ in self.columns],
                              tags=("even" if index % 2 == 0 else "odd",))
        self.open_button.configure(state="disabled")
        self.recover_button.configure(state="disabled")

    def sort(self, column):
        self.descending = not self.descending if self.order_column == column else False
        self.order_column = column
        self._render()
        for name, label, _ in self.columns:
            self.table.heading(name, text=label + (" v" if self.descending else " ^") if name == column else label)

    def selected(self) -> list[dict]:
        return [self.rows[int(key)] for key in self.table.selection()]

    def _details(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def select(self, event=None):
        selection = self.selected()
        if not selection:
            return
        row = selection[0]
        path = row.get("log_path")
        self.open_button.configure(state="normal" if path and Path(path).exists() else "disabled")
        self.recover_button.configure(state="normal" if self.mode.get() == "Sweeps" and row.get("status") == "running" else "disabled")
        config = json.loads(row.get("configuration", "{}"))
        details = {key: value for key, value in row.items() if key not in ("configuration", "details")}
        details["conditions"] = {key: config.get(key) for key in ("reference_version", "ifc_hash", "reference_hash",
            "system_prompt_hash", "skill_hash", "sampling", "reasoning", "env_primer", "audit", "runtime", "core_files") if key in config}
        if row.get("details"):
            run_details = json.loads(row["details"])
            details["run_findings"] = {key: run_details.get(key) for key in ("completion_issues", "skill_saves", "reason", "context_changed", "integrity_error")}
        self._details(json.dumps(details, indent=2, ensure_ascii=True))

    def export(self):
        path = filedialog.asksaveasfilename(title="Export displayed experiment table", defaultextension=".csv", filetypes=[("Excel-compatible CSV", "*.csv")])
        if path:
            try:
                export_csv(Path(path), self.rows, [name for name, _, _ in self.columns])
                self.status.configure(text=f"Exported {len(self.rows)} displayed rows to {path}")
            except OSError as exc:
                self.status.configure(text=f"Export failed: {exc}", text_color=ORANGE)

    def backup(self):
        if self.store is None:
            return
        path = filedialog.asksaveasfilename(title="Back up experiment database", defaultextension=".sqlite3", filetypes=[("SQLite database", "*.sqlite3")])
        if path:
            try:
                self.store.backup(Path(path))
                self.status.configure(text=f"Database backup saved to {path}")
            except Exception as exc:
                self.status.configure(text=f"Backup failed: {exc}", text_color=ORANGE)

    def copy(self):
        rows = self.selected()
        if not rows:
            return
        output = io.StringIO()
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow([label for _, label, _ in self.columns])
        for row in rows:
            values = []
            for name, _, _ in self.columns:
                value = row.get(name)
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    value = "'" + value
                values.append("" if value is None else value)
            writer.writerow(values)
        self.clipboard_clear()
        self.clipboard_append(output.getvalue())

    def open_log(self):
        rows = self.selected()
        if rows and rows[0].get("log_path"):
            try:
                os.startfile(rows[0]["log_path"])
            except OSError as exc:
                self.status.configure(text=f"Could not open log: {exc}", text_color=ORANGE)

    def recover(self):
        rows = self.selected()
        if self.mode.get() != "Sweeps" or not rows or rows[0].get("status") != "running":
            return
        if messagebox.askyesno("Recover interrupted sweep", "Only continue if this sweep is no longer running in any window or terminal. Mark its unfinished attempts as interrupted?"):
            self.store.interrupt_sweep(rows[0]["id"])
            self.refresh()