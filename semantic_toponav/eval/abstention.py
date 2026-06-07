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
from typing import Literal

import yaml

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.llm.backends import LLMBackend
from semantic_toponav.query.llm_resolve import llm_resolve_goal
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


def _rate(num: int, den: int) -> float:
    return num / den if den else 0.0


def _resolve_abstains(
    graph: TopologyGraph,
    query: str,
    backend: LLMBackend | None,
    top_k: int,
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
    result = llm_resolve_goal(graph, query, backend, top_k=top_k)
    if not result.candidates or result.clarification is not None:
        return True, None
    return False, result.candidates[0].node_id


def run_abstention_benchmark(
    graph: TopologyGraph,
    cases: list[AbstentionCase],
    *,
    backend: LLMBackend | None = None,
    top_k: int = 5,
) -> AbstentionReport:
    """Run the abstention benchmark over ``cases`` on ``graph``.

    Deterministic and backend-free by default (uses :func:`resolve_goal`);
    pass ``backend`` to measure the LLM-augmented path.
    """
    outcomes: list[AbstentionOutcome] = []
    for case in cases:
        abstained, top1 = _resolve_abstains(graph, case.query, backend, top_k)
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


__all__ = [
    "AbstentionCase",
    "AbstentionCategory",
    "AbstentionOutcome",
    "AbstentionReport",
    "CategoryMetrics",
    "abstention_report_markdown",
    "load_abstention_corpus",
    "run_abstention_benchmark",
]
