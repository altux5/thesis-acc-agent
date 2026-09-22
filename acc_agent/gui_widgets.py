"""Presentation-only widgets for the desktop compliance checker."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import customtkinter as ctk
from scoring import parse_verdict

BACKGROUND = "#111614"
PANEL = "#1a211e"
SURFACE = "#232d28"
BORDER = "#39483f"
TEXT = "#e7eee9"
MUTED = "#a9b8af"
ACCENT = "#72d5b1"
PRIMARY = "#24755b"
HOVER = "#315544"
BLUE = "#8abfff"
GREEN = "#85dfac"
ORANGE = "#f0bf74"
RED = "#ff9999"

METRIC_GUIDE = (
    "Recall: Of the reference violations, how many did the agent find? Low recall means missed violations.\n\n"
    "Precision: Of the violations the agent reported, how many match the reference? Low precision means false alarms.\n\n"
    "F1: Balances precision and recall, from 0 to 1. It does not show whether every element was labelled.\n\n"
    "Union accuracy: Matching element labels divided by all IDs labelled by either side. Missing, extra or wrong labels reduce it.\n\n"
    "Coverage: Share of reference elements with a submitted label. Full coverage does not prove correct measurements.\n\n"
    "TP / FP / FN: Matching violations / false alarms / missed reference violations.\n\n"
    "Exact match: The violation sets match. Verdict match: The overall verdict matches. Neither alone proves full coverage.\n\n"
    "Parsed: The final verdict was readable. Completion separately checks reporting consistency and known IFC scope.\n\n"
    "Mean +/- standard deviation: Average and variation across repeats. Unavailable union accuracy is excluded, not treated as zero.\n\n"
    "No reference violations: Recall and F1 cannot demonstrate violation detection. With no reported violations, precision is conventionally 100%.\n\n"
    "All scores measure agreement with the reference, which may itself be incomplete or wrong."
)

COMPLETION_LABELS = {
    "complete": "Complete",
    "incomplete": "Incomplete",
    "abstained": "Abstained",
    "reported_unverified_scope": "Scope unverified",
    "not recorded": "Not recorded",
}


def percent(value) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def dark_text(parent, **kwargs) -> tk.Text:
    return tk.Text(
        parent, bg=BACKGROUND, fg=TEXT, insertbackground=TEXT,
        selectbackground=HOVER, selectforeground=TEXT, relief="flat",
        borderwidth=0, highlightthickness=0, wrap="word", font=("Segoe UI", 11),
        padx=14, pady=12, spacing3=4, **kwargs,
    )


def bind_wrapping(label):
    def resize(event):
        width = max(120, int(event.width / label._get_widget_scaling()) - 12)
        if label.cget("wraplength") != width:
            label.configure(wraplength=width)

    tk.Misc.bind(label, "<Configure>", resize, add="+")


def result_presentation(payload: dict) -> dict:
    parsed = parse_verdict(str(payload.get("verdict", "")))
    completion = payload.get("completion_status", "not recorded")
    color = MUTED
    if completion == "incomplete":
        title, color = "Check incomplete", RED
    elif completion == "reported_unverified_scope":
        title, color = "Scope not verified", ORANGE
    elif parsed.verdict == "UNKNOWN" or completion == "abstained":
        title, color = "Unable to conclude", ORANGE
    elif parsed.verdict == "NON_COMPLIANT":
        title, color = "Violations reported", RED
    elif parsed.verdict == "COMPLIANT":
        title, color = "No violations reported", GREEN if completion == "complete" else ORANGE
    else:
        title = "No accepted verdict"
    reason = payload.get("reason") or " ".join(payload.get("completion_issues", []))
    detail = str(reason) or (
        "Complete label submission; measurement correctness is not independently verified."
        if completion == "complete" else "Completion status was not recorded."
    )
    return {"title": title, "color": color, "detail": detail,
            "completion": COMPLETION_LABELS.get(completion, "Not recorded"),
            "violations": str(len(parsed.violations)) if parsed.parse_ok else "-"}


class ResultView(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=PANEL, corner_radius=0)
        self.raw_verdict = ""
        self.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(8, 0))
        top.grid_columnconfigure(0, weight=1)
        self.run_label = ctk.CTkLabel(top, text="LATEST RESULT", height=18, font=("Segoe UI", 11, "bold"), text_color=MUTED, anchor="w")
        self.run_label.grid(row=0, column=0, sticky="ew")
        self.raw_button = ctk.CTkButton(top, text="Raw verdict", width=94, height=26, corner_radius=4,
                                      fg_color=SURFACE, hover_color=HOVER, text_color=TEXT,
                                      state="disabled", command=self.show_raw)
        self.raw_button.grid(row=0, column=1)
        self.title_label = ctk.CTkLabel(self, text="Ready to run", height=32, font=("Segoe UI", 22, "bold"), text_color=TEXT, anchor="w", width=1)
        self.title_label.grid(row=1, column=0, sticky="ew", padx=16)
        self.status_label = ctk.CTkLabel(self, text="No result yet", height=18, text_color=MUTED, font=("Segoe UI", 11), anchor="w", width=1)
        self.status_label.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 6))
        figures = ctk.CTkFrame(self, fg_color="transparent")
        figures.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 8))
        self.figures = {}
        for column, (key, label) in enumerate((("violations", "VIOLATIONS"), ("labels", "LABELS SUBMITTED"), ("iterations", "ITERATIONS"), ("input", "INPUT TOKENS"), ("output", "OUTPUT TOKENS"))):
            figures.grid_columnconfigure(column, weight=1, uniform="metrics")
            ctk.CTkLabel(figures, text=label, height=16, font=("Segoe UI", 10), text_color=MUTED, anchor="w", width=1).grid(row=0, column=column, sticky="ew", padx=(0, 6))
            value = ctk.CTkLabel(figures, text="-", height=24, font=("Consolas", 17), text_color=TEXT, anchor="w", width=1)
            value.grid(row=1, column=column, sticky="ew", padx=(0, 6))
            self.figures[key] = value
        self.detail = ""

    def reset(self, run_label="LATEST RESULT", running=False):
        self.raw_verdict = ""
        self.raw_button.configure(state="disabled")
        self.run_label.configure(text="LATEST RESULT | " + run_label if run_label != "LATEST RESULT" else run_label)
        self.title_label.configure(text="Checking model" if running else "Ready to run", text_color=ACCENT if running else TEXT)
        self.status_label.configure(text="In progress" if running else "No result yet", text_color=MUTED)
        for widget in self.figures.values():
            widget.configure(text="-")

    def show_result(self, payload):
        display = result_presentation(payload)
        self.raw_verdict = str(payload.get("verdict", ""))
        self.detail = display["detail"]
        self.title_label.configure(text=display["title"], text_color=display["color"])
        self.status_label.configure(text="Submission: " + display["completion"], text_color=MUTED)
        if payload.get("usage_complete") is False:
            self.status_label.configure(text="Submission: " + display["completion"] + " | Usage partial", text_color=ORANGE)
        self.raw_button.configure(state="normal")
        values = {"violations": display["violations"], "labels": payload.get("labels", "-"),
                  "iterations": payload.get("iterations", "-"), "input": payload.get("prompt_tokens", 0),
                  "output": payload.get("completion_tokens", 0)}
        for name, value in values.items():
            self.figures[name].configure(text=f"{value:,}" if isinstance(value, int) else str(value))

    def show_raw(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Recorded verdict")
        dialog.geometry("620x380")
        dialog.minsize(380, 260)
        dialog.configure(fg_color=BACKGROUND)
        dialog.transient(self.winfo_toplevel())
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(0, weight=1)
        text = dark_text(dialog)
        text.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        scroll = ctk.CTkScrollbar(dialog, command=text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scroll.set)
        text.insert("1.0", self.detail + "\n\n" + self.raw_verdict)
        text.configure(state="disabled")
        dialog.bind("<Escape>", lambda event: dialog.destroy())


class ScoreView(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=BACKGROUND, corner_radius=0)
        self.entries: dict[str, dict] = {}
        self.summaries: dict[str, str] = {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=3, minsize=140)
        self.grid_rowconfigure(4, weight=1)
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        toolbar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(toolbar, text="Reference agreement", font=("Segoe UI", 17, "bold"), text_color=TEXT).grid(row=0, column=0, sticky="w")
        self.guide_button = ctk.CTkButton(
            toolbar, text="Metric guide", width=112, height=30, corner_radius=4,
            fg_color=SURFACE, hover_color=HOVER, text_color=TEXT, command=self.show_guide,
        )
        self.guide_button.grid(row=0, column=1, sticky="e")
        self.context = ctk.CTkLabel(self, text="No scored runs yet.", text_color=MUTED, anchor="w", justify="left", width=1)
        self.context.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        bind_wrapping(self.context)

        table_frame = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        table_frame.grid(row=2, column=0, sticky="nsew", padx=12)
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Scores.Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=TEXT, rowheight=32, borderwidth=0, font=("Segoe UI", 10))
        style.configure("Scores.Treeview.Heading", background=SURFACE, foreground=MUTED,
                        borderwidth=0, font=("Segoe UI", 10, "bold"))
        style.map("Scores.Treeview", background=[("selected", HOVER)], foreground=[("selected", TEXT)])
        style.map("Scores.Treeview.Heading", background=[("active", HOVER)])
        columns = ("case", "run", "completion", "recall", "precision", "f1", "union", "coverage")
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", style="Scores.Treeview", height=5, selectmode="browse")
        for name, heading, width in zip(columns, ("Case", "Run", "Completion", "Recall", "Precision", "F1", "Union acc.", "Coverage"), (210, 112, 130, 68, 76, 55, 86, 86)):
            self.table.heading(name, text=heading)
            self.table.column(name, width=width, minwidth=width, anchor="w" if name in ("case", "run", "completion") else "center", stretch=True)
        self.table.grid(row=0, column=0, sticky="nsew")
        scroll = ctk.CTkScrollbar(table_frame, command=self.table.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal = ctk.CTkScrollbar(table_frame, orientation="horizontal", command=self.table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.table.bind("<<TreeviewSelect>>", self._select)
        self.aggregate_label = ctk.CTkLabel(self, text="", text_color=MUTED, anchor="w", justify="left", font=("Segoe UI", 11), width=1)
        self.aggregate_label.grid(row=3, column=0, sticky="ew", padx=12, pady=8)
        bind_wrapping(self.aggregate_label)
        details_frame = ctk.CTkFrame(self, fg_color="transparent")
        details_frame.grid(row=4, column=0, sticky="nsew", padx=0, pady=(0, 8))
        details_frame.grid_columnconfigure(0, weight=1)
        details_frame.grid_rowconfigure(0, weight=1)
        self.details = dark_text(details_frame, height=4)
        self.details.grid(row=0, column=0, sticky="nsew")
        details_scroll = ctk.CTkScrollbar(details_frame, command=self.details.yview)
        details_scroll.grid(row=0, column=1, sticky="ns")
        self.details.configure(yscrollcommand=details_scroll.set)
        self.reset()

    def reset(self, context="No scored runs yet."):
        self.entries.clear()
        self.summaries.clear()
        self.table.delete(*self.table.get_children())
        self.context.configure(text=context)
        self.aggregate_label.configure(text="")
        self._set_details("Recall = violations found. Precision = reported violations that match.\nUnion accuracy = agreement across element labels. Coverage = reference elements labelled.")

    def _set_details(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def add_score(self, payload):
        metrics = payload["scores"]
        key = f"{payload['case_id']}:{payload['mode']}:{payload['rep']}"
        self.entries[key] = payload
        status = COMPLETION_LABELS.get(payload.get("completion_status", "not recorded"), "Not recorded")
        values = (payload["case_id"], f"{payload['mode']} {payload['rep']}", status, percent(metrics.recall),
                  percent(metrics.precision), f"{metrics.f1:.2f}", percent(metrics.union_accuracy), percent(metrics.label_coverage))
        if self.table.exists(key):
            self.table.item(key, values=values)
        else:
            self.table.insert("", "end", iid=key, values=values)
        caveat = " No reference violations: F1/recall do not test detection." if payload["gt_n"] == 0 else ""
        if payload.get("harness") == 3:
            caveat += " TRAIN: reference feedback was shown to the agent."
        self.context.configure(text=f"{payload['case_id']} | {payload['gt_n']} reference violations.{caveat}")
        self.table.selection_set(key)
        self.table.see(key)
        self._select()

    def _select(self, event=None):
        selected = self.table.selection()
        if not selected or selected[0] not in self.entries:
            return
        payload = self.entries[selected[0]]
        metrics = payload["scores"]
        status = COMPLETION_LABELS.get(payload.get("completion_status", "not recorded"), "Not recorded")
        lines = [f"{payload['case_id']} | {payload['mode']} - run {payload['rep']} | {status}",
                 f"Found {metrics.tp} of {payload['gt_n']} reference violations. False alarms: {metrics.fp}. Missed: {metrics.fn}.",
                 f"Labels submitted: {metrics.labels_reported}/{metrics.labels_expected}. Coverage: {percent(metrics.label_coverage)}.",
                 f"Exact violation-set match: {'yes' if metrics.exact_set_match else 'no'}. Verdict match: {'yes' if metrics.verdict_match else 'no'}. Parsed: {'yes' if metrics.parse_ok else 'no'}.",
                 f"Iterations: {payload['iterations']}. Tokens as logged: {payload['prompt_tokens']:,} input / {payload['completion_tokens']:,} output."]
        if metrics.union_accuracy is None:
            lines.append("Union accuracy unavailable; this run is excluded from its conditional mean, not counted as zero.")
        if metrics.abstained:
            lines.append("Agent abstained. An empty violation list is not proof of compliance.")
        if payload.get("usage_complete") is False:
            lines.append("Token counts are known usage only; some request usage is unavailable.")
        lines.extend(str(issue) for issue in payload.get("completion_issues", []))
        if metrics.confusion:
            lines.append("Label comparison (reference -> submitted): " + "; ".join(f"{label}: {count}" for label, count in metrics.confusion.items()))
        self._show_aggregates(payload["case_id"])
        self._set_details("\n\n".join(lines))

    def _show_aggregates(self, case_id):
        self.aggregate_label.configure(text="\n".join(
            text for (case, _), text in self.summaries.items() if case == case_id
        ))

    def add_aggregate(self, payload):
        metrics = payload["agg"].metrics
        count = payload["n"]
        f1 = metrics["f1"]
        case_id = payload.get("case_id", "")
        text = (f"{case_id} | " if case_id else "") + f"{payload['mode']} | {count} runs | F1 {f1['mean']:.2f} +/- {f1['std']:.2f}"
        if "union_accuracy" in metrics:
            union = metrics["union_accuracy"]
            text += f" | Union {percent(union['mean'])} across {int(union.get('n', 0))}/{count} runs"
        self.summaries[(case_id, payload["mode"])] = text
        selected = self.table.selection()
        active_case = self.entries[selected[0]]["case_id"] if selected else case_id
        self._show_aggregates(active_case)

    def show_guide(self):
        guide = ctk.CTkToplevel(self)
        guide.title("Score definitions")
        guide.geometry("600x620")
        guide.minsize(400, 350)
        guide.configure(fg_color=BACKGROUND)
        guide.transient(self.winfo_toplevel())
        guide.grid_columnconfigure(0, weight=1)
        guide.grid_rowconfigure(0, weight=1)
        content = dark_text(guide)
        content.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        scrollbar = ctk.CTkScrollbar(guide, command=content.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", pady=12)
        content.configure(yscrollcommand=scrollbar.set)
        content.insert("1.0", METRIC_GUIDE)
        content.configure(state="disabled")
        guide.bind("<Escape>", lambda event: guide.destroy())