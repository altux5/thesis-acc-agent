# Development Instructions

Read this file before planning, building, or changing this application. Then read
[NOTES.md](NOTES.md) for current decisions and [langchain.md](langchain.md) for the migration scope.

## Fix The Design, Not Just The Symptom

- If an error appears to require a substantial workaround, stop and revisit the design before adding more patches.
- Trace the failure to the component that owns the behavior. State the cause and use a small reproducing test before changing it.
- Prefer a coherent root-cause solution over case-specific exceptions, stacked retries, fallback chains, and duplicated guardrails.
- Review the relevant architecture when a local fix cannot express the intended behavior cleanly. Discuss material contract or scope changes with the user before implementing them.
- Keep necessary input validation, resource limits, and scientific integrity checks. Lean code does not mean silently accepting invalid or unsupported results.

## Keep The Application Lean

- Use standard library/framework capabilities before inventing custom infrastructure.
- Maintain one active implementation for each responsibility. Replace superseded paths rather than wrapping them or leaving commented implementations behind.
- Keep retired code for the thesis in `archive/`, not as comments in live files: copy it verbatim into a file there with a header (retired when, why, replaced by what, source file and line range at the latest tag), then remove it from the live file. Nothing imports from `archive/`. Tag milestones in the publishing repository so each stage can be checked out whole.
- Reuse suitable modules and tests. Do not introduce speculative abstractions, framework adapters, plugin systems, or future-proofing layers.
- No case-specific checking logic, hints, or reference answers in the evaluated agent. Preserve the separation between execution and offline scoring.
- Preserve user changes, historical experiments, and reference data. Do not delete features merely because they look unused; confirm scope first.
- Make a small testable change, run the focused check, and expand only after it passes. Report limitations honestly; do not claim tests or live API checks that were not run.
- Record meaningful architecture decisions and verification in [NOTES.md](NOTES.md).

## Test Case Names

- A case ID names the check (rule and model) and never changes. The current reference always owns the plain ID.
- Do not add version or scope tags such as `_v2`, `_v0`, `_full` or `_new` to case IDs. Record the version inside the reference (`reference.version`, `supersedes`), not in the name.
- To update a test, keep the old file as `<case_id>_deprecated_v<N>` (oldest `N=1`, never renumbered), point `supersedes` at it, and write the new reference under the unchanged ID. The GUI hides deprecated cases.
- Never reuse a deprecated ID. Runs are identified by reference hash, so old and new runs of one ID never pool.
- For requested GitHub updates, publish only reviewed agent files to [altux5/thesis-acc-agent](https://github.com/altux5/thesis-acc-agent) through the separate `C:\Users\Cogalgil\Documents\thesis-acc-agent` checkout, following the [publishing workflow](../.github/copilot-instructions.md#publishing-the-acc-agent). Exclude credentials, private artifacts and old Git history; leave the original `tez` repository untouched.