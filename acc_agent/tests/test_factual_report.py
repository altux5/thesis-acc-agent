import os
import subprocess
import sys
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from factual_report import generate_report, parse_log, render_html, render_text, step_summary


HEADER = """# Compliance check sweep
- **Case:** sample
- **Model:** offline
- **Modes:** stateful x 1
- **Harness:** level 1
- **Max iterations:** 3

# stateful - run 1/1
"""


class FactualReportTests(unittest.TestCase):
    def parse(self, body):
        return parse_log(HEADER + body, Path("sample.md"))

    def test_partial_usage_survives_failed_run_without_final_verdict(self):
        report = self.parse('''
## Iteration 1 / 3
### Usage
```json
{"phase":"iteration 1","usage_reported":true,"prompt_tokens":1000,"completion_tokens":100}
```
### Partial usage
```json
{"prompt_tokens":1000,"completion_tokens":100,"iterations":2,"usage_complete":false}
```
## ERROR
```
RuntimeError: second call failed
```
''')
        run = report.runs[0]
        self.assertEqual(run.tokens, (1000, 100))
        self.assertFalse(run.usage_complete)
        self.assertFalse(run.verdict_recorded)
        self.assertIn("known usage only", render_text(report))

    def test_structured_execution_status_takes_precedence_over_stdout(self):
        report = self.parse('''
## Iteration 1 / 3
### Code
```python
print("traceback hidden by output")
```
### Output
```
captured text only
```
### Execution status
```json
{"error":true,"error_text":"SystemExit: 7","truncated":true}
```
### Code
```python
print("Traceback (most recent call last):")
```
### Output
```
Traceback (most recent call last):
... [truncated 3 characters]
```
### Execution status
```json
{"error":false,"error_text":"","truncated":false}
```
''')
        run = report.runs[0]
        self.assertEqual(run.errors, 1)
        self.assertEqual(run.truncations, 1)
        self.assertIn("SystemExit: 7", render_text(report))

    def test_mixed_old_and_new_output_statuses_do_not_mask_old_errors(self):
        report = self.parse('''
## Iteration 1 / 3
### Output
```
Traceback (most recent call last):
ValueError: old error
```
### Output
```
no printed error
```
### Execution status
```json
{"error":true,"error_text":"RuntimeError: new error","truncated":false}
```
''')
        self.assertEqual(report.runs[0].errors, 2)

    def test_code_and_output_cannot_spoof_score_or_run_sections(self):
        report = self.parse('''
## Iteration 1 / 3
### Code
```python
print("report_labels is not a submission")
# stateful - run 2/2
```
### Output
```
**Score** (sample): labels=212/212 F1=1.00
```
### Verdict
FINAL: {"verdict": "COMPLIANT", "violations": []}
**Score** (sample): F1=0.00 union_acc=n/a labels=0/212 parse_ok=1
''')
        self.assertEqual(len(report.runs), 1)
        run = report.runs[0]
        self.assertEqual(run.labels, (0, 212))
        self.assertEqual(run.attempts, 1)
        self.assertEqual(run.errors, 0)
        self.assertIn("No element labels submitted", render_text(report))

    def test_errors_truncation_and_retries_are_recorded_not_inferred(self):
        report = self.parse('''
## Iteration 1 / 3
### Reasoning
I intend to compute everything.
### Code
```python
raise ValueError("broken")
```
### Output
```
Traceback (most recent call last):
ValueError: broken
... [truncated 12 characters]
```
> NOTE: Forcing a best-effort verdict (attempt 1/3).
### Code
```python
print(1)
```
### Output
```
1
```
''')
        run = report.runs[0]
        self.assertEqual(run.attempts, 2)
        self.assertEqual(run.errors, 1)
        self.assertEqual(run.truncations, 1)
        self.assertFalse(run.verdict_recorded)
        self.assertIsNone(run.labels)
        self.assertIn("ValueError: broken", render_text(report))

    def test_custom_run_is_unscored_not_failed(self):
        report = self.parse('''
## Iteration 1 / 3
### Verdict
FINAL: {"verdict": "UNKNOWN", "violations": [], "reason": "Missing data"}
- iterations: 1
- tokens: 12 in / 8 out
''')
        run = report.runs[0]
        self.assertEqual(run.verdict, "UNKNOWN")
        self.assertEqual(run.tokens, (12, 8))
        self.assertEqual(run.warnings, [])
        self.assertIn("label counts unavailable in 1", render_text(report))

    def test_interrupted_sweep_and_legacy_scores(self):
        text = HEADER.replace("stateful x 1", "stateful, stateless x 3") + '''
## Iteration 1 / 3
### Code
```python
print(1)
```
## ERROR
```
RuntimeError: provider unavailable
```
'''
        report = parse_log(text, Path("interrupted.md"))
        self.assertEqual(report.expected_runs, 6)
        self.assertIn("fewer runs logged than requested", render_text(report))
        self.assertIn("Code was logged without corresponding output", render_text(report))
        self.assertIn("provider unavailable", render_text(report))

    def test_kernel_restart_is_reported_as_lost_session_state(self):
        report = self.parse('''
## Iteration 1 / 3
### Code
```python
while True:
    pass
```
### Output
```
The execution kernel was restarted because this block exceeded its time budget.
```
### Execution status
```json
{"error": true, "error_text": "ExecutionTimeout: the code block was still running after 600 seconds and the session was terminated.", "truncated": false, "output_dropped_chars": 0, "labels_valid": false, "kernel_restarted": true, "restart_reason": "timeout"}
```
''')
        run = report.runs[0]
        self.assertEqual(run.restarts, ["timeout"])
        self.assertEqual(run.errors, 1)
        self.assertIn("ExecutionTimeout", step_summary(run.steps[-1]))
        self.assertIn("session state lost", step_summary(run.steps[-1]))
        self.assertTrue(any("kernel restart" in warning for warning in run.warnings))
        self.assertIn("kernel restart", render_text(report))

    def test_in_process_run_never_claims_a_restart(self):
        report = self.parse('''
## Iteration 1 / 3
### Code
```python
raise ValueError("boom")
```
### Output
```
ValueError: boom
```
### Execution status
```json
{"error": true, "error_text": "ValueError: boom", "truncated": false, "labels_valid": false}
```
''')
        run = report.runs[0]
        self.assertEqual(run.restarts, [])
        self.assertEqual(run.errors, 1)
        self.assertFalse(any("kernel restart" in warning for warning in run.warnings))

    def test_recent_pilot_logs(self):
        logs = Path(__file__).resolve().parents[1] / "logs"
        condo = logs / "20260907-191344_doors_windows_storey__condo_stateful.md"
        slab = logs / "20260907-190720_slab_thickness__mall_stateful.md"
        if not condo.exists() or not slab.exists():
            self.skipTest("Local pilot logs are not distributed with the repository")
        report = parse_log(condo.read_text(encoding="utf-8"), condo)
        self.assertEqual([run.labels for run in report.runs], [(0, 212), (0, 212), (212, 212), (212, 212)])
        self.assertEqual([run.errors for run in report.runs], [0, 2, 0, 3])
        self.assertEqual([run.iterations for run in report.runs], [2, 14, 5, 14])
        self.assertIn("Conditional mean union accuracy: 1.000 over 2/4", render_text(report))
        report = parse_log(slab.read_text(encoding="utf-8"), slab)
        self.assertEqual([run.labels for run in report.runs], [(112, 112), (0, 112), (112, 112)])
        self.assertIn("reference is known to be invalid", render_text(report))
        self.assertIn("0.661 over 2/3", render_text(report))

    def test_unsupported_input_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "No GUI run sections"):
            parse_log("not a GUI log", Path("unknown.md"))

    def test_html_escapes_agent_content_and_links_to_exact_source_lines(self):
        report = self.parse('''
## Iteration 1 / 3
### Reasoning
<script>alert("not trusted")</script>
### Code
```python
print("<img src=https://example.com>")
```
### Output
```
<img src=https://example.com>
```
''')
        page = render_html(report)
        self.assertIn('&lt;script&gt;alert(&quot;not trusted&quot;)&lt;/script&gt;', page)
        self.assertNotIn('<script>alert', page)
        self.assertNotIn('<img src=', page)
        self.assertIn('Agent explanation excerpt (unverified)', page)
        step_line = report.runs[0].steps[0].line
        self.assertIn(f'href="#L{step_line}"', page)
        self.assertIn(f'id="L{step_line}"', page)

    def test_generation_preserves_source_and_can_be_repeated(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "sample.md"
            source.write_text(HEADER, encoding="utf-8")
            original = source.read_bytes()
            report, destination = generate_report(source)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(destination.name, "sample.report.html")
            page = destination.read_bytes()
            generate_report(source)
            self.assertEqual(destination.read_bytes(), page)
            self.assertEqual(report.expected_runs, 1)

    def test_summary_can_omit_timeline_without_losing_results(self):
        report = self.parse('''
## Iteration 1 / 3
### Reasoning
An unverified explanation.
### Verdict
FINAL: {"verdict": "COMPLIANT", "violations": []}
**Score** (sample): labels=0/10 F1=0.00
''')
        summary = render_text(report, include_timeline=False)
        self.assertNotIn("An unverified explanation", summary)
        self.assertIn("No element labels submitted", summary)
        self.assertIn("F1: 0.00", summary)
        self.assertIn("An unverified explanation", render_html(report))

    def test_completion_record_is_separate_from_verdict_or_reference_score(self):
        report = self.parse('''
## Iteration 1 / 3
### Completion
```json
{"status":"incomplete","issues":["No report_labels submission"],"expected_anchors":112,"labels_submitted":0,"finalization_attempts":3}
```
### Verdict
(no verdict reached)

**Completion reason:** No report_labels submission
- iterations: 1
**Score** (sample): labels=0/112 F1=1.00 parse_ok=0
''')
        run = report.runs[0]
        self.assertFalse(run.verdict_recorded)
        self.assertEqual(run.verdict, "(no verdict reached)")
        self.assertEqual(run.completion["status"], "incomplete")
        self.assertIn("1 incomplete", render_text(report))
        self.assertIn("IFC scope anchors: 112", render_text(report))
        self.assertIn("No report_labels submission", render_html(report))
        self.assertNotIn("Final verdict recorded", render_html(report))

    def test_version_two_warning_does_not_call_repaired_reference_invalid(self):
        header = HEADER.replace("sample", "slab_thickness__mall").replace("- **Model:**", "- **Reference:** 2\n- **Model:**")
        report = parse_log(header, Path("v2.md"))
        self.assertIn("100 PASS / 12 ALERT / zero FAIL", render_text(report))
        self.assertNotIn("known to be invalid", render_text(report))
        legacy = parse_log(HEADER.replace("sample", "slab_thickness__mall_deprecated_v1"), Path("v1.md"))
        self.assertIn("known to be invalid", render_text(legacy))

    def test_cli_handles_unicode_with_ascii_console(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "unicode.md"
            source.write_text(HEADER + '\n## Iteration 1 / 3\n### Reasoning\nA -> B \u2192 C\n', encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parents[1] / "factual_report.py"), str(source)],
                env={**os.environ, "PYTHONIOENCODING": "ascii"},
                capture_output=True, text=True, encoding="ascii", check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(source.with_suffix(".report.html").exists())


if __name__ == "__main__":
    unittest.main()