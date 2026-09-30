"""Offline reports from GUI Markdown logs. Never imports or calls the agent."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean


@dataclass
class Section:
    header: str
    line: int
    text: str = ""


@dataclass
class Step:
    title: str
    line: int
    sections: list[Section] = field(default_factory=list)

    @property
    def codes(self) -> list[Section]:
        return [section for section in self.sections if section.header == "### Code"]

    @property
    def outputs(self) -> list[Section]:
        return [section for section in self.sections if section.header == "### Output"]

    def _output_records(self) -> list[tuple[Section, dict]]:
        records: list[tuple[Section, dict]] = []
        for section in self.sections:
            if section.header == "### Output":
                records.append((section, {}))
            elif section.header == "### Execution status" and records:
                try:
                    status = json.loads(section.text)
                except ValueError:
                    continue
                if isinstance(status, dict):
                    records[-1] = (records[-1][0], status)
        return records

    @property
    def errors(self) -> list[str]:
        errors = []
        for output, status in self._output_records():
            failed = status["error"] if isinstance(status.get("error"), bool) else "Traceback (most recent call last):" in output.text
            if failed:
                lines = str(status.get("error_text") or output.text).splitlines()
                errors.append(next(
                    (line.strip() for line in reversed(lines)
                     if re.match(r"^(?:[\w.]+(?:Error|Exception)|SystemExit|KeyboardInterrupt|Execution(?:Timeout|KernelDied)):", line)),
                    "Execution failed; exception details unavailable",
                ))
        return errors

    @property
    def restarts(self) -> list[str]:
        """Kernel restarts, which discard everything the session had built up."""
        return [str(status.get("restart_reason") or "unspecified")
                for _, status in self._output_records()
                if status.get("kernel_restarted") is True]

    @property
    def truncations(self) -> int:
        return sum(int(status["truncated"]) if isinstance(status.get("truncated"), bool)
               else len(re.findall(r"\[truncated \d+ characters\]", output.text))
               for output, status in self._output_records())


@dataclass
class Run:
    mode: str
    repeat: int
    expected_repeats: int
    line: int
    steps: list[Step] = field(default_factory=list)
    metrics: dict[str, str] = field(default_factory=dict)
    verdict: str = "Not recorded"
    verdict_recorded: bool = False
    violations: int | None = None
    score_line: int | None = None
    iterations: int | None = None
    tokens: tuple[int, int] | None = None
    failure: str = ""
    completion: dict = field(default_factory=dict)
    usage_complete: bool | None = None
    usage_records: list[dict] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.mode} {self.repeat}/{self.expected_repeats}"

    @property
    def labels(self) -> tuple[int, int] | None:
        match = re.fullmatch(r"(\d+)/(\d+)", self.metrics.get("labels", ""))
        return (int(match[1]), int(match[2])) if match else None

    @property
    def submitted_count(self) -> int | None:
        if self.labels:
            return self.labels[0]
        value = self.completion.get("labels_submitted")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @property
    def attempts(self) -> int:
        return sum(len(step.codes) for step in self.steps)

    @property
    def errors(self) -> int:
        return sum(len(step.errors) for step in self.steps)

    @property
    def truncations(self) -> int:
        return sum(step.truncations for step in self.steps)

    @property
    def restarts(self) -> list[str]:
        return [reason for step in self.steps for reason in step.restarts]

    @property
    def warnings(self) -> list[str]:
        warnings = []
        if self.usage_complete is False:
            warnings.append("Token counts are known usage only; one or more requests have unreported usage. They are not a full cost total.")
        status = self.completion.get("status")
        if status and status != "complete":
            warnings.append("Completion status: " + str(status) + ".")
        warnings.extend(str(issue) for issue in self.completion.get("issues", []))
        if status == "incomplete":
            warnings.append("No accepted final submission within the available budget.")
        elif not self.verdict_recorded:
            warnings.append("No final verdict recorded; run may be interrupted.")
        elif self.metrics.get("parse_ok") == "0":
            warnings.append("Final verdict was not parseable by the checker.")
        if self.failure:
            warnings.append("Sweep error recorded: " + excerpt(self.failure))
        if self.labels and self.labels[1] > 0:
            if self.labels[0] == 0:
                warnings.append("No element labels submitted; a verdict is not a complete report.")
            elif self.labels[0] < self.labels[1]:
                warnings.append("Fewer labels submitted than reference anchors.")
            elif self.labels[0] > self.labels[1]:
                warnings.append("More labels submitted than reference anchors; check evaluation scope.")
        coverage = metric_number(self.metrics.get("coverage"))
        if coverage is not None and coverage < 1:
            warnings.append("Submitted labels do not cover every reference anchor.")
        if self.errors:
            warnings.append(f"{self.errors} execution attempt(s) returned a traceback.")
        if self.restarts:
            reasons = ", ".join(sorted(set(self.restarts)))
            warnings.append(
                f"{len(self.restarts)} execution kernel restart(s) ({reasons}); "
                "everything the session had built up was discarded at that point.")
        if self.truncations:
            warnings.append(f"{self.truncations} output(s) truncated before logging; evidence is missing.")
        if any(len(step.codes) > len(step.outputs) for step in self.steps):
            warnings.append("Code was logged without corresponding output; execution outcome unavailable.")
        if any("Final step: requesting" in section.header
               for step in self.steps for section in step.sections):
            warnings.append("Final-step budget prompt issued.")
        if self.metrics.get("union_acc") == "n/a":
            warnings.append("Union accuracy unavailable; excluded from the existing conditional average.")
        return warnings


@dataclass
class Report:
    source: Path
    metadata: dict[str, str]
    runs: list[Run]
    source_text: str

    @property
    def expected_runs(self) -> int:
        modes = self.metadata.get("Modes", "")
        repeats = re.search(r"(?:\u00d7|\bx)\s*(\d+)\s*$", modes)
        if repeats:
            return int(repeats[1]) * len(re.findall(r"\b(?:stateful|stateless)\b", modes))
        return sum(max(run.expected_repeats for run in self.runs if run.mode == mode)
                   for mode in {run.mode for run in self.runs})


def excerpt(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[:limit - 3] + "..."


def metric_number(value: str | None) -> float | None:
    try:
        return float(value) if value is not None and value != "n/a" else None
    except ValueError:
        return None


def _sections(text: str) -> list[Section]:
    sections: list[Section] = []
    current: Section | None = None
    body: list[str] = []
    fence = ""
    for number, line in enumerate(text.splitlines(), 1):
        fence_match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence:
            body.append(line)
            if re.fullmatch(r"\s{0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*", line):
                fence = ""
            continue
        if fence_match:
            fence = fence_match[1]
            body.append(line)
            continue
        if re.match(r"^#{1,3} |^\*\*Score\*\*|^> NOTE:|^- \*\*|^- (?:iterations|tokens):|^  confusion:", line):
            if current:
                current.text = "\n".join(body).strip()
                sections.append(current)
            current = Section(line, number)
            body = []
        else:
            body.append(line)
    if current:
        current.text = "\n".join(body).strip()
        sections.append(current)
    for section in sections:
        if section.header in ("### Code", "### Output", "### Execution status", "### Completion", "### Usage", "### Usage summary", "### Partial usage", "## ERROR"):
            lines = section.text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
            section.text = "\n".join(lines)
    return sections


def parse_log(text: str, source: Path) -> Report:
    metadata: dict[str, str] = {}
    runs: list[Run] = []
    run: Run | None = None
    step: Step | None = None
    for section in _sections(text):
        header = section.header
        run_match = re.fullmatch(r"# (stateful|stateless) .*?run (\d+)/(\d+)", header)
        if run_match:
            run = Run(run_match[1], int(run_match[2]), int(run_match[3]), section.line)
            runs.append(run)
            step = None
            continue
        if run is None:
            meta = re.fullmatch(r"- \*\*([^*]+):\*\*\s*(.*)", header)
            if meta:
                metadata[meta[1]] = meta[2]
            continue
        if header.startswith("## Iteration ") or header == "## Plan":
            step = Step(header[3:], section.line)
            run.steps.append(step)
        elif header.startswith("**Score**"):
            run.metrics = dict(re.findall(r"(\w+)=([^\s]+)", header))
            run.score_line = section.line
            if run.metrics.get("iters", "").isdigit():
                run.iterations = int(run.metrics["iters"])
            tokens = re.fullmatch(r"(\d+)/(\d+)", run.metrics.get("tok", ""))
            if tokens:
                run.tokens = int(tokens[1]), int(tokens[2])
        elif header in ("### Usage", "### Usage summary", "### Partial usage"):
            try:
                usage = json.loads(section.text)
            except ValueError:
                run.usage_complete = False
                continue
            if isinstance(usage, dict):
                if header == "### Usage":
                    run.usage_records.append(usage)
                    if usage.get("usage_reported") is False:
                        run.usage_complete = False
                elif isinstance(usage.get("usage_complete"), bool):
                    run.usage_complete = usage["usage_complete"]
                if header == "### Partial usage":
                    counts = (usage.get("prompt_tokens"), usage.get("completion_tokens"))
                    if all(isinstance(value, int) for value in counts):
                        run.tokens = counts
                    run.iterations = usage.get("iterations", run.iterations)
        elif header == "### Completion":
            try:
                completion = json.loads(section.text)
                if isinstance(completion, dict):
                    run.completion = completion
            except ValueError:
                run.completion = {"status": "unreadable", "issues": ["Completion record could not be parsed."]}
        elif header == "### Verdict":
            raw = section.text.strip()
            run.verdict_recorded = bool(raw and not raw.startswith("(no verdict reached)"))
            run.verdict = (excerpt(raw, 100) if run.verdict_recorded else "(no verdict reached)")
            after = raw.partition("FINAL:")[2].strip()
            try:
                verdict, _ = json.JSONDecoder().raw_decode(after)
                if isinstance(verdict, dict):
                    run.verdict = str(verdict.get("verdict", "Not recorded"))
                    if isinstance(verdict.get("violations"), list):
                        run.violations = len(set(map(str, verdict["violations"])))
            except (ValueError, TypeError):
                pass
        elif header.startswith("- iterations:"):
            value = header.partition(":")[2].strip()
            run.iterations = int(value) if value.isdigit() else None
        elif header.startswith("- tokens:"):
            tokens = re.search(r"(\d+) in / (\d+) out", header)
            if tokens:
                run.tokens = int(tokens[1]), int(tokens[2])
        elif header == "## ERROR":
            run.failure = section.text
        if step is not None and (header.startswith("### ") or header.startswith("> NOTE:") or header == "## Plan"):
            step.sections.append(section)
    if not runs:
        raise ValueError("No GUI run sections found in this log.")
    return Report(source, metadata, runs, text)


def step_summary(step: Step) -> str:
    if step.errors:
        outcome = "; ".join(excerpt(error, 120) for error in step.errors)
        if step.restarts:
            outcome += f" [kernel restarted: {', '.join(step.restarts)}; session state lost]"
    elif step.outputs:
        outcome = "Output recorded; correctness not assessed"
    elif step.codes:
        outcome = "Code logged; no output recorded"
    elif any(section.header == "### Verdict" for section in step.sections):
        outcome = "Final-response section recorded"
    else:
        outcome = "No code attempt logged"
    return f"{step.title}: {len(step.codes)} code attempt(s). {outcome}. Source line {step.line}."


def step_explanation(step: Step) -> str:
    return next((section.text for section in step.sections
                 if section.header in ("### Reasoning", "## Plan") and section.text), "")


def render_text(report: Report, include_timeline: bool = True) -> str:
    lines = ["FACTUAL REPORT", report.metadata.get("Case", report.source.stem)]
    lines.append(" | ".join(f"{key}: {report.metadata.get(key, 'not recorded')}"
                            for key in ("Provider", "Model", "Modes", "Harness", "Max iterations")))
    finished = sum(run.verdict_recorded for run in report.runs)
    lines.append(f"Runs logged: {len(report.runs)}/{report.expected_runs}; final verdicts recorded: {finished}.")
    statuses = [run.completion.get("status", "not recorded") for run in report.runs]
    lines.append("Completion: " + ", ".join(f"{statuses.count(status)} {status}" for status in dict.fromkeys(statuses)) + ".")
    lines.append("No AI calls. Reference agreement is not independent verification of correctness.")
    lines.append("Labels submitted are not proof of inspection. Missing log content cannot be recovered.")
    if report.metadata.get("Harness", "").startswith("level 3"):
        lines.append("WARNING: level 3 uses same-case reference feedback; TRAIN results only.")
    if report.metadata.get("Case") in ("slab_thickness__mall", "slab_thickness__mall_deprecated_v1"):
        # Pre-2026-09-30 logs used the plain ID for the invalid legacy reference; its logs record no version 2.
        if report.metadata.get("Reference") == "2":
            lines.append("WARNING: reference v2 is a 100 PASS / 12 ALERT / zero FAIL control. F1 cannot measure violation detection on this case.")
        else:
            lines.append("WARNING: this slab reference is known to be invalid (see NOTES.md); do not rank agents by these scores.")
    if len(report.runs) < report.expected_runs:
        lines.append("WARNING: fewer runs logged than requested; sweep may be interrupted.")
    for mode in dict.fromkeys(run.mode for run in report.runs):
        runs = [run for run in report.runs if run.mode == mode]
        f1_values = [value for run in runs if (value := metric_number(run.metrics.get("F1"))) is not None]
        accuracy_values = [value for run in runs if (value := metric_number(run.metrics.get("union_acc"))) is not None]
        lines.append(f"\n{mode.upper()} SUMMARY")
        lines.append(f"Labels submitted in {sum(bool(run.submitted_count) for run in runs)}/{len(runs)} runs "
                 f"(label counts unavailable in {sum(run.submitted_count is None for run in runs)}).")
        if f1_values:
            lines.append(f"Mean F1 vs reference: {mean(f1_values):.3f} over {len(f1_values)}/{len(runs)} runs.")
        if accuracy_values:
            lines.append(f"Conditional mean union accuracy: {mean(accuracy_values):.3f} over "
                         f"{len(accuracy_values)}/{len(runs)} runs; missing values excluded, not zero.")
        for run in runs:
            lines.extend(["", f"{run.name}: {run.verdict}"])
            lines.append(f"Completion: {run.completion.get('status', 'not recorded')}; "
                         f"IFC scope anchors: {run.completion.get('expected_anchors', 'not recorded')}; "
                         f"finalization turns: {run.completion.get('finalization_attempts', 'not recorded')}.")
            labels = f"{run.labels[0]}/{run.labels[1]}" if run.labels else str(run.submitted_count) if run.submitted_count is not None else "not recorded"
            lines.append(f"Labels submitted: {labels}; coverage: {run.metrics.get('coverage', 'n/a')}; "
                         f"F1: {run.metrics.get('F1', 'n/a')}; union accuracy: {run.metrics.get('union_acc', 'n/a')}.")
            lines.append(f"Violations in verdict: {run.violations if run.violations is not None else 'not recorded'}; "
                         f"TP/FP/FN vs reference: {run.metrics.get('tp', '?')}/{run.metrics.get('fp', '?')}/{run.metrics.get('fn', '?')}.")
            tokens = f"{run.tokens[0]} in / {run.tokens[1]} out (as logged)" if run.tokens else "not recorded"
            lines.append(f"Iterations: {run.iterations}; code attempts: {run.attempts}; errors: {run.errors}; tokens: {tokens}.")
            lines.extend("WARNING: " + warning for warning in run.warnings)
            if include_timeline:
                for step in run.steps:
                    lines.append("  " + step_summary(step))
                    explanation = step_explanation(step)
                    if explanation:
                        lines.append("    Agent excerpt (unverified): " + excerpt(explanation))
                    for output in step.outputs:
                        lines.append("    Output excerpt: " + excerpt(output.text))
    return "\n".join(lines) + "\n"


_STYLE = """
:root { color-scheme: light; --ink: #222; --muted: #555; --line: #d6dcde;
        --accent: #0065bd; --warning: #9a3c14; }
* { box-sizing: border-box; letter-spacing: 0; }
body { margin: 0; color: var(--ink); background: #f6f8f8;
       font: 15px/1.5 'Segoe UI', sans-serif; }
main { max-width: 1120px; padding: 24px; margin: auto; }
h1 { font-size: 25px; margin: 0 0 8px; }
h2 { font-size: 19px; margin: 0 0 10px; }
h3 { font-size: 16px; }
section { padding: 20px 0; border-top: 1px solid var(--line); }
p, li, td, summary { overflow-wrap: anywhere; }
a { color: var(--accent); }
.muted { color: var(--muted); }
.warning { color: var(--warning); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; background: white; }
th, td { padding: 9px 10px; text-align: left; border-bottom: 1px solid var(--line); }
th { font-size: 13px; background: #eaf0f0; }
details { padding: 10px 0; border-bottom: 1px solid var(--line); }
summary { cursor: pointer; font-weight: 600; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #eef1f2;
      padding: 12px; font: 12px/1.5 Consolas, monospace; }
blockquote { border-left: 3px solid #91aaa3; margin: 12px 0; padding: 0 12px; }
.source-line { display: block; scroll-margin-top: 12px; }
.source-line:target { background: #fff0b3; }
.line-number { color: #666; display: inline-block; width: 5em; user-select: none; }
@media (max-width: 600px) { main { padding: 14px; } th, td { padding: 7px; } }
"""


def _link(line: int, label: str) -> str:
    return f'<a href="#L{line}" data-evidence="true">{html.escape(label)}</a>'


def render_html(report: Report) -> str:
    escape = html.escape
    title = report.metadata.get("Case", report.source.stem)
    summary = render_text(report).splitlines()
    overview = summary[:next((index for index, line in enumerate(summary) if line.endswith(" SUMMARY")), len(summary))]
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; script-src \'unsafe-inline\'">',
        f'<title>Factual report: {escape(title)}</title><style>{_STYLE}</style></head><body><main>',
        f'<h1>{escape(title)}</h1><p>Factual run report | {escape(report.metadata.get("When", "Time not recorded"))}</p>',
        f'<p class="muted">Source: {escape(report.source.name)}. Zero additional AI tokens.</p>',
    ]
    for line in overview[2:]:
        if line:
            css = ' class="warning"' if line.startswith("WARNING:") else ""
            parts.append(f'<p{css}>{escape(line)}</p>')
    parts.append('<p class="muted">Code below was logged for execution, not merely proposed. '
                 'A recorded output does not prove correctness. Agent excerpts are unverified, '
                 'not explanations inferred by this report. Complete AI replies and truncated output '
                 'are not available in these logs. Retries are shown as separate attempts; their intent is not inferred.</p>')
    parts.append('<section><h2>Results</h2><div class="table-wrap"><table><thead><tr>'
                 '<th>Run</th><th>Verdict</th><th>Completion</th><th>Labels submitted</th><th>F1</th>'
                 '<th>Union accuracy</th><th>Iterations</th><th>Code attempts / errors</th>'
                 '</tr></thead><tbody>')
    for number, run in enumerate(report.runs, 1):
        labels = f"{run.labels[0]}/{run.labels[1]}" if run.labels else str(run.submitted_count) if run.submitted_count is not None else "Not recorded"
        values = [run.verdict, str(run.completion.get("status", "not recorded")), labels, run.metrics.get("F1", "n/a"),
                  run.metrics.get("union_acc", "n/a"), str(run.iterations or "Not recorded"),
                  f"{run.attempts} / {run.errors}"]
        parts.append(f'<tr><td><a href="#run-{number}">{escape(run.name)}</a></td>' +
                     "".join(f'<td>{escape(value)}</td>' for value in values) + '</tr>')
    parts.append('</tbody></table></div>')
    for line in summary:
        if line.startswith(("Labels submitted in ", "Mean F1 vs reference:", "Conditional mean union accuracy:")) or line.endswith(" SUMMARY"):
            parts.append(f'<p>{escape(line)}</p>')
    parts.append('</section>')
    for number, run in enumerate(report.runs, 1):
        parts.append(f'<section id="run-{number}"><h2>{escape(run.name)}: {escape(run.verdict)}</h2>')
        parts.append(f'<p>{_link(run.score_line or run.line, "Source result")} | '
                     f'Violations in verdict: {run.violations if run.violations is not None else "not recorded"} | '
                     f'TP/FP/FN: {escape(run.metrics.get("tp", "?"))}/'
                     f'{escape(run.metrics.get("fp", "?"))}/{escape(run.metrics.get("fn", "?"))}</p>')
        if run.tokens:
            parts.append(f'<p>Tokens as logged: {run.tokens[0]:,} input / {run.tokens[1]:,} output. '
                         'New input totals include cache once. Partial usage is a lower bound; older logs may omit cache counts.</p>')
        if run.warnings:
            parts.append('<ul class="warning">' + ''.join(f'<li>{escape(warning)}</li>' for warning in run.warnings) + '</ul>')
        parts.append('<h3>Execution timeline</h3>')
        for step in run.steps:
            parts.append(f'<details><summary>{escape(step_summary(step))}</summary>')
            parts.append(f'<p>{_link(step.line, "Step evidence")}</p>')
            explanation = step_explanation(step)
            if explanation:
                parts.append(f'<p class="muted">Agent explanation excerpt (unverified):</p>'
                             f'<blockquote>{escape(excerpt(explanation, 500))}</blockquote>')
            else:
                parts.append('<p class="muted">Agent explanation not recorded.</p>')
            for section in step.sections:
                if section.header in ("### Code", "### Output"):
                    label = "Code attempt" if section.header == "### Code" else "Recorded output"
                    parts.append(f'<details><summary>{label} ({_link(section.line, "source")})</summary>'
                                 f'<pre>{escape(section.text)}</pre></details>')
                elif section.header.startswith("> NOTE:"):
                    parts.append(f'<p class="warning">{escape(section.header[2:])}</p>')
                elif section.header == "### Verdict":
                    parts.append(f'<p>Recorded final response: {escape(excerpt(section.text, 240))}</p>')
            parts.append('</details>')
        parts.append('</section>')
    parts.append('<section><details id="source"><summary>Original log with line references</summary><pre>')
    parts.extend(f'<span class="source-line" id="L{number}"><span class="line-number">{number}</span>{escape(line)}</span>'
                 for number, line in enumerate(report.source_text.splitlines(), 1))
    parts.append('</pre></details></section></main><script>'
                 'document.addEventListener("click", function(event) {'
                 'const link = event.target.closest("a[data-evidence]");'
                 'if (link) document.getElementById("source").open = true;'
                 '});</script></body></html>')
    return '\n'.join(parts)


def generate_report(source: Path) -> tuple[Report, Path]:
    source = Path(source)
    report = parse_log(source.read_text(encoding="utf-8-sig"), source)
    destination = source.with_suffix(".report.html")
    destination.write_text(render_html(report), encoding="utf-8")
    return report, destination


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", type=Path, nargs="+", help="GUI Markdown log file(s).")
    args = parser.parse_args()
    for path in args.logs:
        try:
            report, destination = generate_report(path)
            print(render_text(report))
            print(f"Report saved to: {destination}")
        except (OSError, ValueError) as exc:
            parser.exit(1, f"{path}: {exc}\n")


if __name__ == "__main__":
    main()