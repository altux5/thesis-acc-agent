"""Retired cross-run skill wiring, archived verbatim on 2026-09-30. Not imported by anything.

Agents could save helper functions with ``save_skill`` and later runs preloaded them
(``skill_library.py``). Cross-run skills were removed from the thesis evaluation with the
LangChain migration (NOTES, 2026-09-17): ``SKILLS``/``SKILLS_DIR`` no longer activate
anything and the GUI has no skills switch. ``skill_library.py`` itself stays in place with
its tests; these are the call sites that used it.

Where to find the code:
- Live (uncommented) version: commit ``fa7b163`` (8 Sep 2026) of altux5/Thesis-initial.
- Commented-out in the live files: tags ``langchain-v1`` and ``stable-case-names`` of
  altux5/thesis-acc-agent. Each fragment header below gives the file and line range at
  ``stable-case-names``; the lines are copied unchanged, including indentation.
"""

# ==== gui.py line 53 (imports) ====
# from skill_library import SkillLibrary

# ==== gui.py lines 370-383 (App.__init__, skills switch and status after the runtime selector) ====
        # self.skills_var = tk.BooleanVar(value=os.environ.get("SKILLS", "1").lower() not in ("0", "false", "no"))
        # self.skills_control = ctk.CTkCheckBox(
        #     bar, text="Use skills", variable=self.skills_var, font=("Segoe UI", 12), command=self._refresh_skill_health,
        #     text_color=MUTED, fg_color=PRIMARY, hover_color=HOVER, checkbox_width=16, checkbox_height=16,
        #     border_color=BORDER, border_width=1,
        # )
        # self.skills_control.pack(fill="x", padx=10, pady=(4, 8))
        # self.skill_health_label = ctk.CTkLabel(bar, text="", height=18, font=("Segoe UI", 11),
        #     text_color=MUTED, wraplength=250, anchor="w", justify="left")
        # self.skill_health_label.pack(fill="x", padx=10, pady=(0, 2))
        # self.skill_details_btn = ctk.CTkButton(bar, text="Skill details", command=self._show_skill_health,
        #     fg_color="transparent", hover_color=SURFACE, text_color=BLUE, height=24, corner_radius=4, anchor="w")
        # self.skill_details_btn.pack(fill="x", padx=10, pady=(0, 6))
        # self._refresh_skill_health()

# ==== gui.py line 589 (App._set_settings_enabled, widget list) ====
                       # self.skills_control,

# ==== gui.py lines 604-642 (App methods: skill status and details dialog) ====
    # def _refresh_skill_health(self) -> dict:
    #     health = SkillLibrary(enabled=bool(self.skills_var.get())).health()
    #     if not health["enabled"]:
    #         self.skill_health_label.configure(text="Off | No skill loading or saving", text_color=MUTED)
    #     else:
    #         entries = health["skills"]
    #         bad = sum(entry["status"] == "unavailable" for entry in entries) + len(health["issues"])
    #         legacy = sum(entry["version"] == "legacy" for entry in entries)
    #         self.skill_health_label.configure(
    #             text=f"{len(entries)} saved | {legacy} legacy | {bad} unavailable",
    #             text_color=ORANGE if bad or legacy else MUTED,
    #         )
    #     return health
    #
    # def _show_skill_health(self) -> None:
    #     health = self._refresh_skill_health()
    #     dialog = ctk.CTkToplevel(self)
    #     dialog.title("Skill library status")
    #     dialog.geometry("620x450")
    #     dialog.minsize(400, 300)
    #     dialog.configure(fg_color=BACKGROUND)
    #     dialog.transient(self)
    #     dialog.grid_columnconfigure(0, weight=1)
    #     dialog.grid_rowconfigure(0, weight=1)
    #     content = dark_text(dialog)
    #     content.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
    #     scrollbar = ctk.CTkScrollbar(dialog, command=content.yview)
    #     scrollbar.grid(row=0, column=1, sticky="ns")
    #     content.configure(yscrollcommand=scrollbar.set)
    #     lines = ["SKILL LIBRARY", "Self-tests are not independent correctness verification. Status inspection does not execute code."]
    #     if not health["enabled"]:
    #         lines.append("Use skills is off: saved helpers and save_skill are not injected into new runs.")
    #     lines.extend(health["issues"])
    #     for entry in health["skills"]:
    #         lines.append(f"\n{entry['name']} | version {entry['version']} | {entry['status']}\n{entry['validation']}")
    #         lines.append(entry.get("issue") or entry.get("path", ""))
    #     content.insert("1.0", "\n".join(lines))
    #     content.configure(state="disabled")
    #     dialog.bind("<Escape>", lambda event: dialog.destroy())

# ==== gui.py lines 1106-1107 (App._on_run, settings) ====
        # skills_enabled = bool(self.skills_var.get())
        # skill_library = SkillLibrary(enabled=skills_enabled)

# ==== gui.py line 1219 (App._on_run, make_executor arguments) ====
                            # skill_library=skill_library,

# ==== gui.py line 1443 (App._handle_event, "__threaddone__") ====
            # self._refresh_skill_health()

# ==== evaluate.py line 44 (imports) ====
# from skill_library import SkillLibrary

# ==== evaluate.py line 76 (_run_once, make_executor arguments) ====
        # skill_library=skill_library,

# ==== evaluate.py lines 224-225 (main, settings) ====
    # skills_enabled = os.environ.get("SKILLS", "1").lower() not in ("0", "false", "no")
    # skill_library = SkillLibrary(enabled=skills_enabled)

# ==== evaluate.py line 269 (main, _run_once arguments) ====
                # skill_library=skill_library,

# ==== run.py line 28 (imports) ====
# from skill_library import SkillLibrary

# ==== run.py lines 96-97 (main, settings) ====
    # skills_enabled = os.environ.get("SKILLS", "1").lower() not in ("0", "false", "no")
    # skill_library = SkillLibrary(enabled=skills_enabled)

# ==== run.py line 101 (main, make_executor arguments) ====
        # skill_library=skill_library,

# ==== experiment_recorder.py line 27 (CORE_FILES) ====
              # "skill_library.py",  # Archived, no longer imported by the agent.

# ==== experiment_recorder.py line 90 (RunTicket.observe, "output" event) ====
            # self.skill_saves += output.count("[skill saved]")

# ==== experiment_recorder.py line 101 (SweepRecorder.__init__) ====
        # self.library = library

# ==== experiment_recorder.py line 165 (SweepRecorder.start_run) ====
            # section = self.library.prompt_section() if self.library is not None else ""

# ==== kernel_executor.py line 117 (_Worker.__init__, priming request) ====
        # reply = self.request({"op": "prime", "skills": bool(skills)}, STARTUP_TIMEOUT)

# ==== kernel_executor.py line 212 (KernelCodeExecutor.__init__) ====
        # self.skill_library = skill_library

# ==== kernel_executor.py line 234 (KernelCodeExecutor._skills_enabled) ====
        # return getattr(self.skill_library, "enabled", False) is True

# ==== kernel_executor.py lines 241-244 (KernelCodeExecutor._start) ====
        # library = self.skill_library
        # if library is not None and self._skills_enabled():
        #     library.loaded = dict(worker.skill_loaded)
        #     library.load_issues = list(worker.skill_issues)

# ==== kernel_executor.py lines 259-260 (KernelCodeExecutor.skill_prompt_section) ====
        # lib = self.skill_library
        # return lib.prompt_section(loaded_only=True) if lib is not None else ""

# ==== kernel_worker.py line 91 (module state) ====
# LIBRARY = None

# ==== kernel_worker.py line 103 (_prime) ====
    # global LIBRARY

# ==== kernel_worker.py lines 108-114 (_prime, skill preloading) ====
    # if request.get("skills"):
    #     from skill_library import SkillLibrary
    #
    #     LIBRARY = SkillLibrary(enabled=True)
    #     NAMESPACE["save_skill"] = LIBRARY.make_save_skill(NAMESPACE)
    #     issues = LIBRARY.preload(NAMESPACE) or []
    #     loaded = LIBRARY.loaded
