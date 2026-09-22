# Thesis ACC Agent

A research prototype for IFC building-compliance checking. A CodeAct agent uses
LangChain to write and execute Python with IfcOpenShell. The primary experiment
compares stateful and stateless execution on the same kernel-style worker runtime.

The application, tests, reference JSONs and development notes are in
[acc_agent](acc_agent). See the [application README](acc_agent/README.md) for setup
and usage, and the [reference audit](acc_agent/PILOT_AUDIT.md) for benchmark limits.

## Repository Scope

This is a clean source snapshot, not the original development repository's Git
history. Credentials, execution logs, traces, experiment databases, saved skills,
slides, personal documents and source IFC models are excluded.

Reference JSONs contain labels and metadata, not the IFC models. Obtain any
required models separately with appropriate permission and preserve the relative
paths documented in the cases. Model-dependent tests may skip when these external
fixtures are unavailable. This prototype is not a certified compliance checker.

## Development

Use Python 3.13 and a virtual environment, then install
[acc_agent/requirements.txt](acc_agent/requirements.txt). For local credentials,
use [environment.example](environment.example) as the template for
`acc_agent/.env`. References to `.env.example` in the application documentation
refer to this template in this source snapshot. Never commit credentials.

From the repository root, run the offline regression suite with:

```console
python -m unittest discover -s acc_agent/tests -t acc_agent -p "test_*.py"
```

The kernel contract check additionally requires the external mall IFC fixture:

```console
python acc_agent/check_runtime_parity.py
```