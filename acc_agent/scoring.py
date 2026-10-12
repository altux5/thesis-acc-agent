"""Parse the agent's FINAL verdict and score it against ground truth.

The agent finishes with a line beginning ``FINAL:`` followed by a JSON object of
the form ``{"verdict": "...", "violations": ["<GlobalId>", ...]}``, where the
verdict is ``COMPLIANT``, ``NON_COMPLIANT`` or — as a last resort, and then with
a ``"reason"`` — ``UNKNOWN``. This module turns that free text into a
:class:`ParsedVerdict`, compares the reported set of violating GlobalIds against
a known-correct set, and aggregates the per-run scores across repetitions so
meaningful averages can be reported.

The core metric is *set agreement* on the violating-GlobalId set — precision,
recall and F1 — rather than a single COMPLIANT/NON-COMPLIANT bit. That is the
honest measure here: it reveals, for example, a model that flags every door
whose stored width is 899.999 mm (floating-point noise around a nominal 900 mm)
as a false positive, instead of hiding it behind a coarse binary verdict.

Set agreement still has a blind spot: an element the agent never looked at is
indistinguishable from one it correctly judged compliant. So a case may also
carry a *per-element labelling* over its anchor elements, and runs that produce
one are additionally scored with **union accuracy** — the share of the union of
both labelled sets on which the two agree. An element only one side labels
enlarges the denominator without being able to contribute a match, so silently
skipping elements is penalised rather than rewarded.
For an explicit annotated-subset reference, known unannotated IFC IDs are
excluded before agreement is computed. They remain required for completion;
unknown extra IDs and missing annotated elements are still penalised.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field

from code_identity import capture_module
capture_module()

FINAL_MARKER = "FINAL:"

# 22-character IFC GlobalId (base64 subset). Used only for the best-effort
# fallback when the model ignores the JSON contract.
_GUID_RE = re.compile(r"\b[0-9A-Za-z_$]{22}\b")

COMPLIANT = "COMPLIANT"
NON_COMPLIANT = "NON_COMPLIANT"
UNKNOWN = "UNKNOWN"
# Returned when a piece of text carries no recognisable verdict at all, which is
# different from the agent *deliberately* answering UNKNOWN.
UNRECOGNISED = ""

_UNKNOWN_WORDS = (
    "UNKNOWN",
    "INDETERMINATE",
    "UNDETERMINED",
    "INCONCLUSIVE",
    "CANNOT_DETERMINE",
    "UNABLE_TO_DETERMINE",
    "INSUFFICIENT",
)

# --- per-element labels ---------------------------------------------------- #
# The verdict above is one bit for a whole model. It cannot express the three
# outcomes that actually dominate real compliance data: the element is exempt,
# the element is modelled too poorly to judge, or the element needs a human.
# Collapsing those into "not a violation" is what lets a checker score well by
# staying silent. These five mutually exclusive labels are the element-level
# outcome space; every anchor element of a rule gets exactly one.
PASS = "PASS"
FAIL = "FAIL"
ALERT = "ALERT"  # modelling precondition broken -> fix the model, not the checker
MANUAL_CHECK = "MANUAL_CHECK"  # a real answer: no deterministic check is possible
NA = "NA"  # out of scope / exempt from the rule

LABELS: tuple[str, ...] = (PASS, FAIL, ALERT, MANUAL_CHECK, NA)
# Agent-only placeholder for an unresolved element; never a reference outcome, so it
# never matches in union accuracy and blocks a decided FinalReport (completion.py).
PENDING = "PENDING"

_LABEL_ALIASES = {
    "PASS": PASS,
    "PASSED": PASS,
    "OK": PASS,
    "COMPLIANT": PASS,
    "COMPLIES": PASS,
    "FAIL": FAIL,
    "FAILED": FAIL,
    "VIOLATION": FAIL,
    "NON_COMPLIANT": FAIL,
    "NONCOMPLIANT": FAIL,
    "ALERT": ALERT,
    "WARNING": ALERT,
    "INCOMPLETE": ALERT,
    "MISSING_DATA": ALERT,
    "MANUAL_CHECK": MANUAL_CHECK,
    "MANUAL": MANUAL_CHECK,
    "MANUALCHECK": MANUAL_CHECK,
    "REVIEW": MANUAL_CHECK,
    "NA": NA,
    "N_A": NA,
    "NOT_APPLICABLE": NA,
    "EXEMPT": NA,
    "OUT_OF_SCOPE": NA,
    "PENDING": PENDING,
}


def normalize_label(value: object) -> str | None:
    """Map any spelling of an element label onto one of :data:`LABELS` or :data:`PENDING`.

    Returns ``None`` when the text is not a recognisable label, so a malformed
    entry is dropped rather than silently scored as a PASS.
    """
    text = str(value or "").strip().upper()
    for ch in "-/ ":
        text = text.replace(ch, "_")
    if not text:
        return None
    return _LABEL_ALIASES.get(text)


def labels_to_violations(labels: dict[str, str]) -> set[str]:
    """The GlobalIds a labelling marks as FAIL."""
    return {guid for guid, label in labels.items() if label == FAIL}


def union_accuracy(predicted: dict[str, str], truth: dict[str, str]) -> float:
    """Agreement over the union of the two labelled element sets.

    ``|{e in both : same label}| / |union of both|``. Elements only one side
    labelled sit in the denominator and can never match, so a run is penalised
    for skipping an element just as much as for mislabelling it. Returns 1.0
    when neither side labelled anything (nothing was claimed, nothing missed).
    """
    universe = set(predicted) | set(truth)
    if not universe:
        return 1.0
    agreed = sum(1 for guid in set(predicted) & set(truth) if predicted[guid] == truth[guid])
    return agreed / len(universe)


def label_confusion(predicted: dict[str, str], truth: dict[str, str]) -> dict[str, int]:
    """Counts of ``"<truth>-><predicted>"`` pairs, plus the two missing-side tallies.

    This is the diagnostic that says *how* a run went wrong: FAIL->PASS is a
    missed violation, PASS->FAIL an over-flag, and ``ALERT->(missing)`` an
    element the run never accounted for at all.
    """
    counts: dict[str, int] = {}
    for guid, actual in truth.items():
        key = f"{actual}->{predicted.get(guid, '(missing)')}"
        counts[key] = counts.get(key, 0) + 1
    for guid, claimed in predicted.items():
        if guid not in truth:
            key = f"(not-anchor)->{claimed}"
            counts[key] = counts.get(key, 0) + 1
    return counts


def normalize_verdict(value: object) -> str:
    """Map any spelling of the verdict onto one of the three verdicts.

    Returns :data:`UNRECOGNISED` (an empty string) when the text carries no
    verdict at all, so callers can tell "the agent said UNKNOWN" apart from
    "there was nothing to read".
    """
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if not text:
        return UNRECOGNISED
    if "NON_COMPLIANT" in text or "NONCOMPLIANT" in text or text in {"FAIL", "FAILED"}:
        return NON_COMPLIANT
    if "COMPLIANT" in text or text in {"PASS", "PASSED", "OK"}:
        return COMPLIANT
    if any(word in text for word in _UNKNOWN_WORDS):
        return UNKNOWN
    return UNRECOGNISED


@dataclass
class ParsedVerdict:
    """The machine-readable result extracted from a FINAL message."""

    verdict: str
    violations: set[str]
    parse_ok: bool
    raw: str = ""
    # Why the agent abstained. Required by the prompt whenever it answers
    # UNKNOWN, empty for a decided verdict.
    reason: str = ""
    # Per-element labelling over the rule's anchor elements, when the run
    # produced one (see :data:`LABELS`). Empty when it only reported a verdict,
    # in which case union accuracy is not computed for the run.
    labels: dict[str, str] = field(default_factory=dict)


def _first_json_object(text: str) -> dict | None:
    """Return the first balanced ``{...}`` in *text* that parses as JSON."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break  # not valid JSON; try the next '{'
                    return obj if isinstance(obj, dict) else None
        start = text.find("{", start + 1)
    return None


def parse_verdict(final_text: str) -> ParsedVerdict:
    """Extract the verdict + violating GlobalIds from a FINAL message.

    Prefers the structured JSON contract; falls back to scraping a verdict
    keyword and any GlobalId-shaped tokens so a malformed final message still
    yields a usable (if lower-confidence) result.

    A deliberate ``"verdict": "UNKNOWN"`` is preserved as such (with its
    ``reason``): the agent is allowed to abstain when the model does not support
    a judgement, and that is a valid answer rather than a parse failure.
    """
    raw = final_text or ""
    after = raw
    if FINAL_MARKER in raw:
        after = raw[raw.index(FINAL_MARKER) + len(FINAL_MARKER) :]

    obj = _first_json_object(after)
    if obj is not None and ("verdict" in obj or "violations" in obj):
        violations = {
            str(v).strip() for v in (obj.get("violations") or []) if str(v).strip()
        }
        verdict = normalize_verdict(obj.get("verdict"))
        if verdict == UNRECOGNISED:
            # No usable verdict field; infer the bit from the reported set.
            verdict = NON_COMPLIANT if violations else COMPLIANT
        reason = str(obj.get("reason") or "").strip()
        labels = parse_labels(obj.get("labels"))
        return ParsedVerdict(
            verdict, violations, parse_ok=True, raw=raw, reason=reason, labels=labels
        )

    # Fallback: no usable JSON. Scrape a keyword + GlobalId-shaped tokens.
    verdict = normalize_verdict(after)
    violations = set(_GUID_RE.findall(after))
    if verdict == UNRECOGNISED:
        verdict = NON_COMPLIANT if violations else UNKNOWN
    return ParsedVerdict(verdict, violations, parse_ok=False, raw=raw)


def parse_labels(value: object) -> dict[str, str]:
    """Coerce a reported ``{guid: label}`` mapping onto the known label space.

    Unrecognised labels are dropped rather than guessed at: a run that writes
    nonsense for an element has not judged it, and should be scored as if it
    said nothing.
    """
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for guid, label in value.items():
        guid = str(guid).strip()
        normalised = normalize_label(label)
        if guid and normalised is not None:
            out[guid] = normalised
    return out


@dataclass
class Scores:
    """Agreement of one run's reported violations against ground truth."""

    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    exact_set_match: bool
    verdict_match: bool
    predicted_verdict: str
    gt_verdict: str
    parse_ok: bool
    # The agent declined to decide. Tracked separately so an abstention is never
    # mistaken for a confident (and here, vacuously precise) answer.
    abstained: bool = False
    # --- element-level agreement (only when both sides carry labels) -------- #
    # None when the case has no labelling, or the run produced none, so an
    # unmeasured run is never averaged in as a zero.
    union_accuracy: float | None = None
    # How much of the case's anchor set the run actually accounted for. This is
    # the number the binary metric cannot see: a run can post a perfect F1 on
    # violations while never looking at 80 % of the elements.
    label_coverage: float | None = None
    labels_reported: int = 0
    labels_expected: int = 0
    confusion: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "exact_set_match": self.exact_set_match,
            "verdict_match": self.verdict_match,
            "predicted_verdict": self.predicted_verdict,
            "gt_verdict": self.gt_verdict,
            "parse_ok": self.parse_ok,
            "abstained": self.abstained,
            "union_accuracy": self.union_accuracy,
            "label_coverage": self.label_coverage,
            "labels_reported": self.labels_reported,
            "labels_expected": self.labels_expected,
            "confusion": self.confusion,
        }


def score(
    parsed: ParsedVerdict,
    ground_truth: set[str],
    gt_labels: dict[str, str] | None = None,
    *,
    unscored_ids: set[str] | None = None,
) -> Scores:
    """Score a parsed verdict against the ground-truth set of violating GlobalIds.

    *gt_labels* is the optional per-element labelling of the case's anchor
    elements. When it is present and the run reported labels of its own, union
    accuracy and anchor coverage are computed alongside the set metrics.

    *unscored_ids* explicitly excludes known, unannotated IFC anchors from
    agreement metrics, not from the submission or its completion requirements.
    Other extra IDs remain errors. Authored reference labels cannot be excluded.
    """
    gt = set(ground_truth)
    truth_labels = gt_labels or {}
    excluded = set(unscored_ids or ())
    if excluded & (gt | set(truth_labels)):
        raise ValueError("Unscored IDs overlap authored reference labels or violations.")
    predicted = set(parsed.violations) - excluded

    tp = len(predicted & gt)
    fp = len(predicted - gt)
    fn = len(gt - predicted)

    # Vacuously perfect when there is nothing to find and nothing was reported.
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    gt_verdict = NON_COMPLIANT if gt else COMPLIANT

    run_labels = {guid: label for guid, label in parsed.labels.items() if guid not in excluded}
    union_acc: float | None = None
    coverage: float | None = None
    confusion: dict[str, int] = {}
    if truth_labels and parsed.labels:
        union_acc = union_accuracy(run_labels, truth_labels)
        coverage = len(set(run_labels) & set(truth_labels)) / len(truth_labels)
        confusion = label_confusion(run_labels, truth_labels)

    return Scores(
        tp=tp,
        fp=fp,
        fn=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        exact_set_match=(predicted == gt),
        verdict_match=(parsed.verdict == gt_verdict),
        predicted_verdict=parsed.verdict,
        gt_verdict=gt_verdict,
        parse_ok=parsed.parse_ok,
        abstained=(parsed.verdict == UNKNOWN and parsed.parse_ok),
        union_accuracy=union_acc,
        label_coverage=coverage,
        labels_reported=len(parsed.labels),
        labels_expected=len(truth_labels),
        confusion=confusion,
    )


@dataclass
class Aggregate:
    """Mean/std of each metric across *n* repetitions of one configuration."""

    n: int
    metrics: dict[str, dict[str, float]] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"n": self.n, "metrics": self.metrics}


_AVERAGED_FIELDS = (
    "precision",
    "recall",
    "f1",
    "exact_set_match",
    "verdict_match",
    "parse_ok",
    "abstained",
)

# Averaged only over the runs that actually produced the measurement. A run with
# no labelling has not scored 0 on union accuracy, it has not been measured, and
# folding it in as a zero would understate every configuration that ever skips it.
_OPTIONAL_FIELDS = (
    "union_accuracy",
    "label_coverage",
)


def _mean_std(values: list[float]) -> dict[str, float]:
    mean = statistics.fmean(values) if values else 0.0
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return {"mean": mean, "std": std}


def aggregate(scores: list[Scores]) -> Aggregate:
    """Aggregate per-run scores into mean/std for each metric."""
    metrics: dict[str, dict[str, float]] = {}
    for name in _AVERAGED_FIELDS:
        values = [float(getattr(s, name)) for s in scores]
        metrics[name] = _mean_std(values)
    for name in _OPTIONAL_FIELDS:
        values = [float(getattr(s, name)) for s in scores if getattr(s, name) is not None]
        if values:
            metrics[name] = {**_mean_std(values), "n": float(len(values))}
    return Aggregate(n=len(scores), metrics=metrics)
