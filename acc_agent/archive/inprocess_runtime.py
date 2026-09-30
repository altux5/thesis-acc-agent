"""Retired in-process runtime, archived verbatim on 2026-09-30. Not imported by anything.

The in-process ``CodeExecutor`` ran agent code with ``exec()`` inside the host process.
Its stateless mode only swapped the namespace dict, so imported modules, environment
variables, the working directory and files survived a "reset". It was retired on
2026-09-16 in favour of the kernel worker (``kernel_executor.py`` / ``kernel_worker.py``);
ledger rows from before then carry ``runtime_isolation = "inprocess-legacy"``.

Where to find the code:
- Live (uncommented) version: commit ``fa7b163`` (8 Sep 2026) of altux5/Thesis-initial.
- Commented-out in the live files: tags ``langchain-v1`` and ``stable-case-names`` of
  altux5/thesis-acc-agent. Each fragment header below gives the file and line range at
  ``stable-case-names``; the lines are copied unchanged, including indentation.
"""

# ==== executor.py line 10 (imports) ====
# import contextlib  # Retired in-process executor.

# ==== executor.py line 29 (module constants) ====
# RUNTIME_ISOLATION = os.environ.get("EXECUTION_RUNTIME", "kernel").strip().lower()

# ==== executor.py lines 121-250 (module level, after _BoundedOutput) ====
# Retired 2026-09-16: namespace resets retain process state. Kept for history only.
# class CodeExecutor:
#     """Executes Python code blocks and captures their printed output.
#
#     Parameters
#     ----------
#     stateful:
#         When True, variables persist across calls (the thesis contribution).
#         When False, every call starts from a fresh namespace (the baseline).
#     output_char_limit:
#         Execution output longer than this is truncated before being returned,
#         so the model's context window does not blow up.
#     skill_library:
#         Archived compatibility argument, ignored. Cross-run skills are excluded
#         from the thesis evaluation; ordinary within-run functions still work.
#
#     Attributes
#     ----------
#     reported_labels:
#         The most recent successfully committed ``{GlobalId: label}`` mapping.
#         A code failure invalidates it. A successful block without a new report
#         cannot restore it. Valid submissions survive stateless namespace resets.
#     """
#
#     def __init__(
#         self,
#         stateful: bool = True,
#         output_char_limit: int = 6000,
#         skill_library: object | None = None,
#     ) -> None:
#         if not isinstance(output_char_limit, int) or output_char_limit < 1:
#             raise ValueError("output_char_limit must be a positive integer")
#         self.stateful = stateful
#         self.output_char_limit = output_char_limit
#         # self.skill_library = skill_library
#         self.skill_library = None
#         # Whether the last executed block raised (used to flag it in the trace).
#         self.last_error = False
#         self.last_execution: dict = {}
#         # The agent's latest per-element labelling, via report_labels(). Survives
#         # a namespace reset, so a stateless run can still report one.
#         self.reported_labels: dict[str, str] = {}
#         self.label_reports = 0
#         self.labels_valid = False
#         self._pending_labels: dict[str, str] | None = None
#         self._pending_label_reports = 0
#         self.skill_load_issues: list[str] = []
#         self._pending_skill_warnings: list[str] = []
#         self._namespace: dict[str, object] = {}
#         self._prime_namespace()
#
#     def _make_report_labels(self):
#         """Build the ``report_labels`` builtin bound to this executor."""
#
#         def report_labels(mapping: dict) -> str:
#             """Record the outcome of every anchor element the rule judges.
#
#             Each call *replaces* the previous labelling, so the agent always has
#             one authoritative answer rather than an accumulation of stale ones.
#             """
#             cleaned = normalise_label_map(mapping)
#             self._pending_labels = cleaned
#             self._pending_label_reports += 1
#             return format_label_receipt(cleaned)
#
#         return report_labels
#
#     def _prime_namespace(self) -> None:
#         """Inject the reporting builtin; cross-run skills are retired."""
#         self._namespace["report_labels"] = self._make_report_labels()
#         self.skill_load_issues = []
#         # lib = self.skill_library
#         # if lib is not None and getattr(lib, "enabled", False):
#         #     self._namespace["save_skill"] = lib.make_save_skill(self._namespace)
#         #     self.skill_load_issues = lib.preload(self._namespace) or []
#         #     self._pending_skill_warnings = list(self.skill_load_issues)
#
#     def skill_prompt_section(self) -> str:
#         # lib = self.skill_library
#         # return lib.prompt_section(loaded_only=True) if lib is not None else ""
#         return ""
#
#     def run(self, code: str) -> str:
#         """Execute *code*, returning captured stdout+stderr (or a traceback)."""
#         self._pending_labels = None
#         self._pending_label_reports = 0
#         self.last_error = False
#         self.last_execution = {}
#         buffer = _BoundedOutput(self.output_char_limit)
#         error_text = ""
#         try:
#             with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
#                 if not self.stateful:
#                     self._namespace = {}
#                     self._prime_namespace()
#                 for warning in self._pending_skill_warnings:
#                     buffer.write(f"[skill load warning] {warning}\n")
#                 self._pending_skill_warnings = []
#                 exec(code, self._namespace)  # noqa: S102 - intentional: this is the REPL
#         except BaseException as exc:
#             self.last_error = True
#             self.reported_labels = {}
#             self.labels_valid = False
#             error_text = format_agent_traceback(exc)
#             if not isinstance(exc, (Exception, SystemExit)):
#                 raise
#         else:
#             if self._pending_labels is not None:
#                 self.reported_labels = self._pending_labels
#                 self.label_reports += self._pending_label_reports
#                 self.labels_valid = True
#         finally:
#             self._pending_labels = None
#             self._pending_label_reports = 0
#             self.last_execution = {
#                 "error": self.last_error, "error_text": error_text,
#                 "truncated": buffer.dropped_chars > 0,
#                 "output_dropped_chars": buffer.dropped_chars,
#                 "labels_valid": self.labels_valid,
#             }
#
#         output = buffer.getvalue().strip() or "(code ran with no output)"
#         if buffer.dropped_chars:
#             output += f"\n... [truncated {buffer.dropped_chars} characters]"
#         if error_text:
#             output += "\n\n" + error_text
#         return output
#
#     def close(self) -> None:
#         """No-op; present so callers can treat both runtimes the same way."""

# ==== executor.py lines 265-280 (inside make_executor) ====
    # choice = (runtime or RUNTIME_ISOLATION).strip().lower()
    # if choice in ("kernel", "subprocess", "worker"):
    #     return KernelCodeExecutor(
    #         stateful=stateful,
    #         output_char_limit=output_char_limit,
    #         skill_library=skill_library,
    #     )
    # if choice not in ("inprocess", "in-process", ""):
    #     raise ValueError(
    #         f"Unknown EXECUTION_RUNTIME {choice!r}; expected 'inprocess' or 'kernel'"
    #     )
    # return CodeExecutor(
    #     stateful=stateful,
    #     output_char_limit=output_char_limit,
    #     skill_library=skill_library,
    # )

# ==== gui.py lines 73-83 (module constants) ====
# KERNEL_LABEL = "kernel"
# INPROCESS_LABEL = "in-process"
# RUNTIME_CHOICES = {"kernel": KERNEL_LABEL, "inprocess": INPROCESS_LABEL}
# RUNTIME_NOTES = {
#     KERNEL_LABEL: "Code runs in a separate process. Stateless restarts it per block, "
#                   "so modules, environment and files really do not carry over. "
#                   "Timeouts and crash containment apply.",
#     INPROCESS_LABEL: "Legacy runtime, retained to reproduce runs from before 2026-09-08. "
#                      "Stateless only swaps the namespace dict: imported modules, "
#                      "environment and files survive the reset.",
# }

# ==== gui.py lines 357-369 (App.__init__, runtime selector after "Session mode") ====
        # label("Execution runtime")
        # self.runtime_var = tk.StringVar(value=RUNTIME_CHOICES.get(RUNTIME_ISOLATION, KERNEL_LABEL))
        # self.runtime_control = ctk.CTkSegmentedButton(
        #     bar, values=list(RUNTIME_CHOICES.values()), variable=self.runtime_var,
        #     command=self._on_runtime, selected_color=PRIMARY, selected_hover_color=HOVER,
        #     unselected_color=SURFACE, unselected_hover_color=HOVER, fg_color=SURFACE,
        #     text_color=TEXT, height=32, corner_radius=4,
        # )
        # self.runtime_control.pack(fill="x", padx=10, pady=(0, 2))
        # self.runtime_note = ctk.CTkLabel(bar, text="", font=("Segoe UI", 11), text_color=MUTED,
        #     wraplength=250, anchor="w", justify="left")
        # self.runtime_note.pack(fill="x", padx=10, pady=(0, 6))
        # self._on_runtime()

# ==== gui.py line 590 (App._set_settings_enabled, widget list) ====
                       # self.runtime_control,

# ==== gui.py lines 594-602 (App methods) ====
    # def _runtime_choice(self) -> str:
    #     return "inprocess" if self.runtime_var.get() == INPROCESS_LABEL else "kernel"
    #
    # def _on_runtime(self, _value: str | None = None) -> None:
    #     label = self.runtime_var.get()
    #     self.runtime_note.configure(
    #         text=RUNTIME_NOTES[label],
    #         text_color=MUTED if label == KERNEL_LABEL else ORANGE,
    #     )

# ==== gui.py line 1109 (App._on_run, settings) ====
        # runtime = self._runtime_choice()

# ==== gui.py line 1166 (App._on_run, log header) ====
            # f"{'  (separate worker process; stateless restarts it per block)' if runtime == 'kernel' else '  (legacy in-process namespace swap; a stateless reset leaves modules, environment and files in place)'}\n"

# ==== gui.py line 1202 (App._on_run, SweepRecorder arguments) ====
                    # runtime=runtime,

# ==== gui.py line 1220 (App._on_run, make_executor arguments) ====
                            # runtime=runtime,

# ==== experiment_recorder.py lines 135-136 (SweepRecorder.__init__, configuration) ====
                # "runtime_isolation": runtime or RUNTIME_ISOLATION,
                # "runtime_isolation_note": "inprocess: stateless resets the namespace dict only, so modules/env/cwd/files persist; kernel: stateless restarts the worker process. Never pool the two.",

# ==== experiment_recorder.py line 143 (SweepRecorder.__init__, end of kernel_settings) ====
                # } if (runtime or RUNTIME_ISOLATION).strip().lower() in ("kernel", "subprocess", "worker") else None,

# ==== check_runtime_parity.py line 21 (imports) ====
# from executor import CodeExecutor

# ==== check_runtime_parity.py lines 53-67 (in-process vs kernel block comparison) ====
# def compare_blocks(stateful: bool, limit: int) -> list[str]:
#     problems = []
#     inproc = CodeExecutor(stateful=stateful, output_char_limit=limit)
#     kernel = KernelCodeExecutor(stateful=stateful, output_char_limit=limit, timeout=60)
#     try:
#         for name, code in BLOCKS:
#             left, right = inproc.run(code), kernel.run(code)
#             if left != right:
#                 problems.append(f"[{name}] output differs\n  in-process: {left!r}\n  kernel:     {right!r}")
#             if observe(inproc) != observe(kernel):
#                 problems.append(f"[{name}] state differs\n  in-process: {observe(inproc)}\n  kernel:     {observe(kernel)}")
#     finally:
#         inproc.close()
#         kernel.close()
#     return problems

# ==== check_runtime_parity.py lines 163-192 (in-process vs kernel on the mall slabs) ====
# def compare_real_model() -> list[str]:
#     problems = []
#     case = ground_truth.load(
#         Path(__file__).resolve().parent / "ground_truth" / "slab_thickness__mall_v2.json")
#     ifc = case.resolve_ifc()
#     code = CLASSIFY.format(ifc=ifc)
#     results = {}
#     for name, executor in (("in-process", CodeExecutor(stateful=True)),
#                            ("kernel", KernelCodeExecutor(stateful=True, timeout=600))):
#         try:
#             output = executor.run(code)
#             if executor.last_error:
#                 problems.append(f"[{name}] classification raised:\n{output[-800:]}")
#             results[name] = dict(executor.reported_labels)
#         finally:
#             executor.close()
#     if results.get("in-process") != results.get("kernel"):
#         left, right = results.get("in-process", {}), results.get("kernel", {})
#         differing = [k for k in set(left) | set(right) if left.get(k) != right.get(k)]
#         problems.append(f"label maps differ on {len(differing)} elements, e.g. {differing[:5]}")
#     reference = case.labels
#     produced = results.get("kernel", {})
#     if set(produced) != set(reference):
#         problems.append(f"anchor set differs from reference: produced {len(produced)}, reference {len(reference)}")
#     counts: dict[str, int] = {}
#     for value in produced.values():
#         counts[value] = counts.get(value, 0) + 1
#     agree = sum(1 for k, v in produced.items() if reference.get(k) == v)
#     print(f"  mall slabs: {len(produced)} labels {counts}, {agree} agree with the reference")
#     return problems

# ==== check_runtime_parity.py lines 217-237 (former parity entry point) ====
# def main() -> int:
#     failures = []
#     for stateful in (True, False):
#         label = "stateful" if stateful else "stateless"
#         print(f"Comparing {len(BLOCKS)} blocks, {label} ...")
#         found = compare_blocks(stateful, 6000)
#         print(f"  {'OK' if not found else str(len(found)) + ' DIFFERENCES'}")
#         failures += found
#     print("Comparing truncation behaviour at a 60-character cap ...")
#     found = compare_blocks(True, 60)
#     print(f"  {'OK' if not found else str(len(found)) + ' DIFFERENCES'}")
#     failures += found
#     print("Replaying a real classification over the mall IFC ...")
#     found = compare_real_model()
#     print(f"  {'OK' if not found else str(len(found)) + ' DIFFERENCES'}")
#     failures += found
#     if failures:
#         print("\nDIFFERENCES FOUND:\n" + "\n".join(failures))
#         return 1
#     print("\nThe two runtimes agree on every checked observable.")
#     return 0

# ==== tests/test_executor.py lines 65-67 (test_keyboard_interrupt_restarts_worker_and_invalidates_labels) ====
        # The retired in-process executor propagated KeyboardInterrupt to the host.
        # with self.assertRaises(KeyboardInterrupt):
        #     executor.run('raise KeyboardInterrupt()')

# ==== tests/test_kernel_executor.py line 26 (imports) ====
# from executor import CodeExecutor, make_executor  # Retired runtime.

# ==== tests/test_kernel_executor.py lines 105-109 (isolation tests) ====
    # def test_inprocess_stateless_leaks_what_the_kernel_does_not(self):
    #     executor = CodeExecutor(stateful=False)
    #     executor.run("import os\nos.environ['ACC_INPROCESS_PROBE'] = 'leaked'")
    #     self.addCleanup(os.environ.pop, "ACC_INPROCESS_PROBE", None)
    #     self.assertIn("leaked", executor.run("import os\nprint(os.environ.get('ACC_INPROCESS_PROBE'))"))

# ==== tests/test_kernel_executor.py lines 480-489 (parity tests) ====
    # def test_identical_output_and_state_for_the_same_blocks(self):
    #     for stateful in (True, False):
    #         for limit in (6000, 60):
    #             inproc = CodeExecutor(stateful=stateful, output_char_limit=limit)
    #             kernel = KernelCodeExecutor(stateful=stateful, output_char_limit=limit, timeout=60)
    #             self.addCleanup(kernel.close)
    #             for code in self.CASES:
    #                 with self.subTest(stateful=stateful, limit=limit, code=code[:30]):
    #                     self.assertEqual(inproc.run(code), kernel.run(code))
    #                     self.assertEqual(self.observed(inproc), self.observed(kernel))
