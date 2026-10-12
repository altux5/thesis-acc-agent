"""Submission checks against public IFC scope and the agent's own labels, never GT."""

from __future__ import annotations

import json
import re

from code_identity import capture_module
capture_module()

COMPLETION_CHECKS_VERSION = 4


def scope_classes(rule: str) -> list[str]:
    match = re.search(r"\(modelled as ([^)]+)\)", rule)
    if match is None:
        match = re.search(r"Every\s+\w+\s+\((Ifc\w+)\)", rule)
    if match is None or not re.fullmatch(r"Ifc\w+(?:\s+or\s+Ifc\w+)*", match[1]):
        return []
    return re.findall(r"Ifc\w+", match[1])


def discover_scope(rule: str, ifc_path: str) -> tuple[set[str] | None, str]:
    classes = scope_classes(rule)
    if not classes:
        return None, "No supported explicit IFC class scope in the rule; full coverage cannot be independently checked."
    try:
        import ifcopenshell

        model = ifcopenshell.open(ifc_path)
        anchors = {entity.GlobalId for name in classes for entity in model.by_type(name)}
        return anchors, "IFC population for " + ", ".join(classes) + "; no reference labels used."
    except Exception as exc:
        return None, f"Public IFC scope unavailable: {type(exc).__name__}: {exc}"


def validate_final(
    text: str,
    labels: dict[str, str],
    label_reports: int,
    last_error: bool,
    anchors: set[str] | None,
) -> tuple[dict | None, list[str]]:
    marker = re.search(r"(?m)^FINAL:\s*", text)
    if marker is None:
        return None, ["Use a FINAL: line containing a JSON object; prose is not a submission."]
    try:
        payload = json.loads(text[marker.end():].strip())
    except (ValueError, TypeError):
        return None, ["FINAL must contain one valid JSON object with no trailing prose."]
    return validate_submission(payload, labels, label_reports, last_error, anchors)


def validate_submission(
    payload: dict,
    labels: dict[str, str],
    label_reports: int,
    last_error: bool,
    anchors: set[str] | None,
    calls_remaining: int = 0,
) -> tuple[dict | None, list[str]]:
    """Validate a structured submission against execution evidence, never references."""
    if not isinstance(payload, dict) or not isinstance(payload.get("verdict"), str) or payload["verdict"] not in {"COMPLIANT", "NON_COMPLIANT", "UNKNOWN"}:
        return None, ["FINAL verdict must be COMPLIANT, NON_COMPLIANT or UNKNOWN."]
    violations = payload.get("violations")
    if not isinstance(violations, list) or any(not isinstance(guid, str) or not guid.strip() for guid in violations):
        return None, ["FINAL violations must be a list of nonempty GlobalId strings."]
    if len(violations) != len(set(violations)):
        return None, ["FINAL violations contains duplicate GlobalIds."]
    failures = {guid for guid, label in labels.items() if label == "FAIL"}
    if payload["verdict"] == "UNKNOWN":
        reason = payload.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return None, ["UNKNOWN requires a concrete reason for not completing the check."]
        if violations or failures:
            return None, ["UNKNOWN conflicts with reported failures; finish or revise the label submission."]
        if calls_remaining > 0:
            return None, [f"UNKNOWN is accepted only on the final model call; {calls_remaining} call(s) remain. "
                          "Continue the check and commit labels (PENDING for elements not yet resolved)."]
        return payload, []
    issues = []
    pending = sum(label == "PENDING" for label in labels.values())
    if pending:
        issues.append(f"{pending} element(s) are still PENDING. Resolve them to PASS, FAIL, ALERT, MANUAL_CHECK or NA "
                      "and resubmit; if calls run out, return UNKNOWN naming what is unresolved.")
    if label_reports == 0:
        issues.append("No report_labels submission is valid for the current execution state. Submit the complete mapping from a successful code block.")
    if last_error:
        issues.append("The last code attempt failed. Repair and resubmit before finalizing.")
    if anchors is not None:
        missing = anchors - set(labels)
        extra = set(labels) - anchors
        if missing or extra:
            issues.append(f"IFC scope coverage mismatch: {len(missing)} missing and {len(extra)} unexpected labels. Enumerate the full rule scope; no reference labels are used here.")
    elif not labels:
        issues.append("No element outcomes available and an empty rule scope has not been verified.")
    if set(violations) != failures:
        issues.append("FINAL violations must equal the submitted FAIL GlobalIds exactly.")
    expected_verdict = "NON_COMPLIANT" if failures else "COMPLIANT"
    if payload["verdict"] != expected_verdict:
        issues.append(f"The submitted labels require {expected_verdict}, not {payload['verdict']}.")
    if labels and set(labels.values()) <= {"ALERT", "MANUAL_CHECK", "NA"} and any(label != "NA" for label in labels.values()):
        issues.append("No applicable element was judged PASS or FAIL; return UNKNOWN with a reason instead of COMPLIANT.")
    return (None, issues) if issues else (payload, [])