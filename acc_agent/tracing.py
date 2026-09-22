"""Optional Langfuse tracing for the CodeAct agent.

One agent run (:meth:`agent.CodeActAgent.check`) becomes exactly one Langfuse
*trace*, shaped so it can be read top-down without opening every node::

    check · staircase_width_v8 · stateful       <- root span = the trace
    ├── iteration 1                            <- span
    │   ├── llm.generate                       <- generation (chat in, reply + usage out)
    │   └── python-exec                        <- tool (code in, captured stdout out)
    ├── iteration 2
    │   ├── llm.generate
    │   └── python-exec
    └── ...

The trace carries a descriptive name (case + mode), the rule as input, a
structured verdict as output, flat metadata (case/mode/provider/model/tokens),
tags for filtering, and a session id grouping every run of one sweep.

Quality metrics (precision / recall / F1 / …) are attached afterwards as Langfuse
*scores* via :func:`score_run`, which is what makes the stateful-vs-stateless
comparison filterable and chartable in the Langfuse UI instead of only living in
``evals/*.json``.

Everything here degrades to a no-op when the ``langfuse`` package is not
installed or the ``LANGFUSE_*`` keys are not set, so tracing is never a hard
dependency and runs behave identically without it.
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Callable, Iterator
from typing import Any

_client: Any = None
_resolved = False


def get_client() -> Any:
    """Return a cached Langfuse client, or ``None`` when unavailable/unconfigured."""
    global _client, _resolved
    if _resolved:
        return _client
    _resolved = True
    if not (
        os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")
    ):
        _client = None
        return _client
    try:
        from langfuse import get_client as _get_client

        _client = _get_client()
    except Exception:  # noqa: BLE001 - tracing must never break the app
        _client = None
    return _client


def enabled() -> bool:
    """True when a configured Langfuse client is available."""
    return get_client() is not None


def langchain_callbacks() -> list:
    """Use Langfuse's standard model/tool tracing without making it a run dependency."""
    if get_client() is None:
        return []
    try:
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler()]
    except Exception:
        return []


class _Noop:
    """Stand-in observation used when tracing is disabled."""

    def update(self, *args: Any, **kwargs: Any) -> None: ...

    def set_trace_io(self, *args: Any, **kwargs: Any) -> None: ...

    def score_trace(self, *args: Any, **kwargs: Any) -> None: ...


def _safe(obj: Any, method: str, **kwargs: Any) -> None:
    """Call ``obj.method(**kwargs)`` if it exists, swallowing any error."""
    try:
        fn = getattr(obj, method, None)
        if callable(fn):
            fn(**kwargs)
    except Exception:  # noqa: BLE001 - tracing must never break the app
        pass


@contextlib.contextmanager
def _optional_context(factory: Callable[[], Any]) -> Iterator[Any]:
    """Ignore telemetry lifecycle failures, never suppress the wrapped operation."""
    try:
        manager = factory()
        observation = manager.__enter__()
    except Exception:
        yield _Noop()
        return
    try:
        yield observation
    except BaseException:
        failure = sys.exc_info()
        try:
            manager.__exit__(*failure)
        except Exception:
            pass
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# The run-level trace
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def check_run(
    name: str = "compliance-check",
    *,
    input: Any = None,
    metadata: dict | None = None,
    tags: list[str] | None = None,
    session_id: str | None = None,
) -> Iterator[Any]:
    """Root observation for one agent run; becomes the Langfuse trace.

    Trace-level attributes (session, tags, metadata) are set with the v4
    ``propagate_attributes`` context manager so every nested observation inherits
    them; the run's input/output go on the trace via ``set_trace_io``.
    """
    client = get_client()
    if client is None:
        yield _Noop()
        return

    try:
        from langfuse import propagate_attributes
    except Exception:  # noqa: BLE001
        propagate_attributes = None

    prop_kwargs: dict[str, Any] = {"trace_name": name}
    if metadata:
        prop_kwargs["metadata"] = metadata
    if tags:
        prop_kwargs["tags"] = tags
    if session_id:
        prop_kwargs["session_id"] = session_id

    with contextlib.ExitStack() as stack:
        if propagate_attributes is not None:
            stack.enter_context(_optional_context(lambda: propagate_attributes(**prop_kwargs)))
        span = stack.enter_context(
            _optional_context(lambda: client.start_as_current_observation(as_type="span", name=name))
        )
        if input is not None:
            # On the trace (for the trace list) *and* on the root span itself, so
            # the rule is visible in an exported observation tree too.
            _safe(span, "set_trace_io", input=input)
            _safe(span, "update", input=input)
        yield span


def finish_trace(
    span: Any,
    *,
    output: Any = None,
    metadata: dict | None = None,
    level: str | None = None,
    status_message: str | None = None,
) -> None:
    """Attach the final output, metadata and status to the run's trace.

    ``level="WARNING"`` (e.g. a run that never produced a parseable verdict)
    makes the trace stand out in the Langfuse trace list instead of looking
    identical to a clean one.
    """
    if output is not None:
        _safe(span, "set_trace_io", output=output)
    update: dict[str, Any] = {}
    if output is not None:
        update["output"] = output
    if metadata:
        update["metadata"] = metadata
    if level:
        update["level"] = level
    if status_message:
        update["status_message"] = status_message
    if update:
        _safe(span, "update", **update)


def current_trace_id() -> str | None:
    """Id of the trace currently in scope (call inside :func:`check_run`)."""
    client = get_client()
    if client is None:
        return None
    try:
        return client.get_current_trace_id()
    except Exception:  # noqa: BLE001
        return None


def trace_url(trace_id: str | None) -> str | None:
    """Deep link to a trace in the Langfuse UI, so logs/reports can point at it."""
    client = get_client()
    if client is None or not trace_id:
        return None
    try:
        return client.get_trace_url(trace_id=trace_id)
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# Nested observations
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def step(name: str, *, metadata: dict | None = None) -> Iterator[Any]:
    """A plain nested span, used to group everything one agent iteration did."""
    client = get_client()
    if client is None:
        yield _Noop()
        return
    with _optional_context(lambda: client.start_as_current_observation(
        as_type="span", name=name, metadata=metadata
    )) as span:
        yield span


@contextlib.contextmanager
def tool(
    name: str, *, input: Any = None, metadata: dict | None = None
) -> Iterator[Any]:
    """The Python execution of an agent-written code block.

    Typed as ``tool`` rather than ``span`` so Langfuse renders it distinctly and
    it can be filtered/aggregated separately from the LLM calls.
    """
    client = get_client()
    if client is None:
        yield _Noop()
        return
    with _optional_context(lambda: client.start_as_current_observation(
        as_type="tool", name=name, input=input, metadata=metadata
    )) as obs:
        yield obs


@contextlib.contextmanager
def generation(
    name: str,
    *,
    model: str,
    input: Any = None,
    model_parameters: dict | None = None,
    metadata: dict | None = None,
) -> Iterator[Any]:
    """A single LLM call, recorded as a Langfuse generation nested in the trace."""
    client = get_client()
    if client is None:
        yield _Noop()
        return
    with _optional_context(lambda: client.start_as_current_observation(
        as_type="generation", name=name, model=model
    )) as gen:
        update: dict[str, Any] = {}
        if input is not None:
            update["input"] = input
        if model_parameters:
            update["model_parameters"] = model_parameters
        if metadata:
            update["metadata"] = metadata
        if update:
            _safe(gen, "update", **update)
        yield gen


def record_usage(
    gen: Any,
    *,
    output: Any,
    prompt_tokens: int,
    completion_tokens: int,
    extra_usage: dict | None = None,
    truncated: bool = False,
    metadata: dict | None = None,
) -> None:
    """Attach the reply, token usage and stop status to a generation.

    ``truncated=True`` (the provider stopped at ``max_tokens``) is flagged as a
    WARNING: a cut-off reply is an expensive silent failure — the agent throws
    away most of what it just paid for — and it is invisible otherwise.
    """
    usage: dict[str, int] = {"input": prompt_tokens, "output": completion_tokens}
    for key, value in (extra_usage or {}).items():
        if value:
            usage[key] = value
    usage["total"] = sum(usage.values())
    update: dict[str, Any] = {"output": output, "usage_details": usage}
    if metadata:
        update["metadata"] = metadata
    if truncated:
        update["level"] = "WARNING"
        update["status_message"] = "reply truncated: hit max_tokens"
    _safe(gen, "update", **update)


def finish(
    obs: Any,
    *,
    output: Any = None,
    metadata: dict | None = None,
    level: str | None = None,
    status_message: str | None = None,
) -> None:
    """Attach the result of a nested observation (span/tool) before it closes."""
    update: dict[str, Any] = {}
    if output is not None:
        update["output"] = output
    if metadata:
        update["metadata"] = metadata
    if level:
        update["level"] = level
    if status_message:
        update["status_message"] = status_message
    if update:
        _safe(obs, "update", **update)


# --------------------------------------------------------------------------- #
# Scores (the evaluation metrics, attached to a finished trace)
# --------------------------------------------------------------------------- #


def score(
    name: str,
    value: float | bool | str,
    *,
    trace_id: str | None = None,
    session_id: str | None = None,
    comment: str | None = None,
    data_type: str | None = None,
) -> None:
    """Attach one evaluation metric to a finished trace (or to a whole session).

    ``data_type`` is inferred when omitted: bool -> BOOLEAN, number -> NUMERIC,
    str -> CATEGORICAL. Booleans are sent as 0/1, as the API requires.
    """
    client = get_client()
    if client is None or not (trace_id or session_id):
        return
    if data_type is None:
        if isinstance(value, bool):
            data_type = "BOOLEAN"
        elif isinstance(value, (int, float)):
            data_type = "NUMERIC"
        else:
            data_type = "CATEGORICAL"
    payload: float | str = float(value) if isinstance(value, bool) else value
    try:
        client.create_score(
            name=name,
            value=payload,
            trace_id=trace_id,
            session_id=session_id,
            data_type=data_type,
            comment=comment,
        )
    except Exception:  # noqa: BLE001 - tracing must never break the app
        pass


_NUMERIC_SCORES = (
    "precision",
    "recall",
    "f1",
    "tp",
    "fp",
    "fn",
    # None on runs that produced no labelling, and skipped rather than sent as 0:
    # an unmeasured run has not scored zero, it has not been measured.
    "union_accuracy",
    "label_coverage",
    "labels_reported",
    "labels_expected",
)
_BOOLEAN_SCORES = ("exact_set_match", "verdict_match", "parse_ok", "abstained")


def score_run(trace_id: str | None, scores: Any, extra: dict | None = None) -> None:
    """Push a whole :class:`scoring.Scores` object onto a trace in one call.

    This is what turns the Langfuse project into the experiment dashboard: every
    run carries precision / recall / f1 / exact-set-match / verdict-match /
    parse-ok, so runs can be compared and charted by mode, model or case.
    """
    if not trace_id or scores is None:
        return
    for name in _NUMERIC_SCORES:
        value = getattr(scores, name, None)
        if value is not None:
            score(name, float(value), trace_id=trace_id)
    for name in _BOOLEAN_SCORES:
        value = getattr(scores, name, None)
        if value is not None:
            score(name, bool(value), trace_id=trace_id)
    predicted = getattr(scores, "predicted_verdict", None)
    if predicted:
        score("verdict", str(predicted), trace_id=trace_id)
    for name, value in (extra or {}).items():
        if isinstance(value, (bool, int, float)):
            score(name, value, trace_id=trace_id)


def score_sweep(session_id: str | None, mode: str, aggregate: Any) -> None:
    """Attach a mode's aggregate metrics to the session that groups the sweep.

    Per-trace scores answer "how did this run do?"; these answer the thesis
    question directly — "stateful vs stateless, averaged over the repeats" — and
    show up on the session in Langfuse.
    """
    if not session_id or aggregate is None:
        return
    metrics = getattr(aggregate, "metrics", None) or {}
    n = getattr(aggregate, "n", 0)
    for name, stats in metrics.items():
        score(
            f"{mode}.{name}",
            float(stats.get("mean", 0.0)),
            session_id=session_id,
            comment=f"mean over {n} run(s), std {stats.get('std', 0.0):.3f}",
        )


def flush() -> None:
    """Flush queued events; call before a short-lived script exits."""
    client = get_client()
    if client is not None:
        try:
            client.flush()
        except Exception:  # noqa: BLE001
            pass
