# Thesis ACC Agent

A research prototype for IFC building-compliance checking, developed for the
master's thesis *LLM-driven Automated Compliance Checking by Advancing CodeAct
Strategies* (Technical University of Munich, 2026). A CodeAct agent uses LangChain
to write and execute Python with IfcOpenShell. The primary experiment compares
stateful and stateless execution on the same kernel-style worker runtime.

The application, tests and reference JSONs are in [acc_agent](acc_agent). See the
[application README](acc_agent/README.md) for setup and usage, and the
[reference audit](acc_agent/PILOT_AUDIT.md) for benchmark limits. The development log
`NOTES.md` is kept private; links to it in the documentation refer to that log.

## Repository Scope

This is a clean source snapshot, not the original development repository's Git
history. Credentials, execution logs, traces, experiment databases, saved skills,
slides and personal documents are excluded.

The public IFC models used by the evaluation are in
[acc_agent/models](acc_agent/models), unmodified, each with its source and licence
notice ([SOURCES.txt](acc_agent/models/SOURCES.txt)).
[MODELS.json](acc_agent/models/MODELS.json) maps the model paths stored in the
reference JSONs to these files and records their SHA-256.

- `ec3/`: models of the EC3-2026 reproduction package (buildingSMART, CC BY 4.0;
  KIT, unrestricted use).
- `heldout/`: Esplanades (CC BY 4.0), Schependomlaan (scientific and academic use
  only), and two web-ifc test files (MPL-2.0).

The Singapore BCA test models used by the development cases are **not** included,
because there is no permission to redistribute them. `MODELS.json` marks them
`"distributed": false`. The cases that need them stay in the catalogue but run only
where the models are available locally; model-dependent tests skip without them.
This prototype is not a certified compliance checker.

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

The kernel contract check additionally requires the BCA mall IFC model, which is
not distributed:

```console
python acc_agent/check_runtime_parity.py
```

## Citation

If you use this code, please cite the thesis. GitHub's "Cite this repository"
button reads [CITATION.cff](CITATION.cff) and provides APA and BibTeX entries. Cite
the IFC models through their original sources as listed in
[acc_agent/models/SOURCES.txt](acc_agent/models/SOURCES.txt).

## Licence

The code, documentation and reference JSONs written for this project are released
under the [MIT Licence](LICENSE). The IFC models in [acc_agent/models](acc_agent/models)
are third-party data and keep their own licences and terms of use, given next to
each model. Labels and messages taken from third-party sources, such as the expert
labels of the BCA test workbooks, remain subject to the terms of those sources.