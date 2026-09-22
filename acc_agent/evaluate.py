"""Repeated evaluation runner: score the agent's agreement with ground truth.

Runs the CodeAct agent ``--repeats`` times per execution mode against a
ground-truth case, scores each run (precision / recall / F1 / exact-set-match /
verdict-match, plus union accuracy over the case's element labelling when it has
one), and reports the mean ± std so comparisons rest on meaningful averages
rather than a single sample.

Two axes are varied independently: ``--modes`` (stateful vs stateless execution)
and ``--harness`` (basic or planning). Reference labels are used only after execution.

Examples (from inside acc_agent/):

    python evaluate.py                              # 3x stateful + 3x stateless, door case
    python evaluate.py --repeats 5                  # 5 runs per mode
    python evaluate.py --modes stateful             # one mode only
    python evaluate.py --harness 2                  # add the planning step
    python evaluate.py --model MiniMax-M2.5         # a different model
    python evaluate.py --case door_width_planterbox # an explicit ground-truth case
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import io
import json
import os
from pathlib import Path

from code_identity import capture_module
capture_module()

import config
import ground_truth as gt_mod
import llm
import scoring
import tracing
from agent import AgentResult, CodeActAgent, save_transcript
from completion import COMPLETION_CHECKS_VERSION
from executor import make_executor
from experiment_recorder import SweepRecorder
# from skill_library import SkillLibrary

PROJECT_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_DIR / ".env")
except ImportError:
    pass


def _run_once(
    llm_client: llm.LLMClient,
    rule: str,
    ifc_path: Path,
    mode: str,
    max_iterations: int,
    reasoning_enabled: bool,
    gt_set: set[str],
    trace_attrs: dict | None = None,
    env_primer: bool = True,
    skill_library: object | None = None,
    harness: int = 1,
    gt_labels: dict[str, str] | None = None,
    recorder: SweepRecorder | None = None,
    unscored_ids: set[str] | None = None,
) -> tuple[scoring.Scores, dict]:
    """Run and score one pass; the archived skill_library argument is ignored."""
    executor = make_executor(
        stateful=(mode == "stateful"),
        output_char_limit=config.OUTPUT_CHAR_LIMIT,
        # skill_library=skill_library,
    )
    agent = CodeActAgent(
        llm_client,
        executor,
        max_iterations=max_iterations,
        reasoning_enabled=reasoning_enabled,
        env_primer=env_primer,
        harness=harness,
    )
    sink = io.StringIO()
    repeat = (trace_attrs or {}).get("metadata", {}).get("repeat", 1)
    ticket = recorder.start_run(mode, repeat, harness) if recorder else None
    try:
        with contextlib.redirect_stdout(sink):
            result = agent.check(rule, str(ifc_path), trace_attrs=trace_attrs,
                                 on_event=ticket.observe if ticket else None)
    except BaseException as exc:
        executor.close()
        partial = getattr(agent, "partial_result", None)
        partial = partial if isinstance(partial, AgentResult) else None
        if recorder:
            recorder.finish_run(ticket, partial, error=f"{type(exc).__name__}: {exc}")
            recorder.save_evidence(ticket, partial, PROJECT_DIR / "runs", force=True)
            recorder.finish(str(exc))
        elif partial is not None:
            try:
                save_transcript(partial, PROJECT_DIR / "runs", f"{mode}_failed")
            except OSError as save_error:
                print(f"Failed to save partial transcript: {save_error}")
        raise

    executor.close()
    parsed = scoring.ParsedVerdict(
        verdict=result.verdict_label,
        violations=set(result.violations),
        parse_ok=result.parse_ok,
        raw=result.verdict,
        reason=result.reason,
        labels=result.labels,
    )
    scores = scoring.score(parsed, gt_set, gt_labels, unscored_ids=unscored_ids)
    if recorder:
        recorder.finish_run(ticket, result, scores)
        recorder.save_evidence(ticket, result, PROJECT_DIR / "runs")
    # Send the metrics back to the trace this run produced, so Langfuse can filter
    # and chart quality (not just tokens/latency) per mode, model and case.
    tracing.score_run(
        result.trace_id,
        scores,
        extra={
            "iterations": result.iterations,
            "executions": result.executions,
            "harness": result.harness,
            "evaluations": result.evaluations,
            "total_tokens": result.prompt_tokens + result.completion_tokens,
        },
    )
    meta = {
        "iterations": result.iterations,
        "executions": result.executions,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "usage_complete": result.usage_complete,
        "cache_read_input_tokens": result.cache_read_input_tokens,
        "cache_creation_input_tokens": result.cache_creation_input_tokens,
        "predicted_violations": sorted(result.violations),
        "verdict_label": result.verdict_label,
        "reason": result.reason,
        "parse_ok": result.parse_ok,
        "completion_status": result.completion_status,
        "completion_issues": result.completion_issues,
        "expected_anchors": result.expected_anchors,
        "scope_note": result.scope_note,
        "finalization_attempts": result.finalization_attempts,
        "harness": result.harness,
        "labels_reported": len(result.labels),
        "label_reports": result.label_reports,
        "evaluations": result.evaluations,
        "early_stop": result.early_stop,
        "feedback_leakage": result.feedback_leakage,
        "trace_id": result.trace_id,
        "trace_url": tracing.trace_url(result.trace_id),
        "experiment_run_id": ticket.id if ticket else None,
    }
    return scores, meta


def _fmt(ms: dict[str, float]) -> str:
    return f"{ms['mean']:.3f} ± {ms['std']:.3f}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repeatedly run the agent and score agreement with ground truth."
    )
    parser.add_argument(
        "--case",
        type=str,
        default="door_width_planterbox",
        help="Ground-truth case id (under ground_truth/) or a path to a JSON case.",
    )
    parser.add_argument("--repeats", type=int, default=3, help="Runs per mode.")
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=("stateful", "stateless"),
        default=["stateful", "stateless"],
        help="Which execution mode(s) to evaluate.",
    )
    parser.add_argument("--model", type=str, default=None, help="Model id override.")
    parser.add_argument(
        "--max-iterations", type=int, default=max(config.MAX_ITERATIONS, 12)
    )
    parser.add_argument(
        "--ifc", type=Path, default=None, help="Override the IFC path from the case."
    )
    parser.add_argument(
        "--rule", type=str, default=None, help="Override the rule text from the case."
    )
    parser.add_argument(
        "--harness",
        type=int,
        choices=(1, 2),
        default=1,
        help="Harness level: 1 basic, 2 planning. All model calls share the same budget.",
    )
    args = parser.parse_args()

    gt = gt_mod.load(args.case)
    ifc_path = args.ifc or gt.resolve_ifc()
    if not ifc_path.exists():
        raise SystemExit(f"IFC file not found: {ifc_path}")
    rule = args.rule or gt.rule
    gt_set = gt.violation_set
    gt_labels = gt.labels
    unscored_ids = gt.unscored_ids

    run_stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    session_id = f"eval-{run_stamp}-{gt.case_id}"

    llm_client = llm.load_llm(args.model)
    reasoning_enabled = os.environ.get("REASONING", "1").lower() not in (
        "0",
        "false",
        "no",
    )
    env_primer = os.environ.get("ENV_PRIMER", "1").lower() not in ("0", "false", "no")
    # skills_enabled = os.environ.get("SKILLS", "1").lower() not in ("0", "false", "no")
    # skill_library = SkillLibrary(enabled=skills_enabled)
    recorder = SweepRecorder(
        entrypoint="eval", requested=len(args.modes) * args.repeats, case=gt, rule=rule,
        ifc_path=ifc_path, client=llm_client, max_iterations=args.max_iterations,
        reasoning=reasoning_enabled, env_primer=env_primer, library=None,
        output_limit=config.OUTPUT_CHAR_LIMIT,
    )

    print(f"Case:      {gt.case_id}  ({len(gt_set)} ground-truth violations)")
    if gt_labels:
        print(f"Anchors:   {gt.anchor_count} labelled elements  {gt.label_counts}")
        if unscored_ids:
            print(f"Scoring:   annotated subset; {len(unscored_ids)} unannotated IFC elements unscored, still required for completion")
    else:
        print("Anchors:   (case carries no labelling; union accuracy unavailable)")
    identity = llm.model_identity(llm_client)
    print(f"Provider:  {identity['provider']}")
    print(f"Model:     {identity['model']}")
    print(f"Harness:   level {args.harness}")
    print(f"Modes:     {', '.join(args.modes)}  x {args.repeats} run(s) each")
    print(f"IFC:       {ifc_path}")
    if tracing.enabled():
        print(f"Langfuse:  session {session_id}")
    print("=" * 66)

    per_mode: dict[str, dict] = {}
    for mode in args.modes:
        run_scores: list[scoring.Scores] = []
        run_meta: list[dict] = []
        for i in range(1, args.repeats + 1):
            scores, meta = _run_once(
                llm_client,
                rule,
                ifc_path,
                mode,
                args.max_iterations,
                reasoning_enabled,
                gt_set,
                trace_attrs={
                    "session_id": session_id,
                    "tags": ["eval"],
                    "metadata": {"case_id": gt.case_id, "repeat": i},
                },
                env_primer=env_primer,
                # skill_library=skill_library,
                harness=args.harness,
                gt_labels=gt_labels,
                recorder=recorder,
                unscored_ids=unscored_ids,
            )
            run_scores.append(scores)
            run_meta.append(meta)
            union = (
                f" A∪={scores.union_accuracy:.2f}"
                f" cov={scores.label_coverage:.2f}"
                if scores.union_accuracy is not None
                else " A∪=n/a"
            )
            print(
                f"[{mode:<9} {i}/{args.repeats}] "
                f"P={scores.precision:.2f} R={scores.recall:.2f} F1={scores.f1:.2f}"
                f"{union} "
                f"exact={int(scores.exact_set_match)} "
                f"tp={scores.tp} fp={scores.fp} fn={scores.fn} "
                f"iters={meta['iterations']} "
                f"tok={meta['prompt_tokens']}/{meta['completion_tokens']}"
                + ("" if scores.parse_ok else "  [parse-fallback]")
                + ("  [ABSTAINED]" if scores.abstained else "")
                + ("  [early-stop]" if meta.get("early_stop") else "")
                + f"  [{meta['completion_status']}]"
            )
            if scores.abstained and meta.get("reason"):
                print(f"            reason: {meta['reason']}")
            if meta.get("trace_url"):
                print(f"            trace: {meta['trace_url']}")
        agg = scoring.aggregate(run_scores)
        # The sweep-level answer ("stateful vs stateless on average") lands on the
        # Langfuse session, next to the individual runs it summarises.
        tracing.score_sweep(session_id, mode, agg)
        per_mode[mode] = {
            "aggregate": agg.as_dict(),
            "runs": [
                {**s.as_dict(), **m} for s, m in zip(run_scores, run_meta)
            ],
        }
        print("-" * 66)
        m = agg.metrics
        print(
            f"  {mode} mean over {agg.n}: "
            f"precision {_fmt(m['precision'])} | "
            f"recall {_fmt(m['recall'])} | "
            f"f1 {_fmt(m['f1'])}"
        )
        print(
            f"    exact-set-match {_fmt(m['exact_set_match'])} | "
            f"verdict-match {_fmt(m['verdict_match'])} | "
            f"parse-ok {_fmt(m['parse_ok'])} | "
            f"abstained {_fmt(m['abstained'])}"
        )
        if "union_accuracy" in m:
            print(
                f"    union-accuracy {_fmt(m['union_accuracy'])} | "
                f"anchor-coverage {_fmt(m['label_coverage'])} "
                f"(over {int(m['union_accuracy'].get('n', 0))}/{agg.n} labelled run(s))"
            )
        else:
            print("    union-accuracy: no run submitted a labelling")
        print("=" * 66)

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    recorder.finish()
    out_dir = PROJECT_DIR / "evals"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stamp}_{gt.case_id}.json"
    out_path.write_text(
        json.dumps(
            {
                "case_id": gt.case_id,
                "complexity": gt.complexity,
                **identity,
                "repeats": args.repeats,
                "modes": args.modes,
                "harness": args.harness,
                "feedback_leakage": False,
                "max_iterations": args.max_iterations,
                "ifc_path": str(ifc_path),
                "rule": rule,
                "langfuse_session": session_id if tracing.enabled() else None,
                "ground_truth_violations": sorted(gt_set),
                "ground_truth_labels": gt_labels,
                "reference": gt.reference,
                "completion_checks": COMPLETION_CHECKS_VERSION,
                "results": per_mode,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"eval results saved to: {out_path}")
    tracing.flush()


if __name__ == "__main__":
    main()
