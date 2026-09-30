"""Run dashboard: simple charts from the experiment ledger. Read-only; no agent or provider calls.

    python acc_agent/dashboard.py              # window that redraws when the ledger changes
    python acc_agent/dashboard.py --save DIR   # write the charts as PNG files and exit
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import textwrap
from collections import Counter
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from experiments import ExperimentStore  # noqa: E402

MODES = {"stateful": "#0065BD", "stateless": "#E37222"}
STATUSES = {"complete": ("complete", "#4C9A2A"), "incomplete": ("incomplete", "#F2B134"),
            "abstained": ("abstained (UNKNOWN)", "#9E9E9E"), "reported_unverified_scope": ("unverified scope", "#B39DDB"),
            "error": ("error", "#C0392B"), "interrupted": ("interrupted", "#7F1D1D"), "running": ("running", "#9FC5E8")}
VERSION_COLORS = ["#B0B0B0", "#8FB8DE", "#0065BD", "#E37222", "#4C9A2A", "#7F1D1D"]
GREY = "#555555"
REFRESH_MS = 10_000
LOG_DIR = Path(__file__).resolve().parent / "logs"
SAVE_DIR = Path(__file__).resolve().parent / "slides" / "charts"


def version(configuration: dict) -> str:
    """The recorded agent-loop tag plus the completion-check version; runs before the tag used the custom loop."""
    return f"{configuration.get('agent_protocol') or 'pre-LangChain loop'}, checks v{configuration.get('completion_checks')}"


def load(store: ExperimentStore) -> dict:
    """All runs (newest first) with cost and version, plus the GUI's suite indexes (newest first)."""
    runs = store.list_runs()
    for run in runs:
        messages = json.loads(run.pop("details") or "{}").get("messages", [])
        run["cost"] = sum(((m.get("response_metadata") or {}).get("cost") or 0) for m in messages if m.get("role") == "assistant")
        run["local_start"] = datetime.fromisoformat(run["started_at"]).astimezone()
        run["version"] = version(json.loads(run.pop("configuration") or "{}"))
    suites = []
    for path in sorted(LOG_DIR.glob("*_health_suite.json"), reverse=True):
        try:
            suites.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue  # the GUI rewrites the index while a suite runs
    return {"runs": runs, "suites": suites}


def latest_batch(ledger: dict) -> tuple[dict | None, list[dict]]:
    """The suite containing the newest run, matched by case log file name, or else the newest run's sweep."""
    runs = ledger["runs"]
    if not runs:
        return None, []
    log_names = {r["sweep_id"]: Path(r["log_path"] or "").name for r in runs}
    newest = runs[0]["sweep_id"]
    for suite in ledger["suites"]:
        names = {Path(case.get("log_path") or "").name for case in suite.get("cases", [])} - {""}
        if log_names[newest] in names:
            sweeps = {sweep for sweep, name in log_names.items() if name in names}
            return suite, [r for r in runs if r["sweep_id"] in sweeps]
    return None, [r for r in runs if r["sweep_id"] == newest]


def group(runs: list[dict], key: str) -> dict[tuple[str, str], list[dict]]:
    groups = {}
    for run in runs:
        if run["status"] != "running":
            groups.setdefault((run["case_id"], run[key]), []).append(run)
    return groups


def versions_in_order(runs: list[dict]) -> list[str]:
    return list(dict.fromkeys(r["version"] for r in reversed(runs)))


def mean(values):
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def pretty(case: str) -> str:
    return case.replace("__", " | ").replace("_", " ")


def style(ax, title, grid="x"):
    ax.set_title(title, fontsize=12, fontweight="bold", loc="left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis=grid, color="#DDDDDD", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=9)


def series_bars(ax, cases, groups, series, value, label, xmax):
    """One horizontal bar per series and case (fixed slot per series), with the value written at the bar end."""
    height = min(0.8 / len(series), 0.4)
    size = 8 if len(series) <= 2 else 7
    for i, case in enumerate(cases):
        if not any((case, s) in groups for s in series):
            ax.text(0, i, " not run yet", va="center", fontsize=size, color="#999999")
            continue
        for j, (name, color) in enumerate(series.items()):
            runs = groups.get((case, name))
            if not runs:
                continue
            y, v = i + height * (j + 0.5 - len(series) / 2), value(runs)
            ax.barh(y, v or 0, height=height * 0.95, color=color)
            ax.text(v or 0, y, " " + label(runs, v), va="center", fontsize=size, color=GREY if v is None else "#222222")
    ax.set_xlim(0, xmax * 1.18)


def draw_case_panels(fig: Figure, cases, groups, series, legend, title, note):
    """Completion, accuracy, calls and input tokens per case, one bar per series."""
    fig.clear()
    axes = fig.subplots(1, 4, sharey=True)
    budget = max((r["budget"] for rs in groups.values() for r in rs), default=0)

    def tokens(rs):
        v = mean(r["prompt_tokens"] for r in rs if r["usage_complete"] is not False)
        return None if v is None else v / 1000

    panels = [
        ("Completed runs", lambda rs: 100 * sum(r["status"] == "complete" for r in rs) / len(rs),
         lambda rs, v: f"{sum(r['status'] == 'complete' for r in rs)}/{len(rs)}", 100),
        ("Accuracy (share of labels correct)", lambda rs: mean(r["union_accuracy"] for r in rs),
         lambda rs, v: "no labels" if v is None else f"{v:.2f}", 1),
        (f"Model calls per run (cap {budget})", lambda rs: mean(r["iterations"] for r in rs),
         lambda rs, v: "-" if v is None else f"{v:.1f}", budget or 1),
        ("Input tokens per run (thousands)", tokens, lambda rs, v: "-" if v is None else f"{v:.0f}k",
         max((tokens(rs) or 0 for rs in groups.values()), default=1) or 1),
    ]
    for ax, (panel, value, label, xmax) in zip(axes, panels):
        series_bars(ax, cases, groups, series, value, label, xmax)
        style(ax, panel)
    axes[0].set_yticks(range(len(cases)), [pretty(c) for c in cases])
    axes[0].set_ylim(len(cases) - 0.5, -0.5)
    axes[0].set_xlabel("% of runs", fontsize=9)
    if budget:
        axes[2].axvline(budget, color="#A02018", linestyle="--", linewidth=1)
    legend_box = fig.legend(handles=[Patch(color=series[s], label=legend.get(s, s)) for s in series],
                            loc="outside lower center", ncols=2, fontsize=10, frameon=False,
                            title=textwrap.fill(note, 230), title_fontsize=9)
    legend_box.get_title().set(style="italic", color=GREY)
    fig.suptitle(title, fontsize=15, fontweight="bold", color="#0065BD", x=0.01, ha="left")


def draw_latest(fig: Figure, ledger: dict):
    suite, batch = latest_batch(ledger)
    if not batch:
        fig.clear()
        fig.suptitle("No runs recorded yet")
        return
    finished = [r for r in batch if r["status"] != "running"]
    running = len(batch) - len(finished)
    started = min(r["local_start"] for r in batch)
    if suite:
        cases = suite["case_ids"]
        what = f"{len(cases)}-case suite ({suite['status']})"
        progress = f"{len(finished)}/{suite['requested_runs']} runs finished"
    else:
        cases = sorted({r["case_id"] for r in batch}, key=pretty)
        what = "single case"
        progress = f"{len(finished)} run(s) finished"
    if running:
        progress += f", {running} running"
    series = {m: c for m, c in MODES.items() if any(r["mode"] == m for r in batch)}
    draw_case_panels(
        fig, cases, group(batch, "mode"), series, {},
        f"Latest: {what}, started {started:%d %b %H:%M} | {progress} | {'; '.join(versions_in_order(batch))}",
        "Version = the agent-loop tag recorded with every run (agent_protocol) plus the completion-check version. "
        "Accuracy counts every run that submitted labels; a suite shows every case it will run, so live runs fill in "
        "case by case. Label in the first panel = completed/finished.")


def draw_all(fig: Figure, ledger: dict):
    runs = ledger["runs"]
    versions = versions_in_order(runs)
    series = {v: VERSION_COLORS[i % len(VERSION_COLORS)] for i, v in enumerate(versions)}
    legend = {}
    for v in versions:
        rs = [r for r in runs if r["version"] == v and r["status"] != "running"]
        done = sum(r["status"] == "complete" for r in rs)
        first = min(r["local_start"] for r in runs if r["version"] == v)
        legend[v] = f"{v}: from {first:%d %b}, {len(rs)} runs, {100 * done / len(rs) if rs else 0:.0f}% complete"
    groups = group(runs, "version")
    draw_case_panels(
        fig, sorted({case for case, _ in groups}, key=pretty), groups, series, legend,
        f"All {len(runs)} runs, by version (oldest at the top of each case)",
        "Version = the agent-loop tag recorded with every run (agent_protocol) plus the completion-check version. "
        "Bars pool both modes, every repeat and smaller prompt or reference changes within a version, "
        "so this shows how each version did overall, not a controlled comparison.")


def draw_timeline(fig: Figure, ledger: dict):
    runs = ledger["runs"]
    fig.clear()
    days = sorted({r["local_start"].date() for r in runs})
    names = [d.strftime("%d %b") for d in days]
    counts = {status: Counter(r["local_start"].date() for r in runs if r["status"] == status) for status in STATUSES}
    ax_runs, ax_cost = fig.subplots(1, 2, width_ratios=(3, 2))

    bottom = [0] * len(days)
    for status, (label, color) in STATUSES.items():
        values = [counts[status][d] for d in days]
        if any(values):
            ax_runs.bar(names, values, bottom=bottom, color=color, label=label, width=0.6)
            bottom = [b + v for b, v in zip(bottom, values)]
    for x, total in enumerate(bottom):
        ax_runs.text(x, total, str(total), ha="center", va="bottom", fontsize=10, fontweight="bold")
    ax_runs.set_ylabel("runs")
    ax_runs.legend(fontsize=9, frameon=False, loc="upper left")
    style(ax_runs, "Runs per day, by outcome", "y")

    cost = [sum(r["cost"] for r in runs if r["local_start"].date() == d) for d in days]
    ax_cost.bar(names, cost, color="#0065BD", width=0.6)
    for x, value in enumerate(cost):
        ax_cost.text(x, value, f"${value:.2f}" if value else "not reported", ha="center", va="bottom", fontsize=10)
    ax_cost.set_ylabel("US$")
    style(ax_cost, "Model cost per day", "y")

    total = len(runs)
    done = sum(r["status"] == "complete" for r in runs)
    fig.suptitle(f"All {total} runs in the ledger: {done} complete ({100 * done / total:.0f}%), ${sum(cost):.2f} reported cost"
                 if total else "No runs recorded yet", fontsize=15, fontweight="bold", color="#0065BD", x=0.01, ha="left")
    fig.supxlabel("Days in local time. Cost is what OpenRouter reports per response; runs through the MiniMax API directly "
                  "(before 28 Sep) report no cost. Mixed cases and setups, so read this as activity, not performance.",
                  fontsize=9, style="italic", color=GREY, x=0.01, ha="left", wrap=True)


FIGURES = {"Latest run": ("latest", draw_latest), "All runs": ("all_runs", draw_all),
           "Over time": ("timeline", draw_timeline)}


def new_figure() -> Figure:
    return Figure(figsize=(17, 11), dpi=100, layout="constrained", facecolor="white")


def save_all(ledger: dict, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for slug, draw in FIGURES.values():
        fig = new_figure()
        draw(fig, ledger)
        paths.append(directory / f"{slug}.png")
        fig.savefig(paths[-1], dpi=120)
    return paths


def ledger_signature(path: Path):
    return tuple(p.stat().st_mtime_ns if p.exists() else None for p in (path, path.with_name(path.name + "-wal")))


class Dashboard(ctk.CTk):
    def __init__(self, store: ExperimentStore):
        super().__init__()
        self.title("ACC agent - run dashboard")
        self.geometry("1600x950")
        self.store, self.signature, self.ledger = store, None, {"runs": [], "suites": []}
        bar = ctk.CTkFrame(self)
        bar.pack(fill="x", padx=8, pady=6)
        self.status = ctk.CTkLabel(bar, text="Loading...", anchor="w")
        self.status.pack(side="left", fill="x", expand=True, padx=6)
        ctk.CTkButton(bar, text="Save PNGs", width=110, command=self.save).pack(side="right", padx=4)
        ctk.CTkButton(bar, text="Refresh", width=90, command=self.refresh).pack(side="right", padx=4)
        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.canvases = {}
        for name in FIGURES:
            canvas = FigureCanvasTkAgg(new_figure(), master=tabs.add(name))
            canvas.get_tk_widget().pack(fill="both", expand=True)
            self.canvases[name] = canvas
        self.poll()

    def poll(self):
        signature = ledger_signature(self.store.path)
        if signature != self.signature:
            self.signature = signature
            self.refresh()
        self.after(REFRESH_MS, self.poll)

    def refresh(self):
        self.ledger = load(self.store)
        for name, canvas in self.canvases.items():
            FIGURES[name][1](canvas.figure, self.ledger)
            canvas.draw_idle()
        runs = self.ledger["runs"]
        text = f"{len(runs)} runs in the ledger"
        if runs:
            r = runs[0]
            text += (f"  |  newest: {pretty(r['case_id'])}, {r['mode']} r{r['repeat']}, {r['status']} "
                     f"(started {r['local_start']:%d %b %H:%M}; {r['version']})")
        self.status.configure(text=f"{text}  |  updated {datetime.now():%H:%M:%S}, redraws when the ledger changes")

    def save(self):
        paths = save_all(self.ledger, SAVE_DIR)
        self.status.configure(text=f"Saved {len(paths)} charts to {SAVE_DIR}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--save", type=Path, metavar="DIR", help="write the charts as PNG files and exit")
    args = parser.parse_args()
    store = ExperimentStore()
    if args.save:
        for path in save_all(load(store), args.save):
            print(path)
        return
    ctk.set_appearance_mode("dark")
    Dashboard(store).mainloop()


if __name__ == "__main__":
    main()
