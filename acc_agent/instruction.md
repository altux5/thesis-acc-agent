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
- Reuse suitable modules and tests. Do not introduce speculative abstractions, framework adapters, plugin systems, or future-proofing layers.
- No case-specific checking logic, hints, or reference answers in the evaluated agent. Preserve the separation between execution and offline scoring.
- Preserve user changes, historical experiments, and reference data. Do not delete features merely because they look unused; confirm scope first.
- Make a small testable change, run the focused check, and expand only after it passes. Report limitations honestly; do not claim tests or live API checks that were not run.
- Record meaningful architecture decisions and verification in [NOTES.md](NOTES.md).