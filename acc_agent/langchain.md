# LangChain Migration Plan

Status: implemented and offline-verified 2026-09-17. Approved MiniMax smoke test passed; live OpenRouter and thinking-enabled tests remain pending.
Scope: migration and simplification only, before the case/reference audit.

## Goal

One small, standard CodeAct system: the model writes Python, the worker executes it,
and the application validates and records the result. Replace custom orchestration;
do not wrap the existing loop in another agent or maintain two implementations.

LangChain standardizes infrastructure. Correctness and defensibility still depend
on explicit execution contracts, independent references, tests, and recorded settings.

## Architecture Verdict

Use LangChain's standard `create_agent`. It already runs on LangGraph; do not build
a custom `StateGraph`, adopt Deep Agents, or preserve the old loop behind a wrapper.

| Component | Decision and reason |
| --- | --- |
| LangChain | Use standard model integrations, tool calling, structured responses, and agent middleware. Replace plumbing we currently own. |
| LangGraph | Use the runtime underneath `create_agent`; no custom workflow graph, checkpointer, server, or deployment service initially. |
| Deep Agents | Do not add its filesystem, delegation, and context-management stack to this migration. Those capabilities are not needed to standardize the current experiment. |
| Existing application | Retain the GUI, Python worker, scientific validation, and experiment records. No replacement UI or second recording system. |

This is one system, not a framework comparison. Standard infrastructure should reduce
maintenance; better compliance accuracy or lower token usage is not assumed.

## How It Works

```text
GUI / CLI -> shared run configuration -> LangChain create_agent
                                          |
                                    run_python(code)
                                          |
                                    existing worker
                                          |
                              output + execution status

Committed labels + final response -> completion validation -> recorded result
Recorded result + reference       -> offline scoring and comparisons
```

1. The existing entry point passes a rule, IFC path, and validated run configuration to one shared runner.
2. A small model factory builds the configured LangChain model. The agent receives one domain-neutral tool: `run_python(code)`.
3. The tool calls the existing worker and returns bounded output and execution status. Calls to a worker are sequential, even if the model requests multiple actions.
      A response mixing Python with FinalReport is rejected before any code executes; the model must resubmit separate actions within its budget.
4. Python submits the full label mapping through `report_labels(...)`. The host retains it; no extra LLM call is needed to transcribe labels.
5. LangChain requests a structured final response. A small completion hook checks it against committed labels, execution status, and independently discoverable scope before acceptance.
6. Pydantic validation through LangChain's `ToolStrategy` checks structured submissions against committed evidence. Rejected submissions receive concrete issues within the same agent run and budget. Exhaustion produces an explicit partial/incomplete outcome, not an outer retry loop or guessed verdict.
7. The existing recorder receives the outcome and usage; the GUI displays progress and results. Reference-based scoring stays outside the agent.

Use standard structured-output support instead of Markdown extraction or `FINAL:`
text parsing on the new model path. Schema validity does not replace scientific
validation. Keep any legacy format handling at the historical-data boundary only.

Use built-in model/tool call limits and retry facilities where suitable; configure
output caps and worker timeouts explicitly. Add only the small application-specific
hooks needed for completion, usage/budget accounting, and existing event consumers.
Do not rebuild the handwritten agent loop inside middleware.

No new API account is required: use the existing LLM providers and optional Langfuse.
Verify provider tool calling, reasoning, structured output, and usage before cutover.
No skills, subagents, cross-run memory, summarization, or model fallback initially.

## Lean Design Rules

- Reuse current modules; avoid a new package hierarchy or one class per processing step.
- One model factory, one runner, one execution tool, and one result serialization path. GUI and CLI do not own agent logic.
- Remove replaced production paths and their exclusive tests in the same migration. Do not retain commented implementations or introduce a compatibility framework.
- Preserve useful contract tests, not every old parser or internal message representation. Fewer lines are not worth weaker failure handling.
- Do not redesign the GUI, database, or report presentation during orchestration migration. Adapt their input boundary and remove proven duplication only.
- No framework-neutral adapter, plugin system, or future Deep Agents switch. Standard LangChain models and tools already provide a reasonable future integration boundary.

## Keep, Replace, Remove

Keep responsibilities and tested behavior, not necessarily every current function or file.

| Area | Proposed treatment |
| --- | --- |
| [agent.py](agent.py) | Replace the handwritten conversation loop with a small LangChain setup and only necessary validation/budget hooks. |
| [llm.py](llm.py) | Replace custom message conversion with a small model factory using supported integrations; no new provider-plugin framework. |
| [kernel_executor.py](kernel_executor.py), [kernel_worker.py](kernel_worker.py) | Keep worker isolation, persistence/reset, timeouts, crash handling, and label commits. |
| [executor.py](executor.py) | Keep reporting/output utilities still used by the worker; remove obsolete code extraction and commented in-process executor after caller migration. |
| [completion.py](completion.py), [scoring.py](scoring.py) | Keep independent validation and scoring; adapt the input format without silently changing label meanings or metrics. |
| [ground_truth.py](ground_truth.py), reference and audit utilities | Keep unchanged. Reference review is the next project stage, not part of migration. |
| [gui.py](gui.py), [run.py](run.py), [evaluate.py](evaluate.py) | Keep existing workflows; all call the same runner. No UI redesign or separate orchestration per entry point. |
| [experiments.py](experiments.py), recorder and code identity | Keep reproducible records, partial failures, and configuration identity; remove duplicate serialization only where demonstrated. |
| [tracing.py](tracing.py) | Keep optional Langfuse through the standard integration where feasible; do not add a second tracing service. |
| [skill_library.py](skill_library.py), retired paths and their exclusive tests | Recommend removing from active source after agreement; preserve history and existing experiment artifacts, and migrate any shared contract tests before deleting old suites. |

## Contracts To Preserve

- Stateful keeps a Python worker; stateless restarts it between blocks. Both retain conversation history.
- Document scratch-file lifetime separately from Python state. Do not add persistent files as an alternative memory channel.
- Graph checkpoints do not restore live Python objects. Do not add automatic resume or replay of executed code in this migration.
- Keep the five labels and distinguish completion, abstention, errors, and incorrect answers. Coverage checks do not prove measurement correctness.
- Keep reference labels and solutions outside model messages/tools. The existing worker is not a security sandbox; filesystem isolation must be addressed explicitly before claiming held-out data is inaccessible.
- Define one budget policy covering model calls, output tokens, execution time, retries, and finalization. Count extra calls; do not silently retry code that may already have executed.
- Record effective prompts, tool schemas, package versions, model/provider settings, budgets, execution mode, and IFC/reference identities. Missing usage remains unknown, not zero cost.
- Give migrated runs a new configuration identity. Preserve historical records without pooling different implementations as identical conditions.

## Agreed Scope

| Decision | Recommendation | Status |
| --- | --- | --- |
| Harness options | H1/basic and H2/planning through the same runner. H3 retired from new runs; historical H3 records unchanged. No new verifier. | Confirmed |
| Run artifacts | Existing ledger retains structured messages, execution evidence and configuration; JSON exports, GUI text/HTML and Langfuse consume the same result/events. No new database or UI. | Retained |
| Archived skills | Keep archived skill code and its standalone tests. It is not exposed to new runs. Do not delete archives as part of this migration. | Confirmed |
| Mixed responses | Reject Python-plus-FinalReport before side effects; request separate actions. No framework-internal routing patches. | Confirmed |

## Implemented Budget

`max_iterations` now means total model calls, including the H2 plan, schema repairs,
and final submissions. Python tool calls have the same numeric cap. Output is capped
at 8,000 tokens per model call; request timeout is 180 seconds. Provider retries are
disabled so hidden retries cannot undermine usage accounting. Existing worker startup,
execution timeout and output limits remain in force. There is no separate finalization
allowance, cumulative token/cost cap, automatic code replay, or cross-run memory.

The existing result's `finalization_attempts` counts FinalReport submissions in the new
protocol. `langchain-codeact-v1` and recording version 3 distinguish these runs from
historical budgets and protocols.

## Migration Steps

1. Agree on the scope above and record the exact contracts and budgets. Use the existing tests to establish the current behavior; do not preserve known defects merely for parity.
2. Verify the selected LangChain/provider versions, `run_python` tool, and bounded completion hook against scripted responses. Reuse the current worker, with no application cutover yet. If standard agent hooks cannot enforce the contract cleanly, revisit the design before adding another loop or graph.
3. Replace the loop and connect GUI, CLI, scoring, recording, and optional tracing to the same runner. Remove superseded code in the same migration, not in an indefinite later cleanup.
4. Adapt existing tests to the public contracts, verify the gates below, pin dependencies, and update operating instructions. Freeze this version before auditing cases.

The temporary integration work is not another benchmark condition or a maintained fallback.
Keep the previous version recoverable in version control. Stop and revisit scope if
provider compatibility requires a substantial custom framework or the migration grows beyond a short milestone.

## Verification

- [x] One active runner and model factory; no nested legacy agent loop. Archived skill/runtime code remains inactive, outside the new orchestration.
- [x] All 208 offline tests and the kernel contract check pass, including both Python execution modes.
- [x] Scripted tests cover tool sequencing, invalid arguments, execution errors/restarts, label commits, rejected finals, budget exhaustion, and partial recording.
- [x] Planning, structured-output repairs, and finalization share the recorded budget; no concurrent worker mutation or automatic replay of code with uncertain execution status.
- [x] Removing a label or contradicting the committed labels cannot produce an accepted complete result.
- [x] Both native provider adapters pass mocked end-to-end tool/schema roundtrips and usage-accounting checks. Dependency consistency and CLI startup checks pass.
- [x] Approved live MiniMax-M3 smoke: H1/stateful, reasoning off, synthetic two-door IFC; complete, both labels correct, 3 model calls / 2 executions, 3,491 input / 559 output tokens (1,664 cached input).
- [ ] Live OpenRouter and thinking-enabled checks. The Anthropic integration warns that forced tool selection is unavailable with thinking enabled; it drops forced selection. No prose-execution fallback was added.
- [x] Existing GUI workflows, logs, scores and reports pass offline integration tests; new orchestration dependencies are pinned and H3 is removed from new-run controls.

Smoke transcript: [runs/20260917-154159_langchain_smoke.json](runs/20260917-154159_langchain_smoke.json).
This is an integration check, not evidence of benchmark accuracy or efficiency.
Restart the GUI before new runs so the imported modules match the migrated source.

## Not Part Of This Work

Reference corrections, Solibri cases, new compliance algorithms, case-specific hints,
performance tuning, new harness experiments, and a framework comparison study.

Lean means fewer active paths and fewer duplicated responsibilities, not fewer tests
or weaker scientific safeguards. Add another abstraction only when two real callers need it.