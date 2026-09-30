# acc_agent - LangChain CodeAct compliance-checking agent

A lean **CodeAct** application for IFC compliance checking. LangChain's
`create_agent` runs the model/tool loop on LangGraph. The model calls
`run_python(code)` to use `ifcopenshell` in the existing worker, commits labels from
executed code, and submits a structured `FinalReport` for validation.

**Migration (2026-09-17):** one active LangChain runner, no custom graph or Deep
Agents. Existing GUI, CLI, kernel, scoring, SQLite records and optional Langfuse
remain. Read [instruction.md](instruction.md) before development and
[langchain.md](langchain.md) for architecture and verification status.

Verified with 208 offline tests and a live MiniMax-M3 H1/stateful smoke test with
reasoning off. Live OpenRouter and thinking-enabled checks are pending. Restart
the GUI after migration; this verification does not establish benchmark accuracy.

**Current scope (2026-09-17): kernel-only execution, without persistent skills.**
The thesis compares within-run stateful and stateless execution without cross-run
tool reuse. `SKILLS=1` no longer enables skills, and the GUI skill controls are
commented out. The in-process runtime and its GUI selector are also commented out.
Ordinary Python functions still work within a stateful session.

The point of this first prototype is to make the **stateful vs. stateless** difference
concrete — that is the core experiment of the thesis:

- `--mode stateful`  → the Python session **persists** across code blocks (variables,
  imports, and the loaded IFC model stay alive). This is the thesis *contribution*.
- `--mode stateless` → the session is **reset** before every code block, so the agent
  must rewrite a complete script each time. This is the *baseline*.

The execution-state difference is whether the kernel keeps or restarts its Python
worker between blocks; see [kernel_executor.py](kernel_executor.py).

### Where the code actually runs

The kernel is the only active runtime. Stateful runs keep one worker for the run;
stateless runs start with a fresh worker and restart it before each subsequent
code block. Both modes use the same execution, timeout and reporting machinery.

The original namespace-reset executor retained imported modules, environment
changes and other process state. It is now preserved as commented code, not a
supported execution path. `EXECUTION_RUNTIME` is ignored; explicit factory requests
for `inprocess` raise an error instead of silently selecting a different runtime.
The GUI retains the **Session mode** control but no longer offers a runtime choice.

<details>
<summary>Historical runtime comparison (in-process implementation retired)</summary>

| | `kernel` | `inprocess` (retired) |
| --- | --- | --- |
| stateful | one worker process for the run | one namespace dict for the run |
| stateless | the worker process is **restarted** per block | a fresh namespace dict per block |
| survives a reset | external state, including shared filesystem writes | `sys.modules`, `os.environ`, cwd, files on disk |
| working directory | a private temp dir per worker | wherever you launched from |
| execution timeout | `EXEC_TIMEOUT`, default 600 s | none |
| native crash | contained; worker restarts | takes down the GUI |

</details>

`kernel` runs each block in a separate process ([kernel_executor.py](kernel_executor.py),
[kernel_worker.py](kernel_worker.py)) and resets interpreter state by restarting it.
Both modes retain conversation history; stateless execution is not a memoryless LLM.
The worker has a private temporary working directory, removed on restart. It is
**containment and reproducibility, not a security sandbox**: the worker runs as the
same user with the same filesystem access. Python-level writes outside the scratch
directory (`open` in a write mode, `os`/`shutil` mutations, moving files out) are
refused with `PermissionError` by an audit hook, and `TEMP`/`TMP` point to scratch.
Reads are unrestricted, and native extension code is not covered by the hook.

IFC paths passed to the agent are resolved against the host working directory before
building the prompt, so relative CLI or GUI inputs work with the private kernel cwd.
Unexpected restarts report that session state was lost and include `kernel_restarted`
and `restart_reason` in execution metadata. If a worker is already dead before a
block starts, that block is not executed; the agent must rebuild its state and retry.
Fatal exceptions, crashes and timeouts invalidate committed labels. Normal stateless
resets do not produce restart warnings or invalidate successful label submissions.

After changing execution code, run the kernel contract check (historical filename):

```powershell
.\.venv\Scripts\python.exe acc_agent\check_runtime_parity.py
```

It checks output, errors, label commits and truncation against expected behavior in
both modes, verifies interpreter/scratch-state persistence or reset, and checks
the real mall slab label map against its reference in both modes. The previous
two-runtime comparison code remains commented out in that file.

New runs record `runtime_isolation=kernel`. Historical in-process results and their
configuration identities are retained, but are not pooled with kernel results.
Configurations also fingerprint the effective `EXEC_TIMEOUT`,
`EXEC_STARTUP_TIMEOUT` and `EXEC_HASH_SEED` settings under `kernel_settings`. These
are loaded when the application imports the runtime; restart after changing them.
Historical records are not backfilled with settings that were never recorded.
Rows written before that column existed read `inprocess-legacy`, inferred rather
than recorded. That historical migration behavior remains unchanged.

```powershell
$env:EXEC_TIMEOUT = "600"  # seconds per code block; restart the app after changing
```

See *Decisions* in [NOTES.md](NOTES.md) for the historical condition ladder
(A single-shot / B reset / C stateful / D + skills). D is now out of scope;
B versus C is the primary comparison.

## Prerequisites

- Python 3.13 is the verified environment for the pinned dependencies.
- An API key for **one** of the supported providers:
  - **MiniMax** (the advanced models, via its Anthropic-compatible endpoint), or
  - **OpenRouter** (the original free/baseline path).

## Setup

```powershell
# from inside acc_agent/
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# provide your key (NEVER commit it)
Copy-Item .env.example .env
# then edit .env and paste your key (see "Providers" below)
```

### Providers

The agent talks to either provider through a small abstraction in
[llm.py](llm.py). Which one is used is chosen by the environment:

- Set `MINIMAX_API_KEY` (or `PROVIDER=minimax`) to use the **MiniMax** models
  through their Anthropic-compatible endpoint (`https://api.minimax.io/anthropic`,
  driven by the `anthropic` SDK).
- Set `OPENROUTER_API_KEY` (or `PROVIDER=openrouter`) to use **OpenRouter**.
- If both keys are present, `PROVIDER` decides; otherwise MiniMax wins when its
  key is set, else OpenRouter.

Add the relevant line(s) to your `.env`:

```dotenv
# MiniMax (advanced models)
MINIMAX_API_KEY=your-minimax-key-here

# or OpenRouter (baseline)
OPENROUTER_API_KEY=your-openrouter-key-here

# optional overrides
# PROVIDER=minimax
# MODEL=MiniMax-M3
```

MiniMax model ids: `MiniMax-M3` (1M context, latest, default here),
`MiniMax-M2.7`, `MiniMax-M2.5`, `MiniMax-M2.5-highspeed`, `MiniMax-M2.1`,
`MiniMax-M2`, etc.

> If `pip install ifcopenshell` fails on your platform, you can instead reuse the
> advisor's `uv` environment under `bca_tests-main/`, which already ships
> `ifcopenshell`.

## Run

```powershell
python run.py                      # stateful, default door rule + planter-box IFC
python run.py --mode stateless     # the baseline, for comparison
python run.py --model MiniMax-M2.5 # a different model id
python run.py --ifc "..\path\to\other_model.ifc"
```

A full transcript of each run (every message + token counts) is written to
`acc_agent/runs/`.

### Model & reasoning

- The default model depends on the provider: **`MiniMax-M3`** for MiniMax,
  **`minimax/minimax-m3`** (the same model) for OpenRouter. Set the `MODEL` environment
  variable (or `--model`) to use a different one. The GUI's Provider switch selects
  the provider per run and resets the model field to that provider's default.
- **Reasoning** is enabled by default: the model's step-by-step thinking is requested
  and preserved across turns so it can continue its chain of thought. On MiniMax this
  uses Anthropic `thinking` blocks (`thinking: {"type": "adaptive"}`); on OpenRouter it
  uses `reasoning_details`. Set `REASONING=0` to turn it off. M3 honours that
  (`thinking: {"type": "disabled"}`), while the MiniMax M2.x models always think and
  ignore it.

## How it works

```
run.py        CLI: pick IFC / rule / mode, wire everything, print + save results
config.py     shared settings (iteration/output caps) + legacy OpenRouter client
llm.py        small factory: LangChain ChatAnthropic (MiniMax) / ChatOpenRouter
executor.py   shared reporting/output helpers, kernel-only factory;
              the original CodeExecutor class is preserved as comments
kernel_executor.py  out-of-process runtime: worker lifetime, per-block timeout,
              crash containment; the only active execution runtime
kernel_worker.py    the child process it drives; not imported by the host
agent.py      create_agent, run_python tool, structured submission validation,
              bounded H1/basic or H2/planning, and the existing event interface
scoring.py    parse the FINAL verdict + score set agreement (precision/recall/F1)
              and union accuracy over the element labels
ground_truth.py  GroundTruth cases (rule + IFC + per-element labels)
import_bca_gt.py  import the advisor's BCA cases (staircase width, headroom, ...) as GT
simple_rules.py   low-complexity (class 1-2) BCA rules + their reference implementations
evaluate.py   run the agent k times per mode and report mean ± std agreement
tracing.py    optional Langfuse tracing (no-op unless LANGFUSE_* keys are set)
skill_library.py  archived exploratory library; not integrated into new runs
tests/        automated software regression checks, separate from benchmark cases
NOTES.md      running project memory: findings, decisions, pitfalls, changelog
```

The default check is: *"every `IfcDoor` must be at least 900 mm wide (using the
`OverallWidth` attribute)."* The agent has to discover the doors and their widths
itself; nothing is hard-coded for it.

The model submits `FinalReport` with `verdict`, `violations` and an optional
`reason`. LangChain validates its schema; the application validates committed labels,
execution status and scope. The host still formats `FINAL: {...}` for existing logs
and displays, but does not parse that marker or Markdown code from model replies.

### The verdict may be COMPLIANT, NON_COMPLIANT or UNKNOWN

`UNKNOWN` is a deliberate **abstention** and a last resort: the prompt tells the
agent to commit to a judgement whenever its measurements support one, even
without full confidence, and to abstain only when it could not obtain the
measurements the rule needs at all (data absent, unreadable, geometry not
evaluable). When it abstains it must supply a concrete `"reason"`:

```json
FINAL: {"verdict": "UNKNOWN", "violations": [],
        "reason": "IfcStair elements carry no geometry and no width quantity, so clear width cannot be measured."}
```

The reason is stored on the result, written to the run log and the eval report,
and shown as the trace's status in Langfuse. This exists because forcing a
verdict out of an agent that has measured almost nothing turns "I don't know"
into a **false COMPLIANT** — the worst failure mode for a compliance checker.
Abstention is tracked separately (`abstained`) so it is never confused with a
confident answer; note that an abstention reports no violations, which makes
precision vacuously 1.0.

## Scoring (agreement %)

A single run tells you little; the experiment needs *meaningful averages*. The
scoring harness runs the agent several times per mode and measures how well its
reported set of violating `GlobalId`s matches a known-correct set.

1. **Ground truth** lives under `ground_truth/` as JSON (rule + IFC + the set of
   violating GlobalIds). Regenerate the door case straight from the model with:

   ```powershell
   python ground_truth.py
   ```

   A door counts as a real violation only when its width is more than a small
   tolerance below the threshold, so the nominal-900 mm doors that IFC stores as
   `899.999…` mm (floating-point noise) are *not* in the ground truth.

2. **Evaluate** — run the agent `--repeats` times per mode and score each run:

   ```powershell
   python evaluate.py                     # 3x stateful + 3x stateless, door case
   python evaluate.py --repeats 5         # 5 runs per mode
   python evaluate.py --modes stateful    # one mode only
   python evaluate.py --model MiniMax-M3  # a different model
   ```

   The metric is **set agreement** on the violating-GlobalId set — precision,
   recall and F1 — plus exact-set-match and the coarse verdict bit. Reporting the
   set (not just COMPLIANT / NON-COMPLIANT) is the honest measure: it surfaces a
   model that over-flags every borderline ~900 mm door as false positives. Each
   evaluation writes a full JSON report to `acc_agent/evals/`.

### Per-element labels and union accuracy

Set agreement has one blind spot left: **an element the agent never looked at is
indistinguishable from one it correctly passed.** A run that enumerates 5 of 212
doors, happens to catch the one broken door among them and reports it, scores
`P = R = F1 = 1.00`.

So a case carries a labelling over its **anchor elements** — every element the
rule judges — with one of five mutually exclusive outcomes:

| label | meaning |
| --- | --- |
| `PASS` | meets the requirement |
| `FAIL` | breaks the requirement (this slice is the old violation set) |
| `ALERT` | the model doesn't carry what the rule needs — fix the model, not the checker |
| `MANUAL_CHECK` | a person has to decide; a real answer, not an evasion |
| `NA` | out of scope / exempt |

`ALERT` is the one that changes the numbers. The original reference labelled
**35 of 112 slabs** in the original mall slab reference (now `slab_thickness__mall_deprecated_v1`) as missing thickness. The later audit
found that many had usable properties the reference missed, so these counts are
not validated outcomes. See the pilot warning below and [NOTES.md](NOTES.md).
The expert BCA workbooks already carried these distinctions (`pass` / `fail` /
`exempt` / `alert`); we were flattening them on import and now do not.

The agent submits its labelling from **executed code**, not from the reply:

```python
report_labels({"<GlobalId>": "PASS", "<GlobalId>": "ALERT", ...})
```

`report_labels` is a rule-agnostic builtin in the REPL. A
labelling of a few hundred elements would otherwise eat the output-token budget
and get truncated, and a label the agent *computed* is worth more than one it
transcribed. Each call replaces the previous one, and it survives a stateless
namespace reset.

Runs with a labelling are additionally scored with **union accuracy**:

$$A_\cup = \frac{|\{e \in E_y \cap E_{y'} : y(e) = y'(e)\}|}{|E_y \cup E_{y'}|}$$

An element only one side labelled sits in the denominator and can never match, so
skipping an element costs exactly as much as mislabelling it. The 5-of-212 run
above scores `F1 = 1.00` but `A∪ = 0.02`. Runs that produce no labelling report
`A∪ = n/a` and are **excluded** from the average rather than counted as zero.

The label space and the metric follow ARCHER (arXiv 2607.25566), the closest
published work; see `studies/ARCHER-agentic-rule.pdf`.

### Harness levels

The second axis of the experiment, orthogonal to stateful/stateless. The backbone
and the executor are held fixed and only the structure around the loop changes,
so a difference in score is attributable to the harness:

| level | what it adds |
| --- | --- |
| 1 | the bare loop: inspect, decide (the baseline) |
| 2 | a **planning** turn first — scope, what to measure and where it might live, the PASS/FAIL boundary, what makes an element ALERT/MANUAL_CHECK/NA, and how coverage will be confirmed |

```powershell
python run.py --harness 2                                  # plan before coding
python evaluate.py --case slab_thickness__mall --harness 2
```

**Level 3 is retired.** It disclosed reference answers during execution. Historical
H3 records retain their training-only identity; new runs expose only H1/H2 and
receive no reference feedback. This does not make the Python worker a filesystem
security sandbox.

### Completion checks (version 3)

All harness levels now apply the same deterministic submission checks. A decided
FinalReport must match its schema, follow a successful code attempt and a `report_labels`
submission, and list exactly the submitted FAIL GlobalIds. Its verdict must agree
with those labels. No prose salvage or unconfirmed bundled-verdict fallback can
bypass these checks. A response containing both Python execution and FinalReport
is rejected before any code from that response runs. The model must resubmit the
actions separately, within its remaining budget.

Version 2 commits `report_labels` only after its entire code block succeeds.
An uncaught execution error discards staged labels and invalidates any previous
submission. A later successful block without a new submission does not restore
those labels: the agent must submit a complete mapping again from a successful
block. Namespace variables themselves are not rolled back. This closes the
"provisional PASS -> exception -> unrelated print -> COMPLIANT" failure path.

Version 3 accepts UNKNOWN only on the final model call. Earlier, the checker rejects
it and asks the agent to continue and label undecidable elements ALERT. This closes
the "one code block, then UNKNOWN" early exit seen in the usable_2 suite.

For catalogue rules with an explicit `(modelled as Ifc...)` scope, the checker
enumerates those classes directly from the IFC and requires exactly that set of
label keys. The default `Every door (IfcDoor)` rule is also supported. This does
not use GT labels, even at levels 1 and 2. Unsupported custom-rule scopes are
reported as unverified; they are not guessed from all class names in the prose.

`--max-iterations` now limits **all model calls**, including H2 planning, structured
output repairs and final submissions. Python tool calls have the same numeric cap.
There are no extra finalization turns. The model output cap is 8,000 tokens per call,
the API timeout is 180 seconds, and automatic provider retries are disabled. Existing
kernel execution/startup timeouts and output caps remain unchanged. There is no
cumulative token/cost cap. `finalization_attempts` now counts FinalReport submissions.

New runs carry `agent_protocol=langchain-codeact-v2` and recording version 3; do not
pool them with historical protocols or budgets as if they were identical settings.
In v2 the model receives execution output as plain text (traceback once); status
metadata is kept as the tool message artifact. v1 sent a JSON wrapper instead.

GUI logs, factual reports, saved transcripts, eval JSON and traces distinguish:

- `complete`: coherent submission with independently checked IFC scope coverage.
- `reported_unverified_scope`: coherent labels and verdict, but scope could not be
  independently established for this rule or IFC.
- `abstained`: explicit UNKNOWN with a reason, not a completed compliance check.
- `incomplete`: no accepted submission within the budget, with rejection reasons.

These are **reporting guarantees, not proof of correct measurements**. Labeling
every element PASS without evidence could still satisfy a structural contract.
Historical logs show completion checks as not recorded. Do not mix pre-change and
post-change results as identical experimental conditions. Existing scoring and
its treatment of missing labels are unchanged; read completion alongside scores.

### Harder cases from the advisor's BCA test set

The advisor's harness (`bca_tests-harness_improvements/`) ships expert ground
truth for real, geometry-dependent rules. [import_bca_gt.py](import_bca_gt.py)
pulls those labels out of the committed `analysis/gt_comparison/<rule>.xlsx`
workbooks and writes them as our `GroundTruth` JSON cases — one
`(rule, model, clause)` per case, where the violation set is every GlobalId the
experts marked **Fail** (`pass` / `exempt` / `alert` are non-violations; rows
with no authored label are skipped).

```powershell
python import_bca_gt.py --list           # show the registered cases
python import_bca_gt.py                   # regenerate the imported cases (validates GUIDs)
python evaluate.py --case staircase_width_v8 --repeats 5 --max-iterations 10
```

The standout case is **staircase_width_v8**: clause E.3.3.1, *"the clear width of
the staircase must be at least 1 m"*, on all 59 `IfcStair` of the v8 model
(26 pass / 23 fail / 6 NA / 4 manual check), built by
[stair_width_reference.py](stair_width_reference.py) from the expert workbook and
IFC evidence. The importer now only reproduces superseded cases
(`staircase_width_v8_deprecated_v1`, `exit_requirements__scdf_5_deprecated_v1`,
`planter_box_gfa_deprecated_v1`) and the retired `headroom_condo_c32`. These
require `openpyxl` (in `requirements.txt`).

### Easier cases: the low-complexity rule ladder

The advisors' EC3-2026 paper groups rules by the Solihin & Eastman (2015) complexity
classes and finds class 1–2 rules tractable while class 3 (rules needing auxiliary
geometric constructions) collapse. `staircase_width_v8` is a class-3 rule, which is
why it is hard. [simple_rules.py](simple_rules.py) adds the cheap end of that ladder
— five class-1/2 rules, four of them from the **same** BCA Approved Document:

| rule id | class | clause | requirement |
| --- | --- | --- | --- |
| `riser_height_e341` | 1 | E.3.4.1 | riser height ≤ 175 mm |
| `tread_width_e342` | 1 | E.3.4.2 | tread width ≥ 275 / 250 / 225 mm by building type |
| `landing_interval_e352` | 2 | E.3.5.2 | ≤ 18 risers without an intermediate landing |
| `slab_thickness` | 1 | BIM validation | slab thickness within 100–1000 mm |
| `doors_windows_storey` | 2 | BIM validation | door/window on its host wall's storey, no orphans |

There is no expert labelling for these clauses, so the ground truth comes from a
**coded reference implementation** (the paper allows exactly this) — the same
approach `ground_truth.py` already uses for the door rule. Each rule is generated
against all 8 IFC models in the workspace, giving 37 cases including fully compliant
models that test false-positive control.

```powershell
python simple_rules.py --list      # the rule catalogue
python simple_rules.py --survey    # violations / population per rule x model
python simple_rules.py --generate  # write the ground_truth/*.json cases

python evaluate.py --case tread_width_e342__mall --repeats 3
python evaluate.py --case landing_interval_e352__stair_v8 --repeats 3
```

The models carry a paper-style `train` / `val` / `test` split (see `SPLIT` in
`simple_rules.py`); the current per-model agent ignores it, but it is there if the
reusable-function pipeline from the paper is added later.

### Case names

A case ID names the check and never changes. The current reference always owns
the plain ID (no `_v2`, `_full` or similar tags). When a reference is replaced,
the old file is kept as `<case_id>_deprecated_v<N>` (oldest `N=1`) so historical
runs can still be traced; deprecated cases are hidden from the GUI. The ledger
translates IDs recorded before the 2026-09-30 renaming. The reference version and
hash in each run's configuration identify which reference a run used.

### The pilot set

**Slab reference repaired:** use `slab_thickness__mall`. It has
100 PASS, 12 ALERT and zero FAIL, with per-element property evidence and recorded
decisions. The invalid legacy version is `slab_thickness__mall_deprecated_v1`;
old logs and scores remain historical records. `staircase_width_v8` labels all
59 stairs. Its predecessor, `staircase_width_v8_deprecated_v1`, had 49 expert
labels and an explicit `annotated-subset-v1` policy; historical subset scores are
not pooled with full-population runs. See [PILOT_AUDIT.md](PILOT_AUDIT.md).
The generated condo reference also remains unaudited. See [NOTES.md](NOTES.md).

The catalogue is too large to report on in full. Three are marked **pilot** (★ in the GUI picker,
`PILOTS` in [gui.py](gui.py)) — one per complexity class, and the standing focus of
the experiment:

| case | class | source | anchors | why |
| --- | --- | --- | --- | --- |
| `slab_thickness__mall` | 1 | Project adjudication | 112 (100 pass, 12 alert, zero fail) | coverage, missing-data and false-positive control; cannot measure violation recall |
| `doors_windows_storey__condo` | 2 | EC3 | 212 (4 fail, 208 pass) | the paper's own rule (1.00 train → 0.25 test); pure relation traversal, no geometry. The 4-in-212 rate is exactly where union accuracy earns its keep |
| `staircase_width_v8` | 3 | BCA | 59 stairs (23 fail, 26 pass, 6 NA, 4 manual check) | thesis anchor; clear-width geometry and E.2.4 exemptions |

Two of the three come from the EC3-2026 rule catalogue on purpose: the paper
publishes per-rule F1 numbers for them, so our results can be read against a
reference instead of standing alone. The class-3 pilot has no such counterpart —
the paper's class-3 rules use models we do not hold — so it is our own reference,
not a comparison.

The repaired slab control has no violations. Condo has about 2% violations and
the staircase case 23 of 59 (about 39%). Do not compare F1 across these populations
without coverage, completion status and the reference limitations.

Pilots get 5 repeats per mode rather than 3, since they are the cases that end up
in the write-up; iteration budgets still follow their class.

### usable_2 cases (2026-09-29 review)

[reference_v2.py](reference_v2.py) builds ten repaired or new cases shown in the GUI
as tier `usable_2` (landing, tread, exit access, planter, door headroom and the EC3
same-storey space elevation rule). Superseded cases are kept as `_deprecated_v1`
files; nine weak cases are marked `Retired`. See [NOTES.md](NOTES.md) for counts and limitations.

```powershell
python reference_v2.py            # write all usable_2 cases
python reference_v2.py --check    # regenerate and compare with the stored files
```

### Regenerating the repaired slab reference

```powershell
python slab_reference.py
# Equivalent route through the catalogue generator:
python simple_rules.py --generate --rule slab_thickness --model mall
```

Both write only `ground_truth/slab_thickness__mall.json`. The deprecated legacy case stays
intact. Version 2 requires at least two agreeing explicit recorded thickness
sources; base-depth conflicts are documented, not silently discarded. Missing
recorded thickness stays ALERT even if geometry could be measured, as required by
the unchanged rule. This is a mall-specific project adjudication, not a universal
property-priority fix or expert regulatory certification. Agreeing fields may
originate from the same authoring tool.

The case stores an IFC SHA-256, units, property/quantity entity IDs and per-element
decisions. Changed IFC hashes, uncorroborated values, explicit unit overrides or
unexpected populations stop regeneration for review. Pair this zero-FAIL control
with verified failing cases before drawing conclusions about violation detection.

## Archived skill library (disabled)

The persistent library was implemented and explored during development, then
excluded on 2026-09-16. Cross-run reuse introduces run-order dependence and a
separate transfer-learning question, requiring frozen libraries and independent
validation on unseen cases. This would broaden the thesis beyond its primary
comparison of within-run execution state. This is not evidence that skills harm
performance; no controlled skills-on/off conclusion is claimed.

The activation code is retained as comments. CLI, evaluation, GUI, agent prompts
and the kernel worker no longer load, save or advertise skills, even with `SKILLS=1`
or an explicitly enabled library argument. The standalone library and its tests
remain for reference; saved helpers and historical results are not deleted.
New runs record disabled skills and empty snapshots. Old skills-on runs retain
their original metadata and remain separate experimental conditions.

Suggested thesis wording:

> A persistent skill library was implemented and explored during development,
> but excluded from the final evaluation to isolate within-run execution state
> from cross-run tool reuse.

<details>
<summary>Historical implementation notes (not the current runtime)</summary>

The agent is not handed domain tools. Instead it can **write its own** reusable
helpers, **self-test** them, and **persist** them so they are remembered and reused
across runs — a growing, self-authored tool library ([skill_library.py](skill_library.py)).

Before persistence, the agent must extract a parameterized operation and describe
its applicability. From inside its code it calls:

```python
save_skill(
  "name", code, test="<assertion using the candidate>",
  contract={
    "summary": "The operation performed.",
    "inputs": "Accepted arguments, types and units.",
    "returns": "Result shape and units.",
    "assumptions": "Conditions and policies the caller must check.",
    "failure_behavior": "Missing data, ambiguity and errors.",
  },
  transfer_tests={
    "normal": "<construct a normal input, call and assert>",
    "edge": "<construct missing/boundary/conflicting input, call and assert>",
    "changed_input": "<vary relevant inputs or settings, call and assert>",
  },
  provenance={"source_case": "audit metadata, not sent in the skill prompt"},
)
```

All three transfer programs execute separately with no live session fixtures;
each must call the helper successfully and execute an assertion. Duplicate test
programs, parameterless entry points, embedded IFC paths and literal `by_guid` /
`by_id` lookups are rejected for new saves. The prompt asks the author to
parameterize thresholds, units and source-selection policies before calling save.
A rejected save returns an execution error so the agent can revise it within its
existing iteration budget. There is no extra LLM rewrite or evaluation call.

These are limited reuse checks, **not automatic generalization or independent
testing**. Different test programs do not prove different meaningful inputs or
adequate coverage, and static checks do not catch every encoded dependency.
The same author supplies the implementation and assertions. Unseen-model tests
with independently established answers are still necessary.

Only name, signature, functional contract and validation limitations enter the
skill catalogue prompt. Legacy free-form descriptions, source cases, scores,
retained test programs and provenance are not copied into it. Provenance remains
in the manifest/history and experiment snapshots for auditing. Authors are told
not to put case origins into contracts, docstrings or comments; this is not an
automatic detector of arbitrary origin text. Useful semantic assumptions remain
visible. Removing a case name does not remove learned assumptions from code, and
in-process Python can still inspect files; this is not a secrecy boundary.

The original `test` is also **required**: at least one assertion must execute successfully, and the test must successfully call the
candidate. The skill must define its own regular synchronous function, with its
imports and helper definitions in its own source. Async/generator entry points
and imported function aliases are not supported. Each saved skill has private
globals, separate from the live session and other skills; only its named function
is installed in the REPL. Harness and Python builtin names are reserved.

Tests execute in a separate namespace. Named inputs referenced from the session
are copied into the test as fixtures, not into the skill's globals. IFC files and
entities are cloned together so tests do not mutate the live model. Imports and
fixture setup can also be written in the test. Fixtures are copied on actual reads,
so imports and local bindings are not mistaken for external inputs. Tests need useful expected values:
a trivial assertion is still a weak test, not proof that a measurement is correct.

Only after testing and persistence succeed does the new function replace the live
one. Rejected replacements leave the old live function and active disk revision
unchanged. New saves compare initial private state before testing with the fresh
installed state and retain its hash for reload checks. Initialization drift is
rejected, including time-dependent globals. Plain values/containers, functions and
imports are supported; unsupported initialization objects must be created inside
the helper. Imported module state and external side effects are not compared.
Older revisions without this hash remain loadable; their initialization was not
checked under this policy. Each save writes an immutable source revision under
`skills/versions/<name>/`, with a SHA-256 and retained test in
`skills/manifest.json`. The manifest is the atomic commit pointer; process locking
and stale-revision checks prevent simultaneous writers silently overwriting one
another. A failed write can leave an unreferenced revision file, but cannot make
it active. Previous revisions and test metadata remain in history.

At load time, names, source paths, committed hashes and Python definitions are
checked. Broken/missing helpers are skipped with visible warnings, not advertised
as available. The agent prompt lists successfully loaded functions only. Old
`skills/<name>.py` entries remain loadable in private namespaces but are labelled
**legacy: original test unavailable** until resaved. Their original files are not
deleted. Older revisions without contracts or transfer tests remain loadable but
are explicitly marked as lacking those checks; their original descriptions are
not used as a substitute contract.

The existing thickness helper has a new immutable revision with a neutral contract
and docstring, the retained 112-slab test, and synthetic normal/missing/conflicting/
changed-value inputs. Its extraction logic is unchanged: ordered source fallback,
raw values, no conflict reconciliation or property-unit override handling. It has
not been silently upgraded to a generally valid measurement algorithm. The old
source and test history are preserved, including the human review provenance.

The GUI's **Use skills** checkbox enables both loading and saving for new runs.
It defaults from `SKILLS`, is locked during a sweep, and shows saved/legacy/
unavailable counts. **Skill details** inspects metadata and source syntax without
executing the code. Actual load failures also appear in the live log and prompt.

Retained tests can be rerun explicitly, with the required inputs supplied:

```python
library.retest("get_slab_thickness", {"model": model})
```

Fixture names and policy are stored, but fixture objects/IFC files are not bundled
into the library. Retesting replays both the original test and transfer programs.
Tests are not automatically rerun on every preload. A self-tested
skill can still be wrong on another model, or on branches its test never exercises.

**This is not a security sandbox.** Code still executes in-process. Imported module
state, filesystem/network effects and arbitrary external side effects are not
rolled back; source/test code must be trusted. Skill isolation does not implement
the deferred stateless-process isolation proposal. The mandatory tests and updated
skill instructions change experimental conditions, so new code/skill fingerprints
must remain separate from old results.

The library ships **empty** — helpers are authored during runs; nothing here
is rule-specific. Disable it for the unaided baseline:

```powershell
$env:SKILLS=0            # no save_skill, no pre-loaded skills
$env:ENV_PRIMER=0        # also drop the environment primer
```

These are historical settings, not current activation instructions. Archived
files under `skills/` are retained but are not loaded into new agent runs.

</details>

## Desktop workspace

The GUI uses a dark theme and opens at a size that fits the current display scale.
Restart an existing GUI process to load UI changes.

- The sidebar groups **Case**, **Execution** and **Input** settings. Filter the
  case picker by Pilots, All cases, complexity, Controls or Custom. Reference
  details are expandable; model and rule remain editable. Run stays visible at the
  bottom while the settings scroll. Settings are locked during a sweep.
- The latest-result panel separates the verdict, completion status, violation
  count, submitted-label count, iterations and input/output tokens. **Raw verdict**
  retains access to the full recorded response and completion reason. Incomplete
  and scope-unverified work is never shown as a green completed result.
- **Live Log** shows the agent's work and execution feedback. **Follow output**
  can be turned off to read earlier steps without being scrolled to the bottom.
- **Scores** holds per-run reference agreement in a selectable table, detailed
  counts and per-mode averages. **Metric guide** defines recall, precision, F1,
  union accuracy, coverage and other metrics, including zero-violation and missing
  data caveats. Scores no longer interrupt the live console, but the same score
  records are still saved in the Markdown log for factual reports.
- **Factual Report** and its saved-log/browser controls work as before.

The UI changes do not alter model prompts, execution modes, harness levels,
completion checks, scoring formulas, skill persistence or API usage.

## Experiment database

New GUI sweeps, `evaluate.py` sweeps and `run.py` attempts are recorded in a local
SQLite database using Python's standard library. No database server, package,
account or extra AI call is needed. The default Windows location is
`%LOCALAPPDATA%/acc_agent/experiments.sqlite3`, outside the Nextcloud-synced project.
Set `EXPERIMENT_DB` to override the location; keep the live file on local storage.
Set `EXPERIMENTS=0` to disable automatic recording (the viewer can still read it).

The **Experiments** tab has three spreadsheet-style views:

- **Configurations:** exact-condition groups with attempts, completion rate,
  mean/standard deviation/count for F1 and union accuracy, and resource averages.
- **Runs:** every attempt, including incomplete, abstained, API-error and interrupted
  outcomes, with scores, time, tokens, errors, audit status and configuration ID.
- **Sweeps:** requested versus attempted runs and batch state. Unstarted repeats
  are not silently turned into failed attempts; the requested total remains here.

Click column headings to sort (numbers sort numerically), resize columns, scroll
horizontally, select rows for condition details, or search by case/model/mode/ID.
**Copy rows** produces tab-separated data for Excel. **Export CSV** exports the
currently displayed table as UTF-8 with a BOM; formula-like text is escaped.
**Open log** follows the selected attempt's evidence file. **Backup** uses SQLite's
backup API, not a copy of an open database file; a backup can be stored in the project.

Runs and configurations show **all recorded attempts by default**, including
skills-enabled runs. The optional **Audited / skills off / H1-2** filter restricts
them to audited relation cases or evidence-backed controls, skills disabled,
harness 1/2, and unchanged execution context. Filtered-empty results are flagged;
the filter does not apply to Sweeps. Hidden records are retained. The sidebar's
former **Use skills** control is retired; all new runs have skills disabled.

Each configuration includes the case/rule/reference and IFC fingerprints, model,
provider, mode, harness, budgets, core and entry-point code fingerprints, runtime
package versions, reasoning/primer settings, sampling defaults and starting skill
manifest/file fingerprints. New runs have empty skill snapshots; historical
snapshots still distinguish earlier skill-enabled configurations. Reference
audits and changed-context flags are retained. API keys and environment contents
are not copied into the database. Fingerprints identify versions; they are not
source-code backups, so keep the corresponding code/model files separately.

Recording v2 separates imported module-code hashes from current disk hashes for
core modules and the entry point. Mismatched or uncaptured code is flagged and
excluded from comparable results, even when disk files stay unchanged throughout
the run. Restart the GUI after editing code. This checks imported code, not later
monkeypatches or arbitrary mutable process state. Configuration uses the effective
run settings; its file hash is explicitly disk-only, not an imported-code claim.

Runs are inserted before model calls and finalized in short transactions. A database
problem produces a visible recording warning rather than breaking the agent. A
crash can leave a `running` record; select its sweep and use **Mark interrupted**
only after confirming that it is no longer active in any window or terminal.
Startup never automatically declares another process's run dead.

On a later API failure, the original exception still surfaces, but accumulated
usage, messages, execution records and committed labels are retained in a partial
JSON transcript. GUI logs also record partial usage. A failed request's unknown
usage is not guessed; no recorded usage leaves database token fields NULL.

Statistics are calculated from individual stored measurements, not saved averages:

- Completion rate = complete / finished attempts. Error, incomplete, abstained and
  interrupted attempts remain in its denominator; currently running attempts do not.
- Aborted run rate = error or interrupted attempts / finished attempts. Recovered
  Python errors and incorrect compliance labels do not count as aborted runs.
- Code error rate = failed Python blocks / executed blocks. Configuration rates
  use pooled block counts from finished attempts with recorded counters, not an
  average of per-run percentages. Missing counters or no executed blocks give
  `n/a`, not zero. Tables display rates as percentages; CSV values remain ratios.
- Score means use all available recorded scores, with each metric's N shown.
  Missing scores remain NULL, never invented zeros. Complete-only union mean is
  available in selected-row details alongside the all-measured-run mean.
- SD is sample standard deviation; one measurement has unknown SD/CI, not zero
  uncertainty. Row details contain descriptive 95% normal-approximation intervals.
  Small samples, dependent repeats and provider defaults limit those intervals.
- Different configurations and test cases are never merged into one global mean.
  Zero-violation controls do not demonstrate violation detection, regardless of F1.
- Duration is wall-clock attempt time, including surrounding local handling.
- New MiniMax input totals include uncached input, cache reads and cache creation
  once. OpenRouter input already includes cache; its cached subset is not added again.
- Partial usage is a known lower bound. It contributes to known token totals but
  is excluded from full-run token means, with partial-run counts shown separately.
  Missing provider usage and failed requests remain unknown; SDK-internal retries
  cannot be reconstructed. No monetary cost is inferred. Older counts are unchanged.

Historical logs are **not automatically imported**: many lack prompt, reference,
skill or sampling metadata. Keep using Factual Report for those records; only new
recorded attempts participate in the database until a provenance-aware importer is
added. Repeating the same configuration in a later sweep pools its runs automatically.
No paid sweeps or synthetic demo rows are inserted into your real database by tests.

See [PILOT_AUDIT.md](PILOT_AUDIT.md) for the current reference audit. Staircase's ten
missing labels remain unresolved and are excluded by the default comparison filter.

## Factual reports (no AI)

After a GUI sweep ends, the **Factual Report** tab shows its settings, per-run
results, submitted-label counts, reference agreement, execution attempts, errors,
token counts and warnings. This is a separate reader of the closed Markdown log:
it does not change the checking agent, prompts, execution loop or model calls.
It uses only the Python standard library and spends no additional AI tokens.

**Open Detailed Report** opens a self-contained HTML file beside the original log
(`*.report.html`). It includes expandable steps, code attempts, recorded output,
short agent-explanation excerpts marked **unverified**, and links to exact lines
in an embedded copy of the source log. The original log is never modified.
**Report From Saved Log** generates the same report for an earlier GUI sweep.
Restart an already-running GUI to load these controls.

From the workspace root, reports can also be generated without opening the GUI:

```powershell
.\.venv\Scripts\python.exe acc_agent/factual_report.py acc_agent/logs/20260907-191344_doors_windows_storey__condo_stateful.md
```

Pass multiple log paths to process several sweeps. Inputs are **GUI Markdown
logs**, not the JSON transcripts or eval files written by the other entry points.
Interrupted sweeps with at least one run heading are supported. Older logs that
lack label counts show **not recorded**, not an invented zero. Conditional
averages explicitly state how many runs contributed; the scorer is unchanged.

The report describes evidence, not correctness: submitted labels do not prove
inspection, reference agreement does not validate the reference, and explanations
are quoted claims rather than inferred intent. It cannot recover truncated output
or unexecuted code omitted from the GUI log, and cannot reconstruct full label
maps that were never logged. Treat any report like its source log when sharing it;
the detailed HTML embeds the recorded source content.

New logs include structured **Execution status** records. Error and truncation
counts use those flags rather than interpreting printed text; legacy logs still
use their existing text-based fallback. Captured stdout/stderr storage is bounded
by the output cap, with a truncation marker when needed. Traceback details are
kept separately (up to 6000 characters), so a long print cannot hide an execution
failure. `SystemExit` raised by executed code is treated as a failed attempt;
external interruption still propagates and invalidates labels.

These fixes do not bound arbitrary computation or allocations made by the code.
There is still no safe execution deadline/cancellation boundary for in-process
code. Process isolation and resource limits remain deferred. Revision checks and
partial-call accounting do not make arbitrary generated Python safe to execute.

## Monitoring (Langfuse)

Every run can be traced to [Langfuse](https://langfuse.com) for token/cost
accounting, latency, quality metrics and a step-by-step view of what the agent
actually did. **One trace = one compliance check.**

It is **entirely optional**: with no `LANGFUSE_*` keys set, [tracing.py](tracing.py)
degrades to a no-op and runs behave identically.

Observation creation, context entry and context exit failures now also degrade
to no-op tracing. They cannot abort successful agent work, replace its exception
or suppress its failure. This contains raised telemetry exceptions, not indefinitely
blocked network calls.

To turn it on, add your keys to `.env` (get them from your Langfuse project
settings — free cloud account at <https://cloud.langfuse.com>):

```dotenv
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com   # or https://us.cloud.langfuse.com (US region)
```

Then just run as usual (`python run.py`, `python evaluate.py`, or the GUI). The
trace URL of each run is printed to the console (and to the GUI log).

### How to read a trace

The existing root trace contains Langfuse's standard LangChain callback events for
the graph, model calls and `run_python` tools. No second tracing service is needed.
The former custom `llm.generate`/iteration nesting and `LANGFUSE_FULL_PROMPT` option
are historical; callback naming and message capture now follow the integration.

- Root input is the rule; root output includes the verdict, violations and reason.
- Tool results contain captured output and explicit execution/error/truncation status.
- LangChain usage metadata normalizes cached input. The application counts total
  input once and keeps cache read/write counts separately; missing usage is unknown.
- Local records retain messages, tool schemas, actual execution records and every
  returned model call. GUI Markdown and HTML reports are presentation views; ledger
  details preserve the structured evidence even when Markdown omits reply content.
- An incomplete run is flagged at the root. A supported UNKNOWN is an abstention.

### Filtering and comparing

Traces carry tags — `mode:stateful` / `mode:stateless`, `case:<id>`,
`model:<id>`, `provider:<id>`, plus the entry point (`cli`, `eval`, `gui`) — and
flat metadata (`case_id`, `mode`, `model`, `iterations`, `executions`,
`total_tokens`, `parse_ok`, …). Filter the trace list on those to compare like
with like.

`evaluate.py` and the GUI additionally attach the **evaluation metrics as
Langfuse scores** on each trace: `precision`, `recall`, `f1`, `tp`/`fp`/`fn`,
`exact_set_match`, `verdict_match`, `parse_ok`, `abstained`, `verdict`,
`iterations`,
`executions`, `total_tokens`. That is what makes the thesis comparison readable
in Langfuse: filter by `mode:stateful` vs `mode:stateless` and chart the mean
`f1`, or sort the trace list by `f1` to find the bad runs immediately.

Every run of one sweep is grouped under a **session** (`eval-<stamp>-<case>`,
`gui-…`, `cli-…`), and the per-mode averages are posted as session scores
(`stateful.f1`, `stateless.f1`, …) so the sweep-level answer sits next to the
runs it summarises.

Token counts are tracked automatically; per-call **cost** only shows up for
models Langfuse has prices for, so MiniMax cost may read as zero (tokens are
still recorded).

## Security note

This application **executes arbitrary Python written by the model** in a separate
worker running as the same OS user. Process isolation is not a security sandbox:
absolute filesystem paths remain accessible. Keep credentials and reference answers
out of model context, and establish a separate filesystem/security boundary before
claiming that held-out reference files are inaccessible. Credentials and run artifacts
must stay out of version control.

## Offline regression tests

Software tests live in `tests/`; the compliance benchmark cases remain in
`ground_truth/`. Application entry points and runtime modules have not moved.

From `acc_agent/`, using the project Python environment:

```powershell
python -m unittest discover -s tests -t . -p "test_*.py" -v
```

From the workspace root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s acc_agent/tests -t acc_agent -p "test_*.py" -v
```

For a single test module, run from `acc_agent/`:

```powershell
python -m unittest tests.test_kernel_executor -v
```

These tests make no live model calls. They cover native tool-call execution, bounded
submission repair, provider response conversion, geometry-unit guidance and post-sweep GUI
integration. Local pilot logs are checked when present; those fixtures are skipped
when the gitignored logs are absent. The tests do not measure LLM quality.

## Next steps (not built yet)

- Extend explicitly approved live smoke coverage to OpenRouter and thinking-enabled
  settings. MiniMax thinking-off passed; offline tests do not establish model performance.
- Audit reference cases, then evaluate the frozen configuration on held-out cases.