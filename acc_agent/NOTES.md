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
  other process state intact. Its class and selection branches are now commented
  out, not aliased to the kernel. New runs always record `runtime_isolation=kernel`;
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
  `.env` file. Each worker gets a private temp directory as its cwd, so a *relative*
  write neither lands in the source tree nor outlives the worker; an *absolute* write
  still persists. Known API-key-shaped env vars and all `PYTHON*` vars are dropped from
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
  labels with the v2 reference in both modes. The old parity code is commented out.
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
- **Staircase ground truth is incomplete.** The IFC has 59 stairs, but only 49
  have expert labels. Since 2026-09-17, `annotated-subset-v1` explicitly excludes
  the ten unannotated IFC IDs from agreement metrics and level-3 feedback only.
  Completion still requires all 59; unannotated does not mean PASS, FAIL or NA.
  Report accuracy as agreement on the 49 authored labels, not all stairs.
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
| `slab_thickness__mall_v2` | Control | 100 / 0 / 12 | Missing-data and false-positive control, not recall |
| `staircase_width_v8` | Provisional | 27 / 22 / 0 | 49 annotated of 59 stairs; physical clear width not independently certified |

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

## Historical pilot cases

The earlier three-case pilot remains available in the GUI's Pilots filter.
Its five-repeat recommendations are historical, not a requirement for the first
health-suite run.

| case | class | anchors | why |
| --- | --- | --- | --- |
| `slab_thickness__mall_v2` | 1 | 112 (100 pass, 12 alert, zero fail) | evidence-backed control; not a violation-recall test |
| `doors_windows_storey__condo` | 2 | 212 (4 fail, 208 pass) | 2% violation rate; where union accuracy earns its keep |
| `staircase_width_v8` | 3 | 49 labelled of 59 stairs (22 fail, 27 pass) | explicit annotated-subset scoring; completion requires all 59 |

## Open items

- **Kernel runtime is built but not yet used for a paid sweep.** Nothing has been run
  under `EXECUTION_RUNTIME=kernel` against a real model, even though it is now the
  default. Before the first sweep:
  measure worker startup + genuine IFC reload cost separately from model latency (in
  stateless mode it is paid per block and will dominate), sanity-check `EXEC_TIMEOUT`
  against the slowest legitimate block seen so far, and keep kernel results in their
  own comparison group. Not yet handled: no interrupt-then-kill escalation (a timeout
  goes straight to kill, so a block cannot clean up), no memory/CPU ceiling on the
  worker, and a killed stateful worker loses the whole run's accumulated state — the
  agent is told, but recovery quality is unmeasured.
- **Condition A (single-shot baseline) — deferred, wanted later.** Not implemented as of
  2026-09-08 by explicit decision; current focus was making B genuinely stateless via the
  kernel. When picked up: cap iterations at 1, do not replay the transcript, one script
  that must call `report_labels` once. The kernel makes this cheap — spawn a worker, run
  one block, discard. **Open design choice that must be settled before running it:**
  zero repair attempts (strictest, matches exposé §4.2 "single-step code generation")
  versus N repair attempts on execution error only. Papers differ; pick one and justify
  it in the methods chapter. Expect A to fail the completion gate often — that is a
  measurement, not a bug to patch. The historical A/B/C/D goal no longer includes D.
- Before the next comparison: retain the explicit staircase evaluation mask,
  adjudicate physical clear-width measurements, keep problematic cases and legacy
  scores out of primary findings, and freeze/log rules, references, completion
  contract, prompts, budgets and sampling. Cross-run skills remain retired.
- RQ3 (sub-task decomposition) unimplemented. Pick between deepagents level 4 and the
  in-house `spawn_subcheck` builtin.
- RQ4 (IfcJSON, graph representations, geometry libs) unimplemented and framed as
  exploratory in the exposé.
- Verify MiniMax `thinking: {"type": "adaptive"}` passthrough survives if the provider
  layer is ever moved onto LangChain chat models. Not guaranteed.
- Decide whether to replace hard output truncation with offload-to-file.

---

## Changelog

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
