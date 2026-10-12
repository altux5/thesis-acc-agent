# Project notes

Running memory for this project: findings, decisions, pitfalls and changes.
Mirrors the repo memory file at `/memories/repo/acc_agent.md`.

**Current scope (2026-09-17): LangChain create_agent, kernel-only execution, H1/H2.**
The lean migration is implemented; read [instruction.md](instruction.md) before work.
Cross-run skills and H3 are unavailable in new runs. Their archives remain unchanged.
The main comparison is iterative stateless versus iterative stateful execution on
the same worker runtime, without a persistent skill library. Earlier instructions
to select the in-process runtime or enable skills are historical and superseded
by the dated decisions and changelog entries.

**How to use:** append short bullets, newest first inside each section. Add a dated
entry to the Changelog for anything that changes behaviour or numbers. Keep it
terse; this file is read before work starts, so length costs.

**Case names (decision 2026-09-30, user):** a case ID names the check and never
changes; the current reference owns the plain ID. No `_v2`/`_full`-style tags. An
update keeps the old file as `<case_id>_deprecated_v<N>` (oldest N=1, never
renumbered or reused), sets `supersedes`, and writes the new reference under the
same ID. The GUI hides deprecated cases. Rules in [instruction.md](instruction.md).
Earlier entries below use the old names; the mapping is
`ground_truth.RENAMED_BEFORE_2026_09_30`.

**Design history (where each stage's code lives):**
- 8 Sep: pre-LangChain custom loop, live in-process executor and skills: commit `fa7b163`
  of altux5/Thesis-initial (the `tez` repository).
- 16-17 Sep: in-process runtime and cross-run skills retired: `archive/inprocess_runtime.py`,
  `archive/skill_integration.py` (verbatim, with source line ranges).
- 22 Sep: LangChain create_agent (`langchain-codeact-v1`), kernel only: tag `langchain-v1`
  of altux5/thesis-acc-agent.
- 30 Sep: `langchain-codeact-v2`, completion checks v3, write confinement, usable_2
  references, stable case IDs, dashboard: tag `stable-case-names`.
- 1 Oct: `langchain-codeact-v3` (visible budget, wrap-up reminder, no-tool-call replies
  returned to the model, ifcopenshell submodules pre-imported). Not yet tagged.
- 1 Oct: `langchain-codeact-v4` + completion checks v4 (PENDING placeholder label,
  last call offers only FinalReport). Not yet tagged.
- 2 Oct: `langchain-codeact-v5` (last call keeps the full tool list; final-report-only is
  enforced by rejection, which keeps the prompt cache). Not yet tagged.

**Agent improvement plan (decision 2026-10-01, user):** fix harness mechanics before
strategy, one protocol version per step so the dashboard separates effects. Step 1 =
v3 (above). Step 2, still open: code-first evaluation with output by exception, H2
planning on multi-criteria rules, cross-checking decisive evidence. No case-specific
hints and no bigger budget as a fix. The worker does NOT preload the IFC `model`:
model loading stays the agent's job so "what the agent keeps" remains the measured
variable; preloading in both modes would be a separate, labelled experiment.

---

## Environment and paths

- BCA test drops (`bca_tests-main/`, `bca_tests-harness_improvements/`) live under
  `tez/gitignore/`, **not** the workspace root.
- All model paths must go through `ground_truth.resolve_model_path()` (tries
  `WORKSPACE_ROOT`, then `WORKSPACE_ROOT/gitignore`).
  Never join `WORKSPACE_ROOT / ifc_rel` directly. That pattern was the bug.
- Ground-truth JSONs in `ground_truth/` store a **workspace-relative** `ifc_path`,
  resolved via `GroundTruth.resolve_ifc()`.
- `evals/`, `logs/`, `runs/`, `langfuse_traces/` contain absolute old paths. They are
  write-only records; do not read paths back out of them.
- `openpyxl` is missing in the default interpreter, so `import_bca_gt.py` will not
  import there. Use the venv (`requirements.txt` has it).
- Env toggles: `ENV_PRIMER=0` (no environment primer),
  `REASONING=0` (no thinking blocks), `PROVIDER=minimax|openrouter`, `MODEL=...`,
  `EXEC_TIMEOUT=<seconds>` (default 600), `EXEC_STARTUP_TIMEOUT=<seconds>` (default 60),
  `EXEC_HASH_SEED=<value>` (default `0`; pinned so set iteration order is deterministic
  across workers — leave it free only if you deliberately want that variance).
- Retired settings: `SKILLS` and `SKILLS_DIR` do not activate skills in application
  runs. The archived standalone library still uses `SKILLS_DIR` in its tests.
- `EXECUTION_RUNTIME` is also retired and ignored. All new runs use the kernel;
  explicit `make_executor(runtime="inprocess")` calls raise a retirement error.
  The GUI has no runtime selector. Stateful/stateless selection remains available.
- Langfuse is optional. With no `LANGFUSE_*` keys, `tracing.py` is a no-op.

## Known pitfalls

- **Case usability is not physical certification.** The 2026-09-17 catalogue
  audit found twelve cases to hold out; source reproduction alone misses bad
  measurement assumptions. GUI tiers are selection guidance, separate from the
  recorder's live audit and default database comparison filter. Neither green
  usability nor successful completion proves general regulatory correctness.
- **A health suite can be token-heavy.** Eight cases in both modes are 16 runs
  per repeat, or 48 runs with three repeats. The GUI requires paid-run confirmation,
  shows the maximum model-call count, and tracks known input/output usage. This is
  not a hard token or money cap; missing provider usage remains unknown. Stop
  takes effect after the current run, not immediately within a model request.
- **LangChain budget and thinking differ from the legacy loop.** All model calls,
  including the plan and final reports, count toward max_iterations; no extra
  finalization allowance. Anthropic's integration drops forced tool selection when
  thinking is enabled. Do not patch this with Markdown execution or guessed finals;
  unsupported completion stays incomplete. Only thinking-off MiniMax was tested live.
- **Historical in-process results must not be pooled with kernel results.** The
  retired executor reset only a namespace, leaving modules, environment, cwd and
  other process state intact. Its class and selection branches are archived in
  `archive/inprocess_runtime.py`, not aliased to the kernel. New runs always record `runtime_isolation=kernel`;
  older rows retain their identities, including the inferred `inprocess-legacy`
  value where runtime was not recorded. Both current modes replay the transcript.
  Statelessness means a fresh interpreter, not erased conversation/external files.
- **Never patch `threading.Thread` globally around kernel construction.** The worker's
  reader must be a real background thread; if a test double runs it inline the protocol
  deadlocks with no output. `kernel_executor` binds `Thread` at import and `executor`
  imports it eagerly for exactly that reason. `test_gui_presentation` patches
  `gui.threading.Thread`, which resolves to the global module attribute; the regression
  is covered by `test_survives_a_caller_patching_threading_thread`.
- **The kernel is containment, not a sandbox.** The worker runs as the same user with
  the same filesystem access and can still read `ground_truth/`, the SQLite DB and a
  `.env` file. Each worker gets a private temp directory as its cwd and `TEMP`. Since
  2026-09-30 an audit hook refuses Python-level writes outside it (`open` in write
  modes, `os`/`shutil` mutations, moves out); native extension writes are not covered
  and reads are unrestricted. Known API-key-shaped env vars and all `PYTHON*` vars are dropped from
  its environment, which reduces exposure without preventing it. Native writes to fd 1
  are redirected to stderr rather than captured (same as in-process, where they went to
  the console). The host's imported-code fingerprint cannot attest what the worker ran,
  because the worker compiles its own copy; only disk hashes of `kernel_*.py` are
  recorded.
- **A kernel restart discards the run's state, and that must stay visible.**
  Timeout, worker death, protocol error and a fatal exception all restart the worker and
  set `last_execution["kernel_restarted"]` plus a `restart_reason`. The model is told in
  the returned text so it stops inventing explanations for sudden `NameError`s, and the
  flags flow to the trace, the GUI log and the factual report. A restart always comes
  with `error: True`, so error counts do not undercount it. In-process runs omit the
  keys entirely rather than reporting a misleading `false`.
- **A kernel restart discards the run's state, and that must stay visible.**
  Timeout, worker death, protocol error and a fatal exception all restart the worker and
  set `last_execution["kernel_restarted"]` plus a `restart_reason`. The model is told in
  the returned text so it stops inventing explanations for sudden `NameError`s, and the
  flags flow to the trace, the GUI log and the factual report. A restart always comes
  with `error: True`, so error counts do not undercount it. In-process runs omit the
  keys entirely rather than reporting a misleading `false`.
- **Run `python acc_agent/check_runtime_parity.py` after touching execution code.**
  The historical filename is retained; this is now a kernel-only contract check.
  It checks 15 blocks against expected output/reporting in both modes at two caps,
  verifies interpreter and scratch-state persistence/reset, and compares mall slab
  labels with the v2 reference in both modes. The old parity code is in `archive/inprocess_runtime.py`.
- **Self-tested skills are not independently verified.** Skill globals and copied
  fixtures are isolated, but execution is still in-process: imported module state
  and external side effects are not sandboxed. Tests are required and retained,
  but cannot establish correctness on untested inputs or other IFC exporters.
- **Pooling is exact-configuration only.** SQLite stores code/rule/reference/IFC
  hashes and starting skill fingerprints. Default comparisons exclude skills-on,
  H3 training, unreviewed/invalid references and changed contexts. Do not interpret
  a zero-FAIL control's F1 as evidence of violation detection.
- **Completion v2 is structural, not semantic validation.** It verifies a label
  submission, exact public IFC class scope where supported, and verdict/FAIL-set
  consistency. It cannot prove the agent measured correctly. Custom scopes can be
  unverified; UNKNOWN is abstention, not completion. Old runs lack this contract.
- **Slab pilot is now `slab_thickness__mall_v2`.** 100 PASS / 12 ALERT / zero FAIL.
  The original ID is retained unchanged and marked legacy-invalid. V2 is a control
  for coverage, missing data and false positives, not violation recall.
- **Captured output is bounded at the configured character cap.** The executor
  appends `[truncated N characters]` and keeps a separate traceback (max6000chars).
  New logs/DB use structured error/truncation flags. Legacy logs use text fallback.
  This does not limit arbitrary code allocation, CPU time or filesystem effects.
- **Staircase hard case is now `staircase_width_v8_full`.** All 59 stairs are
  labelled (26 PASS / 23 FAIL / 6 NA / 4 MANUAL_CHECK). The 49-stair subset case
  `staircase_width_v8` is unchanged, marked Review/superseded, and keeps its
  `annotated-subset-v1` scoring for historical comparisons. Never pool the two.
  The full case's rule states E.2.1/E.2.4 plus the reference checker's manual-check
  and width conventions; those conventions are benchmark policy, not regulation.
- **The full staircase audit does not recompute geometry.** `audit_case` checks the
  recorded evidence against the workbook, adjudications and IFC hash in seconds.
  Geometry regeneration loads ~620k triangles (railings dominate) and takes about
  two minutes: run `python acc_agent/stair_width_reference.py --check` after
  changing the builder or model files.
- **Harness level 3 leaks.** The run is scored against the case it is being graded on.
  Those results carry `feedback_leakage: true` and are **train numbers only**. Levels
  1 and 2 are leakage-free.
- **F1 alone is misleading at low violation rates.** `doors_windows_storey__condo` is
  4 fail in 212 anchors; a run that inspects 5 elements can post F1 = 1.00. Always
  report union accuracy alongside.
- Runs with no `report_labels(...)` call report `A∪ = n/a` and are *excluded* from the
  average, not scored as zero.
- Abstention (`UNKNOWN`) reports no violations, which makes precision vacuously 1.0.
  Tracked separately as `abstained`.

## Findings

- **2026-10-04 - Sonnet 5.5 on staircase_width_v8 (2 stateful v5 runs).** Both complete,
  0.95 and 0.97 (MiniMax: 0 of 6 v1/v2 runs completed; no v3+ runs). 18 and 20 calls
  (r1 finished on its last call), 543k/714k input at 91-92% cache, $0.45/$0.54, 12-13
  min. Errors are exemption rows (NA labelled FAIL/PASS: a stair inside a residential
  unit, a 2-riser stair, an attic stair) plus one FAIL labelled PASS (...pN).

- **2026-10-04 - Sonnet 5.5 on the exit cases (5 runs, OpenRouter, reasoning off).** All
  complete in 7-13 calls (MiniMax 16-20), 1-3.4 min, $0.13-0.31 per run, cache reads
  80-86%, no tool-less replies. scdf_3: 1.00 and 0.75 (r2 labelled shops 296/297 and
  office 298 FAIL although its own reason says each has its own exit). scdf_5: 0.67,
  0.54, 0.56, i.e. near the reachable ceiling: 12 of the 39 scored rows disagree with
  the reference in 7 of 8 complete v5 runs of both models. Seven offices with one exit
  to a reception are NA in the reference via the authority's transitional-space
  exemption, which the rule text does not state; three receptions are PASS although
  the prompt says common areas "may" be NA; the two tenant-internal corridor FAILs
  (...LH9, ...LK5) are the interpretation the reference itself lists as a limitation.
  A run that reads these consistently scores at most 27/39 = 0.69, so scdf_5 does not
  separate the models. Needs a decision on the case text or reference, not an agent fix.

- **2026-10-03 - v5 usable_2 suites on OpenRouter (30 stateful runs on 2 Oct, 30
  stateless on 3 Oct).** Both 29/30 complete (v3: 74%); exit cases 5/6 complete in each.
  Stateful 6.1M input / 0.33M output, $0.96, 3.2 h; stateless 7.1M / 0.49M, $1.26,
  2.0 h; cache reads about 84% in both. Replaying two slow stateful runs' code took
  0.6 of 27.7 min and 0.2 of 13.0 min, so wall time is model latency. Stateless:
  16 of 438 calls hit `MAX_TOKENS` (8000) with empty content and no tool call; the
  reasoning had degenerated into repetition loops (e.g. "Look at placement.</parameter>"
  repeated). These calls used 128k output tokens and $0.19, and each cost one budget
  call (the harness returned them to the model). All 30 OpenRouter length stops since
  2026-09-30 came from the upstream without a `system_fingerprint`; none in 529 calls
  from the vLLM upstream or in 590 MiniMax-direct calls. OpenRouter's upstream provider
  name is not recorded. Accuracy as before, except exit scdf_3 stateless r3 complete at
  0.17 and space elevation mall stateless 0.93 in 2 of 3 runs.
- **2026-10-02 - token use (first 6 v4 runs, all landing cases, MiniMax direct).** 1.48M
  input / 55k output tokens, in line with v3 on the same cases (108-315k input per hard
  run; easy cases 15-50k). Every call resends the conversation (1.9k -> 32.7k prompt
  over 20 calls), so long runs grow superlinearly; about 88% was cache reads. Since
  2026-10-01 10:38 the GUI runs used the `minimax` provider, which reports no cost, so
  the ledger shows $0. v4 side effect: restricting the tool list on the last call broke
  the prompt cache (32.7k prompt, 1.1k cached), doubling that run's uncached input.
- **2026-10-01 - effect of v3 (46 stateful usable_2 runs vs 37 v2 runs, same cases).**
  Completion 65% -> 74% (without the two exit cases 74% -> 92%: landing mall 1/3 -> 5/6,
  space elevation mall 1/3 -> 3/3, landing v8 3/5 -> 5/6, planter 2/3 -> 3/3, tread mall
  5/6 -> 6/6); accuracy unchanged. util.unit/element import errors 11 -> 0; 10
  no-tool-call replies returned to the model, 3 of those runs completed. The wrap-up
  reminder was ignored: all 11 budget-exhausted v3 runs kept running code on calls
  17-20 (10 already had full labels) and never tried FinalReport. Side effect: 4 of 44
  labelled runs ended with provisional ALERT/MANUAL_CHECK where the reference differs
  (58 labels; e.g. landing mall's 16 trap flights). Exit cases still fail. Two suites
  were interrupted: OpenRouter returned `provider_unavailable` without `choices`
  (the SDK raised ResponseValidationError; retries are off, suites stop on errors),
  then a local connection loss.
- **2026-10-01 - why the hard cases fail (141 LangChain runs analysed).** Eleven cases
  complete about 95% of runs in 4-15 calls; seven (staircase width, exit scdf_5/scdf_3,
  landing mall/v8, space elevation mall, planter) need 14-20 of 20 calls and 136-332k
  input tokens. 23 of 30 incomplete runs hit the budget. (1) Late commitment: 16
  incomplete runs had valid labels, 14 of them committed in call 20 itself, leaving no
  call for FinalReport; the budget was never shown before the last call. (2) Python used
  as a viewer: hard runs print element listings in 5.2 blocks per run, 35k output
  characters and 2.6-3.7 truncations per run; the model then labels in its reasoning
  ("Stair 0: SPIRAL, 2199mm, PASS ...") and pages through truncated output. (3) Stateful
  runs reopen the IFC in 43% of later blocks (latest staircase run: every block), so the
  persistence under test is barely used. (4) 40 of the AttributeErrors were
  `ifcopenshell.util.unit` not loaded, a primer defect; others are wrong attribute names
  or relationship directions. (5) Completed-but-wrong runs trust one recorded value
  (landing mall: flight `NumberOfRiser` 27 is the staircase total; staircase: flight
  extent as clear width). (6) Two MiniMax replies carried tool syntax as plain text and
  ended the run.
- **2026-09-29 - usable_2 suite, stateless (after completion v3 and write confinement;
  30 runs, 17 complete, 2 abstained, 11 incomplete).** All runs used the new prompt.
  One early UNKNOWN was rejected (exit scdf_3 r3). The write hook refused one
  `os.replace` of the benchmark IFC into temp (exit scdf_3 r2); the model file is
  intact. **New failure:** twice (landing mall r1 at call 11, tread mall r1 at call 3)
  MiniMax returned its native tool-call syntax as plain text with `stop`; the loop
  treated it as a final answer and ended the run with calls left, and the issue text
  wrongly blames the budget. Budget caused the other 9 incomplete runs, including all
  exit runs. Space elevation scdf_3 complete runs now score 1.00 with the fixed
  reference. The landing traps held (mall r3, scdf_5 r1/r3). Headroom r2 said 1800 mm
  fails but submitted 0 FAILs; planter r2's reason contradicts its labels.
- **2026-09-29 - first usable_2 suite (OpenRouter minimax-m3, H1, stateful only,
  3 repeats, 20 calls; 30 runs, 20 complete, ~$0.68, 84 min).** Harness recorded
  everything (all audits `evidence-checked`, no context changes). Door headroom 3/3
  exact; tread mall 2/3 exact (r1 read "single riser" as "single tread"); landing v8
  finds all 28 FAILs but misses the attic/single-step E.2.4/E.2.1 NAs; scdf_5
  landing trap caught the agent 3/3 (6 false FAILs); mall trap: 1 run FAIL, 2 runs
  ALERT; exit scdf_5 0/3 labelled (budget; boundary API errors); planter L-shape
  judged by bounding box 2/2, plus one premature UNKNOWN after one code block that
  the completion gate accepted. **Reference defect:** 2 scdf_3 "Area" spaces
  (NOTDEFINED but carrying SGPset_SpaceArea_GFA) are GFA objects; the agent's NA is
  right, the reference FAIL is not. Side channel still open: runs wrote
  `%TEMP%\flights.json` and `Documents\cache_planter.pkl` via absolute paths.
  Budget exhaustion caused 8 of the 10 incomplete runs, twice with correct labels.

- **2026-09-29 - usable_2 build and second verification (offline, no paid runs).**
  - The earlier landing estimate was superseded: geometric riser counts have a +-1
    arrival ambiguity, so the builder uses (low, high) bounds; v8 is 28 FAIL /
    20 PASS / 19 NA. v8 and scdf_5 stair-level `NumberOfRiser` equals the sum of
    chosen flight counts on every stair; mall's four 27-total stairs use geometric
    upper bounds (sum 28-29, every flight <= 12, outcome robust).
  - The OBOS model records `OwnerBuiltOwnerStay = TRUE`: E.2.4(d) exempts every
    staircase, so its landing/tread cases cannot be repaired (would be all NA).
    **Condo also records TRUE**; under E.2.4(d) its stairs are exempt from riser
    and tread rules. The Usable `tread_width_e342__condo` rule instead states "all
    staircases are common" and omits E.2.4, so it is a recorded-property task, not
    a regulatory one. Likewise the only FAIL of Usable `riser_height_e341__stair_v8`
    (`38SnC...Sxe`, 200 mm) is an attic stair the expert exempts under E.2.4(c).
    Health-suite cases were deliberately left unchanged; decide before reporting.
  - Mall treads: every tread measured; tapered treads at 500 mm from the narrow end
    (`0yAK...LzTF` 281 mm, near the 275 mm limit; spiral 255 mm). Stair-level
    `TreadLength` gives the same outcome for every judged flight.
  - Mall headroom spaces are NOT usable: 118/123 expert values equal the modelled
    IfcSpace height, ramps at 1.3-1.6 m above parking places/an office and a beam
    at 1.6 m in a kitchen are labelled PASS, and the one FAIL is not reproduced.
  - Mall door headroom follows the authority's ClearHeight convention exactly; the
    test model sets ClearHeight independently of leaf size (4 PASS doors 1800 mm
    high, 3 FAIL doors 2100-2400 mm), so the convention is stated in the rule.
  - Planter: re-measured widest strip (maximum inscribed circle) and communal
    overlap agree with every expert row. Expert depths exceed the mesh height, but
    no label depends on which reading is used.
  - Space elevation: placement origins differ from geometric bottoms for most FAIL
    spaces (Revit base offsets), so the rule states "bottom of the modelled volume".
  - EC3 rules not added: E.3.4.4 uniform risers/treads (one plausible violation in
    all models; end risers are not measurable from flight meshes); large spaces
    >= 50 m2 with 2 doors (door/opening counting and area source ambiguous, 26/40
    mall spaces would fail); stair-slab connection (partial models, adjacency needs
    adjudication); the remaining catalogue rules need the paper's models or ADA data.

- **2026-09-29 - repairability review of non-suite cases (read-only, no labels changed).**
  Provenance: simple_rules.py cases take rule choice from the EC3-2026 paper
  (studies/) with BCA V7.08 clauses and coded single-property references; the four
  import_bca_gt.py cases come from the advisors' `analysis/gt_comparison/*.xlsx`
  (expert CSV joined to candidate output; `requirement` truncated to 300 chars by
  `build_gt_comparison.py`, which is why exit access is cut off). BCA Template
  xlsx files are blank row lists but define each clause's authority scope.
  - Landing E.3.5.2: flight meshes confirm v8/OBOS single-flight straight stairs
    with 24 recorded risers really have 23 modelled treads over 3833 mm (genuine
    FAIL); spirals should be NA. Mall/scdf_5 FAILs are stair totals on 4/2-flight
    stairs (flights have 1-12 risers). Repair: per-flight count, spiral NA.
    v8 becomes about 25 PASS / 30 FAIL / 12 NA (3 flights with 19 recorded and 18
    modelled risers, plus 3 PASS flights with >18 levels, need adjudication).
  - Tread mall: 46/78 flights agree with step-centroid geometry; 30 short/winder
    flights unmeasured by that method; spiral centroid 281 vs recorded 250.
    v8/OBOS treads are all 250-260 mm, so their outcome depends only on the
    assumed building type (v8 mixes residential, industrial and cinema spaces).
  - Slab (non-mall): exporters disagree across Depth, explicit thickness and mesh
    (condo roofs Depth 100 vs mesh 50; OBOS landing Depth 1200 vs mesh 201;
    scdf models have no explicit thickness). Not repairable without per-model
    adjudication of an arbitrary BIM range.
  - Exit scdf_5: the 39 labelled spaces are exactly the template rows; the other
    84 are corridors, exit stairs, lobbies and duplicate-named rooms. Full clause
    is in the template. scdf_3 has 12 template rows, all PASS.
  - Planter: expert messages state all four criteria and measured values.
  - Headroom: door rows follow SGPset ClearHeight=2000; 8 condo and 4 mall PASS
    doors have OverallHeight/mesh 650-1980 mm. Mall sheet has complete labels
    (each row duplicated blank): doors 154 P / 3 F, spaces 118 P / 56 NA / 1 F.

- **2026-09-29 - first paired health suites (OpenRouter minimax-m3, H1, 20 calls,
  3 repeats).** Stateful 21/21 complete, stateless 20/21 (one plain-text final
  answer with correct labels); every labelled run matched the reference exactly, so
  accuracy is at ceiling and only effort differs (stateful 7.2 calls / 44.6k input
  tokens per run, stateless 6.4 / 30.8k; n=3 per cell, high variance). Staircase
  full: 0/3 stateful complete at 20 calls; the labelled run used flight extents as
  clear width (0.69). Audit of 334 code blocks: no reads of references, logs, ledger,
  env or network. **Side channel:** staircase runs wrote `stair_*.txt` to the
  workspace root via absolute paths to bypass the output cap, and one condo run kept
  labels in `%TEMP%\labels_state.json`. In stateless mode this would be hidden memory;
  fix before new tests. Summary deck: `slides/build_deck_vol6.py`.

- **2026-09-28 - the ten "unannotated" v8 stairs were annotated under E.2.4.**
  The gt_comparison v8 sheet has all 59 rows; the importer kept only `e.3.3.1`.
  The other ten are six `exempt` (plant room, production area, attic <10 m2 x3,
  single step) and four `alert` "requires manual checking" (cinema x3,
  NOTDEFINED shape x1). IFC spaces, storeys and geometry support nine directly.
  `38SnC...Su4` starts in a 28.7 m2 2nd-storey room and rises into the 9.7 m2
  attic room, so its NA is an adjudicated interpretation. The single-step stair's
  Pset says 2 risers, but its geometry rises one 167 mm step with nothing above.
  Building use (industrial) and residential-unit status are not in the IFC.
- **2026-09-28 - clear widths independently measured.** `stair_width_reference.py`
  ray-casts cross sections (radial for spirals) over the 2 m zone above the treads.
  It reproduces 40/49 expert widths within 10 mm and 48/49 outcomes. The expert
  convention measures from walls or flight edges; railings count only when they
  project >80 mm, and a railing within a flight splits it (`...9kN`: 900 mm lane
  of a 3000 mm flight). A strict balustrade-inner-side reading flips `...KfP`
  (1000 -> 924) and `...fnh` (910 -> 1030). Outcome conflict `35pIuS$v94_8nIIWR7TtCO`:
  expert 1000 PASS, but a Run 2 railing sits 75-125 mm inside the flight edge
  (875 mm under either reading). Not expert certification.
- **2026-09-17 - all 43 reference cases reviewed.** All 2,425 stored label entries
  resolve to IFC IDs; source reproduction succeeds, but that does not validate
  their physical meaning. Detailed evidence and every case's assessment are in
  [PILOT_AUDIT.md](PILOT_AUDIT.md). Hold four landing cases (whole-stair counts
  repeated on flights and ignored spiral exemptions), five slab cases (including
  legacy mall), headroom, exit access and planter GFA. Headroom has conflicting
  height evidence; exit access has a truncated rule and only 39/123 spaces labelled;
  planter GFA confuses inclusion classification with violation labels.
  Twenty-two cases have no FAILs; twenty have only one label category. All thirty
  OBOS validation flights reuse IDs from v8 training data. Related model versions
  are not independent held-out buildings. No labels were changed by this review.
- **2026-09-17 - six usable data checks plus a control form an initial health gate.**
  The six mixed cases contain only fifteen FAIL entries, so they are baselines,
  not evidence of broad reliability. Verify repeated completion, full scope,
  label/verdict consistency, missed violations, false positives, missing-data
  handling and recorded usage. Pair benchmark runs with offline timeout, worker
  crash, invalid-output and provider-error tests. Keep the hard staircase case
  provisional: the 49/59 scoring fix did not certify its clear-width geometry.
- **2026-09-17 - migrated integration verified.** All 208 offline tests pass;
  kernel contracts pass, including exact 112-slab reference maps in both modes.
  Native MiniMax/OpenRouter adapters pass mocked tool/schema roundtrips and cache
  accounting. Approved live MiniMax-M3 smoke on a synthetic two-door IFC completed
  with correct labels: H1/stateful, reasoning off, 3 calls, 2 code executions,
  3,491 input / 559 output tokens; 1,664 input tokens cached. Transcript:
  [runs/20260917-154159_langchain_smoke.json](runs/20260917-154159_langchain_smoke.json).
  No benchmark performance claim. OpenRouter and thinking-enabled live tests remain pending.
- **2026-09-17 - staircase reference scope corrected.** Preserved the workbook's
  27 PASS / 22 FAIL labels; recorded the exact ten unannotated IFC IDs and model
  fingerprint. The importer reproduces the policy. CLI/GUI scoring and Harness 3
  now agree on that subset, while completion and early-finalization checks still
  require full IFC coverage. Bogus extra IDs and missing labelled IDs remain
  penalised. New audited subset runs are comparison-eligible; old results remain
  unchanged and separate. Expert annotation of the ten stairs is still pending.
- **2026-09-07 - repeatable pilot audit before experiment pooling.** All 43 JSON
  cases passed structural checks. Slab v2 matches rebuilt property evidence. An
  independent raw-relation traversal matches condo's 208 PASS/4 FAIL across 212
  anchors. Staircase workbook matches stored labels but still covers49/59 stairs;
  H3 scope feedback conflicts with full-population completion. No geometric expert
  re-adjudication performed. See PILOT_AUDIT.md; non-pilot semantics remain unaudited.
- Fixed scoring's abstention flag: UNKNOWN now counts as deliberate abstention
  only when parse_ok=True. Incomplete/unparsed fallback UNKNOWN is not abstention.
  Old results unchanged; newly recorded code fingerprint separates the versions.
- **2026-09-07 - repaired slab reference and completion v1.**
  - `slab_reference.py` records IFC source IDs, model-unit conversions, hash and
    per-anchor provenance. 61 floor slabs have agreeing Default/Dimensions
    Thickness; 39 landings have agreeing Monolithic/Total Thickness. All recorded
    values are 100-550 mm; 12 slabs have no recorded thickness and remain ALERT.
    This supersedes the older geometry-only all-PASS interpretation for this rule.
  - The 15 old FAILs become PASS; 23 of 35 old ALERTs become PASS. The old case,
    old logs and old scores are not modified. Both catalogue generation and GUI
    pilot selection now route to v2. Unexpected evidence or a changed IFC hash
    requires review, not automatic replacement under the same version.
  - `completion.py` uses only explicit public rule scope and IFC element IDs,
    never ground-truth labels. Agent finalization allows code for repairs and
    report submission, with the same maximum three extra turns. Every acceptance
    path is gated; prose and stale bundled FINAL fallbacks were removed.
  - Completion states are persisted separately from parse_ok and agreement:
    complete, reported_unverified_scope, abstained, incomplete. Rejected work is
    not converted into guessed PASS/COMPLIANT. GUI and factual reports expose
    issues, IFC scope size and finalization attempts. Scoring semantics unchanged.
  - Skill persistence/sampling settings were not changed. The 19:58 slab sweep
    demonstrably reused the skill saved by run1 in runs2-5; do not treat those as
    independent cold-start attempts. Use SKILLS=0 for the unaided comparison.
  - Validated with live IFC reference checks and offline scripted completion
    tests in both modes. No paid LLM sweep run; performance gain not measured.
- **2026-09-07 - pilot variability investigation (offline).** Read the local
  memory, notes, README, pilot logs/evals and the controlling harness code.
  - Slab sweep `logs/20260813-124017_slab_thickness__mall_stateful.md` has
    same-setting F1 **1.00, 0.00, 0.00** (M3, stateful, 8 iterations). Run 1
    prioritises `Qto_SlabBaseQuantities.Depth`; runs 2/3 prefer explicit thickness
    fields. This reproduces the reference bug rather than measuring which run is
    physically correct. Live spot-check: landing `22KrR6OPjFB8$H01Xk0TiE` has
    quantity depth 1175 mm but monolithic and total thickness both 200 mm.
  - The current slab rule explicitly says no *recorded* thickness means ALERT.
    Geometry-only answers for the remaining 12 slabs therefore need a rule-policy
    decision; do not replace the reference with all-PASS solely from the old audit.
  - `evals/20260721-130918_staircase_width_v8.json` has same-sweep F1
    **0.00, 0.622, 0.387** (M2.5, stateful, 14 iterations). Later M3 logs also
    show exploration without population-wide clear-width measurements, followed
    by COMPLIANT. A bounding-box width is not necessarily regulatory clear width.
  - Live scope check: slabs **112/112** IFC/labelled; condo doors/windows
    **212/212**; stairs **59/49**. A constructed report matching all 49 expert
    labels and labelling the other 10 scores **49/59 = 0.831** union accuracy.
    Level 3 incorrectly called those 10 "not in scope" under the old policy.
    The explicit evaluation mask added on 2026-09-17 fixes this without inventing
    their outcomes; historical scores are unchanged.
  - Aug 18 slab repeats have union accuracy **n/a, 0.661, 0.661**. The existing
    conditional mean excludes the failed-to-report run; counting it as zero gives
    **0.440**, not 0.661. Keep completion rate visible alongside conditional scores.
  - Offline scripted replies reproduce acceptance of COMPLIANT after `print(123)`
    with no labels, and acceptance of a FINAL contradicting a reported FAIL.
    Completion/consistency are prompt requests, not enforced gates. Not changed.
  - Fixed two independent defects in `agent.py`: incorrect model-unit guidance
    for metre-based `create_shape` meshes, and finalization accepting a bundled
    FINAL before executing its code. Four offline tests in `test_agent.py` pass;
    synthetic millimetre IFC geometry also verifies default and converted units.
  - Both providers omit sampling controls. Both sweep runners share a writable
    skill store across repeats/modes. This is a potential confound, not an observed
    cause here: no skill saves occur in the inspected pilot logs, and no current
    `skills/` directory exists. No condo pilot sweep was found in local logs/evals.
  - No paid/API sweeps were run. No GT labels, scoring policy, harness levels or
    sampling settings were changed. Historical runs predate these prompt fixes.
- **2026-08-18 — `slab_thickness__mall` ground truth is invalid. All 50 non-PASS
  labels are wrong.** Audited every one of the 112 anchors against the raw IFC.
  - All **15 FAIL are false positives**. Every one is a `Monolithic Landing:200mm
    Thickness`. Four independent sources agree they are 200 mm (element name,
    `Construction.Monolithic Thickness`, `Dimensions.Total Thickness`, geometry
    z-extent 200-479 mm). The GT reads `Qto_SlabBaseQuantities.Depth` first, and
    Revit exported the landing's **plan depth** (1050-1600 mm) into that field.
    IFC4 defines `Depth` as slab thickness, so the GT follows the schema and gets
    the wrong answer.
  - All **35 ALERT are wrong**. 23 carry `Construction.Monolithic Thickness = 200`
    and `Dimensions.Total Thickness = 200`; the data is present, just under names
    absent from `SLAB_KEYS`. The other 12 have no thickness property but readable
    geometry (464-472 mm). None are unjudgeable.
  - **Judged from geometry, all 112 slabs PASS.** The case has zero discriminative
    power. An agent that reads `Monolithic Thickness` or measures geometry (the
    correct behaviour) scores F1 0.00; one that reproduces our bug scores 1.00.
  - `SLAB_KEYS` is 3/5 dead on this model: `SGPset_SlabDimension.Thickness`,
    `Construction.Thickness` and `Pset_SlabCommon.Thickness` match nothing. The
    real name is `Construction.Default Thickness`. The README claim about "three
    property names" and "largest ALERT population" is an artefact of that list.
  - The two working keys **disagree on 16 of 50** slabs where both exist
    (`Floor_250_50`: Depth 200 vs Thickness 250; `Floor_550_200_150`: 200 vs 550).
    Structural core vs total build-up. The rule never says which it means.
  - Case-level problems beyond the labels: the rule is not a regulation (a chosen
    100-1000 mm plausibility range, clause "BIM validation", no source, no expert
    who could adjudicate), and the anchor set is wrong for the rule (51 of 112
    `IfcSlab` are stair landings, while 293 `IfcPlate` are ignored).
  - **The failure is the finding.** A spec-following rule-based checker gets 15
    elements wrong here and cannot notice. That is exactly the case where an agent
    consulting several sources and reasoning about the conflict should win. Do NOT
    patch `SLAB_KEYS`; that only relocates the arbitrary choice.
- **2026-08-18 — every generated case is suspect by the same mechanism.**
  `RISER_KEYS`, `TREAD_KEYS`, `RISER_COUNT_KEYS` are fixed priority lists with the
  same failure mode, and `ground_truth.door_width_ground_truth` reads only
  `IfcDoor.OverallWidth` with no fallback. The 2026-08-13 tread-width eval
  (F1 1.00, 36 violations from `Dimensions.Actual Tread Depth`) is not trustworthy
  until audited. Treat all 37 `simple_rules.py` cases as unvalidated; the 4 BCA
  expert-labelled cases are the only ones with independent authority.
- **2026-08-18 — deepagents assessment.** Would help RQ3 (sub-agents with isolated
  context) and context offloading; neutral-to-harmful for RQ1/RQ2, since the
  stateful/stateless contrast lives entirely in `CodeExecutor._namespace` and no
  framework supplies that. Duplicates what we already have for planning (harness 2),
  skills (`skill_library.py`) and tracing (Langfuse). Decision below.
- Exposé section 4.3 explicitly names "LangChain, including its deepagents extension",
  and **RQ3 (sub-task decomposition) currently has no implementation at all**.
- The `staircase_width_v8` failure case: 12 iterations, 104k tokens, returned
  `COMPLIANT` against 22 real failures, with recall 0 from its second step onward and
  nothing in the loop able to see it. This is why harness level 3 exists as a
  diagnostic.
- `slab_thickness__mall`: 35 of 112 slabs carry no thickness property. Before the
  `ALERT` label existed these were silently scored as correct passes.
- Class-3 rules (auxiliary geometric constructions) are where the EC3-2026 paper's
  approach collapses; `staircase_width_v8` is class 3 and is the thesis anchor.

## Decisions

- **2026-10-12 - freeze `langchain-codeact-v5` for the final evaluation (user).** No
  further agent behaviour changes: prompts, budget (20 calls, 8000 output tokens),
  completion checks v4, kernel settings and label protocol stay as they are. Only
  measurement was added: recording v5 stores `seconds` per model call and per code
  block (stateless blocks include the worker restart and IFC reload). Provider:
  OpenRouter, reasoning off; Claude requests carry `cache_control` and no forced
  `tool_choice` (adapter only, agent unchanged). Final matrix: usable_2 + staircase
  width, both modes, 3 repeats, MiniMax M3 and Sonnet 5.5; later the Solibri cases;
  optional third model stateful only. Pre-freeze v5 runs (recording v4) stay as a
  replication. Paid runs other than MiniMax need the user's approval.

- **2026-09-29 - context between model calls (user-approved), `langchain-codeact-v2`.**
  History stays append-only: every call resends system prompt, rule, all code, all
  outputs and the model's earlier reasoning. No trimming, summarization or context
  editing, so stateless/stateful differ only in the interpreter and prompt caching
  keeps its prefix (measured 90-99% cache reads after the first calls on OpenRouter
  minimax-m3). Reasoning is resent by both adapters as MiniMax requires for
  interleaved thinking; do not strip it. Tool results use LangChain
  `content_and_artifact`: the model gets the plain output text (truncation marker and
  traceback once); `error`, `error_text`, `truncated`, `output_dropped_chars`,
  `labels_valid` go to the `ToolMessage.artifact`. v1 sent a JSON wrapper with
  escaped newlines and the traceback twice. The model no longer sees `labels_valid`;
  a failed block still clears labels and the completion check reports it. Do not
  pool v1 and v2 runs.
- **2026-09-29 - usable_2 tier and retirements (user-approved).** Repaired and new
  cases are generated by [reference_v2.py](reference_v2.py) under new IDs and shown
  as tier `usable_2`; superseded cases stay unchanged (Problematic/Review with a
  pointer). Retired, not deleted: slab thickness condo/planterbox/scdf_3/scdf_5/OBOS,
  tread v8/OBOS, headroom condo, and landing OBOS (all-NA once E.2.4(d) is applied).
  The health suites are unchanged. usable_2 cases are not pilots or suite members;
  pool them only per case and version.
- **2026-09-28 - full-population staircase reference.** User approved adding the
  E.2.1/E.2.4 wording, scoring the four manual-check stairs as `MANUAL_CHECK`
  (also exercises that label), and independent IFC checks. Made autonomously while
  the user was unavailable, pending review: `...TtCO` adjudicated FAIL from the model
  geometry; `...Su4` kept NA; the expert width convention is stated in the rule text
  rather than relabelling to the strict balustrade reading. The new case is a new
  ID with version `full-population-v1`; the tier stays Provisional. Unrecorded
  expert/IFC disagreements stop regeneration.
- **2026-09-17 - GUI health-suite selection.** Keep the six usable cases below,
  mall slab v2 as a control, and staircase width as a provisional hard case.
  Display Usable / Control / Provisional / Review / Problematic tiers for the
  audited catalogue; unknown future IDs remain Unreviewed. Problematic and review
  cases stay accessible for explicitly confirmed exploratory runs, not in the
  automatic suite. Keep reference labels and review guidance outside agent inputs.
  Suite execution reuses the ordinary single-case runner sequentially, with the
  selected model, H1/H2, modes, repeats and model-call cap frozen. Each case uses
  its stored rule and IFC, not edited custom input fields. Preserve per-case
  logs, reports, database configurations and scores; never pool accuracy across
  the control, hard case and ordinary cases. The suite JSON is only a progress
  and artifact index, not a new transcript format or resumable agent state.
- **2026-09-17 - migration scope confirmed.** New runs retain H1/basic and H2/planning;
  H3/reference-feedback is retired. Archived skill code and standalone tests stay,
  but are not exposed to the agent. GUI, SQLite ledger, reports and Langfuse remain.
- **2026-09-17 - separate action and submission contract.** LangChain handles its
  structured output before execution tools; mixed Python/FinalReport responses are
  rejected before side effects, then resubmitted separately within budget. This was
  explicitly agreed after the integration test exposed a routing mismatch. No
  framework internals or outer retry loop were patched.
- **2026-09-17 - new run budget and identity.** `langchain-codeact-v1`, recording v3:
  max_iterations counts all model calls including planning, repairs and final reports;
  Python calls have the same cap. 8,000 output tokens/call, 180-second API timeout,
  zero automatic provider retries, sequential tool execution. Kernel limits unchanged.
  No extra finalization turns or cumulative cost cap. Historical runs are unchanged.
- **2026-09-17 - lean LangChain migration authorized.** Use `create_agent` with
  LangGraph as its underlying runtime, not a custom graph or Deep Agents. One
  `run_python(code)` tool delegates to the existing kernel. Keep Python execution
  modes, GUI/CLI, completion validation, offline scoring, experiment recording and
  optional Langfuse. Replace the custom model/message loop, not wrap it. No new UI,
  tracing service, cross-run memory, skills, subagents or framework comparison.
- **2026-09-17 - design before workarounds.** Read [instruction.md](instruction.md)
  before development. If a failure requires a substantial workaround, revisit the
  owning architecture instead of adding case-specific patches or redundant guardrails.
  Necessary validation and scientific safeguards stay. Feature removals still need
  scope agreement; paid API smoke tests require explicit approval.

- **2026-09-16 - retire the in-process executor; use the kernel for all evaluation.**
  - Why: clearing a namespace does not reset interpreter-level state. The kernel
    makes the B/C comparison depend on worker lifetime, with the same reporting,
    timeout and crash-containment machinery in both modes. Maintaining another
    active runtime adds configuration and testing complexity outside the thesis
    question; old prototype results do not justify that cost.
  - Comment out the complete `CodeExecutor` class, runtime-selection branches,
    GUI controls/callbacks and old parity comparison code. Keep shared extraction,
    label validation, bounded output and traceback helpers in `executor.py`.
    Do not delete the module or silently alias the old class to the kernel.
  - Migrate execution tests to real kernel workers with explicit cleanup. Replace
    two-runtime parity tests with expected-behavior tests and direct IFC/reference
    agreement. Worker KeyboardInterrupt is contained, not propagated to the host.
  - New records always identify the kernel and its effective timeout/hash settings.
    Ignore legacy recorder runtime arguments; reject explicit factory requests for
    retired runtimes. Preserve old results and historical database migration logic.
  - Statelessness resets interpreter state and the private worker scratch directory,
    not conversation history or arbitrary external files. The kernel is not a
    security sandbox. Interpret startup/reload overhead separately from LLM latency
    when analysing efficiency; this cleanup does not claim a performance gain.
  - Suggested thesis wording: "The initial prototype reset the execution namespace
    between steps. It was replaced with a worker-based runtime because namespace
    resets retained interpreter-level state. The evaluation uses the same runtime
    in both modes, with persistence determined by worker lifetime."

- **2026-09-16 - exclude persistent skills from the thesis evaluation.**
  - Keep within-run state: variables, imports, loaded IFC data, intermediate
    results and ordinary locally defined functions. Remove cross-run tool reuse
    from both execution modes. The primary controlled comparison remains B vs C.
  - Why: a changing skill library introduces learning between repeats, dependence
    on run order and another source of memory in the stateless condition. Studying
    transfer would require separate development/test splits, frozen libraries and
    independent validation of generated helpers. Self-authored tests do not prove
    regulatory correctness or transfer to unseen models.
  - This is a scope decision for the remaining two months, not a finding that
    skills reduce accuracy. No controlled skills-on/off performance claim is made.
  - Comment out the active CLI, evaluator, GUI, agent-prompt and runtime hooks.
    Ignore legacy enabled-library arguments and worker activation requests.
    `SKILLS=1` cannot restore the feature; the GUI activation/details controls are
    retired. Keep the environment primer, harness levels and scoring unchanged.
  - Preserve the standalone implementation, its unit tests, saved skill files and
    historical runs. Keep historical skill fields/filters; new runs record skills
    disabled, empty snapshots and zero saves. Never relabel or pool old skills-on
    runs as the new baseline. Restart the GUI after these code changes.
  - Suggested thesis wording: "A persistent skill library was implemented and
    explored during development, but excluded from the final evaluation to isolate
    within-run execution state from cross-run tool reuse."

- **Historical experiment ladder A-B-C-D.** Agreed 2026-09-08; condition D was
  removed from the planned evaluation on 2026-09-16.

  | id | iteration + execution feedback | persistent namespace | skills across runs | corresponds to |
  | --- | --- | --- | --- | --- |
  | A | no (single shot, no transcript) | no | no | prior work / exposé §4.2 floor |
  | B | yes | no | no | current `--mode stateless` |
  | C | yes | yes | no | current `--mode stateful`, the contribution |
  | D | yes | yes | yes | skill library, already implemented |

  Each edge answers a different question: A→B how much comes from iterating and seeing
  errors at all; **B→C how much comes from persistent state specifically (this is RQ1/RQ2)**;
  A→C the end-to-end system claim. **B is the control and must not be dropped** — without
  it, a C win is attributable to error feedback, which is already established in the
  CodeAct literature, and statefulness is never isolated. B is an ablation, not a
  shippable configuration; label it as such rather than defending it as a product.
- **State has two channels, and B separates them.** In B the agent still has state via
  the context window (it can copy its own earlier code out of the transcript) while
  having none via the namespace. Say this explicitly in the methodology chapter; it is
  the point of the condition, not a flaw. A removes both channels at once.
- **Expect a cost finding, not a reliability finding.** Sept 8 sweeps: slab 5/5 vs 4/5
  exact, condo 5/5 vs 5/5; mean tokens 61.7k vs 79.4k and 35.6k vs 48.2k; mean seconds
  61.5 vs 108.0 and 65.0 vs 82.7. Accuracy is at ceiling on both, so RQ1's reliability
  claim is currently unsupported by our own pilots. "Statefulness buys efficiency;
  reliability comes from iteration" is an honest and defensible result — but only
  reportable if B exists. Two ceiling-accuracy cases cannot discriminate A/B/C at all;
  the discriminating case is the class-3 staircase.
- **Execution mode moves into a kernel process.** Agreed 2026-09-08, advisor's
  suggestion. **Implemented 2026-09-08** as `kernel_executor.py` + `kernel_worker.py`,
  selected by `EXECUTION_RUNTIME=kernel`; default stays `inprocess` so existing results
  reproduce. Not `jupyter_client`: a single request/response per block over a private
  pipe is more predictable than draining iopub and needs no new dependency, so this is
  kernel-*style*, not the Jupyter protocol. Say that precisely in the thesis.
  Worker lifetime per condition: C = one worker per run; B = restart before every block
  after the first; A = spawn, run once, discard (not implemented).
  Design points that mattered:
  - `CodeExecutor` public surface unchanged (`run`, `close`, `reported_labels`,
    `label_reports`, `labels_valid`, `last_error`, `last_execution`,
    `skill_load_issues`, `skill_prompt_section`), so `agent.py`/`gui.py`/`evaluate.py`/
    `completion.py` needed no changes beyond calling `executor.make_executor`.
  - The control channel is a private dup of fds 0/1 taken before any agent code runs;
    fd 0 is then pointed at devnull and fd 1 at stderr. Agent code therefore cannot
    read the protocol or forge a reply by printing one. Both are regression-tested.
  - `report_labels` stages in the worker and the *host* applies the commit-on-success
    rule, so transactional label semantics are identical in both runtimes. Output text
    is assembled by shared `executor.assemble_output`/`normalise_label_map` so the two
    cannot drift.
  - `save_skill`/`preload` run in the worker. The manifest commit was already atomic
    with a cross-process lock, so this needed no change; the host's `SkillLibrary.loaded`
    is synced from the worker's actual load outcome so the prompt stays truthful.
  - Timeout (`EXEC_TIMEOUT`, default 600s) and worker death are distinguished by *why*
    the reply was missing, not by polling the child, which races: a crashed worker is
    usually not yet reaped. Both kill and respawn, and the message returned to the model
    says the session was restarted, so it stops inventing explanations for NameErrors.
- **Ground truth must be multi-source with recorded adjudication.** The root error
  in `simple_rules.py` is that the GT is a single-source lookup and so is the thing
  under test, which makes the comparison circular in exactly the dimension the
  thesis studies (heterogeneous naming). Replacement design:
  1. Per element, harvest **every** candidate value: all psets, quantity sets,
     material layer sets, type-level properties, geometry. Sources that agree give
     an automatic, trustworthy label.
  2. Conflicts are adjudicated once by hand, and the decision **plus its reason**
     is stored in the case file.
  3. Store provenance per element (value, source, agreeing sources, conflicting
     sources, adjudicator, note) so an agent/GT disagreement can be attributed.
  4. Report accuracy separately on the **clean** and **conflicting** subsets. That
     split is a stronger result than an aggregate F1 and answers the actual
     question about heterogeneous IFC data.
- **deepagents: additive, not a migration.** Keep levels 1-3 untouched (they are the
  controlled experiment and existing `evals/` depend on them). If adopted, it becomes
  **harness level 4** with `CodeExecutor` wrapped as its code tool.
- **Superseded 2026-09-16:** the earlier decision to retain `save_skill` as an active
  differentiator is withdrawn. The implementation remains archived, not enabled.
- Cheaper path to RQ3 if the framework is not worth the dependency: a
  `spawn_subcheck(prompt) -> summary` builtin next to `report_labels` and `save_skill`
  in `executor.py`. No new dependency, no provider risk.
- Skill library ships empty by design. Nothing rule-specific is pre-given.
- Ground truth for the class-1/2 rules comes from coded reference implementations
  (`simple_rules.py`), which the EC3-2026 paper explicitly permits.

## Current health suite

These are rule/model cases, not eight independent buildings or regulations.

| Case | Tier | PASS / FAIL / ALERT | Interpretation |
| --- | --- | --- | --- |
| `door_width_planterbox` | Usable | 27 / 7 / 0 | Explicit OverallWidth proxy, not physical clear opening |
| `doors_windows_storey__condo` | Usable | 208 / 4 / 0 | Independently checked IFC relationships |
| `doors_windows_storey__mall` | Usable | 216 / 1 / 0 | Independently checked IFC relationships |
| `riser_height_e341__mall` | Usable | 77 / 1 / 0 | Recorded height; mesh corroboration where measurable |
| `riser_height_e341__stair_v8` | Usable | 66 / 1 / 0 | Recorded height; only one failure |
| `tread_width_e342__condo` | Usable | 29 / 1 / 0 | Supplied common-stair assumption |
| `slab_thickness__mall` | Control | 100 / 0 / 12 | Missing-data and false-positive control, not recall |
| `staircase_width_v8` | Provisional | 26 / 23 / 0 (+6 NA, 4 MANUAL_CHECK) | All 59 stairs; workbook labels cross-checked against IFC widths/spaces; 2 adjudicated; stated width convention |

The GUI defaults to this shortlist. **Run 8-case health suite** confirms the
selected mode(s), repeats, total runs and maximum model calls before starting.
The same call cap applies to every case; selecting the hard case internally does
not silently increase the budget. **Stop after current run** prevents subsequent
runs/cases while preserving the current result. Provider exceptions stop the
suite; incomplete returned results remain visible and do not abort other cases.
Scores retain separate case/mode/repeat rows and selected-case aggregates.
Each case has its usual log/report and database sweep. A
`logs/<timestamp>_health_suite.json` index links started cases and records requested
runs, returned-run count, complete-run count, known token totals and usage status.
It does not resume interrupted sweeps or change audit eligibility.

**Cost and verification policy:** begin with one repeat in both modes (16 runs).
After checking outcomes and actual usage, use three repeats (48 runs). The earlier
42-run recommendation covered only the six usable cases plus control, without the
hard case. At an illustrative 50,000 combined input/output tokens per run, 16 runs
would consume 800,000 tokens and 48 would consume 2.4 million. These are arithmetic
examples, not forecasts, billing estimates or caps; context growth, reasoning,
geometry exploration and provider caching can change actual cost substantially.
Use a fixed model/settings/budget and compare individual runs as well as means.
Passing supports consistent operation on these tasks, not general compliance
reliability. No paid suite was launched while implementing these controls.

## usable_2 cases (not in the suites)

Built by `reference_v2.py`; regenerate or check with `python acc_agent/reference_v2.py [--check]`.

| Case | PASS / FAIL / NA | Note |
| --- | --- | --- |
| `landing_interval_e352__stair_v8` | 20 / 28 / 19 | Per flight; spiral and E.2.1/E.2.4 NA |
| `landing_interval_e352__mall` | 76 / 0 / 2 | Trap control: flights repeat the 27-riser stair total |
| `landing_interval_e352__scdf_5` | 73 / 0 / 0 | Trap control: flights repeat the 21-riser stair total |
| `tread_width_e342__mall` | 40 / 36 / 2 | Every tread measured; tapered at 500 mm |
| `exit_requirements__scdf_5` | 23 / 3 / 13 | 39 template spaces scored, 84 unscored; ~12 rows rest on unstated conventions (Findings 2026-10-04) |
| `exit_requirements__scdf_3` | 10 / 0 / 2 | Control; 47 unscored |
| `planter_box_gfa` | 1 / 7 / 0 | PASS = excluded from GFA; eight elements |
| `headroom_door_c321__mall` | 154 / 3 / 0 | ClearHeight convention stated; 33 lift doors unscored |
| `space_elevation__mall` | 186 / 19 / 4 | EC3 BIM consistency rule |
| `space_elevation__scdf_3` | 53 / 1 / 5 | EC3 BIM consistency rule; GFA area objects NA |

## Historical pilot cases

The earlier three-case pilot remains available in the GUI's Pilots filter.
Its five-repeat recommendations are historical, not a requirement for the first
health-suite run.

| case | class | anchors | why |
| --- | --- | --- | --- |
| `slab_thickness__mall` | 1 | 112 (100 pass, 12 alert, zero fail) | evidence-backed control; not a violation-recall test |
| `doors_windows_storey__condo` | 2 | 212 (4 fail, 208 pass) | 2% violation rate; where union accuracy earns its keep |
| `staircase_width_v8` | 3 | 59 stairs (23 fail, 26 pass, 6 NA, 4 manual check) | full population; the older 49-stair subset case is deprecated |

## Open items

- **Kernel limits not handled:** no interrupt-then-kill escalation (a timeout goes
  straight to kill), no memory/CPU ceiling on the worker, and a killed stateful worker
  loses the run's state (the agent is told; recovery quality unmeasured). No timeout or
  restart occurred in the v5 suites. Per-block seconds are recorded from recording v5.
- **Condition A (single-shot baseline): out of scope** for the final evaluation unless
  the advisor asks for it. Design if picked up: one block, no transcript replay; settle
  zero vs N repair attempts first.
- RQ3 (sub-task decomposition) and RQ4 (IfcJSON, graph representations, geometry libs)
  are unimplemented; planned as future work, to confirm with the advisor.
- Exit scdf_5 reference conventions (Findings 2026-10-04): report as is unless decided
  otherwise.
- Solibri-derived held-out cases (advisor request, 2026-10-12): planned after the freeze.
- Verify MiniMax `thinking: {"type": "adaptive"}` passthrough survives if the provider
  layer is ever moved onto LangChain chat models. Not guaranteed.
- Decide whether to replace hard output truncation with offload-to-file.

---

## Changelog

- **2026-10-12 - recording v5 and the v5 freeze.** `agent.py` stores `seconds` per
  model call (`llm_calls`) and per code block (`execution_records`); recording version
  4 -> 5. No behaviour change. 250 tests and the kernel contract check pass. First
  frozen MiniMax batch (OpenRouter, 41 finished runs at 21:39): 39 complete, 2
  abstained, 0 incomplete; accuracy as in the 2-3 Oct suites; model wait dominates
  (code 14% of time stateful, 28% stateless; median 1.8 s vs 3.1 s per block). Lost
  runs: 2 OpenRouter `provider_unavailable` (evaluate.py stops the case's remaining
  repeats) and 1 laptop standby 18:06-20:52. Reruns overlapped the main batch, so
  their code seconds may be slightly inflated. Published as tag `v5-frozen`.

- **2026-10-04 - suite repeats follow the slider.** The 7-case and usable_2 suite
  buttons no longer use a fixed 3 repeats; every suite takes the repeat slider value,
  shown in the confirmation and recorded in the suite index. Selecting a case still
  moves the slider to that case's recommendation, so check it before starting.

- **2026-10-03 - prompt caching for Claude on OpenRouter.** Claude caches only when the
  request asks for it; until now no `cache_control` was sent, so a Claude run would have
  paid full input price on every call. `llm.load_llm` now sends top-level
  `cache_control: {"type": "ephemeral"}` (5-minute TTL; OpenRouter moves the breakpoint
  to the latest message) for `anthropic/` models only; MiniMax requests are unchanged.
  Agent protocol unchanged. Claude 5.x rejects forced tool use outright, with or
  without reasoning ("tool_choice: type "tool" and "any" are not supported for this
  model", every OpenRouter upstream). LangChain forces `tool_choice="any"` whenever
  FinalReport is a structured-output tool, so the first Sonnet 5.5 request failed.
  `llm.ClaudeOpenRouter` drops `tool_choice` for `anthropic/` models; RunEvents already
  returns tool-less replies to the model. MiniMax still gets `required`.
  Verified offline: the serialized request carries `cache_control` and no `tool_choice`
  for Claude, and neither change for MiniMax; 250 tests pass. One live Sonnet 5.5
  request through the adapter returned a run_python call ($0.0014).

- **2026-10-02 - agent protocol `langchain-codeact-v5`.** The last model call keeps the
  same tool list (changing it invalidated the provider's prompt cache). Final-report-only
  is enforced by rejecting any `run_python` call on the last call before it runs; the
  last-call message says so. Completion checks stay v4. Do not pool v5 with v4. Watch
  whether more runs now spend the last call on rejected code. Verified offline: 249 tests
  pass; the last-call test now asserts an unchanged tool list and that the code is not run.
- **2026-10-01 - agent protocol `langchain-codeact-v4`, completion checks v4.**
  Decision (user): stop overloading ALERT/MANUAL_CHECK as placeholders and enforce the
  final call. (1) New agent-only label `PENDING` (executor `REPORT_LABELS`, scoring alias;
  not in `scoring.LABELS`, so references never use it and it never matches in union
  accuracy). COMPLIANT/NON_COMPLIANT are rejected while any PENDING remains; UNKNOWN on
  the final call is accepted if there are no FAILs. The prompt asks for early
  provisional labelling with PENDING and keeps ALERT/MANUAL_CHECK to their definitions.
  (2) The last model call binds only the FinalReport tool, and any `run_python` call on
  it is rejected without running (providers may ignore the tool list). The wrap-up
  reminder now says so. A run that still has FAILs plus PENDING on the last call ends
  incomplete. The recorder stores `pending_labels` per run. Do not pool v4 with v3.
  Verified offline: 249 tests pass (4 new: last call binds only FinalReport and runs no
  code, PENDING blocks decided verdicts and allows final UNKNOWN, resolved PENDING
  completes, completion-level PENDING check); `check_runtime_parity.py` passes.
- **2026-10-01 - agent protocol `langchain-codeact-v3`.** The system prompt states the
  model-call budget and asks for a complete provisional labelling as soon as every
  element can be labelled (ALERT/MANUAL_CHECK where unresolved, refined later; leftovers
  are scored as submitted). Each `run_python` result ends with `[Model call k of N used;
  N-k remain.]` (execution records and GUI output keep the raw text). When 4 calls remain
  (`WRAP_UP_CALLS`) a reminder asks to commit labels so FinalReport fits; the last-call
  notice is unchanged. A reply with no tool call no longer ends the run: it returns to
  the model as a protocol error and costs a call; on the last call the run stays
  incomplete. The worker pre-imports `ifcopenshell.geom` and `ifcopenshell.util.element/
  unit/shape` into the module cache only (namespace unchanged, about 0.1 s per worker
  start); the primer shows the explicit import line. Prompt hash and protocol changed:
  do not pool v3 runs with v2. Caveat: provisional ALERT/MANUAL_CHECK stretches those
  labels' meaning; watch whether runs finish with unresolved provisional labels.
  Verified offline: 245 tests pass (4 new: budget text/counter/reminder, text-only reply
  returned, text on last call stays incomplete, submodules pre-imported but not
  injected); `check_runtime_parity.py` passes. No paid runs yet.
- **2026-10-01 - README file map; `inspect_doors.py` archived.** The README's "How it
  works" list is now a grouped map of every file (programs, agent core, execution,
  experiments and reports, references, checks and history). `inspect_doors.py` (unused
  door-width helper) moved unchanged to `archive/` with a 3-line header; the next
  publication deletes it from the top level. Folder restructure deferred until the
  thesis experiments are frozen: file moves change recorded code fingerprints.
- **2026-09-30 - commented-out code moved to `archive/`.** 48 fragments (about 290
  lines) from executor, gui, check_runtime_parity, evaluate, run, experiment_recorder,
  kernel_executor, kernel_worker and two test files now live verbatim in
  `archive/inprocess_runtime.py` and `archive/skill_integration.py`, each with its line
  range at tag `stable-case-names`. Verified: every fragment equals the tagged lines;
  every live file has the same AST as at the tag (only the executor and
  check_runtime_parity docstrings changed to point to the archive). The publishing
  file list now includes `acc_agent/archive/*.py`. Published as `f6c4ba5`; 241 tests
  pass in both trees (17 skipped in the publishing checkout), kernel checks pass.
- **2026-09-30 - published to thesis-acc-agent.** Commit `1751f49` (60 paths: 17 added,
  1 renamed, 1 deleted, 40 modified); tags `langchain-v1` (`426377d`, 22 Sep) and
  `stable-case-names` (`1751f49`). Code history: pre-LangChain loop = `tez` commit
  `fa7b163` (8 Sep, `Thesis-initial`); later stages = tags above. Publishing-root tests:
  241 pass, 17 skipped (IFC models and authority templates are not distributed);
  `check_runtime_parity.py` passed in the source workspace. Fixed
  `test_reference_v2` to skip, not error, when the exit authority template is missing.
- **2026-09-30 - stable case IDs.** Renamed 17 reference files: current
  `slab_thickness__mall_v2`, `staircase_width_v8_full`, `landing_interval_e352__{stair_v8,mall,scdf_5}_v2`,
  `tread_width_e342__mall_v2`, `exit_requirements__{scdf_5,scdf_3}_v2`, `planter_box_gfa_v2`
  lost their suffix; the superseded `slab_thickness__mall`, `staircase_width_v8`,
  `landing_interval_e352__{stair_v8,mall,scdf_5}`, `tread_width_e342__mall`,
  `exit_requirements_v0` (now `exit_requirements__scdf_5_deprecated_v1`) and `planter_box_gfa`
  became `_deprecated_v1`. Current files were regenerated by their builders; deprecated
  files only had `case_id` changed. The GUI's Problematic/Review tiers are gone
  (deprecated cases are hidden; `case_assessment` returns `Deprecated`). The ledger is
  unchanged: `list_runs` maps IDs of rows with `recording_version` < 4 (the recorder
  now writes 4). Logs, evals and Langfuse keep old names. The factual report decides the
  slab warning by the logged reference version, because old logs used the plain slab ID
  for the invalid legacy reference. New runs get a new reference hash (the ID is inside
  the reference) and do not pool with earlier runs. `reference_v2.py` keeps its file name.
  Verified: all 54 files equal their pre-rename content with only IDs substituted;
  241 offline tests pass; the ledger reads 5 old subset runs as
  `staircase_width_v8_deprecated_v1` and the rest under current IDs.
- **2026-09-30 - `dashboard.py` (read-only charts).** Tabs: *Latest run* (the GUI
  suite containing the newest run, matched by case log file name against
  `logs/*_health_suite.json`, else that run's sweep; per case and mode), *All runs*
  (per case and version) and *Over time* (runs per day by outcome, OpenRouter-reported
  cost). Version = recorded `agent_protocol` (none = pre-LangChain loop) plus
  `completion_checks`; All runs pools modes and prompt changes within a version, so it
  is descriptive only. The window redraws when the ledger or its WAL changes;
  `--save DIR` writes PNGs. Adds matplotlib.
- **2026-09-30 - fixes from the usable_2 suite run:**
  - References: `space_elevation__*` now also labels NA any IfcSpace carrying an
    `SGPset_SpaceArea*` set (scdf_3: 53 PASS / 1 FAIL / 5 NA; mall unchanged). The
    tread rule now says a flight with two or more risers has a tread and is assessed.
    Both cases rebuilt; `reference_v2.py --check` passes. Earlier scdf_3 and tread
    scores used the old reference and wording.
  - Completion checks v3: UNKNOWN is accepted only on the final model call; earlier
    it is rejected with the calls remaining. The system prompt states this and the
    relative-path rule, so the prompt hash changed. Do not pool new runs with older ones.
  - Kernel: an audit hook in the worker refuses Python-level writes outside the
    scratch folder, and `TEMP`/`TMP`/`TMPDIR` point to scratch. The stray
    `%TEMP%\flights.json` and `Documents\cache_planter.pkl` were deleted.
    `check_runtime_parity.py` passes.
- **2026-09-29 - usable_2 suite button:** runs all ten usable_2 cases at a fixed
  3 repeats through the same suite runner, confirmation, stop and index as the
  health suites. With both modes this is 60 runs, at most 1,200 model calls.
- **2026-09-29 - protocol v2 tool results:** `run_python` is a
  `content_and_artifact` tool; transcripts record the artifact; GUI log header reads
  `AGENT_PROTOCOL`. Tests: plain output with one traceback (ScriptedClient), and the
  MiniMax/OpenRouter roundtrip now asserts earlier reasoning and plain tool output
  reach the second request. Full offline suite (236) passes; no paid runs.
- **2026-09-29 - usable_2 references:** added `reference_v2.py` (10 cases):
  landing E.3.5.2 v8/mall/scdf_5 `_v2`, tread mall `_v2`, exit access scdf_5/scdf_3
  `_v2` (full template clause, authority definitions, template-scope subset with
  exempt Pass rows as NA), planter GFA `_v2` (criteria stated), mall door headroom
  (`headroom_door_c321__mall`), and EC3 same-storey elevation (mall, scdf_3). GUI
  tiers `usable_2` and `Retired`; audit status `evidence-checked` via fast
  `verify_recorded`. `reference_v2.py --check` reproduces all 10 stored cases; all
  235 offline tests pass. Restart the GUI to load the new tiers.
- **2026-09-29 - 7-case suite button:** runs the six usable cases plus the slab
  control, without the staircase hard case, at a fixed 3 repeats (the repeat
  slider is ignored and left unchanged). Same runner, budget, confirmation, stop
  and suite index as the 8-case suite; the index records its case list and repeats.
  With both modes this is 42 runs, at most 840 model calls. GUI tests pass.

- **2026-09-28 - first live OpenRouter run reviewed (door width, stateful, H1,
  `minimax/minimax-m3`):** pipeline sound - completion complete (34/34 labels),
  usage reported (55,476 in / 4,550 out, 10 calls), log, report, Langfuse trace and
  score recorded. Two prompt defects fixed in `LABEL_PROTOCOL`: (1) the model spent
  calls 4-8 trying to import `report_labels`; the prompt now says it is predefined.
  (2) The rule never stated the references' 0.5 mm float-noise tolerance, so a
  literal `< 900` check flagged nine nominal-900 doors (P=0.44, F1=0.61, union 0.735)
  - the agent followed the text correctly. Without tolerance, riser mall also changes
  3 labels. The prompt now states that values within 0.5 mm of a limit meet it; this
  is general, not case-specific, and matches every reference. Runs before this change
  have a different prompt hash and must not be pooled.

- **2026-09-28 - OpenRouter timeout unit fix:** `langchain_openrouter` takes the
  request timeout in milliseconds; we passed 180, i.e. 0.18 s, and the first live
  OpenRouter request hung with no error. Now 180,000 ms (MiniMax/Anthropic stays
  180 s). Verified with two 16-token live calls (~$0.00004 each): raw HTTP 2.9 s,
  app client 3.7 s. Observation: `minimax/minimax-m3` via OpenRouter produced
  reasoning tokens even with `REASONING=0`, so it is not the same condition as the
  MiniMax-direct thinking-off smoke test; record and do not pool.

- **2026-09-28 - GUI provider switch:** Provider (minimax/openrouter) is chosen in
  the GUI per run and passed to `llm.load_llm(model, provider)`; switching resets the
  model field to that provider's default. The OpenRouter default is now
  `minimax/minimax-m3` (same model family as the MiniMax path; OpenRouter lists tools
  and structured outputs, $0.30/$1.20 per M tokens on 2026-09-28). The provider is
  recorded in run identity, so MiniMax-direct and OpenRouter runs never pool.
  OpenRouter is still not live-tested; do one single cheap run first.

- **2026-09-28 - fixed model-call cap:** every run (GUI single runs, health suite,
  CLI and evaluation defaults) uses `config.MAX_ITERATIONS = 20` model calls. The
  GUI slider was removed and per-group recommendations now cover repeats only. It is
  a cap, not a quota: a run ends as soon as its FinalReport is accepted.
  Reason: Sept 8 staircase runs used 15-16 of a 16-call cap under the old loop,
  which also allowed up to 3 extra finalization turns; the new budget counts the
  plan and final report too. Simple cases used 5-14 and stop when done. If the
  first 16-run suite shows the staircase hitting 20, revisit before 48 runs.
  CLI `--max-iterations` remains for explicit experiments; such runs get a
  different configuration identity and must not be pooled.

- **2026-09-28 - full v8 staircase reference:** added `stair_width_reference.py`
  and `ground_truth/staircase_width_v8_full.json`; GUI pilot and health suite now
  use it, the subset case is Review/superseded, and `evidence-checked` audits are
  comparison-eligible. Added `tests/test_stair_width_reference.py`. All 226 offline
  tests pass; `stair_width_reference.py --check` reproduces the stored evidence.
  No paid model calls. Restart the GUI to load the new case routing.
- **2026-09-17 - reviewed case tiers and confirmed eight-case GUI suite:** added
  all-catalogue selection statuses, reference warnings, a sequential suite button,
  run-count/call-budget confirmation, stop-after-current-run control and known
  token tracking. Separate case logs/reports/database sweeps remain unchanged in
  meaning; score rows and aggregates are now keyed by case as well as mode.
  An artifact index records suite progress without duplicating transcripts.
  Offline scripted tests cover all eight cases in both modes, subset scoring,
  cancellation, missing models, provider errors and failed startup. Restart the
  GUI to load the new controls. No paid benchmark run or reference relabelling.
- **2026-09-17 - LangChain application cutover:** replaced custom provider adapters
  and the handwritten action loop with standard chat models, `create_agent`, call-limit
  middleware and Pydantic/ToolStrategy completion validation. Removed active Markdown
  code extraction. GUI/CLI and recording use the shared runner; ledger details retain
  structured messages and execution evidence. Langfuse uses its standard callback.
  All 208 offline tests, kernel contracts, dependency checks and CLI startup pass.
  One explicitly approved live MiniMax smoke test passed; no compliance benchmark
  performance measurement was made. Restart the GUI before running migrated code.
- **2026-09-17 - migration started:** recorded the agreed lean architecture and added
  [instruction.md](instruction.md), linked by the workspace Copilot instructions for
  future sessions. Application cutover and provider validation are not yet complete.

### 2026-09-16
- Retired the in-process runtime after the skill retirement below. Preserved its
  complete class, factory selection and GUI controls as comments. The kernel is
  now the only runtime; both stateful and stateless modes remain available.
- Removed active references to the old class from the agent and execution tests;
  each migrated test closes its kernel workers. Kernel contract checks now use
  explicit expectations rather than another executor as the oracle. The historical
  `check_runtime_parity.py` command checks both modes and exact IFC/reference labels.
- New GUI/SQLite records use the effective kernel runtime even when old environment
  or recorder settings request in-process execution. Historical records, separation
  filters and inferred legacy runtime metadata are unchanged. Restart the GUI.
- Kernel-only verification: all 198 tests passed. The revised contract command
  passed 15 blocks in both modes at 6000/60-character output caps, state persistence
  and reset checks, and exact agreement with all 112 mall slab labels in both modes.
  An AST audit of 44 Python modules found no active `CodeExecutor` references;
  fresh CLI/evaluation/GUI imports with legacy environment settings still selected
  the kernel and retained verified code fingerprints. No paid LLM calls.
- Retired persistent skills from new runs to isolate within-run statefulness and
  avoid expanding the thesis into cross-run learning and tool-transfer evaluation.
- Commented out skill imports/construction in CLI/evaluation/GUI, skill controls
  and callbacks, agent prompt/warning hooks, and both runtimes' preload/save hooks.
  Explicit enabled-library arguments, `SKILLS=1` and old worker requests are ignored.
- New trace/SQLite/log metadata consistently records skills disabled; historical
  columns, filters and saved results remain intact. The archived library is no
  longer part of the active-code fingerprint. No saved skill files were deleted.
- Updated former integration tests to assert retirement and normal local-function
  recovery; retained standalone library/contract tests. Added checks for enabled
  legacy settings, existing saved files, prompts, recording and the GUI sweep.
  No paid model calls or claimed skills-on/off performance comparison.
- Added the short thesis scope statement above and marked README skill guidance
  as historical. The environment primer, execution modes and scoring are unchanged.
- Skills-retirement verification (before kernel-only cleanup): all 197 tests passed.
  Runtime parity passed in both
  modes, including all 112 mall slab labels (100 PASS, 12 ALERT). A fresh-process
  import check confirmed CLI/evaluation/GUI do not import the archived library and
  active-code fingerprints remain verified. No paid agent runs were used.

### 2026-09-08
- Fixed the three issues reproduced in the independent kernel review. Configuration
  fingerprints now include effective kernel execution/startup timeouts and Python
  hash seed, using loaded runtime settings rather than rereading environment values.
  In-process configurations do not vary with unused kernel settings; historical
  records remain unchanged.
- `CodeActAgent.check` resolves IFC paths against the host cwd before constructing
  prompts or discovering scope. Relative CLI, GUI and evaluation inputs now work
  with the kernel's private cwd; the scratch-directory isolation is unchanged.
- Unexpected kernel restarts now expose `kernel_restarted` and `restart_reason` in
  execution metadata and explain the loss of session state to the model. A dead
  worker detected before execution rejects that pending block without running it,
  invalidates labels and asks the agent to rebuild state. Fatal exception notices
  remain visible even after output truncation. Scheduled stateless resets stay quiet
  and retain valid committed labels.
- Added regression coverage for each kernel setting's configuration identity,
  relative-path IFC reads in both runtimes/modes, death between blocks and fatal
  exception recovery. No paid model calls or historical record changes.
- Pre-sweep audit of the kernel (`check_runtime_parity.py`, new). Found and fixed three
  real differences before any paid run; the two runtimes now agree on every observable.
  - Worker cwd was `acc_agent/`, so a relative write landed in the **source tree** and
    survived a stateless restart, contradicting the "nothing persists" claim. Each
    worker now gets a private temp scratch dir, removed when it dies: one per run in
    stateful, one per block in stateless. Absolute writes still persist — documented.
  - Tracebacks embedded the harness frame, so every execution error differed between
    runtimes (`executor.py` vs `kernel_worker.py`). `format_agent_traceback` now strips
    frames from harness files in **both** runtimes; the model sees only `<string>` and
    saved-skill frames. Cleaner, but it means neither runtime reproduces the exact
    prompt bytes of pre-2026-09-08 runs. The executor code hash records this.
  - `-I` silently discarded `PYTHONHASHSEED` *and* the `PYTHONIOENCODING` we set, so
    every worker had its own hash seed and set iteration order varied per block — new
    nondeterminism that did not exist when all repeats shared one process. Replaced
    `-I` with `-s` plus an explicitly sanitised environment (all `PYTHON*` dropped,
    then encoding and `PYTHONHASHSEED=0` pinned; override with `EXEC_HASH_SEED`).
    Verified `PYTHONPATH` no longer leaks and ifcopenshell still imports.
- Measured, so the cost story is not guesswork. `import ifcopenshell` ≈ 1.0 s cold.
  In-process stateless paid it **once per GUI session** (0.94 s, then 0.000 s); kernel
  stateless pays it **per block**. So the old stateless baseline was flattered by
  roughly 1 s per block after the first — order 5–13 s per run against mean run times
  of 82–108 s. Tokens are unaffected. `ifcopenshell.open()` on the mall IFC dominates
  at ≈ 10 s per call and is identical in both runtimes; worker spawn is negligible
  beside it.
- **Stateful results can still shift**, for reasons unrelated to correctness: repeats
  now run in separate processes instead of sharing the GUI's, so cross-repeat module,
  environment, cwd and file carryover is gone. That is better hygiene, not a bug, but
  new stateful numbers are not strictly comparable to old ones. Add ≈ 1–2 s per run for
  worker start plus a genuine ifcopenshell import.
- Added 4 parity/scratch regression tests. 185 offline tests pass. No paid model calls.
- Kernel is now the **default** runtime and the GUI has an Execution runtime switch
  (kernel / in-process) next to Session mode, locked during a sweep, with a note that
  spells out what each one actually resets. The choice is written into the sweep log
  header, passed to the recorder, and applies to *both* session modes — running one arm
  in-process and the other in a kernel would confound the comparison.
- Experiments schema v2: `runtime_isolation` column on `runs` and `configurations`,
  added by an idempotent `ALTER TABLE` so v1 databases upgrade in place. Pre-existing
  rows are backfilled as `inprocess-legacy` rather than plain `inprocess`, because that
  value is inferred (the kernel did not exist) rather than recorded. Shown in the Runs
  and Configurations tables and searchable. Verified on a *copy* of the live database:
  25 runs preserved, 6 configurations, user_version 1 -> 2, original byte-identical.
- `executor` now imports `kernel_executor` eagerly, and `kernel_executor` binds
  `threading.Thread` at import. Without that, `test_gui_presentation`'s global
  `threading.Thread` patch made the worker's reader run inline and deadlocked the
  protocol. Regression test added.
- GUI closes each executor after its repeat and in the sweep `finally`, so kernel
  workers do not accumulate across a sweep; `evaluate.py` closes on both paths.
  `CodeExecutor.close()` is a no-op so callers need not care which runtime they hold.
- 181 offline tests pass. Real GUI checked headlessly: default kernel, switch works,
  control locks during a sweep. No paid model calls, no sweep under the new runtime.
- Added the out-of-process execution kernel: `kernel_worker.py` (child) and
  `kernel_executor.KernelCodeExecutor` (host), chosen via `EXECUTION_RUNTIME=kernel`.
  Default remains `inprocess`, so existing behaviour and results are unchanged.
  `executor.make_executor` is the single construction point; `evaluate.py`, `gui.py`
  and `run.py` use it. Stateless now restarts the worker per block, so modules, env,
  cwd and scratch files genuinely do not carry over; verified against the in-process
  runtime, which demonstrably leaks all four.
- Label validation, receipt text and output assembly moved to shared functions in
  `executor.py` (`normalise_label_map`, `format_label_receipt`, `assemble_output`) so
  the two runtimes cannot diverge. `CodeExecutor` behaviour is byte-identical.
- Worker control channel is a private dup of fds 0/1 taken before any agent code runs;
  agent code cannot read the protocol or forge a reply. Per-block `EXEC_TIMEOUT`
  (default 600s) and worker death are handled separately and both restart the worker,
  telling the model the session was reset. API-key-shaped env vars are dropped from the
  worker environment. This is containment, not a sandbox.
- Skills load and save inside the worker; the host's `SkillLibrary.loaded` is synced
  from the worker's real load outcome. `SKILLS_DIR` env override added because a
  separate process cannot inherit a monkeypatched module attribute. Verified the real
  `get_slab_thickness` preloads in a worker with the manifest left untouched.
- Recorder stores `runtime_isolation` plus disk hashes of the kernel files in the run
  configuration, so kernel and in-process runs get different config hashes and never
  pool. Kernel files are deliberately not in `CORE_FILES`: the worker compiles its own
  copy, so the host's imported-code check cannot attest it.
- 177 offline tests pass (25 new in `test_kernel_executor.py`). No paid model calls, no
  reference/scoring/prompt/harness changes, no production sweep under the new runtime.
- Design review of the stateful/stateless comparison (no code changed). Recorded the
  A/B/C/D condition ladder, kept B as the control that isolates statefulness, deferred
  condition A, and adopted the advisor's kernel-process execution model. See Decisions
  and Open items. Added `slides/build_deck_vol5.py`.
- Skill reuse admission: new saves require a functional contract and three distinct
  normal/edge/changed-input test programs, each executing assertions and a successful
  candidate call without live session fixtures. Obvious embedded IFC paths and
  literal entity lookups are rejected; task-specific settings should be arguments.
  These are self-authored examples and limited static checks, not proof of generality.
- Model-facing skill entries use contracts and uncertainty only, not legacy free-form
  descriptions, origin cases, scores or test fixtures. Provenance remains in metadata,
  history and experiment snapshots. Origin names in arbitrary code cannot be fully
  detected; filesystem introspection is still available to in-process execution.
- get_slab_thickness v2 revision 9ca6b7daf9ad46d1b4d951504b91f773: neutral docstring and
  explicit limitations, retained old test plus synthetic transfer examples. Extraction
  AST unchanged except docstring; original revision preserved. Retest passed and both
  modes still reproduce112labels. This is not an unseen-model validation. No paid calls.
- Follow-up reproduced bug fixes: MiniMax input totals include cache reads/writes
  once; OpenRouter cache is already in input. Per-call usage/stop metadata and
  execution evidence survive later request failures in AgentResult and transcripts.
  GUI/CLI/evaluation record partial results before re-raising/reporting the original
  failure. Missing usage stays unknown; partial sums are excluded from full-run
  means but retained in known totals. No paid calls or historical record changes.
- Recording v2 captures imported module code separately from disk source. Stale or
  uncaptured imports are flagged and excluded from comparable results, even if the
  files do not change during the run. Config identity uses effective run settings
  plus an explicitly disk-only file hash. Not a check of mutable module state.
- Skill tests resolve fixtures on actual reads, avoiding imported/local-name false
  dependencies, and require an assertion to execute successfully. New saves check
  initial private state before testing against fresh installation and reloads;
  differing or unsupported initialization is rejected without replacing the old
  helper. Imported module/external state remains outside this check. Retained mall
  slab helper v1 self-test replay passed without modifying its source or manifest.
- Critical reliability fixes only: completion v2 stages label submissions and
  commits on successful code-block completion. Any uncaught execution failure
  clears labels/validity; a later harmless success cannot restore them. The next
  decided FINAL needs a fresh successful submission. Both modes tested end to end.
- Captured stdout/stderr buffer is bounded; traceback kept separately, so printing
  cannot hide the error. Executed SystemExit is a failed block; KeyboardInterrupt
  propagates while invalidating labels. No worker architecture, timeouts or new UI.
- Agent output events, GUI Execution status JSON and DB counters carry explicit
  error/truncation/label-validity metadata. Factual reports use the flags when
  present and preserve fallback behavior for historical logs. No old logs changed.
- Optional tracing context creation/entry/exit failures no longer abort agent
  work. Genuine body exceptions propagate even if telemetry tries to suppress
  them or its exit raises another exception. No additional LLM calls.
- Still open: safe execution deadlines/resource isolation, unknown expenditure
  on failed requests/SDK retries, and unisolated imported-module/external effects.
  Stateless process isolation remains deferred; reference/scoring policies unchanged.
- Hardened skills: private globals per helper, required asserting invocation test,
  copied session fixtures (including cloned IFC models/entities), reserved Python
  and harness names. Candidate code never installs in the live namespace before
  successful testing and persistence. Failed replacement preserves the old helper.
- Immutable source revisions + retained tests/fixture names/history/hash; atomic
  manifest commit, local cross-process lock and stale-writer protection. Corrupt
  manifests fail visibly and are not reset. Missing/broken/hash-mismatched skills
  are skipped, warned about and omitted from the available-helper prompt.
- Legacy helpers load with an explicit unretained-test warning. Retained tests can
  be replayed via SkillLibrary.retest(name, fixtures); tests are not run on every
  preload. GUI status checks inspect syntax/metadata without executing skill code.
- Renamed the existing skill switch to Use skills and added saved/legacy/unavailable
  counts + Skill details. It enables both loading and saving, defaults from SKILLS
  and remains locked during sweeps. Stateless execution behavior is unchanged.
- Experiment skill fingerprints now use committed revision paths; actual system
  prompt hash is stored on the run separately from the pre-load catalogue hash.
- Resaved the existing get_slab_thickness implementation unchanged via the hardened
  API after an all-112-mall-slab test plus selected missing/boundary/fallback/conflict
  property checks. Format2/version1, archived legacy source retained. Test replay
  and exact112-label agreement with slabv2 verified in both modes. Not validated
  for other models or explicit property-unit overrides. No paid model calls.

### 2026-09-07
- Added SQLite experiments.py + experiment_recorder.py for configurations, sweeps
  and individual attempts. GUI/eval/CLI record before model calls, include failed
  runs, context/skill hashes, audit status and resource usage. Local AppData default,
  EXPERIMENT_DB override, EXPERIMENTS=0 disables recording. No secrets/env dump.
- Experiments tab: sortable, resizable, horizontally scrollable run/config/sweep
  tables; filter, row details, Excel-safe CSV/clipboard, evidence links, SQLite
  backup and explicit interrupted-sweep recovery. No historical auto-import.
- Added Reuse saved skills checkbox, defaulting from SKILLS. Default experiment
  filter uses audited refs + skills-off + H1/2. All other records remain inspectable.
- Added repeatable pilot audit and tests. No new paid agent runs; table previews
  use isolated temporary databases. Exact configurations pool across sweeps;
  missing scores have explicit N and are never manufactured as zero.
- Redesigned desktop GUI in dark mode. Added `gui_widgets.py` for presentation:
  latest-result panel with coherent status/color and separate token/label figures,
  raw-verdict dialog, Scores table with selectable run details and metric guide.
  Score/aggregate displays moved out of Live Log; Markdown score records unchanged.
- Sidebar has case filters, expandable reference details, grouped execution/input
  controls, pinned Run button and settings lock during sweeps. Added Follow output
  checkbox. Initial window fits display scaling; minimum size stays 960x640.
- Added presentation and real-Tk offline workflow regressions for both modes,
  settings, scoring, original logs and factual reports. Checked small-window
  screenshots, long captions, incomplete states and dark dialogs. No provider calls
  or checking-pipeline/scoring/skill behavior changes. Restart GUI to load redesign.
- Repaired slab reference as a new v2 case with 112 provenance records and an IFC
  hash; preserved legacy labels. Changed future GUI pilot and generator routing.
- Added completion v1 checks to all final acceptance paths; label repair is now
  allowed during bounded finalization. Added explicit status to GUI logs, offline
  reports, eval JSON, CLI transcripts and traces. No scoring-policy changes.
- Added `factual_report.py`: standalone, standard-library reader of GUI Markdown
  logs, with no LLM calls or checking-pipeline changes. Writes sibling
  `*.report.html` files with results, conditional-average denominators, submitted
  label counts, execution attempts/errors, budget/truncation warnings, expandable
  code/output and unverified explanation excerpts with source-line links.
- GUI closes the sweep log, then opens a compact Factual Report tab. Detailed
  reports open locally in the browser; Report From Saved Log supports older runs.
  Reporting failures remain separate from run results. Original logs unchanged.
- Added offline reader/HTML/GUI tests, including interrupted and legacy logs,
  escaped untrusted content, missing submissions and Windows console Unicode.
  Console text uses backslash replacement for unsupported characters; HTML keeps
  UTF-8. No labels or reference validity are inferred from printed claims.
- Generated reports for the user's Sept 7 pilot sweeps: slabs submitted labels
  in 2/3 runs (conditional union accuracy .661); condo in 2/4 (conditional union
  accuracy 1.0; mean F1 .75). Both used M3/stateful/harness1 with a 14-step budget.
- Investigated pilot score variation using saved runs and offline runtime probes.
  Found the 59-stair/49-label scope mismatch and reproduced completion/scoring gaps.
- Corrected geometry-unit guidance and code-before-verdict ordering in finalization.
  Added four passing offline regression tests. No new agent quality scores measured.
- Updated README pilot warnings; preserved existing GT and scoring semantics.

### 2026-08-18
- Audited `slab_thickness__mall` end to end against the raw IFC. All 50 non-PASS
  labels are wrong; geometry says all 112 slabs pass. Case is unusable as scored.
  Recorded under Findings, with the multi-source GT design under Decisions.
- Assessed LangChain deepagents against the codebase and the exposé. Recorded under
  Findings and Decisions above. Nothing built.
- Created this file.
