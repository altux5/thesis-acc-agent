"""CLI entry point for the ACC CodeAct agent.

Examples (run from inside acc_agent/, or as `python acc_agent/run.py`):

    python run.py                          # stateful, default door rule + planter IFC
    python run.py --mode stateless         # the baseline
    python run.py --ifc path/to/model.ifc  # a different model
    python run.py --model openai/gpt-4o    # a different model id
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
from pathlib import Path

from code_identity import capture_module
capture_module()

import config
import llm
import tracing
from agent import AgentResult, CodeActAgent, save_transcript
from executor import make_executor
from experiment_recorder import SweepRecorder
from ground_truth import resolve_model_path
# from skill_library import SkillLibrary

PROJECT_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = PROJECT_DIR.parent

# Load the .env sitting next to this script, regardless of the current working
# directory (so `python acc_agent/run.py` works from the repo root too).
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_DIR / ".env")
except ImportError:
    pass

DEFAULT_IFC = resolve_model_path(
    "bca_tests-main/bca_tests-main/BCATestCases/"
    "Planter boxes/Test models/20240313_URA_Planterbox.ifc"
)

DEFAULT_RULE = (
    "Every door (IfcDoor) in the model must have a clear width of at least 900 mm. "
    "For this first check, use the door's OverallWidth attribute as the width. "
    "Report every door whose width is below 900 mm."
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the ACC CodeAct agent on one compliance rule."
    )
    parser.add_argument(
        "--ifc", type=Path, default=DEFAULT_IFC, help="Path to the IFC model."
    )
    parser.add_argument(
        "--rule", type=str, default=DEFAULT_RULE, help="Regulatory rule text."
    )
    parser.add_argument(
        "--mode",
        choices=("stateful", "stateless"),
        default="stateful",
        help="stateful = persistent REPL (contribution); stateless = baseline.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=(
            "Model id. Defaults to the configured provider's default "
            "(MiniMax-M3 for minimax, minimax/minimax-m3 for openrouter). "
            "Override here or with the MODEL env var."
        ),
    )
    parser.add_argument(
        "--max-iterations", type=int, default=config.MAX_ITERATIONS
    )
    parser.add_argument(
        "--harness",
        type=int,
        choices=(1, 2),
        default=1,
        help="1 = basic; 2 = plan before coding. Planning and finalization share the model-call budget.",
    )
    args = parser.parse_args()

    if not args.ifc.exists():
        raise SystemExit(f"IFC file not found: {args.ifc}")

    llm_client = llm.load_llm(args.model)
    # skills_enabled = os.environ.get("SKILLS", "1").lower() not in ("0", "false", "no")
    # skill_library = SkillLibrary(enabled=skills_enabled)
    executor = make_executor(
        stateful=(args.mode == "stateful"),
        output_char_limit=config.OUTPUT_CHAR_LIMIT,
        # skill_library=skill_library,
    )
    # OpenRouter `reasoning` is on unless REASONING=0 is set in the environment.
    reasoning_enabled = os.environ.get("REASONING", "1").lower() not in ("0", "false", "no")
    # General environment primer is on unless ENV_PRIMER=0 (baseline = unaided).
    env_primer = os.environ.get("ENV_PRIMER", "1").lower() not in ("0", "false", "no")
    agent = CodeActAgent(
        llm_client,
        executor,
        max_iterations=args.max_iterations,
        reasoning_enabled=reasoning_enabled,
        env_primer=env_primer,
        harness=args.harness,
    )

    identity = llm.model_identity(llm_client)
    print(f"Provider: {identity['provider']}")
    print(f"Model: {identity['model']}")
    print(f"Mode:  {args.mode}")
    print(f"Harness: level {args.harness}")
    print(f"IFC:   {args.ifc}")
    print(f"Rule:  {args.rule}")

    recorder = SweepRecorder(
        entrypoint="cli", requested=1, case=None, rule=args.rule, ifc_path=args.ifc,
        client=llm_client, max_iterations=args.max_iterations, reasoning=reasoning_enabled,
        env_primer=env_primer, library=None, output_limit=config.OUTPUT_CHAR_LIMIT,
    )
    ticket = recorder.start_run(args.mode, 1, args.harness)
    try:
        result = agent.check(
            args.rule, str(args.ifc), on_event=ticket.observe if ticket else None,
            trace_attrs={
                "session_id": f"cli-{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}",
                "tags": ["cli"],
            },
        )
    except BaseException as exc:
        partial = getattr(agent, "partial_result", None)
        partial = partial if isinstance(partial, AgentResult) else None
        recorder.finish_run(ticket, partial, error=f"{type(exc).__name__}: {exc}")
        recorder.save_evidence(ticket, partial, PROJECT_DIR / "runs", force=True)
        recorder.finish(str(exc))
        raise
    finally:
        executor.close()
    recorder.finish_run(ticket, result)
    recorder.finish()

    print("\n========================= RESULT =========================")
    print(result.verdict)
    print(f"Completion: {result.completion_status}")
    for issue in result.completion_issues:
        print(f"  {issue}")
    print(
        f"\niterations: {result.iterations} | "
        f"tokens: {result.prompt_tokens} in / {result.completion_tokens} out"
    )
    if result.labels:
        counts: dict[str, int] = {}
        for label in result.labels.values():
            counts[label] = counts.get(label, 0) + 1
        print(f"labelled {len(result.labels)} elements: {dict(sorted(counts.items()))}")
    else:
        print(f"labelled 0 elements ({result.label_reports} report_labels submissions)")
    url = tracing.trace_url(result.trace_id)
    if url:
        print(f"langfuse trace: {url}")

    transcript_path = save_transcript(result, PROJECT_DIR / "runs", args.mode)
    recorder.attach_log(ticket, transcript_path)
    print(f"transcript saved to: {transcript_path}")
    tracing.flush()


if __name__ == "__main__":
    main()
