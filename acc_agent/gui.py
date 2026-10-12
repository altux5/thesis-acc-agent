"""Desktop GUI to watch the compliance-checking agent run, step by step.

Pure Python (Tkinter + customtkinter) — no browser. Run with:
    python acc_agent/gui.py

Every run also writes a readable Markdown log to acc_agent/logs/ containing the
settings, the model's reasoning, the code it wrote, the execution output and the
final verdict — so the whole run can be reviewed (or shared) afterwards.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox

from code_identity import capture_module
capture_module()

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))  # so `import config/agent/executor` works

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_DIR / ".env")
except ImportError:
    pass

import customtkinter as ctk

import config
import factual_report
import ground_truth
import llm
import simple_rules
import tracing
from agent import AGENT_PROTOCOL, AgentResult, CodeActAgent
from completion import COMPLETION_CHECKS_VERSION
from executor import RUNTIME_ISOLATION, make_executor
from experiment_recorder import SweepRecorder
from experiment_view import ExperimentsView
from scoring import ParsedVerdict, aggregate, score
from gui_widgets import (
    ACCENT, BACKGROUND, BORDER, HOVER, MUTED, PANEL, PRIMARY, SURFACE, TEXT,
    BLUE, GREEN, ORANGE, RED, ResultView, ScoreView, bind_wrapping, dark_text, result_presentation,
)

WORKSPACE_ROOT = PROJECT_DIR.parent
LOG_DIR = PROJECT_DIR / "logs"
DEFAULT_IFC = ground_truth.resolve_model_path(
    "bca_tests-main/bca_tests-main/BCATestCases/"
    "Planter boxes/Test models/20240313_URA_Planterbox.ifc"
)
DEFAULT_RULE = (
    "Every door (IfcDoor) in the model must have a clear width of at least 900 mm. "
    "For this first check, use the door's OverallWidth attribute as the width. "
    "Report every door whose width is below 900 mm."
)

CUSTOM_CHOICE = "Custom (manual rule / IFC)"

# --- test-case grouping ---------------------------------------------------- #
# The catalogue has grown past 40 cases, so the picker groups them by Solihin &
# Eastman complexity class: class 1 (read a property) is where the agent should
# succeed, class 3 (construct auxiliary geometry) is where the advisors' EC3-2026
# paper shows it collapsing. Fully compliant cases are parked at the bottom - they
# test false-positive control only, so they are not the interesting runs.
GROUP_SIMPLE_1 = "Class 1 \u00b7 property checks (easiest)"
GROUP_SIMPLE_2 = "Class 2 \u00b7 relational checks"
GROUP_HARD_3 = "Class 3 \u00b7 geometric, expert ground truth (hardest)"
GROUP_CONTROL = "Compliant controls \u00b7 no violations to find"
GROUP_OTHER = "Other"
GROUP_PILOT = "\u2605 Pilot set \u00b7 one case per complexity class"
GROUP_ORDER = (
    GROUP_PILOT,
    GROUP_SIMPLE_1,
    GROUP_SIMPLE_2,
    GROUP_HARD_3,
    GROUP_CONTROL,
    GROUP_OTHER,
)

# --- the pilot set ---------------------------------------------------------- #
# One case per complexity class, chosen as the standing focus of the experiment.
# Selection criteria: (a) comparable to a rule the advisors' EC3-2026 paper reports
# numbers for, so our results can be read against theirs; (b) a violation rate that
# leaves headroom - not 0 %, not 100 %, and not a single-element set where F1
# collapses to a coin flip; (c) it exercises something the class is actually about.
PILOTS: dict[str, str] = {
    "slab_thickness__mall": (
        "Repaired, evidence-backed reference: 100 PASS, 12 ALERT, zero FAIL. "
        "Coverage, missing-data and false-positive control only; this case cannot "
        "measure violation recall. The original invalid reference is retained as legacy."
    ),
    "doors_windows_storey__condo": (
        "The paper's own 'doors and windows' rule (train F1_agg 1.00 -> test 0.25, "
        "cited there as the overfitting illustration). Our 4 violations in 212 "
        "openings sit close to its 2. Pure relation traversal, no geometry, so it "
        "isolates class-2 reasoning."
    ),
    "staircase_width_v8": (
        "The thesis anchor case: all 59 stairs of the v8 model, 23 FAIL / 26 PASS / "
        "6 NA / 4 MANUAL_CHECK. Expert labels cross-checked against IFC geometry and "
        "spaces. No EC3 counterpart - the paper's class-3 rules use models we do not "
        "hold - so treat it as our own class-3 reference rather than a comparison."
    ),
}

# Recommended repeats per mode per group. Harder rules need more repeats, because
# their run-to-run variance is what the stateful-vs-stateless comparison measures.
RECOMMENDED: dict[str, int] = {
    GROUP_SIMPLE_1: 3,
    GROUP_SIMPLE_2: 3,
    GROUP_HARD_3: 5,
    GROUP_CONTROL: 3,
    GROUP_OTHER: 3,
}
# Pilots are the cases we will report on, so they get the larger repeat budget
# their class would otherwise only get at class 3.
PILOT_REPEATS = 5
HEADER_PREFIX = "\u2500\u2500 "  # marks a non-selectable group header in the dropdown

USABLE_CASES = (
    "door_width_planterbox",
    "doors_windows_storey__condo",
    "doors_windows_storey__mall",
    "riser_height_e341__mall",
    "riser_height_e341__stair_v8",
    "tread_width_e342__condo",
)
HEALTH_SUITE_CASES = USABLE_CASES + ("slab_thickness__mall", "staircase_width_v8")
QUICK_SUITE_CASES = USABLE_CASES + ("slab_thickness__mall",)
# One cap for every run so cases and modes are compared under the same budget.
MAX_MODEL_CALLS = config.MAX_ITERATIONS
# Held out for good after the 2026-09-29 review; files are kept for historical runs.
RETIRED_CASES = {
    "slab_thickness__condo": "Retired: thickness sources conflict (Depth 100 vs mesh 50 mm on roofs); arbitrary BIM range.",
    "slab_thickness__planterbox": "Retired: only exported Depth recorded; roofs Depth 100 vs mesh 50 mm; arbitrary BIM range.",
    "slab_thickness__scdf_3": "Retired: no explicit thickness recorded; ALERTs overlook layer quantities; arbitrary BIM range.",
    "slab_thickness__scdf_5": "Retired: all five FAILs are plan-depth values; no explicit thickness recorded.",
    "slab_thickness__stair_obos": "Retired: all four FAILs read plan depth (1200 mm) on 201 mm landings.",
    "tread_width_e342__stair_v8": "Retired: all treads 250-260 mm, so the outcome depends only on the assumed building type.",
    "tread_width_e342__stair_obos": "Retired: owner-built house (E.2.4(d) exempts every staircase); IDs overlap v8.",
    "headroom_condo_c32": "Retired: door labels follow ClearHeight while 8 doors are 650-1980 mm high; room scope undefined.",
    "landing_interval_e352__stair_obos": "Retired: the building is recorded as owner-built (E.2.4(d)), so every staircase is exempt; a repaired case would be all NA.",
}
# Built by reference_v2.py (2026-09-29 review): repaired or new cases with recorded IFC evidence.
USABLE_2_CASES = {
    "landing_interval_e352__stair_v8": "E.3.5.2 per flight: 28 FAIL / 20 PASS / 19 NA (spiral, E.2.1/E.2.4). Counts corroborated by step geometry.",
    "landing_interval_e352__mall": "Control with a trap: 16 flights record the 27-riser staircase total; every flight has at most 12 risers.",
    "landing_interval_e352__scdf_5": "Control with a trap: 6 flights record the 21-riser staircase total; all 73 flights pass.",
    "tread_width_e342__mall": "Every tread measured (tapered treads at 500 mm from the narrow end): 36 FAIL / 40 PASS / 2 NA.",
    "exit_requirements__scdf_5": "Full SCDF clause and authority definitions; 39 template spaces scored (3 FAIL / 23 PASS / 13 NA), 84 unscored.",
    "exit_requirements__scdf_3": "Control: 12 template spaces scored (10 PASS / 2 NA), 47 unscored.",
    "planter_box_gfa": "URA GFA-exclusion criteria stated: 1 PASS / 7 FAIL. Only eight elements.",
    "headroom_door_c321__mall": "Doorway headroom by the authority's ClearHeight convention: 3 FAIL / 154 PASS; 33 lift doors unscored.",
    "space_elevation__mall": "EC3 same-storey elevation rule: 19 FAIL / 186 PASS / 4 NA. BIM consistency, not a regulation.",
    "space_elevation__scdf_3": "EC3 same-storey elevation rule: 1 FAIL / 53 PASS / 5 NA. BIM consistency, not a regulation.",
}
USABLE_2_SUITE_CASES = tuple(USABLE_2_CASES)
CONTROL_CASES = {
    "doors_windows_storey__planterbox", "doors_windows_storey__scdf_3", "doors_windows_storey__scdf_5",
    "landing_interval_e352__condo", "landing_interval_e352__planterbox", "landing_interval_e352__scdf_3",
    "landing_interval_e352__stair_industrial",
    "riser_height_e341__condo", "riser_height_e341__planterbox", "riser_height_e341__scdf_3",
    "riser_height_e341__scdf_5", "riser_height_e341__stair_industrial", "riser_height_e341__stair_obos",
    "slab_thickness__mall", "slab_thickness__stair_industrial", "slab_thickness__stair_v8",
    "tread_width_e342__planterbox", "tread_width_e342__scdf_3", "tread_width_e342__scdf_5",
    "tread_width_e342__stair_industrial",
}


def case_assessment(case_id: str) -> tuple[str, str]:
    """Human-reviewed selection guidance, not automatic reference certification."""
    if case_id in USABLE_CASES:
        return "Usable", "Supported for the stated recorded-IFC task; not general physical compliance certification."
    if case_id in USABLE_2_CASES:
        return "usable_2", USABLE_2_CASES[case_id]
    if case_id in RETIRED_CASES:
        return "Retired", RETIRED_CASES[case_id]
    if ground_truth.is_deprecated(case_id):
        return "Deprecated", "Superseded reference kept only for historical runs; not shown in the case picker."
    if case_id == "staircase_width_v8":
        return "Provisional", "Hard case: all 59 stairs. Expert labels cross-checked against IFC geometry and spaces; 2 adjudicated; width convention stated in the rule."
    if case_id in CONTROL_CASES:
        return "Control", "Negative, missing-data or abstention control only; no violation-recall evidence."
    return "Unreviewed", "Not covered by the 2026-09-17 reference review."


# --- harness levels --------------------------------------------------------- #
# The second axis of the experiment, orthogonal to stateful/stateless: the model
# and the executor are held fixed and only the structure around the loop changes,
# so a difference in score is attributable to the harness.
HARNESS_LABELS = {
    1: "1 \u00b7 bare",
    2: "2 \u00b7 plan",
}
HARNESS_HELP = {
    1: "Bare loop with completion checks.",
    2: "Plan first, then inspect and check.",
}

# --- test-case provenance --------------------------------------------------- #
# Each case is tagged with where its *rule* comes from, so the picker makes the
# mix explicit at a glance. The tag is derived from the case's clause + source
# fields, so newly generated cases tag themselves.
#   BCA  - BCA Approved Document (Acceptable Solutions V7.08)
#   SCDF - SCDF Fire Code 2023
#   URA  - URA Gross Floor Area guidelines
#   EC3  - rule catalogue of the advisors' EC3-2026 paper
#   DEMO - warm-up rule written for this project
WORKBOOK_AUTHORITY: dict[str, tuple[str, str]] = {
    "staircase_width.xlsx": ("BCA", "BCA Approved Document (Acceptable Solutions V7.08)"),
    "headroom.xlsx": ("BCA", "BCA Approved Document (Acceptable Solutions V7.08)"),
    "exit_requirements.xlsx": ("SCDF", "SCDF Fire Code 2023, chapter 2 (means of escape)"),
    "planter_box.xlsx": ("URA", "URA Gross Floor Area guidelines (planter boxes)"),
}

GREY = MUTED

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ACC Agent | Compliance workspace")
        scaling = self._get_window_scaling()
        width = max(960, min(1240, int(self.winfo_screenwidth() / scaling) - 64))
        height = max(640, min(820, int(self.winfo_screenheight() / scaling) - 100))
        self.geometry(f"{width}x{height}+20+20")
        self.minsize(960, 640)
        self.configure(fg_color=BACKGROUND)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.log_fh = None
        self.current_log_path: Path | None = None
        self.current_report_path: Path | None = None
        self.current_gt = None  # GroundTruth for the selected case, or None (custom)
        self.current_case: str | None = None
        self.case_labels: dict[str, dict] = {}
        self._last_case_choice = CUSTOM_CHOICE
        self._active_run = ""
        self._latest_completion = {}
        self._sweep_caption = ""
        self._case_details_visible = False
        self._suite: dict | None = None
        self._suite_path: Path | None = None
        self._suite_client = None
        self._suite_next = False
        self._stop_requested = threading.Event()

        self._build_sidebar()
        self._build_main()
        self._on_case(self.case_var.get())  # populate rule/IFC for the default case

    # ---- UI construction ---------------------------------------------------
    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, width=306, corner_radius=0, fg_color=PANEL)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_rowconfigure(1, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(sidebar, text="ACC / Agent", font=("Segoe UI", 22, "bold"), text_color=TEXT, anchor="w").grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 12))
        bar = ctk.CTkScrollableFrame(sidebar, width=280, corner_radius=0, fg_color=PANEL)
        bar.grid(row=1, column=0, sticky="nsew", padx=8)
        self.settings_body = bar

        def section(title):
            ctk.CTkFrame(bar, height=1, fg_color=BORDER).pack(fill="x", padx=10, pady=(10, 5))
            ctk.CTkLabel(bar, text=title, height=18, font=("Segoe UI", 11, "bold"), text_color=ACCENT).pack(anchor="w", padx=10, pady=(0, 6))

        def label(title):
            ctk.CTkLabel(bar, text=title, height=18, font=("Segoe UI", 12), text_color=MUTED).pack(anchor="w", padx=10, pady=(6, 3))

        section("01 / CASE")
        values, self.case_labels = self._case_catalog()
        first = next((v for v in values if not v.startswith(HEADER_PREFIX)), CUSTOM_CHOICE)
        first = next((name for name, metadata in self.case_labels.items() if metadata["case_id"] == USABLE_CASES[0]), first)
        self.case_filter = tk.StringVar(value="Health suite")
        self.case_group_menu = ctk.CTkOptionMenu(
            bar, values=["Health suite", "Usable", "usable_2", "Controls", "Provisional", "Retired", "Pilots", "All cases", "Class 1", "Class 2", "Class 3", "Custom"],
            variable=self.case_filter, command=self._filter_cases, height=30, corner_radius=4,
            fg_color=SURFACE, button_color=SURFACE, button_hover_color=HOVER,
            text_color=MUTED, dropdown_fg_color=SURFACE, dropdown_text_color=TEXT,
        )
        self.case_group_menu.pack(fill="x", padx=10, pady=(0, 6))
        self.case_var = tk.StringVar(value=first)
        self.case_menu = ctk.CTkOptionMenu(
            bar, values=[name for name, metadata in self.case_labels.items() if metadata["case_id"] in HEALTH_SUITE_CASES],
            variable=self.case_var, command=self._on_case, height=34, corner_radius=4,
            fg_color=SURFACE, button_color=PRIMARY, button_hover_color=HOVER,
            text_color=TEXT, dropdown_fg_color=SURFACE, dropdown_text_color=TEXT,
        )
        self.case_menu.pack(fill="x", padx=10, pady=(0, 6))
        self.case_summary = ctk.CTkLabel(bar, text="", font=("Segoe UI", 11), text_color=MUTED, anchor="w", justify="left", wraplength=250)
        self.case_summary.pack(fill="x", padx=10)
        self.case_details_btn = ctk.CTkButton(bar, text="Reference details", command=self._toggle_case_details,
            fg_color="transparent", hover_color=SURFACE, text_color=BLUE, height=26, anchor="w", corner_radius=4)
        self.case_details_btn.pack(fill="x", padx=10, pady=(2, 0))
        self.case_info = ctk.CTkLabel(
            bar, text="", font=ctk.CTkFont(size=11), text_color=GREY,
            anchor="w", justify="left", wraplength=250,
        )
        self.execution_heading = ctk.CTkFrame(bar, fg_color="transparent", height=1)
        self.execution_heading.pack(fill="x")
        section("02 / EXECUTION")
        label("Provider")
        self.provider_var = tk.StringVar(value=llm.resolve_provider())
        self.provider_control = ctk.CTkSegmentedButton(
            bar, values=list(llm.DEFAULT_MODELS), variable=self.provider_var, command=self._on_provider,
            selected_color=PRIMARY, selected_hover_color=HOVER, unselected_color=SURFACE,
            unselected_hover_color=HOVER, fg_color=SURFACE, text_color=TEXT, height=32, corner_radius=4,
        )
        self.provider_control.pack(fill="x", padx=10, pady=(0, 6))
        label("Model")
        self.model_var = tk.StringVar(value=llm.default_model())
        self.model_entry = ctk.CTkEntry(bar, textvariable=self.model_var, height=32, corner_radius=4,
                                      fg_color=BACKGROUND, border_color=BORDER, text_color=TEXT)
        self.model_entry.pack(fill="x", padx=10, pady=(0, 6))
        label("Session mode")
        self.mode_var = tk.StringVar(value="stateful")
        self.mode_control = ctk.CTkSegmentedButton(
            bar, values=["stateful", "stateless", "both"], variable=self.mode_var,
            selected_color=PRIMARY, selected_hover_color=HOVER, unselected_color=SURFACE,
            unselected_hover_color=HOVER, fg_color=SURFACE, text_color=TEXT, height=32, corner_radius=4,
        )
        self.mode_control.pack(fill="x", padx=10, pady=(0, 6))
        label("Harness")
        self.harness_var = tk.IntVar(value=1)
        self.harness_choice = tk.StringVar(value=HARNESS_LABELS[1])
        self.harness_control = ctk.CTkSegmentedButton(
            bar, values=list(HARNESS_LABELS.values()), variable=self.harness_choice,
            command=self._on_harness, height=32, corner_radius=4,
            selected_color=PRIMARY, selected_hover_color=HOVER, unselected_color=SURFACE,
            unselected_hover_color=HOVER, fg_color=SURFACE, text_color=TEXT,
        )
        self.harness_control.pack(fill="x", padx=10, pady=(0, 4))
        self.harness_info = ctk.CTkLabel(
            bar, text=HARNESS_HELP[1], font=ctk.CTkFont(size=11), text_color=GREY,
            anchor="w", justify="left", wraplength=250,
        )
        self.harness_info.pack(fill="x", padx=10, pady=(0, 8))
        self.repeats_label = ctk.CTkLabel(bar, text="Repeats per mode: 3", text_color=MUTED)
        self.repeats_label.pack(anchor="w", padx=10)
        self.repeats_var = tk.IntVar(value=3)
        self.repeats_slider = ctk.CTkSlider(
            bar, from_=1, to=10, number_of_steps=9,
            variable=self.repeats_var, command=self._on_repeats,
            progress_color=PRIMARY, button_color=ACCENT, button_hover_color=GREEN, fg_color=BORDER,
        )
        self.repeats_slider.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(
            bar, text=f"Max model calls: {MAX_MODEL_CALLS} (fixed cap; a run stops earlier once its report is accepted)",
            text_color=MUTED, anchor="w", justify="left", wraplength=250,
        ).pack(fill="x", padx=10, pady=(0, 4))
        self.reco_label = ctk.CTkLabel(
            bar, text="", font=ctk.CTkFont(size=11), text_color=GREY,
            anchor="w", justify="left", wraplength=250,
        )
        self.reco_label.pack(fill="x", padx=10, pady=(0, 4))
        section("03 / INPUT")
        label("IFC model")
        self.ifc_var = tk.StringVar(value=str(DEFAULT_IFC))
        self.ifc_entry = ctk.CTkEntry(bar, textvariable=self.ifc_var, height=32, corner_radius=4,
                                    fg_color=BACKGROUND, border_color=BORDER, text_color=TEXT)
        self.ifc_entry.pack(fill="x", padx=10, pady=(0, 4))
        self.browse_btn = ctk.CTkButton(
            bar, text="Browse IFC", height=26, fg_color="transparent", hover_color=SURFACE,
            border_width=1, border_color=BORDER, text_color=BLUE, command=self._browse, corner_radius=4,
        )
        self.browse_btn.pack(anchor="e", padx=10, pady=(0, 6))
        label("Rule")
        self.rule_box = ctk.CTkTextbox(bar, height=150, wrap="word", corner_radius=4,
                                     fg_color=BACKGROUND, border_width=1, border_color=BORDER, text_color=TEXT)
        self.rule_box.insert("1.0", DEFAULT_RULE)
        self.rule_box.pack(fill="x", padx=10, pady=(0, 16))
        footer = ctk.CTkFrame(sidebar, fg_color=PANEL, corner_radius=0)
        footer.grid(row=2, column=0, sticky="ew", padx=18, pady=(10, 16))
        self.run_btn = ctk.CTkButton(footer, text="Run checks", height=40, command=self._on_run,
            fg_color=PRIMARY, hover_color=HOVER, text_color=TEXT, corner_radius=4, font=("Segoe UI", 13, "bold"))
        self.run_btn.pack(fill="x")
        self.suite_btn = ctk.CTkButton(footer, text="Run 8-case health suite", height=34,
            command=self._on_suite, fg_color=SURFACE, hover_color=HOVER, text_color=TEXT, corner_radius=4)
        self.suite_btn.pack(fill="x", pady=(6, 0))
        self.quick_suite_btn = ctk.CTkButton(
            footer, text=f"Run {len(QUICK_SUITE_CASES)}-case suite (no staircase)", height=34,
            command=lambda: self._on_suite(QUICK_SUITE_CASES),
            fg_color=SURFACE, hover_color=HOVER, text_color=TEXT, corner_radius=4)
        self.quick_suite_btn.pack(fill="x", pady=(6, 0))
        self.usable_2_suite_btn = ctk.CTkButton(
            footer, text=f"Run {len(USABLE_2_SUITE_CASES)}-case usable_2 suite", height=34,
            command=lambda: self._on_suite(USABLE_2_SUITE_CASES),
            fg_color=SURFACE, hover_color=HOVER, text_color=TEXT, corner_radius=4)
        self.usable_2_suite_btn.pack(fill="x", pady=(6, 0))
        self.stop_btn = ctk.CTkButton(footer, text="Stop after current run", height=28,
            command=self._on_stop, state="disabled", fg_color=SURFACE, hover_color=HOVER,
            text_color=ORANGE, corner_radius=4)
        self.stop_btn.pack(fill="x", pady=(6, 0))
        self.suite_status = ctk.CTkLabel(footer, text="", font=("Segoe UI", 11), text_color=MUTED,
            anchor="w", justify="left", wraplength=260)
        self.suite_status.pack(fill="x", pady=(4, 0))

    def _build_main(self) -> None:
        main = ctk.CTkFrame(self, corner_radius=0, fg_color=BACKGROUND)
        main.grid(row=0, column=1, sticky="nsew", padx=14, pady=14)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        self.header = ctk.CTkLabel(
            main, text="Compliance workspace", text_color=TEXT, width=1,
            font=ctk.CTkFont(size=16, weight="bold"), anchor="w", justify="left",
        )
        self.header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        bind_wrapping(self.header)
        self.result_view = ResultView(main)
        self.result_view.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        self.verdict_label = self.result_view.title_label
        self.metrics_label = self.result_view.status_label

        self.views = ctk.CTkTabview(main, corner_radius=0, fg_color=BACKGROUND,
            segmented_button_fg_color=SURFACE, segmented_button_selected_color=PRIMARY,
            segmented_button_selected_hover_color=HOVER, segmented_button_unselected_color=SURFACE,
            segmented_button_unselected_hover_color=HOVER, text_color=TEXT, anchor="w")
        self.views.grid(row=2, column=0, sticky="nsew")
        self.views.add("Live Log")
        self.views.add("Scores")
        self.views.add("Factual Report")
        self.views.add("Experiments")
        scores_frame = self.views.tab("Scores")
        scores_frame.grid_rowconfigure(0, weight=1)
        scores_frame.grid_columnconfigure(0, weight=1)
        self.score_view = ScoreView(scores_frame)
        self.score_view.grid(row=0, column=0, sticky="nsew")
        experiments_frame = self.views.tab("Experiments")
        experiments_frame.grid_rowconfigure(0, weight=1)
        experiments_frame.grid_columnconfigure(0, weight=1)
        self.experiments_view = ExperimentsView(experiments_frame)
        self.experiments_view.grid(row=0, column=0, sticky="nsew")
        self.views.configure(command=self._on_view)
        console_frame = self.views.tab("Live Log")
        console_frame.grid_rowconfigure(1, weight=1)
        console_frame.grid_columnconfigure(0, weight=1)
        self.follow_output = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(console_frame, text="Follow output", variable=self.follow_output,
            font=("Segoe UI", 11), text_color=MUTED, fg_color=PRIMARY, hover_color=HOVER,
            checkbox_width=16, checkbox_height=16, border_width=1, border_color=BORDER,
        ).grid(row=0, column=0, sticky="e", padx=12, pady=(6, 8))

        self.console = dark_text(console_frame)
        self.console.grid(row=1, column=0, sticky="nsew")
        scroll = ctk.CTkScrollbar(console_frame, command=self.console.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.console.configure(yscrollcommand=scroll.set, state="disabled")
        self._configure_tags()

        report_frame = self.views.tab("Factual Report")
        report_frame.grid_columnconfigure(0, weight=1)
        report_frame.grid_rowconfigure(1, weight=1)
        report_tools = ctk.CTkFrame(report_frame, fg_color="transparent")
        report_tools.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.report_open_btn = ctk.CTkButton(
            report_tools, text="Open Detailed Report", state="disabled",
            command=self._open_report, fg_color=SURFACE, hover_color=HOVER, text_color=TEXT, corner_radius=4,
        )
        self.report_open_btn.pack(side="left", padx=(0, 8))
        self.report_load_btn = ctk.CTkButton(
            report_tools, text="Report From Saved Log", command=self._report_saved_log,
            fg_color=SURFACE, hover_color=HOVER, text_color=TEXT, corner_radius=4,
        )
        self.report_load_btn.pack(side="left")
        self.report_console = dark_text(report_frame)
        self.report_console.grid(row=1, column=0, sticky="nsew")
        report_scroll = ctk.CTkScrollbar(report_frame, command=self.report_console.yview)
        report_scroll.grid(row=1, column=1, sticky="ns")
        self.report_console.configure(yscrollcommand=report_scroll.set)
        self.report_console.tag_configure("warning", foreground=ORANGE)
        self.report_console.tag_configure("heading", foreground=BLUE, font=("Segoe UI", 12, "bold"))
        self.report_console.tag_configure("excerpt", foreground=GREY, font=("Segoe UI", 10, "italic"))
        self._set_report_text("No report yet.\n")

        self.artifact_label = ctk.CTkLabel(main, text="", text_color=MUTED, font=("Segoe UI", 10), anchor="w", width=1)
        self.artifact_label.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        bind_wrapping(self.artifact_label)

    def _configure_tags(self) -> None:
        c = self.console
        c.tag_configure("iter", foreground=BLUE, font=("Segoe UI Semibold", 13, "bold"), spacing1=14, spacing3=4)
        c.tag_configure("hdr", font=("Segoe UI Semibold", 11, "bold"), foreground=TEXT, spacing1=8)
        c.tag_configure("reason", foreground=GREY, font=("Segoe UI", 10, "italic"), lmargin1=14, lmargin2=14)
        c.tag_configure("code", font=("Consolas", 10), background=SURFACE, foreground=TEXT, lmargin1=14, lmargin2=14, spacing1=2, spacing3=2)
        c.tag_configure("out", font=("Consolas", 10), background=PANEL, foreground=MUTED, lmargin1=14, lmargin2=14)
        c.tag_configure("notice", foreground=ORANGE, font=("Segoe UI", 10, "italic"))
        c.tag_configure("ok", foreground=GREEN, font=("Segoe UI Semibold", 12, "bold"))
        c.tag_configure("bad", foreground=RED, font=("Segoe UI Semibold", 12, "bold"))
        c.tag_configure("run_sep", foreground=BLUE, font=("Segoe UI Semibold", 12, "bold"), spacing1=14, spacing3=6)
        c.tag_configure("score_hdr", foreground=TEXT, font=("Segoe UI Semibold", 12, "bold"), spacing1=8, spacing3=2)
        c.tag_configure("score_good", foreground=GREEN, font=("Consolas", 10))
        c.tag_configure("score_bad", foreground=RED, font=("Consolas", 10))
        c.tag_configure("score_neutral", foreground=MUTED, font=("Consolas", 10))

    def _toggle_case_details(self) -> None:
        self._case_details_visible = not self._case_details_visible
        if self._case_details_visible:
            self.case_info.pack(fill="x", padx=10, pady=8, before=self.execution_heading)
        else:
            self.case_info.pack_forget()
        self.case_details_btn.configure(text="Hide reference details" if self._case_details_visible else "Reference details")

    def _on_view(self) -> None:
        if self.views.get() == "Experiments":
            self.experiments_view.refresh()

    def _filter_cases(self, choice: str) -> None:
        groups = {"Class 1": GROUP_SIMPLE_1, "Class 2": GROUP_SIMPLE_2, "Class 3": GROUP_HARD_3}
        values = [name for name, metadata in self.case_labels.items()
                  if choice == "All cases" or (choice == "Pilots" and metadata["pilot"])
                  or (choice == "Health suite" and metadata["case_id"] in HEALTH_SUITE_CASES)
                  or metadata["assessment"] == ("Control" if choice == "Controls" else choice)
                  or (choice in groups and metadata["class_group"] == groups[choice])]
        if choice in ("Custom", "All cases"):
            values.append(CUSTOM_CHOICE)
        values = values or [CUSTOM_CHOICE]
        self.case_menu.configure(values=values)
        selected = self.case_var.get() if self.case_var.get() in values else values[0]
        self.case_var.set(selected)
        self._on_case(selected)

    def _set_settings_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (self.case_group_menu, self.case_menu, self.provider_control, self.model_entry, self.mode_control,
                       self.harness_control, self.repeats_slider,
                       self.ifc_entry, self.browse_btn, self.rule_box,
                       ):
            widget.configure(state=state)

    # ---- small helpers -----------------------------------------------------
    def _on_provider(self, provider: str) -> None:
        self.model_var.set(llm.DEFAULT_MODELS[provider])

    def _on_repeats(self, val: float) -> None:
        self.repeats_label.configure(text=f"Repeats per mode: {int(float(val))}")

    def _on_harness(self, choice: str) -> None:
        """Store the selected harness level and show what it changes."""
        level = next(
            (lvl for lvl, text in HARNESS_LABELS.items() if text == choice), 1
        )
        self.harness_var.set(level)
        self.harness_info.configure(text=HARNESS_HELP[level])

    def _cases(self) -> list[str]:
        """Current ground-truth case ids under ground_truth/; deprecated references are hidden."""
        d = ground_truth.GT_DIR
        return sorted(p.stem for p in d.glob("*.json") if not ground_truth.is_deprecated(p.stem)) if d.exists() else []

    @staticmethod
    def _group_of(gt) -> str:
        """Sort a ground-truth case into a difficulty group.

        The complexity class is stored on the case itself; the ``source`` sniffing
        below is only a fallback for cases written before that field existed.
        """
        if not gt.violation_set and gt.case_id not in PILOTS:
            return GROUP_CONTROL
        if gt.complexity is not None:
            return {
                1: GROUP_SIMPLE_1,
                2: GROUP_SIMPLE_2,
                3: GROUP_HARD_3,
            }.get(gt.complexity, GROUP_OTHER)
        source = gt.source or ""
        if source.startswith("simple_rules.py::"):
            rule_id = source.split("::")[1]
            rule = simple_rules.BY_ID.get(rule_id)
            if rule is not None:
                return GROUP_SIMPLE_1 if rule.complexity == 1 else GROUP_SIMPLE_2
        if ".xlsx::" in source:
            return GROUP_HARD_3
        if gt.case_id.startswith("door_width"):
            return GROUP_SIMPLE_1  # the warm-up rule: read one attribute
        return GROUP_OTHER

    @staticmethod
    def _provenance(gt) -> tuple[str, str]:
        """Where a case comes from: a short tag + a one-line description.

        The description names both the regulation the rule was taken from and how
        its ground truth was produced, since those are two different provenances.
        """
        source = gt.source or ""
        clause = (gt.clause or "").strip()
        if source.startswith("slab_reference.py::"):
            return "BIM", "Project reference v2: recorded property evidence and documented conflict decisions; not expert regulatory certification"
        if source.startswith("reference_v2.py::"):
            origin = "usable_2 reference (reference_v2.py): IFC evidence, workbook rows and recorded adjudications; not expert certification"
            if clause.startswith("fc:"):
                return "SCDF", f"SCDF Fire Code 2023, clause 2.2.12b \u00b7 {origin}"
            if clause == "-":
                return "URA", f"URA Gross Floor Area guidelines (planter boxes) \u00b7 {origin}"
            if clause == "BIM validation":
                return "EC3", f"Rule catalogue of the advisors' EC3-2026 paper (same-storey elevation) \u00b7 {origin}"
            return "BCA", f"BCA Approved Document (Acceptable Solutions V7.08), clause {clause.upper()} \u00b7 {origin}"
        # BCA paragraphs read as "E.3.4.2"; other authorities use their own casing
        # (e.g. the fire code's "fc:2.2.12b"), so only upper-case the former.
        pretty = clause.upper() if re.fullmatch(r"[a-z](\.\d+)+", clause) else clause
        if source.startswith("simple_rules.py::"):
            gt_origin = "ground truth: coded reference implementation"
            if clause.lower().startswith("e."):
                return "BCA", (
                    f"BCA Approved Document (Acceptable Solutions V7.08), clause "
                    f"{pretty} \u00b7 {gt_origin}"
                )
            return "EC3", (
                f"Rule catalogue of the advisors' EC3-2026 paper "
                f"({clause or 'BIM validation'}) \u00b7 {gt_origin}"
            )
        if ".xlsx::" in source:
            workbook = source.split("::")[0]
            tag, authority = WORKBOOK_AUTHORITY.get(
                workbook, ("BCA", "Advisors' BCA test set")
            )
            where = f", clause {pretty}" if clause and clause != "-" else ""
            return tag, (
                f"{authority}{where} \u00b7 expert ground truth from the advisors' "
                f"harness"
            )
        return "DEMO", (
            "Warm-up rule written for this project \u00b7 ground truth derived from "
            "IfcDoor.OverallWidth"
        )

    def _case_catalog(self) -> tuple[list[str], dict[str, dict]]:
        """Dropdown entries grouped by difficulty + a label -> case metadata map.

        Returns the option values (group headers included, prefixed with
        ``HEADER_PREFIX`` so they can be rejected on selection) and a mapping from
        each selectable label to ``{"case_id", "group", "violations", "origin"}``.
        """
        buckets: dict[str, list[tuple[str, dict]]] = {g: [] for g in GROUP_ORDER}
        for case_id in self._cases():
            try:
                gt = ground_truth.load(case_id)
            except Exception:  # noqa: BLE001 - a malformed case must not kill the GUI
                continue
            class_group = self._group_of(gt)
            _, origin = self._provenance(gt)
            n = len(gt.violation_set)
            anchors = gt.anchor_count
            pilot = case_id in PILOTS
            family, _, model_id = case_id.partition("__")
            label = {
                "door_width_planterbox": "Door width / planterbox",
                "doors_windows_storey": "Host storey", "slab_thickness": "Slab",
                "riser_height_e341": "Riser", "tread_width_e342": "Tread",
                "landing_interval_e352": "Landing", "staircase_width_v8": "Stair width / v8",
                "headroom_condo_c32": "Headroom / condo",
                "planter_box_gfa": "Planter GFA",
                "exit_requirements": "Exit access", "headroom_door_c321": "Door headroom",
                "space_elevation": "Space elevation",
            }.get(family, family.replace("_", " "))
            if model_id:
                model_name = {"stair_industrial": "industrial", "stair_obos": "OBOS", "stair_v8": "v8"}.get(model_id, model_id.replace("_", " "))
                label += " / " + model_name
            assessment, review_note = case_assessment(case_id)
            label = f"[{assessment}] {label}"
            buckets[GROUP_PILOT if pilot else class_group].append(
                (
                    label,
                    {
                        "case_id": case_id,
                        "group": GROUP_PILOT if pilot else class_group,
                        "class_group": class_group,
                        "violations": n,
                        "anchors": anchors,
                        "label_counts": gt.label_counts,
                        "origin": origin,
                        "pilot": pilot,
                        "assessment": assessment,
                        "review_note": review_note,
                    },
                )
            )

        values: list[str] = []
        labels: dict[str, dict] = {}
        for group in GROUP_ORDER:
            if group == GROUP_PILOT:
                # Pilots read best in ascending complexity, not alphabetically.
                entries = sorted(
                    buckets[group], key=lambda e: GROUP_ORDER.index(e[1]["class_group"])
                )
            else:
                entries = sorted(buckets[group], key=lambda e: e[0])
            if not entries:
                continue
            values.append(f"{HEADER_PREFIX}{group}")
            for label, meta in entries:
                values.append(label)
                labels[label] = meta
        return values, labels

    def _apply_recommended(self, class_group: str, pilot: bool = False) -> None:
        """Set the repeat slider to the recommendation for *class_group*."""
        repeats = RECOMMENDED.get(class_group, RECOMMENDED[GROUP_OTHER])
        if pilot:
            repeats = max(repeats, PILOT_REPEATS)
        self.repeats_var.set(repeats)
        self._on_repeats(repeats)
        self.reco_label.configure(text=f"Recommended: {repeats} repeats")

    def _on_case(self, choice: str, *, apply_recommended: bool = True) -> None:
        """Load the selected case's ground truth and populate the rule + IFC fields."""
        if choice.startswith(HEADER_PREFIX):
            # A group header is not a case: bounce back to the previous selection.
            self.case_var.set(self._last_case_choice)
            return
        self._last_case_choice = choice

        if choice == CUSTOM_CHOICE:
            self.current_gt = None
            self.current_case = None
            self.case_summary.configure(text="Custom rule | No reference scoring", text_color=MUTED)
            self.case_info.configure(text="Free-form rule and IFC path. No reference labels are supplied.")
            self.reco_label.configure(text="")
            return

        meta = self.case_labels.get(choice)
        case_id = meta["case_id"] if meta else choice
        try:
            gt = ground_truth.load(case_id)
        except Exception as exc:  # noqa: BLE001
            self.current_gt = None
            self.current_case = None
            self.case_info.configure(text=f"Could not load case: {exc}")
            self.case_summary.configure(text="Case could not be loaded.", text_color=RED)
            self.reco_label.configure(text="")
            return
        self.current_gt = gt
        self.current_case = case_id
        self.rule_box.delete("1.0", "end")
        self.rule_box.insert("1.0", gt.rule)
        self.ifc_var.set(str(gt.resolve_ifc()))
        self.ifc_entry.xview_moveto(1)
        class_group = meta["class_group"] if meta else self._group_of(gt)
        origin = meta["origin"] if meta else self._provenance(gt)[1]
        pilot = bool(meta and meta["pilot"])
        assessment, review_note = case_assessment(case_id)
        lines = [case_id, f"Reference review: {assessment} (2026-09-17)", review_note, class_group, origin]
        if pilot:
            lines.append(f"\u2605 PILOT \u2014 {PILOTS[case_id]}")
        if gt.labels:
            lines.append(
                f"{gt.anchor_count} anchor elements labelled {gt.label_counts} "
                f"\u00b7 scored on set agreement + union accuracy"
            )
        else:
            lines.append(
                f"{len(gt.violation_set)} ground-truth violations \u00b7 scored on "
                f"set agreement only (case carries no element labelling)"
            )
        self.case_info.configure(text="\n".join(lines))
        summary = f"{assessment} | Class {gt.complexity or '?'} | {gt.anchor_count} reference elements\n{len(gt.violation_set)} FAIL / {gt.label_counts.get('ALERT', 0)} ALERT\n{review_note}"
        colors = {"Usable": GREEN, "usable_2": GREEN, "Control": BLUE, "Deprecated": RED, "Provisional": ORANGE, "Retired": GREY}
        self.case_summary.configure(text=summary, text_color=colors.get(assessment, MUTED))
        if apply_recommended:
            self._apply_recommended(class_group, pilot)

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            title="Select IFC model",
            filetypes=[("IFC files", "*.ifc"), ("All files", "*.*")],
        )
        if path:
            self.ifc_var.set(path)

    def _write(self, text: str, tag: str | None = None) -> None:
        self.console.configure(state="normal")
        self.console.insert("end", text, tag or ())
        if self.follow_output.get():
            self.console.see("end")
        self.console.configure(state="disabled")

    def _log(self, text: str) -> None:
        if self.log_fh:
            self.log_fh.write(text)
            self.log_fh.flush()

    def _reset_console(self) -> None:
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    def _set_report_text(self, text: str) -> None:
        self.report_console.configure(state="normal")
        self.report_console.delete("1.0", "end")
        for line in text.splitlines():
            tag = (
                "warning" if line.startswith("WARNING:")
                else "heading" if line.endswith(" SUMMARY") or line == "FACTUAL REPORT"
                else "excerpt" if "Agent excerpt (unverified):" in line
                else ""
            )
            self.report_console.insert("end", line + "\n", tag)
        self.report_console.configure(state="disabled")
        self.report_console.yview_moveto(0)

    def _show_factual_report(self, source: Path) -> None:
        self.current_report_path = None
        self.report_open_btn.configure(state="disabled")
        try:
            report, destination = factual_report.generate_report(source)
        except Exception as exc:
            self._set_report_text(f"Report unavailable: {type(exc).__name__}: {exc}\n\nOriginal log: {source}\n")
        else:
            self.current_report_path = destination
            self._set_report_text(factual_report.render_text(report, include_timeline=False))
            self.report_open_btn.configure(state="normal")
            self.artifact_label.configure(text=f"Report saved: {destination.name}")
        self.views.set("Factual Report")

    def _report_saved_log(self) -> None:
        source = filedialog.askopenfilename(
            title="Select a completed GUI log", initialdir=LOG_DIR,
            filetypes=[("GUI Markdown logs", "*.md")],
        )
        if source:
            self._show_factual_report(Path(source))

    def _open_report(self) -> None:
        if self.current_report_path:
            webbrowser.open(self.current_report_path.resolve().as_uri())

    # ---- run lifecycle -----------------------------------------------------
    def _set_suite_buttons(self, state: str) -> None:
        for button in (self.suite_btn, self.quick_suite_btn, self.usable_2_suite_btn):
            button.configure(state=state)

    def _on_suite(self, case_ids: tuple[str, ...] = HEALTH_SUITE_CASES) -> None:
        if self._suite is not None or (self.worker and self.worker.is_alive()):
            return
        try:
            for case_id in case_ids:
                case = ground_truth.load(case_id)
                if not case.resolve_ifc().is_file() or not case.rule.strip():
                    raise ValueError(f"{case_id}: IFC file missing or rule empty.")
                _ = case.unscored_ids
        except Exception as exc:
            messagebox.showerror("Health suite unavailable", str(exc), parent=self)
            return
        mode = self.mode_var.get()
        modes = ["stateful", "stateless"] if mode == "both" else [mode]
        repeats = int(self.repeats_var.get())
        budget = MAX_MODEL_CALLS
        runs = len(case_ids) * len(modes) * repeats
        tiers = ", ".join(f"{sum(case_assessment(c)[0] == tier for c in case_ids)} {tier.lower()}"
                          for tier in ("Usable", "usable_2", "Control", "Provisional") if any(case_assessment(c)[0] == tier for c in case_ids))
        staircase = "Staircase width is scored on all 59 stairs.\n" if "staircase_width_v8" in case_ids else ""
        if not messagebox.askyesno(
            "Confirm paid health suite",
            f"{len(case_ids)} cases: {tiers}\n\n"
            f"Provider: {self.provider_var.get()}\nModel: {self.model_var.get()}\nModes: {', '.join(modes)}\n"
            f"{repeats} repeat(s) per mode: {runs} runs\n"
            f"Fixed {budget} model calls per run: at most {runs * budget} model calls\n\n"
            "Each case uses its stored rule and IFC, not the edited input fields.\n"
            f"{staircase}\n"
            "Token cost is unknown and can reach millions of tokens. This is not a token/spend cap.\n"
            "Stop takes effect after the current agent run. Provider errors stop the suite.\n\nStart?",
            parent=self, default="no",
        ):
            return
        try:
            self._suite_client = llm.load_llm(self.model_var.get().strip() or None, self.provider_var.get())
        except Exception as exc:
            messagebox.showerror("Model unavailable", str(exc), parent=self)
            return
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self._suite_path = LOG_DIR / f"{stamp}_health_suite.json"
        self._suite = {
            "suite_id": f"health-{stamp}", "status": "running",
            "case_ids": list(case_ids), "cases": [],
            "settings": {**llm.model_identity(self._suite_client), "modes": modes, "repeats": repeats,
                         "max_model_calls": budget, "harness": int(self.harness_var.get()),
                         "reasoning": os.environ.get("REASONING", "1").lower() not in ("0", "false", "no"),
                         "env_primer": os.environ.get("ENV_PRIMER", "1").lower() not in ("0", "false", "no")},
            "requested_runs": runs, "finished_runs": 0, "complete_runs": 0,
            "known_input_tokens": 0, "known_output_tokens": 0, "usage_complete": True,
        }
        self._stop_requested.clear()
        self._save_suite()
        self._start_next_suite_case()

    def _save_suite(self) -> None:
        try:
            self._suite_path.parent.mkdir(parents=True, exist_ok=True)
            self._suite_path.write_text(json.dumps(self._suite, indent=2), encoding="utf-8")
        except OSError as exc:
            self._stop_requested.set()
            self._write(f"Suite index could not be saved: {exc}\n", "bad")

    def _start_next_suite_case(self) -> None:
        suite = self._suite
        if suite is None:
            return
        if self._stop_requested.is_set():
            self._end_suite("stopped")
            return
        index = len(suite["cases"])
        if index == len(suite["case_ids"]):
            self._end_suite("finished")
            return
        case_id = suite["case_ids"][index]
        choice = next((name for name, metadata in self.case_labels.items() if metadata["case_id"] == case_id), None)
        if choice is None:
            self._write(f"Suite case unavailable: {case_id}\n", "bad")
            self._end_suite("error")
            return
        self._set_settings_enabled(True)
        self.case_filter.set("Health suite" if case_id in HEALTH_SUITE_CASES else case_assessment(case_id)[0])
        self.case_menu.configure(values=[name for name, metadata in self.case_labels.items() if metadata["case_id"] in suite["case_ids"]])
        self.case_var.set(choice)
        self._on_case(choice, apply_recommended=False)
        suite["cases"].append({"case_id": case_id, "assessment": case_assessment(case_id)[0], "status": "running"})
        self.suite_status.configure(text=f"Case {index + 1}/{len(suite['case_ids'])} | {suite['finished_runs']}/{suite['requested_runs']} runs finished", text_color=MUTED)
        try:
            started = self.current_case == case_id and self._on_run()
        except Exception as exc:
            started = False
            suite["cases"][-1]["error"] = str(exc)
            self._write(f"Could not start {case_id}: {exc}\n", "bad")
        if not started:
            if self.log_fh:
                self.log_fh.close()
                self.log_fh = None
            suite["cases"][-1]["status"] = "error"
            self._end_suite("error")
            return
        suite["cases"][-1]["log_path"] = str(self.current_log_path)
        self._save_suite()

    def _end_suite(self, status: str) -> None:
        suite = self._suite
        suite["status"] = status
        self._save_suite()
        tokens = suite["known_input_tokens"] + suite["known_output_tokens"]
        caption = f"Suite {status} | {suite['finished_runs']}/{suite['requested_runs']} runs finished\n{suite['complete_runs']} complete | {tokens:,} known tokens"
        self.suite_status.configure(text=caption, text_color=RED if status == "error" else MUTED)
        self.header.configure(text=caption.replace("\n", " | "))
        self.artifact_label.configure(text=f"Suite index: {self._suite_path}")
        self._suite = None
        self._suite_client = None
        self._suite_next = False
        self.run_btn.configure(state="normal", text="Run checks")
        self._set_suite_buttons("normal")
        self.stop_btn.configure(state="disabled")
        self._set_settings_enabled(True)
        self.views.set("Scores")

    def _on_stop(self) -> None:
        self._stop_requested.set()
        self.stop_btn.configure(state="disabled", text="Stopping after this run...")
        self.suite_status.configure(text="Stop requested. The current agent run may still consume tokens.", text_color=ORANGE)

    def _on_run(self) -> bool:
        if self.worker and self.worker.is_alive():
            return False

        if self._suite is None:
            assessment, note = case_assessment(self.current_case or "custom")
            if assessment in ("Deprecated", "Provisional", "Retired") and not messagebox.askyesno(
                    "Reference warning", f"{assessment}: {note}\n\nRun as an exploratory check?",
                    parent=self, default="no"):
                return False
            self._stop_requested.clear()
            self.suite_status.configure(text="")

        ifc = self.ifc_var.get().strip()
        self._reset_console()
        if not Path(ifc).exists():
            self._write("IFC file not found:\n" + ifc + "\n", "bad")
            return False

        model = self.model_var.get().strip() or None
        try:
            llm_client = self._suite_client if self._suite is not None else llm.load_llm(model, self.provider_var.get())
        except Exception as exc:
            self._write(str(exc) + "\n", "bad")
            return False

        identity = llm.model_identity(llm_client)
        model = identity["model"]
        mode_choice = self.mode_var.get()
        modes = ["stateful", "stateless"] if mode_choice == "both" else [mode_choice]
        repeats = self._suite["settings"]["repeats"] if self._suite is not None else int(self.repeats_var.get())
        max_iter = MAX_MODEL_CALLS
        rule = self.rule_box.get("1.0", "end").strip()
        reasoning_enabled = os.environ.get("REASONING", "1").lower() not in ("0", "false", "no")
        env_primer = os.environ.get("ENV_PRIMER", "1").lower() not in ("0", "false", "no")
        skills_enabled = False
        runtime = RUNTIME_ISOLATION
        gt = self.current_gt
        gt_set = gt.violation_set if gt is not None else None
        gt_labels = gt.labels if gt is not None else {}
        unscored_ids = gt.unscored_ids if gt is not None else set()
        harness = int(self.harness_var.get())
        case_id = self.current_case or "custom"
        suite_id = self._suite["suite_id"] if self._suite is not None else ""
        if self._suite is not None:
            settings = self._suite["settings"]
            modes, repeats, max_iter = settings["modes"], settings["repeats"], settings["max_model_calls"]
            harness, reasoning_enabled, env_primer = settings["harness"], settings["reasoning"], settings["env_primer"]

        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        session_id = f"gui-{stamp}-{case_id}"

        self._sweep_caption = f"{case_id} | {model} | {', '.join(modes)} x {repeats}"
        self.header.configure(text=self._sweep_caption)
        self.result_view.reset(running=True)
        if self._suite is None or len(self._suite["cases"]) == 1:
            self.score_view.reset("Waiting for scored results." if gt is not None else "Custom rule: no reference scores available.")
        self.artifact_label.configure(text="")
        self.run_btn.configure(state="disabled", text="Running...")
        self._set_suite_buttons("disabled")
        self.stop_btn.configure(state="normal", text="Stop after current run")
        self._set_settings_enabled(False)
        self.current_report_path = None
        self.report_open_btn.configure(state="disabled")
        self.report_load_btn.configure(state="disabled")
        self._set_report_text("Sweep in progress.\n")
        self.views.set("Live Log")

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.current_log_path = LOG_DIR / f"{stamp}_{case_id}_{mode_choice}.md"
        self.log_fh = open(self.current_log_path, "w", encoding="utf-8")
        gt_line = (
            f"- **Ground truth:** {len(gt_set)} violations (case {case_id})\n"
            if gt_set is not None
            else "- **Ground truth:** none (custom rule, unscored)\n"
        )
        self._log(
            f"# Compliance check sweep\n\n"
            f"- **When:** {stamp}\n"
            f"- **Case:** {case_id}\n"
            f"- **Case assessment:** {case_assessment(case_id)[0]} (2026-09-17)\n"
            f"- **Health suite:** {suite_id or 'none'}\n"
            f"- **Modes:** {', '.join(modes)}  \u00d7 {repeats}\n"
            f"- **Harness:** level {harness}\n"
            f"- **Agent protocol:** {AGENT_PROTOCOL}\n"
            f"- **Provider:** {identity['provider']}\n"
            f"- **Model:** {model}\n"
            f"- **Completion checks:** v{COMPLETION_CHECKS_VERSION} (IFC scope and committed labels; no reference answers)\n"
            f"- **Reference:** {gt.reference.get('version', 'legacy/unversioned') if gt else 'none'}\n"
            f"- **Reference scope:** {len(gt_labels)} labelled; {len(unscored_ids)} unannotated IFC elements unscored, still required for completion\n"
            f"- **Skills enabled:** {skills_enabled}\n"
            f"- **Execution runtime:** {runtime}"
            "  (separate worker process; stateless restarts it per block)\n"
            f"- **Max iterations:** {max_iter}\n"
            f"- **IFC:** {ifc}\n"
            f"{gt_line}"
            f"- **Langfuse session:** {session_id}\n\n"
            f"**Rule:**\n\n> {rule}\n\n---\n"
        )
        if gt_set is not None:
            self._write(
                f"Case {case_id} \u00b7 {len(gt_set)} ground-truth violations \u00b7 "
                f"{', '.join(modes)} \u00d7{repeats} \u00b7 Langfuse session {session_id}\n",
                "reason",
            )
        else:
            self._write("Custom rule (unscored)\n", "reason")
        self._write(f"Rule: {rule}\n", "reason")

        def work() -> None:
            recorder = None
            ticket = None
            sweep_error = ""
            agent = None
            executor = None

            def on_event(event_type: str, payload: dict) -> None:
                if ticket is not None:
                    ticket.observe(event_type, payload)
                self.q.put((event_type, payload))

            try:
                recorder = SweepRecorder(
                    entrypoint="gui", requested=len(modes) * repeats, case=gt, rule=rule,
                    ifc_path=Path(ifc), client=llm_client, max_iterations=max_iter,
                    reasoning=reasoning_enabled, env_primer=env_primer, library=None,
                    output_limit=config.OUTPUT_CHAR_LIMIT, log_path=self.current_log_path,
                    warning=lambda message: self.q.put(("notice", {"message": message})),
                )
                per_mode: dict[str, list] = {}
                for mode in modes:
                    scores_list: list = []
                    for rep in range(1, repeats + 1):
                        if self._stop_requested.is_set():
                            break
                        agent = None
                        ticket = recorder.start_run(mode, rep, harness)
                        self.q.put(
                            ("run_header", {"mode": mode, "rep": rep, "repeats": repeats})
                        )
                        executor = make_executor(
                            stateful=(mode == "stateful"),
                            output_char_limit=config.OUTPUT_CHAR_LIMIT,
                        )
                        agent = CodeActAgent(
                            llm_client, executor,
                            max_iterations=max_iter, reasoning_enabled=reasoning_enabled,
                            env_primer=env_primer,
                            harness=harness,
                        )
                        trace_attrs = {
                            "session_id": session_id,
                            "tags": ["gui"],
                            "metadata": {"case_id": case_id, "repeat": rep, "mode": mode,
                                         "health_suite_id": suite_id or None,
                                         "experiment_run_id": ticket.id if ticket else None},
                        }
                        result = agent.check(
                            rule, ifc, on_event=on_event, trace_attrs=trace_attrs
                        )
                        trace_link = tracing.trace_url(result.trace_id)
                        if trace_link:
                            self.q.put(("trace", {"url": trace_link}))
                        sc = None
                        if gt_set is not None:
                            parsed = ParsedVerdict(
                                result.verdict_label, set(result.violations),
                                result.parse_ok, result.verdict, result.reason,
                                result.labels,
                            )
                            sc = score(parsed, gt_set, gt_labels, unscored_ids=unscored_ids)
                            scores_list.append(sc)
                            # Mirror the metrics onto the trace so the Langfuse
                            # project shows quality, not just tokens/latency.
                            tracing.score_run(
                                result.trace_id,
                                sc,
                                extra={
                                    "iterations": result.iterations,
                                    "executions": result.executions,
                                    "harness": result.harness,
                                    "evaluations": result.evaluations,
                                    "total_tokens": result.prompt_tokens
                                    + result.completion_tokens,
                                },
                            )
                            self.q.put(
                                ("score", {
                                    "mode": mode, "rep": rep, "scores": sc,
                                    "iterations": result.iterations,
                                    "prompt_tokens": result.prompt_tokens,
                                    "completion_tokens": result.completion_tokens,
                                    "case_id": case_id, "gt_n": len(gt_set),
                                    "completion_status": result.completion_status,
                                    "completion_issues": result.completion_issues,
                                    "usage_complete": result.usage_complete,
                                    "harness": harness,
                                })
                            )
                        recorder.finish_run(ticket, result, sc)
                        ticket = None
                        executor.close()
                        executor = None
                        self.q.put(("__runfinished__", {"completion_status": result.completion_status,
                            "prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens,
                            "usage_complete": result.usage_complete}))
                    if scores_list:
                        per_mode[mode] = scores_list
                for mode, scs in per_mode.items():
                    agg = aggregate(scs)
                    tracing.score_sweep(session_id, mode, agg)
                    if len(scs) > 1:
                        self.q.put(
                            ("aggregate", {"case_id": case_id, "mode": mode, "agg": agg, "n": len(scs)})
                        )
            except BaseException as exc:
                sweep_error = traceback.format_exc()
                partial = getattr(agent, "partial_result", None)
                partial = partial if isinstance(partial, AgentResult) else None
                if recorder is not None:
                    recorder.finish_run(ticket, partial, error=sweep_error)
                    evidence = recorder.save_evidence(ticket, partial, PROJECT_DIR / "runs", force=True)
                    if evidence:
                        self.q.put(("notice", {"message": f"Partial transcript saved to {evidence}"}))
                    ticket = None
                if partial is not None:
                    self.q.put(("partial_result", {"prompt_tokens": partial.prompt_tokens,
                        "completion_tokens": partial.completion_tokens, "usage_complete": partial.usage_complete,
                        "completion_status": "incomplete", "verdict": "(no verdict reached)",
                        "reason": partial.reason, "iterations": partial.iterations, "labels": len(partial.labels)}))
                self.q.put(("__error__", {"trace": sweep_error}))
                if not isinstance(exc, Exception):
                    raise
            finally:
                if executor is not None:
                    executor.close()
                if recorder is not None:
                    recorder.finish(sweep_error)
                # Flush here, on the worker, not on the Tk thread: a Langfuse
                # flush does network I/O and would freeze the whole UI.
                tracing.flush()
                self.q.put(("__threaddone__", {"error": bool(sweep_error), "stopped": self._stop_requested.is_set()}))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        self.after(80, self._poll)
        return True

    def _poll(self) -> None:
        # Read liveness BEFORE draining. If the worker finishes *during* the
        # drain, whatever it enqueued on its way out (notably '__threaddone__')
        # is still guaranteed one more poll; checking afterwards could drop it
        # and leave the UI stuck on "Running…" forever with the run long done.
        was_alive = bool(self.worker and self.worker.is_alive())
        try:
            while True:
                event_type, payload = self.q.get_nowait()
                self._handle(event_type, payload)
        except queue.Empty:
            pass
        if was_alive:
            self.after(80, self._poll)
        elif self._suite_next:
            self._suite_next = False
            self._start_next_suite_case()

    def _handle(self, event_type: str, payload: dict) -> None:
        if event_type == "iteration_start":
            self.result_view.status_label.configure(text=f"In progress | Step {payload['n']} of {payload['total']}", text_color=MUTED)
            self._write(f"\nIteration {payload['n']} / {payload['total']}\n", "iter")
            self._log(f"\n## Iteration {payload['n']} / {payload['total']}\n")
        elif event_type == "assistant":
            reasoning = (payload.get("reasoning") or "").strip()
            if reasoning:
                self._write("Thinking\n", "hdr")
                self._write(reasoning + "\n", "reason")
                self._log(f"\n### Reasoning\n\n{reasoning}\n")
        elif event_type == "code":
            self._write("Code\n", "hdr")
            self._write(payload["code"] + "\n", "code")
            self._log(f"\n### Code\n\n```python\n{payload['code']}\n```\n")
        elif event_type == "output":
            self._write("Output\n", "hdr")
            self._write(payload["output"] + "\n", "out")
            self._log(f"\n### Output\n\n```\n{payload['output']}\n```\n")
            if isinstance(payload.get("error"), bool):
                status = {key: payload[key] for key in
                          ("error", "error_text", "truncated", "output_dropped_chars",
                           "labels_valid", "kernel_restarted", "restart_reason")
                          if key in payload}
                self._log("\n### Execution status\n\n```json\n" + json.dumps(status, indent=2) + "\n```\n")
        elif event_type == "usage":
            self._log("\n### Usage\n\n```json\n" + json.dumps(payload, indent=2) + "\n```\n")
        elif event_type == "partial_result":
            self.result_view.show_result(payload)
            qualifier = "known usage only; failed request usage may be unavailable"
            self._write(f"Partial run: {payload['prompt_tokens']} input / {payload['completion_tokens']} output tokens ({qualifier}).\n", "notice")
            self._log("\n### Partial usage\n\n```json\n" + json.dumps(payload, indent=2) + "\n```\n")
            if self._suite is not None:
                self._suite["known_input_tokens"] += payload["prompt_tokens"]
                self._suite["known_output_tokens"] += payload["completion_tokens"]
                self._suite["usage_complete"] = False
        elif event_type == "notice":
            self._write("\u2022 " + payload["message"] + "\n", "notice")
            self._log(f"\n> NOTE: {payload['message']}\n")
        elif event_type == "plan":
            self._write("Plan\n", "hdr")
            self._write(payload["content"] + "\n", "reason")
            self._log(f"\n## Plan\n\n{payload['content']}\n")
        elif event_type == "evaluation":
            self._write(f"Evaluator \u00b7 A\u222a = {payload['accuracy']:.3f}\n", "hdr")
            self._write(payload["feedback"] + "\n", "notice")
            self._log(
                f"\n### Evaluator (union accuracy {payload['accuracy']:.3f})\n\n"
                f"{payload['feedback']}\n"
            )
        elif event_type == "trace":
            self._write(f"Langfuse trace: {payload['url']}\n", "notice")
            self._log(f"\n- **Langfuse trace:** {payload['url']}\n")
        elif event_type == "run_header":
            bar_line = "\u2501" * 52
            mode, rep, reps = payload["mode"], payload["rep"], payload["repeats"]
            self._active_run = f"{mode.upper()} | RUN {rep} OF {reps}"
            self._latest_completion = {}
            self.result_view.reset(run_label=self._active_run, running=True)
            self._write(
                f"\n{bar_line}\n{mode.upper()}  \u00b7  run {rep}/{reps}\n{bar_line}\n",
                "run_sep",
            )
            self._log(f"\n\n# {mode} \u00b7 run {rep}/{reps}\n")
        elif event_type == "score":
            self._render_score(payload)
        elif event_type == "aggregate":
            self._render_aggregate(payload)
        elif event_type == "done":
            self._finish(payload)
        elif event_type == "completion":
            self._latest_completion = payload
            status = str(payload.get("status", "not recorded"))
            tag = "score_good" if status == "complete" else "notice"
            self._write(f"\nCompletion: {status}\n", tag)
            for issue in payload.get("issues", []):
                self._write(str(issue) + "\n", "notice")
            self._log("\n### Completion\n\n```json\n" + json.dumps(payload, indent=2) + "\n```\n")
        elif event_type == "__error__":
            self.result_view.title_label.configure(text="Sweep interrupted", text_color=RED)
            self.result_view.status_label.configure(text="See Live Log for the recorded error", text_color=ORANGE)
            self._write("\nERROR:\n" + payload["trace"] + "\n", "bad")
            self._log(f"\n## ERROR\n\n```\n{payload['trace']}\n```\n")
            if self._suite is not None:
                self._suite["usage_complete"] = False
        elif event_type == "__runfinished__":
            if self._suite is not None:
                suite = self._suite
                suite["finished_runs"] += 1
                suite["complete_runs"] += payload["completion_status"] == "complete"
                suite["known_input_tokens"] += payload["prompt_tokens"]
                suite["known_output_tokens"] += payload["completion_tokens"]
                suite["usage_complete"] = suite["usage_complete"] and payload["usage_complete"]
                tokens = suite["known_input_tokens"] + suite["known_output_tokens"]
                self.suite_status.configure(text=f"Case {len(suite['cases'])}/{len(suite['case_ids'])} | {suite['finished_runs']}/{suite['requested_runs']} runs finished\n{tokens:,} known tokens")
                self._save_suite()
        elif event_type == "__threaddone__":
            self.run_btn.configure(state="normal", text="Run checks")
            self._set_settings_enabled(True)
            if self.log_fh:
                self.log_fh.close()
                self.log_fh = None
            status = "error" if payload.get("error") else "stopped" if payload.get("stopped") else "finished"
            self.header.configure(text=f"Sweep {status} | " + self._sweep_caption)
            self._set_suite_buttons("normal")
            self.stop_btn.configure(state="disabled")
            self.report_load_btn.configure(state="normal")
            if self.current_log_path:
                self._show_factual_report(self.current_log_path)
            self.experiments_view.refresh()
            if self._suite is not None:
                self._suite["cases"][-1].update(status=status,
                    report_path=str(self.current_report_path) if self.current_report_path else None)
                self._save_suite()
                if status != "finished" or self._stop_requested.is_set():
                    self._end_suite(status if status != "finished" else "stopped")
                else:
                    self.run_btn.configure(state="disabled")
                    self._set_suite_buttons("disabled")
                    self._set_settings_enabled(False)
                    self._suite_next = True

    def _finish(self, payload: dict) -> None:
        verdict = str(payload.get("verdict", "")).strip()
        reason = str(payload.get("reason", "")).strip()
        display = result_presentation(payload)
        tag = "bad" if display["color"] == RED else "ok" if display["color"] == GREEN else "notice"
        self._write("\n" + display["title"] + " | " + display["completion"] + "\n", tag)
        if reason:
            self._write(f"Completion reason: {reason}\n", "notice")
        self.result_view.show_result(payload)
        if self.current_log_path:
            self.artifact_label.configure(text=f"Log: {self.current_log_path.name}")
        self._log(
            f"\n\n### Verdict\n\n{verdict}\n\n"
            + (f"**Completion reason:** {reason}\n\n" if reason else "")
            + f"- iterations: {payload.get('iterations')}\n"
            f"- tokens: {payload.get('prompt_tokens')} in / "
            f"{payload.get('completion_tokens')} out\n"
        )
        if "usage_complete" in payload:
            usage = {key: payload[key] for key in ("usage_complete", "cache_read_input_tokens", "cache_creation_input_tokens") if key in payload}
            self._log("\n### Usage summary\n\n```json\n" + json.dumps(usage, indent=2) + "\n```\n")

    def _render_score(self, p: dict) -> None:
        """Render one run's agreement score against ground truth, human-readable."""
        sc = p["scores"]
        self.score_view.add_score(p)
        union = (
            f" union_acc={sc.union_accuracy:.3f} coverage={sc.label_coverage:.3f}"
            f" labels={sc.labels_reported}/{sc.labels_expected}"
            if sc.union_accuracy is not None
            else f" union_acc=n/a labels=0/{sc.labels_expected}"
        )
        self._log(
            f"\n**Score** ({p['case_id']}): P={sc.precision:.2f} R={sc.recall:.2f} "
            f"F1={sc.f1:.2f} exact={int(sc.exact_set_match)} tp={sc.tp} fp={sc.fp} "
            f"fn={sc.fn} verdict_match={int(sc.verdict_match)} "
            f"parse_ok={int(sc.parse_ok)}{union} iters={p['iterations']} "
            f"tok={p['prompt_tokens']}/{p['completion_tokens']}\n"
            + (f"\n  confusion: {sc.confusion}\n" if sc.confusion else "")
        )

    def _render_aggregate(self, p: dict) -> None:
        """Render the mean ± std summary for one mode across its repeats."""
        m = p["agg"].metrics
        n = p["n"]
        mode = p["mode"]

        def pct(name: str) -> str:
            return f"{m[name]['mean'] * 100:.0f}% \u00b1 {m[name]['std'] * 100:.0f}%"

        self.score_view.add_aggregate(p)
        self._log(
            f"\n## {mode} mean over {n}: precision {pct('precision')} "
            f"recall {pct('recall')} f1 {m['f1']['mean']:.2f}±{m['f1']['std']:.2f} "
            f"exact {pct('exact_set_match')} verdict {pct('verdict_match')} "
            f"parse {pct('parse_ok')} abstained {pct('abstained')}\n"
        )


if __name__ == "__main__":
    App().mainloop()
