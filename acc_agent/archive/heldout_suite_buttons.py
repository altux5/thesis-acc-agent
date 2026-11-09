"""Retired held-out suite buttons, archived verbatim on 2026-11-02. Not imported by anything.

These entries of ``HELDOUT_PILOTS`` in ``gui.py`` defined the GUI buttons of the finished test-set
experiments (planning step, GPT-6 Luna, reasoning on, Sonnet 5.5 stateless, 40-call budget, file system).
They were removed from the GUI after their suites were complete (user request, 2026-11-02); the
suite index kind (dictionary key) is still the label of their runs in ``logs/*_health_suite.json`` and
the experiment ledger, and ``thesis/analysis/load_runs.py`` selects the runs by these kinds.
Source: ``acc_agent/gui.py`` lines 185-212 on 2026-11-02 (after the single-shot buttons were added);
the last published version containing them is commit d1e8084 of altux5/thesis-acc-agent (without the
budget and file-system entries, which were added later). Plans and results: NOTES.md, Decisions.
Kept in the GUI: ``heldout_m3_files_budget40`` (unfinished) and the single-shot baseline buttons.
"""

MAX_MODEL_CALLS = 20  # gui.MAX_MODEL_CALLS at the time

HELDOUT_PILOTS_RETIRED = {
    "heldout_h2_minimax": {"label": "Held-out extra planning step: M3 (MiniMax API), stateful", "provider": "minimax",
                           "model": "MiniMax-M3", "mode": "stateful", "repeats": 2, "harness": 2},
    # Same as heldout_h2_minimax (recorded reasoning false), but the plan call is added on top of the 20-call budget.
    "heldout_h2_minimax_21": {"label": "Held-out extra planning step, 21 calls (plan + 20): M3 (MiniMax API), stateful",
                              "provider": "minimax", "model": "MiniMax-M3", "mode": "stateful", "repeats": 2,
                              "harness": 2, "reasoning": False, "max_model_calls": MAX_MODEL_CALLS + 1},
    "heldout_luna": {"label": "Held-out: GPT-6 Luna (OpenRouter), stateful + stateless", "provider": "openrouter",
                     "model": "openai/gpt-6-luna", "mode": "both", "repeats": 2, "harness": 1},
    "heldout_m3_reasoning_stateful": {"label": "Held-out reasoning on: M3 (MiniMax API), stateful",
                                      "provider": "minimax", "model": "MiniMax-M3", "mode": "stateful",
                                      "repeats": 1, "harness": 1, "reasoning": True},
    "heldout_m3_reasoning_stateless": {"label": "Held-out reasoning on: M3 (MiniMax API), stateless",
                                       "provider": "minimax", "model": "MiniMax-M3", "mode": "stateless",
                                       "repeats": 2, "harness": 1, "reasoning": True},
    # Stateless counterpart of the Sonnet held-out run (suite 20261018-215712-011319: stateful, 1 x 95, reasoning false).
    "heldout_sonnet_stateless": {"label": "Held-out: Sonnet 5.5 (OpenRouter), stateless", "provider": "openrouter",
                                 "model": "anthropic/claude-sonnet-5.5", "mode": "stateless",
                                 "repeats": 1, "harness": 1, "reasoning": False},
    # Larger budget on the harder rules: as the M3 main run's stateful arm, but 40 model calls and classes 2-3 only.
    "heldout_m3_budget40": {"label": "Held-out larger budget, 40 calls, classes 2-3: M3 (MiniMax API), stateful",
                            "provider": "minimax", "model": "MiniMax-M3", "mode": "stateful", "repeats": 2,
                            "harness": 1, "reasoning": False, "max_model_calls": 2 * MAX_MODEL_CALLS,
                            "complexity": (2, 3)},
    # File-system condition (protocol langchain-codeact-v5-files-guided): as the M3 main run, plus run-workspace
    # file tools with usage guidance. The neutral pilot used suite kind heldout_m3_files (5 runs, not resumed).
    "heldout_m3_files_guided": {"label": "Held-out file system (guided): M3 (MiniMax API), stateful + stateless",
                                "provider": "minimax", "model": "MiniMax-M3", "mode": "both", "repeats": 2,
                                "harness": 1, "reasoning": False, "file_system": True},
}

# Archived 2026-11-04 from gui.py HELDOUT_PILOTS (lines 205-214 of that day, not published): the first script-mode
# pilot, protocol langchain-codeact-v5-script (separate write_file and run_file calls). It ran once (suite
# 20261104-184803-761749, 4 runs, 1 complete): M3 sends one tool call per reply, so each script run cost two model
# calls. Replaced by protocol v2 (write_file/edit_file with run=true) and its pilot buttons. NOTES.md 2026-11-04.
HELDOUT_PILOTS_RETIRED["heldout_m3_script_pilot"] = {
    "label": "Script-mode pilot (run_file only): M3 (MiniMax API), stateless",
    "provider": "minimax", "model": "MiniMax-M3", "mode": "stateless", "repeats": 1,
    "harness": 1, "reasoning": False, "max_model_calls": MAX_MODEL_CALLS,
    "script_mode": True,
    "cases": ("door_clear_width__clinic", "slab_thickness_range__nus",
              "stair_slab_connection__smiley", "door_front_clearance__fzk")}

# Archived 2026-11-04 from gui.py (HELDOUT_PILOTS and HELDOUT_CHAINS, not published): the script-mode v2 pilot
# (protocol langchain-codeact-v5-script-v2), finished the same day: suites 20261104-193837-243077 (M3, 4 runs + one
# provider-error attempt) and 20261104-202202-952176 (Luna, 4 runs). Replaced by the class-3 series buttons.
SCRIPT_PILOT_CASES = ("door_clear_width__clinic", "slab_thickness_range__nus", "stair_slab_connection__smiley",
                      "door_front_clearance__fzk")
HELDOUT_PILOTS_RETIRED["heldout_m3_script_v2_pilot"] = {
    "label": "Script-mode v2 pilot: M3 (MiniMax API), stateless",
    "provider": "minimax", "model": "MiniMax-M3", "mode": "stateless", "repeats": 1,
    "harness": 1, "reasoning": False, "max_model_calls": MAX_MODEL_CALLS,
    "script_mode": True, "cases": SCRIPT_PILOT_CASES}
HELDOUT_PILOTS_RETIRED["heldout_luna_script_v2_pilot"] = {
    "label": "Script-mode v2 pilot: GPT-6 Luna (OpenRouter), stateless",
    "provider": "openrouter", "model": "openai/gpt-6-luna", "mode": "stateless",
    "repeats": 1, "harness": 1, "reasoning": False,
    "max_model_calls": MAX_MODEL_CALLS, "script_mode": True,
    "cases": SCRIPT_PILOT_CASES}
HELDOUT_CHAINS_RETIRED = {
    "heldout_script_v2_pilot_all": {"label": "Script-mode v2 pilot, both models: M3, then GPT-6 Luna (4 + 4 runs)",
                                    "kinds": ("heldout_m3_script_v2_pilot", "heldout_luna_script_v2_pilot")},
}

# Archived 2026-11-07 from gui.py (user request: all experiment runs are done, remove the unnecessary buttons). The
# remaining held-out and chain buttons are retired with the code only they used (resume of finished cases, chained
# suites, case_complexity), and so is the usable_2 calibration-suite button. Their suites had finished:
# heldout_m3_files_budget40 (73 cases; last suites 20261103-100204-030077 and 20261103-192734-173044),
# heldout_single_shot_m3, _sonnet and _luna (95 cases each), heldout_m3_script_v2_class3 and
# heldout_luna_script_v2_class3 (9 each); heldout_m3_script was never started. Kept in the GUI: Run checks, the
# 8-case health suite and Stop. App._on_suite keeps its kind, reasoning, budget, file_system, single_shot and
# script_mode arguments, so an archived configuration can still be run from code; its confirmed argument, used only
# by the chain, was removed. Source: acc_agent/gui.py on 2026-11-07 (working copy after the 2026-11-04 changes, not
# published), kept below as verbatim text because the blocks reference gui.py names.

# gui.py line 171
GUI_USABLE_2_SUITE_CASES = r'''
USABLE_2_SUITE_CASES = tuple(USABLE_2_CASES)
'''

# gui.py lines 184-252
GUI_HELDOUT_CONFIG = r'''
# Held-out suite buttons. Key = suite index kind; "reasoning" overrides REASONING for that suite.
# Buttons of finished experiments are archived in archive/heldout_suite_buttons.py (their kinds still label the runs).
# Script-mode v2 class-3 series (NOTES 2026-11-04), fixed before any run: per class-3 rule, 3 of its held-out cases
# drawn with random.Random(20261104).sample from the sorted cases of the rule, excluding the script-mode pilot case
# door_front_clearance__fzk.
SCRIPT_CLASS3_CASES = ("door_front_clearance__duplex", "door_front_clearance__smiley", "door_front_clearance__wohnung",
                       "slab_fall_protection__esplanades", "slab_fall_protection__fzk",
                       "slab_fall_protection__schependomlaan", "unallocated_floor_area__clinic",
                       "unallocated_floor_area__duplex", "unallocated_floor_area__fzk")
HELDOUT_PILOTS = {
    # Budget check for the file system: as heldout_m3_budget40 (40 calls, classes 2-3, stateful x2) plus the guided
    # file system, so the pair differs only in the file system.
    "heldout_m3_files_budget40": {"label": "Held-out file system (guided), 40 calls, classes 2-3: M3 (MiniMax API), stateful",
                                  "provider": "minimax", "model": "MiniMax-M3", "mode": "stateful", "repeats": 2,
                                  "harness": 1, "reasoning": False, "max_model_calls": 2 * MAX_MODEL_CALLS,
                                  "complexity": (2, 3), "file_system": True},
    # Single-shot baseline (protocol langchain-codeact-v5-single-shot): one model call, one script run once,
    # no output shown. One block, so the mode is recorded as stateless; budget 1. Plan: NOTES 2026-11-02.
    "heldout_single_shot_m3": {"label": "Held-out single-shot baseline: M3 (OpenRouter)", "provider": "openrouter",
                               "model": "minimax/minimax-m3", "mode": "stateless", "repeats": 2, "harness": 1,
                               "reasoning": False, "max_model_calls": 1, "single_shot": True},
    "heldout_single_shot_sonnet": {"label": "Held-out single-shot baseline: Sonnet 5.5 (OpenRouter)",
                                   "provider": "openrouter", "model": "anthropic/claude-sonnet-5.5", "mode": "stateless",
                                   "repeats": 2, "harness": 1, "reasoning": False, "max_model_calls": 1,
                                   "single_shot": True},
    "heldout_single_shot_luna": {"label": "Held-out single-shot baseline: GPT-6 Luna (OpenRouter)",
                                 "provider": "openrouter", "model": "openai/gpt-6-luna", "mode": "stateless",
                                 "repeats": 2, "harness": 1, "reasoning": False, "max_model_calls": 1,
                                 "single_shot": True},
    # Script mode (script_agent.py): code runs only from workspace files, each run in a fresh interpreter, so
    # stateless only. Main-run settings otherwise. Plan: NOTES 2026-11-04. Protocol v2 (write_file/edit_file with
    # run=true save and run in one call); the v1 and v2 pilot buttons are archived in archive/heldout_suite_buttons.py.
    # Class-3 series: both models on SCRIPT_CLASS3_CASES, 1 repeat each, started together by the chain button.
    "heldout_m3_script_v2_class3": {"label": "Script-mode v2 class-3 series: M3 (MiniMax API), stateless",
                                    "provider": "minimax", "model": "MiniMax-M3", "mode": "stateless", "repeats": 1,
                                    "harness": 1, "reasoning": False, "max_model_calls": MAX_MODEL_CALLS,
                                    "script_mode": True, "cases": SCRIPT_CLASS3_CASES},
    "heldout_luna_script_v2_class3": {"label": "Script-mode v2 class-3 series: GPT-6 Luna (OpenRouter), stateless",
                                      "provider": "openrouter", "model": "openai/gpt-6-luna", "mode": "stateless",
                                      "repeats": 1, "harness": 1, "reasoning": False,
                                      "max_model_calls": MAX_MODEL_CALLS, "script_mode": True,
                                      "cases": SCRIPT_CLASS3_CASES},
    "heldout_m3_script": {"label": "Held-out script mode: M3 (MiniMax API), stateless",
                          "provider": "minimax", "model": "MiniMax-M3", "mode": "stateless", "repeats": 2,
                          "harness": 1, "reasoning": False, "max_model_calls": MAX_MODEL_CALLS, "script_mode": True},
}


def case_complexity(case_id: str) -> int | None:
    complexity = json.loads((ground_truth.GT_DIR / f"{case_id}.json").read_text(encoding="utf-8")).get("complexity")
    return int(complexity) if complexity is not None else None


# Cases per held-out button; "complexity" restricts a button to the listed Solihin & Eastman classes, "cases" to a
# fixed list.
HELDOUT_PILOT_CASES = {kind: tuple(c for c in HELDOUT_SUITE_CASES
                                   if ("complexity" not in pilot or case_complexity(c) in pilot["complexity"])
                                   and ("cases" not in pilot or c in pilot["cases"]))
                       for kind, pilot in HELDOUT_PILOTS.items()}
# Chained held-out suites: one confirmation, then the remaining cases of each listed suite kind run one
# after another, each as its own suite index (so each kind resumes on its own).
HELDOUT_CHAINS = {
    "heldout_single_shot_all": {"label": "Held-out single-shot baseline, all remaining: Luna, Sonnet 5.5, M3",
                                "kinds": ("heldout_single_shot_luna", "heldout_single_shot_sonnet",
                                          "heldout_single_shot_m3")},
    "heldout_script_v2_class3_both": {"label": "Script-mode v2 class-3 series, both models: M3, then GPT-6 Luna "
                                               "(9 + 9 runs)",
                                      "kinds": ("heldout_m3_script_v2_class3", "heldout_luna_script_v2_class3")},
}
'''

# gui.py lines 507-526 (App._build_sidebar, footer buttons)
GUI_SUITE_BUTTONS = r'''
        self.usable_2_suite_btn = ctk.CTkButton(
            footer, text=f"Run {len(USABLE_2_SUITE_CASES)}-case usable_2 suite", height=34,
            command=lambda: self._on_suite(USABLE_2_SUITE_CASES),
            fg_color=SURFACE, hover_color=HOVER, text_color=TEXT, corner_radius=4)
        self.usable_2_suite_btn.pack(fill="x", pady=(6, 0))
        self.heldout_pilot_btns = {}
        for kind, pilot in HELDOUT_PILOTS.items():
            button = ctk.CTkButton(
                footer, text=f"{pilot['label']}, {pilot['repeats']} run(s) x {len(HELDOUT_PILOT_CASES[kind])} cases", height=34,
                command=lambda kind=kind: self._on_heldout_pilot(kind),
                fg_color=PRIMARY, hover_color=HOVER, text_color=TEXT, corner_radius=4)
            button.pack(fill="x", pady=(6, 0))
            self.heldout_pilot_btns[kind] = button
        self.heldout_chain_btns = {}
        for chain_id, chain in HELDOUT_CHAINS.items():
            button = ctk.CTkButton(
                footer, text=chain["label"], height=34, command=lambda chain_id=chain_id: self._on_heldout_chain(chain_id),
                fg_color=PRIMARY, hover_color=HOVER, text_color=TEXT, corner_radius=4)
            button.pack(fill="x", pady=(6, 0))
            self.heldout_chain_btns[chain_id] = button
'''

# gui.py lines 975-1064 (App methods)
GUI_PILOT_AND_CHAIN_HANDLERS = r'''
    def _pilot_finished_cases(self, kind: str) -> set[str]:
        """Held-out cases whose pilot run finished in an earlier session of this pilot (from the suite indexes)."""
        finished = set()
        for path in LOG_DIR.glob("*_health_suite.json"):
            try:
                suite = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if suite.get("kind") == kind:
                finished.update(entry["case_id"] for entry in suite.get("cases", []) if entry.get("status") == "finished")
        return finished

    def _apply_pilot_settings(self, pilot: dict) -> None:
        self.provider_var.set(pilot["provider"])
        self.model_var.set(pilot["model"])
        self.mode_var.set(pilot["mode"])
        self.harness_choice.set(HARNESS_LABELS[pilot["harness"]])
        self._on_harness(HARNESS_LABELS[pilot["harness"]])
        self.repeats_var.set(pilot["repeats"])
        self._on_repeats(pilot["repeats"])

    def _start_pilot_suite(self, kind: str, cases: tuple[str, ...], confirmed: bool = False) -> None:
        pilot = HELDOUT_PILOTS[kind]
        self._on_suite(cases, kind=kind, reasoning=pilot.get("reasoning"),
                       budget=pilot.get("max_model_calls", MAX_MODEL_CALLS), file_system=pilot.get("file_system", False),
                       single_shot=pilot.get("single_shot", False), script_mode=pilot.get("script_mode", False),
                       confirmed=confirmed)

    def _pilot_remaining_cases(self, kind: str) -> tuple[str, ...]:
        done = self._pilot_finished_cases(kind)
        return tuple(case for case in HELDOUT_PILOT_CASES[kind] if case not in done)

    def _on_heldout_chain(self, chain_id: str) -> None:
        """Confirm once, then run the remaining cases of each suite kind of the chain in order."""
        if self._suite is not None or (self.worker and self.worker.is_alive()):
            return
        steps = [(kind, self._pilot_remaining_cases(kind)) for kind in HELDOUT_CHAINS[chain_id]["kinds"]]
        steps = [(kind, cases) for kind, cases in steps if cases]
        if not steps:
            messagebox.showinfo("Nothing to run", "Every suite of this chain has finished all its cases.", parent=self)
            return
        lines, total = [], 0
        for kind, cases in steps:
            pilot = HELDOUT_PILOTS[kind]
            runs = len(cases) * pilot["repeats"] * (2 if pilot["mode"] == "both" else 1)
            total += runs
            lines.append(f"- {pilot['label']}\n  {pilot['provider']} / {pilot['model']}: {len(cases)} remaining cases, {runs} runs")
        if not messagebox.askyesno(
                "Confirm chained paid suites",
                "The suites run one after another without further questions:\n\n" + "\n".join(lines)
                + f"\n\nTotal: {total} runs. Token cost is unknown; this is not a spend cap.\n"
                "Stop ends the whole chain after the current run. A provider error reruns the whole case, "
                f"at most {len(PROVIDER_RETRY_DELAYS)} times, then skips it.\n\nStart?", parent=self, default="no"):
            return
        self._chain = [kind for kind, _ in steps]
        self._continue_chain()

    def _continue_chain(self) -> None:
        if self.worker and self.worker.is_alive():  # the last run's thread is still closing
            self.after(2000, self._continue_chain)
            return
        while self._chain:
            kind = self._chain.pop(0)
            cases = self._pilot_remaining_cases(kind)
            if cases:
                self._apply_pilot_settings(HELDOUT_PILOTS[kind])
                self._start_pilot_suite(kind, cases, confirmed=True)
                if self._suite is None:  # the suite could not start (e.g. model unavailable): end the chain
                    self._chain = []
                return

    def _on_heldout_pilot(self, kind: str) -> None:
        if self._suite is not None or (self.worker and self.worker.is_alive()):
            return
        pilot = HELDOUT_PILOTS[kind]
        self._apply_pilot_settings(pilot)
        suite_cases = HELDOUT_PILOT_CASES[kind]
        done = self._pilot_finished_cases(kind) & set(suite_cases)
        cases = suite_cases
        if done:
            remaining = tuple(case for case in suite_cases if case not in done)
            choice = messagebox.askyesnocancel(
                "Resume held-out pilot",
                f"{len(done)} of {len(suite_cases)} cases already finished in earlier pilot sessions.\n\n"
                f"Yes: run the remaining {len(remaining)} cases.\nNo: run all {len(suite_cases)} cases again.\n"
                "Cancel: do nothing.", parent=self)
            if choice is None or (choice and not remaining):
                return
            cases = remaining if choice else suite_cases
        self._start_pilot_suite(kind, cases)
'''

# gui.py lines 1256-1259 (end of App._end_suite; self._chain was initialised as [] in App.__init__)
GUI_END_SUITE_CHAIN = r'''
        if status == "finished" and self._chain:
            self.after(1000, self._continue_chain)
        else:
            self._chain = []
'''
