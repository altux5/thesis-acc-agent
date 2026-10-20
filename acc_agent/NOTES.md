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

- **2026-10-13 - final evaluation, frozen v5/v5.1 (OpenRouter, reasoning off, H1, 20
  calls; usable_2 + staircase width).** MiniMax M3: 66 runs, 3 per case and mode
  (recording v5, plus 4 exit scdf_5 reruns on v5.1); Sonnet 5.5: 44 runs, 2 per case
  and mode (v5.1). The 4 crashed v5 runs (malformed tool calls) are excluded and were
  rerun; the fix did not trigger in any v5.1 run.

  | model / mode | finished | complete | abst. | incompl. | mean acc | calls | input | cache | cost | min/run | s/block |
  | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
  | MiniMax stateful | 33 | 29 | 2 | 2 | 0.894 | 13.9 | 184k | 81% | $1.00 | 4.6 | 1.8 |
  | MiniMax stateless | 33 | 31 | 0 | 2 | 0.900 | 14.1 | 222k | 83% | $1.29 | 8.3 | 5.7 |
  | Sonnet stateful | 22 | 22 | 0 | 0 | 0.920 | 10.8 | 158k | 87% | $2.88 | 2.3 | 1.7 |
  | Sonnet stateless | 22 | 22 | 0 | 0 | 0.946 | 10.9 | 180k | 85% | $3.99 | 3.5 | 7.4 |

  - Stateful vs stateless: no accuracy difference for either model (within run-to-run
    spread). Stateless costs more: 13-20% more input tokens, longer runs, and 3-4x the
    code time per block (worker restart and IFC reload: 1.7-1.8 s vs 5.7-7.4 s median).
    Call counts are the same.
  - Model: Sonnet completes 44/44 (MiniMax 60/66) with fewer calls and resolves what
    MiniMax does not: landing mall trap 0.99 vs 0.77-0.78, staircase width 0.85-0.95 vs
    0.61-0.78, planter 1.00 vs 0.88, landing scdf_5 trap 1.00 in 3 of 4 runs vs 0.92 in
    all 6. MiniMax is better on exit scdf_3 (mostly 1.00 vs Sonnet 0.75-0.92). Exit
    scdf_5 stays low for both (0.56-0.82). Easy cases are 1.00 for both.
  - MiniMax: 16 output-limit cutoffs (reasoning loops, OpenRouter); Sonnet: none.

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
  A run that reads these the way 7 of 8 runs did scores at most 27/39 = 0.69, so scdf_5
  does not separate the models. (2026-10-13: runs that read some of these rows
  differently reached 0.74 and 0.82, so 0.69 is not a hard ceiling.) Needs a decision
  on the case text or reference, not an agent fix.

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
  then a local connection loss. (Corrected 2026-10-13: the first interruption was a
  malformed tool call sent back to the provider, not an outage; see Changelog.)
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

- **2026-10-20 - IFC models distributed in `acc_agent/models/` (user).** The thesis cites
  the thesis-acc-agent repository, so it must contain the models. All 20 model paths
  stored in ground_truth/*.json (plus the GUI default) map to 16 unmodified files
  (322 MB; the bca_tests-main and harness_improvements copies were byte-identical):
  `ec3/` (EC3 repository models, CC BY 4.0 / KIT unrestricted use), `heldout/`
  (Esplanades CC BY 4.0, Schependomlaan academic use, kleine Wohnung and NUS from the
  web-ifc test files, MPL-2.0 repository), `bca/` (bca_tests, MIT). `MODELS.json` maps
  each stored path to its file with SHA-256; `ground_truth.resolve_model_path` looks
  there first, so the reference JSONs (and their hashes) are unchanged and other
  paths (BCA workbooks, Solibri exports) still resolve to `gitignore/`. Licence and
  attribution files sit next to the models (`SOURCES.txt`). `tests/test_models.py`
  checks every reference model is present and byte-identical (including the frozen
  `ifc_sha256` of the held-out references). The originals in `gitignore/` stay. In tez
  the IFC files are git-ignored; the publishing repo tracks them (one `.gitignore`
  exception). New runs record the new absolute IFC path; the IFC hash is unchanged.

- **2026-10-20 - GPT-6 Luna tests (user, before deciding its held-out run).** Model id
  `openai/gpt-6-luna` via OpenRouter needs no code change (free model field; `load_llm`
  accepts any OpenRouter id). Reasoning: the frozen setting `reasoning: {enabled: false}`
  is ignored by Luna; single calls returned about 30 reasoning tokens with
  enabled false, enabled true or no field, 23 with effort "minimal", 0 with effort
  "none". Agent tests, 5 held-out cases, stateful, outside any suite:
  (a) frozen setting (Luna reasons, `reasoning_content` in most replies): 5/5 complete,
  4/5 exactly correct (stair_slab_connection__wohnung wrong), 4-14 calls, 0.2-1.7 min,
  $0.017 in total; runs f2e632d3, d12e1aea, 1595c064, 7d39f99d, 1696ba02.
  (b) effort "none" via a temporary in-memory patch of `llm.with_reasoning` (no file
  changed; recorded configuration still says reasoning false): 3/5 complete and
  correct, 2 abstained at the 20-call cap (stair_slab_connection__wohnung,
  door_front_clearance__fzk), up to 18 calls on an easy case; runs b00e1012, 180cfc09,
  915a354e, 9f976e1e, 824d6089. No reasoning content in any reply. Decision pending:
  run Luna with the frozen setting (provider-default reasoning, documented) or add an
  explicit effort "none" mapping (changes `llm.py`, a frozen file).
  - **Decision (user): option A**, frozen setting. Checked against recorded replies:
    via OpenRouter, the "reasoning off" setting did not stop reasoning for other models
    either: Sonnet 141 of 243 replies (first 30 runs) carry reasoning text (median 240
    characters), M3 pilot 1 via OpenRouter 329 of 479 (median 718). Via the direct
    MiniMax API it is honoured: 0 of 1965 replies in the M3 main run. So M3 main, planning
    step and later MiniMax runs ran without reasoning; all OpenRouter runs (calibration,
    pilot 1, Sonnet, Luna) with the provider's reasoning. State this in the thesis.
  - Reasoning effect estimate from existing data (M3 stateful, same 95 cases): pilot 1
    via OpenRouter (reasoning text, 1 run) vs main run via MiniMax API (no reasoning,
    2 runs): complete 64 % vs 61 %, exactly correct 54 % vs 46 %, accuracy of complete
    runs 0.916 vs 0.874, output tokens per run 17.3k vs 9.9k. Per case: completion 16
    better / 12 worse (p = 0.57), exact 17 / 6 (p = 0.035). Confounded with provider
    (OpenRouter had output-limit cutoffs and multi-call replies) and run count. Mode and
    planning-step comparisons are unaffected (all within the no-reasoning MiniMax API
    runs). The calibration vs held-out comparison for M3 changes provider and reasoning
    together. A clean check, if wanted: M3 via MiniMax API, stateful, REASONING=1
    (thinking enabled; setting only, no code change), 2 x 95.
  - **Reasoning-on run plan (user, 2026-10-20), fixed before the run:** M3 via MiniMax API
    with reasoning on (`thinking: adaptive`, set per suite button; no frozen file
    changed), H1, frozen budget, all 95 cases: stateful x1 and stateless x2 (two GUI
    buttons, suite index kinds `heldout_m3_reasoning_stateful` / `_stateless`). Analysis
    (user decision): stateful with reasoning = this run + pilot 1 (OpenRouter, reasoning
    text present), stateless with reasoning = the two new runs; compared per case with
    the main run (no reasoning, 2 + 2). The user accepts the provider difference in the
    stateful arm because the question is the reasoning effect. Smoke test
    stair_riser_height__duplex: stateful (bd8f5f6d) and stateless (16145d10) complete,
    1.0, thinking blocks in 15/18 and 5/8 replies. LangChain warns that forced tool use
    is dropped when thinking is on (the Anthropic API does not allow both), so with
    reasoning the model may answer without a tool call; that is part of the condition,
    as for Claude via OpenRouter.
  - GUI cleanup (user): removed the pilot, main, Sonnet, 95-case and 7-case (no staircase)
    suite buttons; kept the 8-case health suite, usable_2 suite, extra planning step,
    Luna and the two reasoning-on buttons. Old suite indexes and results are unchanged.
  - **Luna held-out run plan, fixed before the run:** `openai/gpt-6-luna` via OpenRouter,
    stateful + stateless, 2 repeats, all 95 cases, H1, frozen agent and budget, REASONING=0
    as everywhere (Luna reasons at its default). Run on the second machine (user "PC");
    suite index kind `heldout_luna`. Compared with M3 and Sonnet on completion, exact
    correctness, accuracy, calls and tokens; its mode timing only within that machine.

- **2026-10-20 - second Windows machine for the OpenRouter lane (user).** The tez remote
  is the old public repo and is not pushed. Transfer package, local and not synced:
  `C:\Users\Cogalgil\acc_transfer\` with `tez.bundle` (git bundle of `main`, including this
  entry, verified) and `gitignore/` holding the 8 held-out IFC models (+ SOURCES_AND_CITATIONS),
  all SHA-256 equal to the frozen references. The recorded runtime packages are all
  pinned in `acc_agent/requirements.txt`; use Python 3.13.7. Own `acc_agent/.env` on that
  machine; its experiment database is separate and is merged afterwards. Record per suite
  which machine ran it.
  - Route chosen (user): published to `altux5/thesis-acc-agent` main at f8dfba9 (v5.1
    agent, held-out references, GUI buttons; 252 tests OK, 17 skipped for local data not
    distributed). The second machine (user "PC") clones it and takes the IFC models from
    `acc_transfer\gitignore` into `<clone>\gitignore\` (ignored by git there). Keep Git's
    default `core.autocrlf=true` so files have the same bytes; code hashes of imported
    modules include the file path and differ between machines, raw file hashes match.
  - Second machine verified 2026-10-20 from its database (copied to `tez/experiments.sqlite3`,
    integrity ok, no id collisions with the main database): one GUI test run
    (space_storey_elevation__nus, M3 via OpenRouter, stateful) on the same Windows 11
    build, Python 3.13.7 and identical recorded package versions; all core files, kernel
    files, config, IFC hash and reference hash byte-identical to this machine; runtime
    verified, usage complete. Clone at `C:\Users\PC\Desktop\thesis-acc\thesis-acc-agent`.
    The test run is outside any suite.

- **2026-10-20 - parallel-run timing test (user request).** Laptop: i5-1145G7, 4 cores /
  8 threads, 15.7 GB RAM. Fixed benchmark (open NUS IFC + 120 slab shapes, no API): alone
  10.9-15.9 s (median about 12.5 s, first run cold 17.5 s); two copies at once 13.0-17.1 s
  (median about 14.7 s), about 15-20 % slower. Real runs: two `evaluate.py` runs started
  together, M3 via MiniMax API and M3 via OpenRouter, slab_thickness_range__nus, stateless
  (every block reloads the NUS model, so near worst case): code block median 13.1 / 12.9 s
  against 9.2-10.6 s in the three solo runs of the same case and mode (17-18 Oct), about
  25-30 % slower; model time unchanged (0.5-0.8 min). Both runs complete (0.98 / 0.99).
  These two test runs are outside any suite. Consequence: parallel suites inflate code
  time noticeably when both do heavy geometry; keep both arms of any timing comparison
  under the same conditions, and run timing-critical experiments (file system) alone or
  on the second computer's lane split.

- **2026-10-20 - advisor meeting: experiment plan extended (advisor and user).** Nothing
  built yet; each new arm needs its own written design and freeze before held-out runs.
  - Experiments of the thesis: (1) stateful vs stateless; (2) model comparison;
    (3) extra planning step (advisor: do not call it "harness level" or "H2" in slides or
    text); (4) virtual file system; plus (5) a larger budget for the hard cases.
  - (4) File system: the advisor's reference is the Deep Agents example in
    `03_agents.ipynb` (TUM Hands-On 4, appendix A.2): LangChain `deepagents` with
    `write_todos`, file tools `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`
    and subagents (`task`); files are virtual and live in the agent state by default.
    Advisor expects better efficiency, especially on 3D geometry runs, and a better
    stateful/stateless comparison. Candidate mechanisms: reusable code written once and
    edited instead of resent (stateless resends full scripts), intermediate results
    saved instead of recomputed, large outputs kept out of the context, and possibly a
    labels file instead of restating long FAIL lists (that changes the submission
    protocol). Possible third execution arm: stateless execution with persistent files.
    Open: Deep Agents framework or file tools on the existing agent; whether the
    FinalReport may reference a file; whether the existing working folder persists
    across stateless blocks.
  - (5) Larger budget (user proposal, advisor agreed): rerun the hard cases with 30-40
    model calls instead of 20 and observe completion and correctness. Select the hard
    cases by a pre-defined criterion (e.g. complexity class 3, or class 2-3), not by
    agent outcomes, to keep the comparison clean.
  - (2) One more LLM (advisor): a GLM model or GPT "Luna". The notebook uses
    `z-ai/glm-5.3-flash` and `openai/gpt-6-luna` via OpenRouter (USD 0.05/0.20 and
    0.10/0.50 per M input/output tokens, Oct 2026); the exact model id is still to be
    chosen. A GLM model also links to the EC3 paper, which used GLM-4.7.

- **2026-10-13 - held-out Solibri test set is the main experiment (user).** The 11 frozen
  v5 cases become design/calibration; results on them are reported as such. Test set:
  4 Solibri-derived rules on 3 new public models, about 10-12 cases. Models in
  `gitignore/heldout_models/` (sources, licences, SHA-256 in SOURCES_AND_CITATIONS.txt):
  Clinic (Revit 2011, IFC2x3), Schependomlaan (ArchiCAD, IFC2x3, mm, Dutch psets),
  Smiley West (ArchiCAD 20, IFC4); KIT Institute is reserve/practice, Duplex pipeline
  pilot only. Rules, each reduced to one stated requirement: (1) door clear width
  >= 900 mm (DIN 18040-1; SOL/208), class 1-2; (2) free area in front of doors
  (SOL/226), class 3; (3) stair riser/tread (DIN 18065; SOL/210), class 2; (4) room
  clear height >= 2.40 m (SOL/202), class 2, cut first if time runs out. Optional
  SOL/236. Protocol: thresholds from the standard, not tuned to outcomes; at most 1-2
  zero-violation controls; case selection may use reference outcomes, never agent
  outputs; rule texts, references, `.cset`, Solibri exports and model hashes are
  committed before the first agent run; no agent change afterwards. Matrix as frozen:
  both modes, MiniMax M3 x3, Sonnet 5.5 x2 (about $0.16/Sonnet run, $0.04/MiniMax run).
  Solibri Office 26.9.0.123; working files and settings log in `gitignore/solibri_work/`.
  - SOL/208 finding (KIT Institute practice run): with default frame and panel
    thickness 0 and "Use spaces" off, Solibri reported 900 mm for doors with
    OverallWidth 1000 and type `IfcDoorLiningProperties.LiningThickness` 50, i.e.
    clear width = OverallWidth - 2 x LiningThickness. 67/67 expected issues at a
    1100 mm test limit. Double-door behaviour not yet verified.
  - SOL/208 on Schependomlaan (900 mm, threshold disabled at 99999): 50 issues, report
    `solibri_work/door_width__schependomlaan.xlsx` (has GUIDs). All 104 doors with
    OverallWidth agree with "OverallWidth - 2 x LiningThickness, else OverallWidth"
    (incl. 1034 - 2 x 67 = 900 PASS). Without lining data Solibri measures the door
    geometry incl. frame (680 -> 795), same labels here. The 101 width-less objects are
    36 `liftdeur` panel parts (28 flagged at 150/332/500 mm from geometry, 8 passed)
    and 65 `stelkozijn` sub-frames (none flagged, even 30 mm wide), so Solibri's
    outcome there is not a statable convention. Decided (user, 2026-10-13): score the
    104 real doors, leave the 101 width-less objects in scope but unscored
    (annotated_subset), as for the headroom lift doors. Mention in the thesis.
  - Role for all reference runs: Get Started (loads no classifications). The
    Schependomlaan export made under Example Rules stands (user, 2026-10-15): SOL/208
    uses no classification here and all 104 scored doors match the IFC convention.
  - SOL/208 Smiley West: 170/170 doors agree with the convention (90 FAIL, 80 PASS).
    Clinic: 252/254 agree (8 FAIL = toilet-partition doors 865 mm). The 2 curtain-wall
    doors (no host wall) are measured from geometry at 899.55 mm and flagged; within
    the 0.5 mm protocol tolerance, so adjudicate PASS. Solibri also reported 3 empty
    `IfcOpeningElement`s as doors (outside the IfcDoor scope, ignored).
  - 2026-10-15: same 0.5 mm tolerance as every calibration reference (user), so the 2
    curtain-wall doors (OverallWidth 899.55) are PASS, adjudicated in
    [solibri_reference.py](solibri_reference.py). Cases `door_clear_width__{clinic,
    schependomlaan,smiley}` written (8/246, 22/82 +101 unscored, 90/80 FAIL/PASS),
    tier `heldout` in the GUI ("Held-out" filter and suite button) and benchmark audit;
    `--check` regenerates them from the Solibri reports, whose SHA-256 and the `.cset`
    hash are recorded in each case. Evidence files stay in `gitignore/solibri_work/`.
    DIN 18040-1 clause verified 2026-10-15: 4.3.3.2 "Maßliche Anforderungen", Table 1
    row 1, all doors clear width >= 90 cm (full text: Nds. MBl. Nr. 37 q/2012, p. 10,
    https://www.niedersachsen.de/download/127059/Nds._MBl._Nr._37_2012_vom_30.10.2012_Anlagenband_37q.pdf).
    Applicability to housing is not stated in the rule text (user: the study tests
    agent capability, not legal applicability).
- **2026-10-16 - EC3 held-out cases: labels from Solibri issues, one source (user-approved
  plan, implemented in [solibri_reference.py](solibri_reference.py) `build_ec3`).**
  12 rules x 5 models (Clinic, Duplex, FZK House, Smiley West from the EC3 package;
  Schependomlaan) plus 3 new models still to find (target 4 EC3 + 4 new). Clinic and
  Smiley use the EC3 IFC copies (`ACC-function-generation/acc/bim_models/<m>/arc.ifc`);
  door clear-width cases regenerated on them with identical labels.
  - Source: our own Excel export (template Issue and Components) of the EC3 `.smc`
    rule sets for every model, not their BCF `topics.json`: 7 Clinic Space Validation
    topics there have an empty message, so message-based labels would miss them. A
    rule name occurring twice in a report is not read.
  - Labels: FAIL = a scope element listed by an issue of the Solibri rule whose text
    matches the rule's message; PASS = every other scope element. Not their first-match
    GT: it drops "non-uniform at beginning", "not connected to slab at the beginning"
    and lets "inside" hide "intersect". Differences from EC3 GT are by design.
  - Single-subject issues (stairs, door clearance, space validation, guarded slabs): an
    issue listing several scope elements does not say which one fails (component order
    in the report is alphabetical by type; Solibri names like Door.-1.142 are not in
    the IFC). Those elements are unscored unless another issue fails them. Schependomlaan:
    62 of 205 doors (clearance), 15 slabs (guarded "adjacent landing" issues).
  - Roof slabs: Solibri classifies IfcSlab ROOF as Roof (its Roof Thickness rule flags
    them, Slab Thickness never does). Slab thickness and guarded cases label them NA,
    stated in the rule text.
  - Thresholds stated as Solibri applies them: ADA 504.2 in inches (177.8 / 101.6 /
    279.4 mm, seen in its messages); slab thickness 30-1000 mm; elevation: when a storey's
    spaces differ at all (6 mm on Duplex flagged), every space of that storey fails
    (Clinic first floor 153 + 1, Duplex all 20 checked against geometry).
  - Known rules on new models: `doors_windows_storey` reuses the calibration text
    verbatim (Schependomlaan: 390 orphans and 74 hosted, incl. 14 proxy hosts, match the
    calibration semantics exactly); `slab_thickness_range` and `space_storey_elevation`
    keep the requirement but state Solibri's parameters, so they are the same rule
    family, not identical prompts.
  - Spot checks against the IFC: Schependomlaan slab thickness 3 FAIL = the 3 floor slabs
    under 30 mm (8/10/18 mm), roof slab 8 mm excluded; elevation PASS on Schependomlaan
    and Smiley (one bottom per storey); Smiley stairs rise 347.5 mm per step in the
    geometry (Solibri 347-348), treads 250 mm.
  - Excluded: the four stair rules on Schependomlaan. Solibri reads every flight with
    1313 mm risers (geometry: about 188 mm) and flags non-uniform steps on 3 of 6
    identical flights, so its issues are no reference there.
  - Adjudicated: 10 Smiley stairs flagged only "beginning 348 mm, elsewhere 347 mm" are
    PASS for uniform risers; the geometry rises 347.5 mm at every step (display rounding).
  - Geometric class-3 judgements (clearance, guarded, unallocated, space validation) are
    Solibri's and not recomputed, as in the EC3 paper. Smiley riser/tread cases are all
    FAIL (30 stairs), uniform 20/10. Many Smiley/Schependomlaan cases are all PASS.
  - ifcopenshell on Schependomlaan: 94 of 100 spaces have only a footprint curve set and
    bounding box (no solid), so geometry-based space rules must use the bounding box.
  - GUI: every generated case of `solibri_reference.BUILDERS` is Held-out; the suite
    holds the cases whose JSON exists.
  - 2026-10-16 (user): slab thickness stays at Solibri's 0.03 m; the user tells the
    advisor that EC3's template and paper state 0.30 m. Unscored ambiguous elements and
    the Smiley/Schependomlaan stair decisions stay, recorded here with reasons.
  - Clinic, Duplex, FZK exports added (their `arc.smc`, 2026-10-16). Parser now counts
    report component rows without a GUID (the model itself, rule Required Components).
    Stair readings agree with geometry: Clinic risers 176 mm, treads 280 mm (PASS), all 3
    stairs unconnected at both ends; Duplex 194 mm / 252 mm (FAIL); FZK spiral tread
    136 mm, last riser 50 mm. Solibri measures the first and last riser to the floor
    slabs (Duplex 0.17 / 0.19 / 0.21 m while the flight is a uniform 194 mm), now stated
    in the uniformity rule text.
  - Agreement with the EC3 published ground truth on the 4 EC3 models: 46 of 48 rule x
    model FAIL sets identical. Differences by design: Clinic clearance (EC3 fails both
    doors of the 5 door-door issues, we leave the 5 unidentified doors unscored) and
    Clinic intersection (14 spaces EC3 assigns only to "inside" by first match). EC3's
    extraction takes every element of the extraction class listed by a matching issue,
    so it counts both doors; ours does not guess. Mapping Solibri names (Door.-1.452.1)
    to GUIDs through unambiguous issues resolves only 3 of 39 Schependomlaan and 0 of 5
    Clinic door-door issues, so not used.
  - Composition after 5 models: 59 cases; 24 without FAIL, 8 without PASS, 27 with both
    (user: all-PASS cases are fine as false-positive tests, but not a majority). Several
    stair cases have 1-3 stairs (FZK 1, Duplex 2, Clinic 3).
  - Pending: 3 new models (their exports plus stair sanity check), then freeze.
  - 2026-10-16 (user, option A): known rules are reported in two groups.
    `doors_windows_storey` = same prompt, new model (calibration text verbatim, Solibri
    semantics identical). `slab_thickness_range` and `space_storey_elevation` = same
    check, new parameters: the prompts state Solibri's conventions (30-1000 mm,
    geometry when unrecorded, roof slabs NA; every space of a storey with any
    difference fails) instead of the calibration ones (100-1000 mm recorded property,
    ALERT; >10 mm from the storey majority). They test whether the agent follows the
    stated convention rather than its calibration behaviour. Rejected: B (calibration
    texts with our own labels, no longer Solibri-derived) and C (treat as new rules).
  - 2026-10-16: three new models selected after a survey of 20 public models
    (survey script and downloads in `gitignore/heldout_candidates/`, sources, licences
    and SHA-256 in `heldout_models/SOURCES_AND_CITATIONS.txt`). Checked: element GUID
    overlap with all 12 EC3 models and Schependomlaan, entity classes and names,
    doors/windows hosted and in the host's storey, door widths and lining, stair
    structure and geometry, space and slab naming, ifcopenshell geometry.
    - Esplanades (Estonian apartment block, ArchiCAD 22, IFC2x3, CC BY 4.0): 211 doors,
      297 windows, 15 slabs + 80 IfcRoof, 4 stairs (flights 160 / 300 mm), 285 spaces,
      846 walls, 37 columns; all doors/windows hosted, no storey mismatch. Handrails
      partly as proxies; 2 roof windows hosted by IfcRoof.
    - kleine Wohnung (German apartment house, Revit re-saved by BlenderBIM, IFC4): 47
      doors, 52 windows, 53 slabs (36 floor finishes "FB 10.0" + structural), 2 stairs
      (200 mm per step), 28 rooms, 211 walls. Clean. Source: web-ifc public test files,
      no model licence.
    - NUS school (Norwegian school, Revit 2019, IFC2x3): 310 doors, 266 windows, 126 slabs
      (landings typed LANDING), 13 IfcStair, 307 spaces, 1057 walls, 34 curtain walls,
      ceilings correctly as IfcCovering. Caveats: 25 IfcSpace "Area" objects are
      whole-floor GFA zones overlapping the rooms; 2 amphitheatre stairs are nested
      IfcStair-in-IfcStair; folding partitions (6.5-9.7 m) are IfcDoor. Same licence
      status as kleine Wohnung.
    - Rejected: Samuel Macalister = Revit rac_basic_sample_project (2122 shared GUIDs, an
      EC3 test model); 4351 is from opensourceBIM TestFiles (EC3); HITOS (about 190
      ceilings modelled as IfcSlab); Molio (579 IfcStair, one per riser); Holter Tower
      (3572 consoles as IfcSlab); Janesville restaurant (stairs nested and outside
      storeys, 4 without geometry); LTU A-House, S_Office, advanced_model, Jesse,
      ISSUE_126 (no IfcSpace); HouseZ (no names, doors not hosted); Mini Project
      (structural only); KIT Haus G-H, Jasmin-Sun, niedriha (clean but small, kept as
      fallback). Sixty5 (SDK S1) needs a Trimble browser download (hundreds of MB).
  - 2026-10-16 (user): Esplanades, kleine Wohnung and NUS accepted; licensing fine; no door
    clear-width cases for them. Exports `ec3_{esplanades,wohnung,nus}_check.xlsx`. Model
    ids `esplanades`, `wohnung`, `nus` in `solibri_reference.MODELS`.
  - Unscored by stated policy (`solibri_reference.UNSCORED`, reasons stored per case):
    - NUS: the 25 IfcSpace "Area" GFA zones in every rule (user). They share the storey
      floor elevations, so they do not cause the NUS elevation flags (Plan 01 fails for
      one room at 131001.5 vs 131200). They do fill floor area, so Solibri reports no
      unallocated area on NUS; with the rule text ("occupied by no space") an agent
      treating them as spaces gets the same answer.
    - Doors/windows that are parts of an IfcCurtainWall (no opening): Clinic 5, NUS 8.
      Solibri relates them to the curtain wall (PASS); the verbatim calibration text
      makes them orphans (FAIL). Found by recomputing the calibration semantics on all
      7 models: every other door/window agrees with Solibri. So the "same prompt" claim
      holds for all scored elements.
    - IfcStair nested in another IfcStair (NUS amphitheatre, 2): Solibri reports the parent.
  - Adjudicated (geometry vs Solibri display rounding, stair_uniform_risers): Esplanades
    4 stairs ("160 vs 159 mm"; first riser from the storey floor 159.5 mm like the rest)
    and NUS Assembled Stair 4960365 ("168 vs 167 mm"; all risers 166.6-166.7 mm) -> PASS.
    Not adjudicated: NUS Assembled Stair 4959975 measures 118.7 mm from the storey level
    to its first tread (typical 168.8) but the floor finish under it is unknown and
    Solibri reports no difference, so its PASS stands.
  - Stair sanity (Solibri vs geometry): NUS cast-in-place treads 272 mm FAIL, amphitheatre
    riser 333 mm FAIL; kleine Wohnung risers 200 mm FAIL; Esplanades 159.5 / 300 mm PASS.
  - kleine Wohnung: every room contains its 100 mm floor-finish slab ("FB 10.0") inside
    the room volume, so space_contains_components is 28/28 FAIL (consistent with the rule).
  - NUS slab thickness: 25 stair tiles (5 mm) and 7 doormats (25 mm) modelled as IfcSlab
    fail, as the Schependomlaan mats do.
  - Esplanades export lacks the "BIM Validation - Architectural" rule set (41 rules vs 83),
    so its 5 BIM Validation cases (clearance, doors/windows, slab thickness, guarded,
    unallocated) need a re-export with all four rule sets checked.
  - State after the new models: 90 held-out cases (3 door clear width + 87 EC3), audit clean,
    all regenerate identically. 40 without FAIL, 10 without PASS, 40 with both.
  - 2026-10-17: Esplanades re-exported with all four rule sets (81 rules). The user's
    separate `esplanades_BIM Validation - Architectural.xlsx` gives identical issues for
    the 5 BIM Validation rules; kept as a record, not used. New Esplanades cases:
    clearance 1/210, doors/windows 0/508 (the 2 roof windows are hosted by IfcRoof and
    pass in both Solibri and the calibration semantics), slab thickness 0/15, guarded
    10/5, unallocated 138/745 (FAIL/PASS). All 12 Esplanades cases audit clean.
  - Complete held-out set: 95 cases (3 door clear width + 12 rules x 8 models - 4 excluded
    Schependomlaan stair cases). `solibri_reference.py --check` regenerates all identically.
    42 without FAIL, 10 without PASS, 43 with both. Next: freeze.
  - Pre-freeze review 2026-10-17: the 8 core agent files and the runtime package set are
    identical to the last frozen v5.1 run (2026-10-13); 95/95 cases parse to the intended
    scope classes, use only scoring labels, carry the builder's rule text and tier;
    REVIEW_DATE set to 2026-10-17 and all cases regenerated. IFC open times: NUS 12.8 s,
    Schependomlaan 11.3 s, others 0.5-3.3 s (stateless reloads each block); multi-core
    geometry for 1800 NUS walls/slabs/spaces/doors takes 31 s, serial about 2 min, inside
    the 600 s block limit. Scored populations range from 1 stair (FZK) to 1124 walls
    (NUS unallocated).
  - Protocol amendment (user, 2026-10-16): the 2026-10-13 plan allowed at most 1-2
    zero-violation controls among about 10-12 cases. With 12 EC3 rules on 8 models,
    all-PASS cases are accepted as false-positive tests as long as they are not the
    majority (42 of 95). Report results per case and per group (EC3 models vs new models,
    known rules, rule complexity class), with all-PASS cases separate from mixed ones.
  - **Frozen 2026-10-17** in local commit `2da536d` (not pushed: the remote is the old
    public repository). Model files and Solibri reports stay in `gitignore/`; every case
    records their SHA-256. Office lock files (`~$*`) are now git-ignored.
  - First pass (user, 2026-10-17): MiniMax M3 via OpenRouter, stateful, 1 repeat, H1,
    reasoning off: 95 runs (estimated about 7-11 h, about $3-6). GUI button "Held-out
    pilot" fixes these settings, writes suite indexes of kind `heldout_pilot` and offers
    to resume with the cases not yet finished in earlier pilot sessions. Decide further
    repeats, stateless mode and Sonnet after this pass.
  - Pilot result 2026-10-17 (suite `20261017-012814-102231`, settings as planned, reasoning
    off): 95/95 finished, no errors, 5.6 h (median 2.6 min/run), 18.7M input tokens (87 %
    cache reads), 1.6M output. 61 complete, 23 incomplete, 11 abstained; mean union
    accuracy of complete runs 0.92. Class-1/2 rules mostly complete and correct (slab
    thickness 8/8, doors/windows 7/8, risers 7/7, treads 7/7); the geometric class-3 rules
    mostly do not complete (clearance 1/8, space intersection 0/8, guarded 3/8,
    unallocated 3/8, space inside 5/8).
  - The 5 complete runs below 0.8 are agent errors, re-checked against the IFC: Esplanades
    treads (agent divides flight length by tread count, geometry 300 mm) and uniform
    risers (agent measures from the flight bottom 14200, the floor slab top is 14300, so
    the first riser is 159.5 mm as adjudicated); FZK slab connection (top tread 2650
    arrives at the Dachgeschoss slab top 2700; the agent took the 3500 mm surface above);
    kleine Wohnung inside (the 100 mm floor finish 503.0-503.1 lies inside rooms
    503.0-505.75, the agent treated it as bounding); Esplanades inside (agent over-flags
    170 of 285 by ray casting).
  - New MiniMax behaviour on the held-out tasks: 9 runs ended at the 20 run_python cap after
    1-11 model calls because single responses contained many code blocks (up to 46),
    written without seeing outputs; they run sequentially as designed, so these are valid
    incomplete runs. Output-limit cutoffs 59 of 1395 calls (4.2 %, calibration 1.6 %),
    malformed tool calls in 11 calls (calibration 0).
  - Second pass (user, 2026-10-17): same 95 x 1, stateless, via the direct MiniMax API
    (`provider=minimax`, model `MiniMax-M3`, Anthropic-compatible endpoint, thinking
    disabled by REASONING=0) to see whether it runs faster; provider differences accepted.
    Smoke test: plain reply in 1.8 s with no thinking block, one run_python tool call in
    1.6 s, automatic prompt-cache reads. GUI: `HELDOUT_PILOTS` defines both passes, one
    button each, resume per suite index kind (`heldout_pilot_stateless_minimax`).
  - Second pass result 2026-10-17 (suite `20261017-102839-754344`): 95/95 finished, no
    errors, 6.8 h summed (median 3.1 min/run), 18.5M input (89 % cache), 1.15M output.
    63 complete, 20 incomplete, 12 abstained; mean union accuracy of complete runs 0.88.
    Not faster: model time is equal (2.56 h both; 6.0 vs 6.6 s per call, but 16.1 vs 14.7
    calls per run), while code execution rose from 2.9 h to 4.1 h (stateless reload,
    median block 2.7 vs 1.2 s); 45 runs reached the 20-call cap (pass 1: 28). The direct
    API changed reply shape: always exactly one tool call per reply, no output-limit
    cutoffs (pass 1: 49), no invalid tool calls (pass 1: 5), no run_python-cap endings.
    Provider and mode changed together, so these differences are not attributable to one.
  - The 10 complete runs below 0.8 are agent errors, re-checked against the IFC:
    kleine Wohnung risers (agent reads 170 mm, flights rise 15 x 200 mm from 503.0 to the
    506.0 slab top) and uniform risers (agent takes the 506.17 stair-part top as the
    arrival floor); Clinic uniform risers (floor 4.570 = 26 x 175.8 mm, agent uses 4.52);
    Smiley uniform risers (agent's last riser of about 1 m up to the stair-part top; the
    10 adjudicated PASS stairs flagged too); FZK treads (agent measures the 750 mm outer
    going of the spiral stair); FZK slab connection (same 3500 mm surface error as pass 1);
    FZK unallocated (the 1.39 m2 strip is exactly Wand-Int-ERDG-3); Schependomlaan
    intersection (bounding boxes); Smiley intersection (agent finds none; reference equals
    EC3 published ground truth); Esplanades guarded (convex-hull footprints).
  - **Main held-out run plan (user, 2026-10-17), fixed before any run:** MiniMax M3 via
    the direct MiniMax API (`provider=minimax`, `MiniMax-M3`), H1, reasoning off, frozen
    budget (20 calls), 95 cases x 2 modes (stateful, stateless) x 2 repeats = 380 runs.
    Each case runs both modes back to back, so provider load and time of day are spread
    evenly. GUI button "Held-out main" writes suite indexes of kind
    `heldout_main_minimax`; resume repeats only cases not finished as a whole. Primary
    analysis: these balanced 2 x 2 runs, case as unit (mean over repeats), paired
    stateful vs stateless comparison on the same 95 cases. The two pilots are reported
    separately: pilot 1 as a provider check (OpenRouter vs direct API), pilot 2 as an extra
    stateless run. If a third repeat is added later, it is a new stateful run on the
    direct API, and pilot 2 becomes the third stateless repeat. Agent and references
    stay unchanged; only documented reference errors may be corrected.
  - Main run result 2026-10-18 (suite `20261017-213604-456415`, one session, 22.7 h wall
    clock): 380/380 runs, every case has exactly stateful r1-r2 and stateless r1-r2, no run
    or sweep errors, no integrity errors, runtime code verified and token usage complete in
    all runs, no context changes. Recorded configuration identical across all 380 runs
    apart from the IFC hash; against pilot 2 only `gui.py` differs (the new button). Each
    case keeps one reference hash across pilot 2 and the main run.
    Stateful: 116 complete, 52 incomplete, 22 abstained, mean union accuracy of complete
    runs 0.874, median 1.7 min/run, 9.8 h. Stateless: 124 / 46 / 20, 0.883, median
    2.9 min/run, 12.3 h. Both about 16 calls per run, 89 % cache reads; direct API again one
    tool call per reply, 1 output-limit cutoff, no invalid tool calls. 9 code blocks hit the
    600 s timeout (7 stateful, 2 stateless). Repeat status agreed in 65/95 (stateful) and
    57/95 (stateless) cases.
  - Low complete runs (38 below 0.8 in 24 cases) were triaged for reference errors by
    comparing all complete runs of each case across both pilots and the main run; none
    found. Elements wrong in every complete run were the already verified FZK slab
    connection and the adjudicated Esplanades/Smiley uniform risers, or method
    approximations that vary between runs. Re-checked against the IFC: Duplex R301 (two
    runs flag the roof slab 6.000-6.457 in the attic space 6.000-9.000; the slab lies
    entirely inside, so it belongs to the inside rule, where R301 fails); kleine Wohnung
    door clearance (16 doors flagged in both complete runs for the roof; with the real roof
    meshes no roof point enters even a two-sided clearance box, roof underside about 509.35
    above door tops 508.22; the agents used bounding boxes or counted opening elements).
  - **Sonnet held-out run plan (user, 2026-10-18), fixed before any run:** Sonnet 5.5 via
    OpenRouter (`anthropic/claude-sonnet-5.5`, as in calibration), stateful, 1 repeat, all
    95 cases, H1, reasoning off, frozen budget. Purpose: model comparison on the same
    held-out set; the mode question is answered by the MiniMax main run. Estimated
    $12-30. Cases are not selected by MiniMax outcomes (selection on agent outputs is
    excluded by the protocol). Suite index kind `heldout_sonnet_stateful`. Further Sonnet
    runs depend on the advisor's budget decision.
  - Sonnet result 2026-10-19 (suite `20261018-215712-011319`): 95/95 runs, no errors or
    integrity errors, runtime verified, usage complete; configuration identical to the
    main run except `gui.py` and model/provider; reference hashes equal. 93 complete,
    2 incomplete, 0 abstained; mean union accuracy of complete runs 0.924, 62 runs exactly
    correct (MiniMax stateful: 88 of 190); 8.3 calls/run, median 0.9 min/run, 2.0 h,
    7.7M input (84 % cache), 0.55M output; 13 output-limit cutoffs, 11 of them in one run.
  - Both incomplete runs are Schependomlaan cases that need a long FINAL violation list.
    doors_windows_storey (390 FAIL): labels exactly correct, but the FinalReport must
    restate all 390 GlobalIds; 11 replies stopped at the 8000-token output limit and the
    other attempts did not match the label set. No run of any model has completed this
    case (MiniMax 0/6 incl. pilots, all with correct labels), so it measures the
    finalization protocol (restating a list of several hundred GlobalIds within 8000 output
    tokens), not the check. unallocated_floor_area (498 FAIL submitted, reference 77):
    13 invalid label submissions, then the last 2 calls hit the output limit while
    writing the list. Across the MiniMax main run, 23 incomplete runs had full-scope
    labels but a FINAL list that did not match, mostly with large FAIL sets. Not changed:
    the agent is frozen; report as a limitation and show label-level scores of these
    runs as a sensitivity analysis.
  - Low complete Sonnet runs (11 below 0.8) triaged against all MiniMax runs. Duplex
    uniform risers: Sonnet measures to the structural floors (0.0, 3.1); the first and
    last riser to the 19 mm wood finish floors differ by about 19 mm, as recorded at the
    freeze (reference FAIL holds). kleine Wohnung intersection: the floor finish lies
    entirely inside the rooms, so it belongs to the inside rule. Schependomlaan space
    validation is a representation ambiguity: 94 of 100 spaces have only a footprint
    curve set and an IfcBoundingBox. Solibri evaluates the box: in space 9.00 the 5 walls
    it reports inside lie within the box (x 8.70-10.60, y 7.27-11.72) but outside the
    footprint polygon. Sonnet and MiniMax's only complete run used footprints and agree
    with each other against the reference on 40 of 42 inside FAILs (23 shared errors on
    intersection). The reference stays (box = the only 3D representation, as decided
    before the freeze); report it as a limitation and run a sensitivity analysis without
    the two Schependomlaan space-validation cases.
  - H2 live smoke test 2026-10-19 (first H2 runs on v5; until now only unit tests with
    fake models): `evaluate.py --harness 2`, slab_thickness_range__fzk, stateful, frozen
    code (agent.py hash matches). MiniMax M3 direct API: plan call without tools
    (`end_turn`, 957-char plan), then tool calls; complete, union accuracy 1.0, 7 calls.
    Sonnet 5.5 OpenRouter: plan (`stop`), complete, 1.0, 4 calls. The plan is stored in
    run details (`plan`) and counts as model call 1 of 20. These smoke runs are outside
    any suite index and are not part of the analysis.
  - **H2 held-out run plan (user, 2026-10-19), fixed before any run:** MiniMax M3 via the
    direct MiniMax API, H2 (planning), stateful, 2 repeats, all 95 cases, reasoning off,
    frozen code and budget (20 model calls including the plan call; planning text and
    wiring unchanged). Suite index kind `heldout_h2_minimax`. Primary comparison: per
    case against the 2 H1 stateful runs of the main run (same provider, model, mode and
    repeats); completion, exact correctness and union accuracy, sign test / Wilcoxon on
    case means. Secondary: whether the saved plans name the correct method in the known
    failure cases (floor surface, outline vs box, inside vs intersect). Sonnet H2 is
    optional and depends on the advisor's budget decision.
  - H2 session 1 (suite `20261019-232632-456392`) stopped after 37 of 95 cases: on
    door_front_clearance__nus repeat 2 the MiniMax API returned 529 `overloaded_error` on
    the plan call (provider-side; frozen `max_retries=0`, so the run is an infrastructure
    error and the suite ends). The 74 runs of the 37 finished cases are healthy (plan
    recorded in all, runtime verified, no errors). Resume reruns the unfinished case as a
    whole; its earlier repeat 1 (abstained) is excluded with the error run, as planned.
  - Interim look 2026-10-20 (37 finished cases: door width, stairs, door clearance; not a
    random subset): H2 vs H1 stateful on the same cases, 74 runs each: complete 48 vs 54,
    exactly correct 33 vs 39, abstained 16 vs 6; per case complete better/worse 6/11
    (sign test p=0.33), exact 6/10 (p=0.45). No significant difference yet. Re-checked
    kleine Wohnung treads (H2 both runs FAIL, reference PASS): modelled treads step
    0.300 m in plan (x 6.285, 6.585, 6.885, ...), so PASS holds; the agent used
    Pset_StairCommon.TreadLength / "Tatsaechliche Auftrittsbreite" 0.2 m (Revit design
    minimum), while the flight Pset records 0.3048.
  - **Naming (advisor, 2026-10-20):** call H2 the "extra planning step" in slides and
    thesis text, not "harness level" or "H2". Code identifiers and recorded settings stay.
  - Planning-step session 2 (suite `20261020-101628-818678`) finished 5 cases
    (door_front_clearance nus/wohnung, doors_windows_storey clinic/duplex/fzk) and stopped
    on doors_windows_storey__schependomlaan repeat 2: the MiniMax API returned a message
    without content (langchain_anthropic `TypeError: 'NoneType' object is not iterable`),
    again a provider-side failure. 42 of 95 cases done. Vol. 8 gained one slide on the
    planning step (`slides/add_planning_slide_vol8.py`, edits the hand-edited deck in
    place): completed 64 % vs 73 % without, all labels right 46 % vs 54 %, abstained
    23 % vs 10 %; per case p = 0.24 / 0.45.

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
  Amended 2026-10-13 (user): the crash fix for malformed tool calls (Changelog) is the
  only post-freeze change; Sonnet runs use 2 repeats per mode.

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
  2026-10-15: the advisors' EC3 package publishes Solibri ground truth for 16 rules on
  12 free models, including Dental Clinic, Smiley West, Duplex and FZK House; ask the
  advisor whether these are the intended held-out cases.
  User 2026-10-15: combine. Use the EC3 models Clinic, Duplex, FZK House and Smiley West
  with their Solibri labels, plus new models with our own Solibri runs. EC3 package
  cloned to `gitignore/ACC-function-generation` (commit 7e8b949, 5 May 2026): 16 rules,
  per model `acc/res/<model>/ground_truth.json` (violations only, grouped per Solibri
  issue, `required_guids`), rule texts and Solibri parameters in
  `acc/config/rule_templates.json`, space-usage classifications per model as CSV,
  Solibri `.smc` per model (embedded rulesets). Smiley and AC20 IFCs are byte-identical
  to ours; their Clinic and Duplex went through Solibri IFC Optimizer (same GUIDs,
  different bytes). Caveats: no PASS/NA population, so the judged scope must come from
  the rule text; 304.3.1, 305.3, 404.2.5 and large-spaces depend on Solibri space
  classifications; doors/windows storey, same-storey elevation and slab thickness are
  rules we already calibrated on.
  Selection (user): the 12 rules without space-usage classification (drop 304.3.1,
  305.3, 404.2.5, large spaces). Consistency check 2026-10-15: our Solibri 26.9 on their
  `smiley_west/arc.smc` (export `solibri_work/ec3_smiley_check.xlsx`), extracted with
  their own description-pattern matching and extraction_element filter, reproduces
  their ground truth exactly for 15/16 rules (all 12 selected); only 305.3 differs
  (36 vs 13, a dropped rule). The `.smc` holds four full rulesets (ADA/ABA, Advanced
  Space Check, BIM Validation - Architectural, General Space Check); the 16 rules are
  filtered from all issues afterwards. Note AC20 (our KIT Institute practice model) is
  in their training split, so it is not a new model.
  - New-model workflow: open their `smiley_west/arc.smc`, Save As
    `solibri_work/ec3_template.smc`, Model Tree > Update Models with the new IFC (keeps
    all four rulesets incl. ADA and the classifications; removing the only model resets
    the project). ADA cannot be exported as `.cset`; `ec3_rulesets.cset` holds the other
    three as a record.
  - Schependomlaan (export `solibri_work/ec3_schependomlaan_check.xlsx`), elements per
    rule with EC3's first-match patterns (superseded by the message-based labels in
    Decisions 2026-10-16): riser 6, tread 6, stair-slab connection 3, non-uniform 0,
    clearance front of doors 51, doors and windows 390 (all orphans: no
    IfcRelFillsElement), slab thickness 3, guarded 53, space inside 42, intersect 14,
    same-storey elevation 0, unallocated areas 77 walls/columns.
  - Excel issue text differs from BCF topic text for slab thickness ("1 component(s)"
    vs "Slab component(s)"), so the pattern needs a rule-name fallback there.
  - Slab thickness limit actually applied by Solibri is >= 0.03 m (issue text in their
    duplex/digital_hub topics.json and our run), not 0.30 m as in their
    rule_templates.json and EC3 Table 2. Tell the advisor; rule texts must say 30 mm.
- Verify MiniMax `thinking: {"type": "adaptive"}` passthrough survives if the provider
  layer is ever moved onto LangChain chat models. Not guaranteed.
- Decide whether to replace hard output truncation with offload-to-file.

## Literature (thesis writing)

- **2026-10-15 - regulatory and data citations (verified against the sources).**
  - BCA (2025). *Approved Document: Acceptable Solutions*, Version 7.08, October 2025.
    Issued by the Commissioner of Building Control under Regulation 27 of the Building
    Control Regulations, Building and Construction Authority, Singapore. Local copy:
    `gitignore/bca_tests-*/BCATestCases/Headroom/Codes/approved-document-v7-08.pdf`
    (PDF pages: C.3.2.1 with Notes p. 37; E.2.1, E.2.2, E.2.4 p. 40; E.3.2.1, E.3.3.1
    with Note p. 41; E.3.4.1 p. 42; E.3.4.2, E.3.4.3, E.3.5.1, E.3.5.2 p. 43; E.3.5.4
    p. 44).
  - SCDF (2023). *Code of Practice for Fire Precautions in Buildings 2023* (Fire Code
    2023), clause 2.2.12 "Location of exits & access to exits", PDF p. 80 of the full
    annotated edition updated 7 Jul 2026:
    https://www.scdf.gov.sg/docs/default-source/firecode-whole-document-with-annotations/firecode_full_latest_07jul2026.pdf
    Clause page: https://www.scdf.gov.sg/fire-safety-services-listing/fire-code-2023/table-of-content/chapter-2-means-of-escape/clause-2.2-determinations-of-exit-requirements
  - URA. *Development Control Handbooks: Gross Floor Area, Planter Boxes* (last updated
    6 June 2026): https://www.ura.gov.sg/guidelines/development-control/development-control-handbooks/gross-floor-area/planter-boxes/
  - DIN 18040-1:2010-10. *Barrierefreies Bauen - Planungsgrundlagen - Teil 1: Öffentlich
    zugängliche Gebäude*. Berlin: Beuth. Clause 4.3.3.2, Table 1 row 1. Full text
    reproduced in Nds. MBl. Nr. 37 q/2012 (link in Decisions 2026-10-13). Cite DIN.
  - Solibri Inc. (2026). Solibri Office 26.9.0.123; rule template SOL/208 Accessible
    Door Rule: https://help.solibri.com/hc/en-us/articles/1500004738282-208-Accessible-Door-Rule
  - Fuchs, Hellin and Borrmann (2026), EC3; reproduction package (MIT):
    https://github.com/stefan-1992/ACC-function-generation . Uses 12 models with
    Solibri ground truth for 16 rules; models from IFCBench (Hellin et al., 2025,
    https://github.com/sylvainHellin/ifc-bench) and the GNI BIM Dataset (Wang, Fuchs,
    Wu, Esser, Wrabel and Borrmann, 2026, Zenodo, https://doi.org/10.5281/zenodo.19722012).
    IFCBench and GNI cited as given in that README, not yet opened.
  - Held-out IFC models: sources, licences and required attributions in
    `gitignore/heldout_models/SOURCES_AND_CITATIONS.txt`.
- **2026-10-15 - clause audit of the calibration rule texts.** Every BCA clause number
  and quotation in the health-suite and usable_2 rules matches V7.08 (list above);
  E.2.4(c) skipping (i) is as printed in V7.08. SCDF 2.2.12b is the right clause, but
  the quote ends after conditions (1)-(2); the current edition also has (3) signage
  "Exit Access Door - Keep Clear" and (4) demarcated egress paths, neither readable
  from IFC. URA planter criteria match the current page. Rule texts are frozen with
  the calibration runs, so nothing was changed; mention the SCDF truncation in the
  thesis. Non-regulatory rules: doors/windows storey and same-storey elevation match
  EC3 Table 2; our slab range 100-1000 mm differs from EC3's 0.30-1.0 m, so do not
  cite EC3 for it. `door_width_planterbox` is a warm-up rule without a source.
- **2026-10-13 - EC3 paper published and citable:** Fuchs, Hellin and Borrmann (2026),
  "Assessing the Viability of LLM Agents for Generating Reusable Compliance Checking
  Functions", EC3 2026 (note in `studies/literature_2026-10/`). Cite it for the
  Solihin and Eastman class wording and the same-storey elevation rule. Its numbers
  differ from the confidential draft in `studies/studies_txt_1.txt` (training F1agg
  0.47 -> 0.55, Table 2 counts); cite only the published version.
- **2026-10-12 - 32 papers read and noted** in `studies/literature_2026-10/`: PDFs named
  by title, one `.md` per paper (summary, link to our research, verbatim key quote
  with PDF page, all quotes checked against the text). Classic ACC background is
  deliberately not expanded (user). Literature review chapter resumes later.
- **Gap:** no code-agent paper isolates interpreter persistence. CodeAct, TaskWeaver,
  Data Interpreter and OpenHands keep state but never compare against a restarted
  interpreter; TaskWeaver argues in-memory state lowers error rates without a
  stateless ablation.
- **Closest BIM work:** Koh et al. 2026 (AutCon, ARCBIM) never executes code in its
  loop, generates once per query, and names missing interaction with the execution
  environment as its main limitation. Only Koh reports tokens and cost; none of the
  AEC papers repeats runs. Kapoor et al. 2024 and Zhu et al. 2025 support our
  repeats, cost reporting and validity checks.
- **Support for our observations:** CodeAct notes the model may "imagine the content
  of a variable without actually printing it out" (p. 9), close to labelling in
  reasoning; SWE-agent supports bounded output; Lost in the Middle bears on the
  growing append-only transcript.
- **Cite table values:** internal contradictions in Koh (80% vs Table 6 76.25%),
  Madireddy (conclusion vs Table 4), PAL (GSM-HARD text vs Table 1), TaskWeaver
  (0.85 vs 0.87), Kang 2026 (time limit, metric count, missing Graph-RAG row) and
  Wang 2026 (180 vs 163 competency questions).
- **Verify before citing:** LLM-FuncMapper journal version (EAAI 2026,
  doi:10.1016/j.engappai.2025.112823, taken from the arXiv page); Yang et al. online
  2026, issue 2027; preprint PDFs without printed venue (Toolformer, Reflexion, Lost
  in the Middle, Self-Debug). Design-science sources (Hevner 2004, Peffers 2007) are
  not downloaded but needed if the thesis keeps the DSR framing.

---

## Changelog

- **2026-10-13 - v5.1 crash fix: malformed tool calls (recording v6).** Protocol name
  stays `langchain-codeact-v5`; patch tag `v5.1-frozen` when published.
  - **Bug.** Occasionally MiniMax returns a tool call whose arguments are not valid
    JSON; LangChain stores it in `AIMessage.invalid_tool_calls`. `after_model` treated
    that reply as "no tool call" and asked for one, but the broken call stayed in the
    history unanswered. The OpenRouter adapter serializes invalid calls into
    `tool_calls` of the next request (checked offline on the crashed message: 1 call,
    arguments not parseable), so the upstream rejected the whole request and OpenRouter
    returned an error body without `choices` (`provider_unavailable` or
    `invalid_request`); the run ended as `error`.
  - **Evidence.** Every LangChain-era run whose transcript contains an invalid tool
    call ended in `error` (3 frozen-v5 runs on 12 Oct: space elevation mall stateless,
    tread mall stateless, exit scdf_5 stateful; 1 v3 run on 1 Oct, exit scdf_3), and no
    `complete`, `abstained` or `incomplete` run contains one. The earlier notes blamed
    OpenRouter `provider_unavailable` for these; that was wrong (corrected here).
  - **Fix.** When a reply has invalid tool calls, they are removed from that message
    (same message id, content and reasoning kept, so the history stays valid) and the
    model is told the call could not be parsed and no code ran. If the reply also had
    valid calls, those run normally. `llm_calls[i].malformed_tool_calls` counts them.
    Test: `test_malformed_tool_call_is_removed_and_the_model_asked_to_resend`.
  - **Why earlier finished runs stay valid.** The patch only adds a branch that runs
    when a reply contains an invalid tool call. No finished run (complete, abstained or
    incomplete) ever reached that state, so for every one of them v5 and v5.1 execute
    the same code path with the same prompts, budget, messages and checks: given the
    same model replies, v5.1 would have produced exactly the same run. Only the runs
    that crashed differ; they were never scored (status `error`) and are rerun under
    v5.1. Finished v5 runs and v5.1 runs can therefore be pooled; recording v6 marks
    which code produced each run.

- **2026-10-12 - recording v5 and the v5 freeze.** `agent.py` stores `seconds` per
  model call (`llm_calls`) and per code block (`execution_records`); recording version
  4 -> 5. No behaviour change. 250 tests and the kernel contract check pass. First
  frozen MiniMax batch (OpenRouter, 41 finished runs at 21:39): 39 complete, 2
  abstained, 0 incomplete; accuracy as in the 2-3 Oct suites; model wait dominates
  (code 14% of time stateful, 28% stateless; median 1.8 s vs 3.1 s per block). Lost
  runs: 2 provider errors (evaluate.py stops the case's remaining repeats; cause
  corrected 2026-10-13: malformed tool calls, see above) and 1 laptop standby
  18:06-20:52. Reruns overlapped the main batch, so
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
