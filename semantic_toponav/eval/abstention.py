"""Abstention benchmark for NL→node grounding, by query *category*.

The grounding eval in :mod:`semantic_toponav.eval.grounding` reports a
single `abstention_rate` / `false_positive_resolve_rate` over one
"unresolvable" bucket. This module breaks the *should-abstain* space into
a taxonomy — mirroring text-QA abstention benchmarks (AbstentionBench /
"Know Your Limits") for *spatial* grounding — so the report shows **where**
a resolver wrongly resolves rather than abstaining:

* ``answerable``     — a real in-map place; the resolver *should* resolve
  (a control: over-abstaining here is the failure).
* ``unresolvable``   — gibberish / vague non-queries with no anchor.
* ``false_premise``  — presupposes a false fact (a floor that doesn't
  exist, a nonexistent attribute) — *part* of the query matches, so a
  naive matcher is tempted.
* ``out_of_map``     — a coherent place type simply absent from *this*
  graph (a pool, a server room) — the classic token-leak trap ("server
  *room*" → the meeting room).

Per category it reports `abstain_rate` and, for the should-abstain
categories, `false_positive_resolve_rate` (resolved when it should have
abstained). The headline: the deterministic floor leaks on `out_of_map` /
`false_premise` exactly where a stray token (``room``, ``kitchen``) pulls
a candidate up — which is the abstention axis the LLM-augmented path is
meant to harden. No OSS surveyed benchmarks language→node grounding with
an abstention taxonomy (see [`docs/related_work.md`](../../docs/related_work.md),
Resolve axis).

The benchmark is deterministic and backend-free by default (it runs
:func:`resolve_goal`); pass an ``LLMBackend`` to measure the
LLM-augmented path instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.llm.backends import LLMBackend
from semantic_toponav.query.llm_resolve import ABSTAIN_AWARE_SYSTEM, llm_resolve_goal
from semantic_toponav.query.resolve import resolve_goal

AbstentionCategory = Literal[
    "answerable", "unresolvable", "false_premise", "out_of_map"
]
_SHOULD_ABSTAIN = ("unresolvable", "false_premise", "out_of_map")
_CATEGORIES: tuple[AbstentionCategory, ...] = (
    "answerable", "unresolvable", "false_premise", "out_of_map",
)


@dataclass
class AbstentionCase:
    """One benchmark query with its expected category."""

    query: str
    category: AbstentionCategory
    note: str = ""


@dataclass
class AbstentionOutcome:
    """What the resolver did with one case."""

    case: AbstentionCase
    abstained: bool
    top1: str | None


@dataclass
class CategoryMetrics:
    """Aggregate metrics for one category."""

    category: AbstentionCategory
    n: int
    abstain_rate: float
    # For should-abstain categories: resolved-when-it-shouldn't. For
    # ``answerable``: the wrongful-abstention rate (lower is better).
    false_positive_resolve_rate: float

    def to_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "n": self.n,
            "abstain_rate": self.abstain_rate,
            "false_positive_resolve_rate": self.false_positive_resolve_rate,
        }


@dataclass
class AbstentionReport:
    """Per-category benchmark result plus the raw outcomes."""

    by_category: dict[str, CategoryMetrics]
    outcomes: list[AbstentionOutcome]

    @property
    def n(self) -> int:
        return len(self.outcomes)

    def to_dict(self) -> dict[str, object]:
        return {
            "n": self.n,
            "by_category": {k: v.to_dict() for k, v in self.by_category.items()},
        }


def load_abstention_corpus(path: str | Path) -> list[AbstentionCase]:
    """Load an abstention corpus YAML (``cases: [{query, category, note}]``)."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    items = raw["cases"] if isinstance(raw, dict) else raw
    cases: list[AbstentionCase] = []
    for i, item in enumerate(items):
        category = item.get("category")
        if category not in _CATEGORIES:
            raise ValueError(
                f"corpus {str(path)!r}: case[{i}] category must be one of "
                f"{_CATEGORIES}, got {category!r}"
            )
        cases.append(
            AbstentionCase(
                query=str(item["query"]),
                category=category,
                note=str(item.get("note", "")),
            )
        )
    return cases


class TranscriptBackend:
    """Replay a recorded transcript of model replies, keyed by query.

    The abstention benchmark's LLM path needs to be **reproducible in CI**,
    which a live model is not. This backend replays a committed transcript —
    ``{query: reply}`` — so the benchmark measures the LLM-augmented path
    deterministically without a network call or an API key. The transcript is
    a *reference* of the replies a correctly-prompted model is expected to
    give (see ``tests/fixtures/grounding/abstention_llm_transcript.yaml``); to
    reproduce against a real model instead, pass an ``AnthropicBackend`` /
    ``OllamaBackend`` to :func:`run_abstention_benchmark` (see
    ``examples/eval_abstention_benchmark.py``).

    The prompt :func:`llm_resolve_goal` builds opens with a ``User query:
    <query>`` line; ``generate`` parses that line and looks the query up. A
    miss raises ``KeyError`` rather than echoing, so transcript / corpus drift
    fails loudly instead of silently scoring the wrong path. Each call is
    recorded in ``calls`` for introspection, mirroring the other backends.
    """

    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = dict(responses)
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _query_of(prompt: str) -> str | None:
        for line in prompt.splitlines():
            if line.startswith("User query: "):
                return line[len("User query: ") :]
        return None

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system})
        query = self._query_of(prompt)
        if query is None or query not in self._responses:
            raise KeyError(
                f"TranscriptBackend has no recorded reply for query {query!r}. "
                f"The transcript and corpus have drifted — re-record the "
                f"transcript or update it to cover this query."
            )
        return self._responses[query]


def load_abstention_transcript(path: str | Path) -> TranscriptBackend:
    """Load a recorded LLM transcript (``responses: {query: reply}``).

    Returns a :class:`TranscriptBackend` ready to hand to
    :func:`run_abstention_benchmark` as ``backend=``.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    responses = raw["responses"] if isinstance(raw, dict) else raw
    return TranscriptBackend({str(k): str(v) for k, v in dict(responses).items()})


def _rate(num: int, den: int) -> float:
    return num / den if den else 0.0


def _resolve_abstains(
    graph: TopologyGraph,
    query: str,
    backend: LLMBackend | None,
    top_k: int,
    system: str | None,
) -> tuple[bool, str | None]:
    """Return ``(abstained, top1_id)`` for one query.

    Abstention means the resolver produced no committed top-1 — either an
    empty candidate list or (LLM path) a clarification instead of a pick.
    """
    if backend is None:
        ranked = resolve_goal(graph, query, top_k=top_k)
        if not ranked:
            return True, None
        return False, ranked[0].node_id
    result = llm_resolve_goal(graph, query, backend, top_k=top_k, system=system)
    if not result.candidates or result.clarification is not None:
        return True, None
    return False, result.candidates[0].node_id


def run_abstention_benchmark(
    graph: TopologyGraph,
    cases: list[AbstentionCase],
    *,
    backend: LLMBackend | None = None,
    top_k: int = 5,
    system: str | None = None,
) -> AbstentionReport:
    """Run the abstention benchmark over ``cases`` on ``graph``.

    Deterministic and backend-free by default (uses :func:`resolve_goal`);
    pass ``backend`` to measure the LLM-augmented path. On the LLM path the
    system instruction defaults to :data:`ABSTAIN_AWARE_SYSTEM` — the variant
    that licenses the model to decline (``Clarify:``) when no candidate
    genuinely matches, which is what hardens the token-leak categories. Pass
    ``system`` to override it (e.g. to measure the stock prompt).
    """
    if backend is not None and system is None:
        system = ABSTAIN_AWARE_SYSTEM
    outcomes: list[AbstentionOutcome] = []
    for case in cases:
        abstained, top1 = _resolve_abstains(graph, case.query, backend, top_k, system)
        outcomes.append(AbstentionOutcome(case=case, abstained=abstained, top1=top1))

    by_category: dict[str, CategoryMetrics] = {}
    for cat in _CATEGORIES:
        group = [o for o in outcomes if o.case.category == cat]
        if not group:
            continue
        n = len(group)
        abstains = sum(1 for o in group if o.abstained)
        abstain_rate = _rate(abstains, n)
        if cat in _SHOULD_ABSTAIN:
            fp = _rate(n - abstains, n)  # resolved when it should abstain
        else:  # answerable: wrongful abstention is the "false positive"
            fp = abstain_rate
        by_category[cat] = CategoryMetrics(
            category=cat, n=n, abstain_rate=abstain_rate,
            false_positive_resolve_rate=fp,
        )

    return AbstentionReport(by_category=by_category, outcomes=outcomes)


def abstention_report_markdown(report: AbstentionReport) -> str:
    """Render an :class:`AbstentionReport` as a Markdown table."""
    lines = [
        f"Abstention benchmark · n = {report.n}",
        "",
        "| category | n | abstain_rate | fp_resolve_rate |",
        "|---|---|---|---|",
    ]
    for cat in _CATEGORIES:
        m = report.by_category.get(cat)
        if m is None:
            continue
        lines.append(
            f"| `{cat}` | {m.n} | {m.abstain_rate:.2f} | "
            f"{m.false_positive_resolve_rate:.2f} |"
        )
    leaks = [
        f"`{o.case.query}` → `{o.top1}`"
        for o in report.outcomes
        if o.case.category in _SHOULD_ABSTAIN and not o.abstained
    ]
    if leaks:
        lines += ["", "False-positive resolves (should have abstained):", ""]
        lines += [f"- {leak}" for leak in leaks]
    return "\n".join(lines)


def abstention_comparison_markdown(
    deterministic: AbstentionReport,
    llm: AbstentionReport,
) -> str:
    """Render a side-by-side fp-resolve comparison of two reports.

    Shows the headline of the LLM-augmented path: the should-abstain
    categories the deterministic floor leaks on (``false_premise`` /
    ``out_of_map``) drop to zero false-positive resolves once the model is
    allowed to decline. The leaks the LLM path *closed* are listed below the
    table — the exact queries that flipped from a wrongful resolve to an
    abstention.
    """
    lines = [
        "Abstention: deterministic floor vs LLM-augmented path",
        "",
        "| category | n | fp_resolve (deterministic) | fp_resolve (LLM) |",
        "|---|---|---|---|",
    ]
    for cat in _CATEGORIES:
        d = deterministic.by_category.get(cat)
        m = llm.by_category.get(cat)
        if d is None or m is None:
            continue
        lines.append(
            f"| `{cat}` | {d.n} | {d.false_positive_resolve_rate:.2f} | "
            f"{m.false_positive_resolve_rate:.2f} |"
        )

    det_leaks = {
        o.case.query: o.top1
        for o in deterministic.outcomes
        if o.case.category in _SHOULD_ABSTAIN and not o.abstained
    }
    llm_abstained = {
        o.case.query for o in llm.outcomes if o.abstained
    }
    closed = sorted(q for q, _ in det_leaks.items() if q in llm_abstained)
    if closed:
        lines += ["", "Leaks closed by the LLM path (resolve → abstain):", ""]
        lines += [f"- `{q}` (was `{det_leaks[q]}`)" for q in closed]
    return "\n".join(lines)


__all__ = [
    "AbstentionCase",
    "AbstentionCategory",
    "AbstentionOutcome",
    "AbstentionReport",
    "CategoryMetrics",
    "TranscriptBackend",
    "abstention_comparison_markdown",
    "abstention_report_markdown",
    "load_abstention_corpus",
    "load_abstention_transcript",
    "run_abstention_benchmark",
]
