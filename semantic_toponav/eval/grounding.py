"""Language-grounding evaluation suite.

The synthetic eval suite (:mod:`semantic_toponav.eval.runner`) measures
the **coordination** axis — grant rate / latency / fairness / etc.
across fleet strategies. It does *not* measure the **language
grounding** axis: how often :func:`~semantic_toponav.query.resolve_goal`
or :func:`~semantic_toponav.query.llm_resolve_goal` pick the right
node for a free-text query, how often they abstain on an unresolvable
query, and how often the LLM rewrite path is *safe* (no dropped node
references, no broken step indices, no leakage from already-traversed
prefix).

This module ships that measurement substrate. The public entry points:

* :func:`load_grounding_corpus` — YAML loader for the gold corpus
  format documented under ``docs/grounding_corpus.md`` (a flat list of
  ``(query, gold, kind)`` cases tagged ``precise`` / ``ambiguous`` /
  ``unresolvable``).
* :func:`evaluate_resolver` — drive a (deterministic or LLM) resolver
  across the corpus and compute precision@1, top-k recall,
  clarification rate, false-positive resolve rate, and abstention
  rate.
* :func:`evaluate_describer_safety` — run :func:`llm_describe_path`
  against a small fixture set and check four deterministic
  invariants the rewrite must satisfy.

The metric design deliberately does **not** use LLM-as-judge as the
main scorer — gold node ids + deterministic invariants are the source
of truth. A small (20–50 case) human-eval addendum for coherence /
helpfulness can be layered on top later as an *optional* signal.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

import yaml

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.llm.backends import EchoBackend, LLMBackend
from semantic_toponav.query.llm_resolve import (
    LLMResolveResult,
    llm_resolve_goal,
)
from semantic_toponav.query.resolve import GoalCandidate, resolve_goal
from semantic_toponav.waypoint.llm_describe import (
    LLMDescribeResult,
    llm_describe_path,
)

CaseKind = Literal["precise", "ambiguous", "unresolvable"]


# ---------------------------------------------------------------------------
# Corpus loader
# ---------------------------------------------------------------------------


@dataclass
class GroundingCase:
    """One row in the gold corpus.

    Attributes
    ----------
    query:
        Free-text user input handed to the resolver.
    gold:
        Acceptable target node ids. ``[]`` when ``kind="unresolvable"``
        — the resolver should abstain.
    kind:
        ``"precise"`` (exactly one gold), ``"ambiguous"`` (two or more
        gold; a clarification is the *preferred* outcome), or
        ``"unresolvable"`` (no gold; abstention expected).
    note:
        Optional free-text comment carried into the report rows for
        debugging — never read by the metrics.
    """

    query: str
    gold: list[str]
    kind: CaseKind
    note: str = ""


@dataclass
class GroundingCorpus:
    """A graph + the gold cases scoped to it."""

    graph_path: str
    graph: TopologyGraph
    cases: list[GroundingCase]


def load_grounding_corpus(path: str | Path) -> GroundingCorpus:
    """Load a gold corpus YAML.

    Expected shape::

        graph: examples/multi_floor_office.yaml
        cases:
          - {query: "second floor meeting room", gold: meeting_room_2f, kind: precise}
          - {query: "near the elevator",
             gold: [meeting_room_2f, exec_office_2f], kind: ambiguous}
          - {query: "the basement", gold: null, kind: unresolvable}

    The graph path is resolved *relative to the corpus file* if it is
    not absolute, so corpora can ship alongside their reference graph.
    """
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"corpus {path!r} root must be a mapping, got {type(raw).__name__}")

    graph_path_raw = raw.get("graph")
    if not isinstance(graph_path_raw, str) or not graph_path_raw:
        raise ValueError(f"corpus {path!r}: 'graph:' must be a non-empty string")
    graph_path = Path(graph_path_raw)
    if not graph_path.is_absolute():
        graph_path = (p.parent / graph_path).resolve()
    graph = load_graph(str(graph_path))
    node_ids: set[str] = {n.id for n in graph.nodes()}

    cases_raw = raw.get("cases")
    if not isinstance(cases_raw, list):
        raise ValueError(f"corpus {path!r}: 'cases:' must be a list")

    cases: list[GroundingCase] = []
    for i, item in enumerate(cases_raw):
        if not isinstance(item, dict):
            raise ValueError(f"corpus {path!r}: case[{i}] must be a mapping")
        query = item.get("query")
        kind = item.get("kind")
        gold_raw = item.get("gold")
        note = item.get("note", "")

        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"corpus {path!r}: case[{i}] 'query' must be a non-empty string")
        if kind not in ("precise", "ambiguous", "unresolvable"):
            raise ValueError(
                f"corpus {path!r}: case[{i}] 'kind' must be precise|ambiguous|unresolvable, "
                f"got {kind!r}"
            )

        if kind == "unresolvable":
            gold: list[str] = []
            if gold_raw not in (None, [], ""):
                raise ValueError(
                    f"corpus {path!r}: case[{i}] kind=unresolvable must have gold=null/[]/'', "
                    f"got {gold_raw!r}"
                )
        elif isinstance(gold_raw, str):
            gold = [gold_raw]
        elif isinstance(gold_raw, list) and all(isinstance(x, str) for x in gold_raw):
            gold = list(gold_raw)
        else:
            raise ValueError(
                f"corpus {path!r}: case[{i}] 'gold' must be str or list[str], got {gold_raw!r}"
            )

        if kind == "precise" and len(gold) != 1:
            raise ValueError(
                f"corpus {path!r}: case[{i}] kind=precise must have exactly one gold id, "
                f"got {gold!r}"
            )
        if kind == "ambiguous" and len(gold) < 2:
            raise ValueError(
                f"corpus {path!r}: case[{i}] kind=ambiguous must have at least two gold ids, "
                f"got {gold!r}"
            )

        for gid in gold:
            if gid not in node_ids:
                raise ValueError(
                    f"corpus {path!r}: case[{i}] gold id {gid!r} is not a node in {graph_path}"
                )

        cases.append(GroundingCase(query=query, gold=gold, kind=kind, note=note))

    return GroundingCorpus(graph_path=str(graph_path), graph=graph, cases=cases)


# ---------------------------------------------------------------------------
# Resolver evaluation
# ---------------------------------------------------------------------------


class _Resolver(Protocol):
    """Common surface for the deterministic and LLM resolvers."""

    def __call__(
        self,
        graph: TopologyGraph,
        text: str,
        *,
        top_k: int,
    ) -> tuple[list[GoalCandidate], bool]: ...


def _deterministic_resolver(
    graph: TopologyGraph,
    text: str,
    *,
    top_k: int,
) -> tuple[list[GoalCandidate], bool]:
    """The deterministic resolver never emits a ClarificationQuestion."""
    return resolve_goal(graph, text, top_k=top_k), False


@dataclass
class _LLMResolverWrapper:
    backend: LLMBackend
    ambiguity_threshold: float = 0.5

    def __call__(
        self,
        graph: TopologyGraph,
        text: str,
        *,
        top_k: int,
    ) -> tuple[list[GoalCandidate], bool]:
        result: LLMResolveResult = llm_resolve_goal(
            graph,
            text,
            self.backend,
            top_k=top_k,
            ambiguity_threshold=self.ambiguity_threshold,
        )
        return result.candidates, result.clarification is not None


@dataclass
class CaseOutcome:
    """Per-case result; metrics roll these up across the corpus."""

    case: GroundingCase
    top1: str | None
    top_k_ids: list[str]
    clarified: bool

    @property
    def correct_at_1(self) -> bool:
        return self.top1 is not None and self.top1 in self.case.gold


@dataclass
class GroundingMetrics:
    """Aggregate metrics for one resolver × one corpus. Rates ∈ [0, 1]."""

    n_total: int
    n_precise: int
    n_ambiguous: int
    n_unresolvable: int
    precision_at_1: float
    recall_at_3: float
    recall_at_5: float
    clarification_rate: float
    false_positive_resolve_rate: float
    abstention_rate: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "n_total": self.n_total,
            "n_precise": self.n_precise,
            "n_ambiguous": self.n_ambiguous,
            "n_unresolvable": self.n_unresolvable,
            "precision_at_1": self.precision_at_1,
            "recall_at_3": self.recall_at_3,
            "recall_at_5": self.recall_at_5,
            "clarification_rate": self.clarification_rate,
            "false_positive_resolve_rate": self.false_positive_resolve_rate,
            "abstention_rate": self.abstention_rate,
        }


def _aggregate(outcomes: Sequence[CaseOutcome]) -> GroundingMetrics:
    precise = [o for o in outcomes if o.case.kind == "precise"]
    ambiguous = [o for o in outcomes if o.case.kind == "ambiguous"]
    unresolvable = [o for o in outcomes if o.case.kind == "unresolvable"]
    answerable = precise + ambiguous

    def _rate(num: int, den: int) -> float:
        return num / den if den else 0.0

    p_at_1 = _rate(sum(1 for o in answerable if o.correct_at_1), len(answerable))

    def _recall(k: int) -> float:
        hit = sum(
            1 for o in answerable if any(gid in o.top_k_ids[:k] for gid in o.case.gold)
        )
        return _rate(hit, len(answerable))

    clar_rate = _rate(sum(1 for o in ambiguous if o.clarified), len(ambiguous))
    fp_resolve = _rate(
        sum(1 for o in unresolvable if o.top1 is not None and not o.clarified),
        len(unresolvable),
    )
    abstention = _rate(
        sum(1 for o in unresolvable if o.top1 is None or o.clarified),
        len(unresolvable),
    )

    return GroundingMetrics(
        n_total=len(outcomes),
        n_precise=len(precise),
        n_ambiguous=len(ambiguous),
        n_unresolvable=len(unresolvable),
        precision_at_1=p_at_1,
        recall_at_3=_recall(3),
        recall_at_5=_recall(5),
        clarification_rate=clar_rate,
        false_positive_resolve_rate=fp_resolve,
        abstention_rate=abstention,
    )


@dataclass
class ResolverEvaluation:
    """Output of :func:`evaluate_resolver` — metrics + per-case detail."""

    resolver_name: str
    metrics: GroundingMetrics
    outcomes: list[CaseOutcome] = field(default_factory=list)


def evaluate_resolver(
    corpus: GroundingCorpus,
    *,
    resolver_name: str,
    backend: LLMBackend | None = None,
    top_k: int = 5,
    ambiguity_threshold: float = 0.5,
) -> ResolverEvaluation:
    """Drive a resolver across ``corpus`` and report metrics.

    ``backend=None`` uses the deterministic :func:`resolve_goal`. Pass
    any :class:`LLMBackend` to route through :func:`llm_resolve_goal`.
    """
    resolver: _Resolver
    if backend is None:
        resolver = _deterministic_resolver
    else:
        resolver = _LLMResolverWrapper(backend=backend, ambiguity_threshold=ambiguity_threshold)

    outcomes: list[CaseOutcome] = []
    for case in corpus.cases:
        candidates, clarified = resolver(corpus.graph, case.query, top_k=top_k)
        top1 = candidates[0].node_id if candidates else None
        top_k_ids = [c.node_id for c in candidates]
        outcomes.append(
            CaseOutcome(
                case=case,
                top1=top1,
                top_k_ids=top_k_ids,
                clarified=clarified,
            )
        )

    return ResolverEvaluation(
        resolver_name=resolver_name,
        metrics=_aggregate(outcomes),
        outcomes=outcomes,
    )


# ---------------------------------------------------------------------------
# Describer rewrite safety
# ---------------------------------------------------------------------------


@dataclass
class DescriberSafetyCase:
    """One describer-safety probe."""

    name: str
    path: list[str]
    start_index: int = 0
    situation: str | None = None
    style: str | None = None


@dataclass
class DescriberSafetyOutcome:
    """Per-case pass/fail across the four invariants."""

    case: DescriberSafetyCase
    references_preserved: bool
    step_indices_preserved: bool
    prior_steps_untouched: bool
    situation_changes_output: bool | None  # None when case has no `situation`
    used_fallback: bool

    @property
    def all_invariants_hold(self) -> bool:
        bits = [
            self.references_preserved,
            self.step_indices_preserved,
            self.prior_steps_untouched,
        ]
        if self.situation_changes_output is not None:
            bits.append(self.situation_changes_output)
        return all(bits)


@dataclass
class DescriberSafetyMetrics:
    n_total: int
    references_preserved_rate: float
    step_indices_preserved_rate: float
    prior_steps_untouched_rate: float
    situation_change_rate: float
    fallback_rate: float
    all_invariants_rate: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "n_total": self.n_total,
            "references_preserved_rate": self.references_preserved_rate,
            "step_indices_preserved_rate": self.step_indices_preserved_rate,
            "prior_steps_untouched_rate": self.prior_steps_untouched_rate,
            "situation_change_rate": self.situation_change_rate,
            "fallback_rate": self.fallback_rate,
            "all_invariants_rate": self.all_invariants_rate,
        }


@dataclass
class DescriberSafetyEvaluation:
    backend_name: str
    metrics: DescriberSafetyMetrics
    outcomes: list[DescriberSafetyOutcome] = field(default_factory=list)


def _label_tokens(label: str | None) -> set[str]:
    """Lowercase alphanumeric tokens from a node label."""
    if not label:
        return set()
    return {tok.lower() for tok in re.findall(r"[A-Za-z0-9]+", label)}


def _step_node_label(graph: TopologyGraph, node_id: str | None) -> str | None:
    if node_id is None:
        return None
    return graph.get_node(node_id).label


def _check_references_preserved(
    result: LLMDescribeResult, graph: TopologyGraph
) -> bool:
    """Each rewritten step must still surface its deterministic-floor node label.

    For every ``base_step`` with a ``node_id``, the rewritten line at
    the same position must contain at least one alphanumeric token
    from that node's label (case-insensitive). This catches a rewrite
    that silently drops the place name. Fallback runs are trivially
    fine because they reuse the deterministic text verbatim.
    """
    if result.used_fallback:
        return True
    for rewritten, base in zip(result.steps, result.base_steps, strict=False):
        label = _step_node_label(graph, base.node_id)
        if label is None:
            continue
        tokens = _label_tokens(label)
        if not tokens:
            continue
        rewritten_tokens = _label_tokens(rewritten)
        if not (tokens & rewritten_tokens):
            return False
    return True


def _check_step_indices_preserved(result: LLMDescribeResult) -> bool:
    """The non-fallback rewrite must emit one line per ``base_step``.

    Fallback runs copy the deterministic text and pass trivially.
    """
    if result.used_fallback:
        return True
    return len(result.steps) == len(result.base_steps)


def _check_prior_steps_untouched(
    result: LLMDescribeResult,
    graph: TopologyGraph,
    full_path: Sequence[str],
    start_index: int,
) -> bool:
    """For mid-traversal rewrites, the rewritten slice must not mention
    labels of nodes that only appear in ``full_path[:start_index]``.

    "Only appear" means tokens that are in some prefix node label
    but NOT in any node label of ``full_path[start_index:]``. Tokens
    that occur in both regions (e.g. "Corridor" appearing on both
    floors) are allowed — they're generic descriptors, not prefix
    leakage.
    """
    if start_index <= 0 or result.used_fallback:
        return True
    prefix_ids = list(full_path[:start_index])
    suffix_ids = list(full_path[start_index:])
    prefix_tokens: set[str] = set()
    for nid in prefix_ids:
        prefix_tokens |= _label_tokens(graph.get_node(nid).label)
    suffix_tokens: set[str] = set()
    for nid in suffix_ids:
        suffix_tokens |= _label_tokens(graph.get_node(nid).label)
    prefix_only = prefix_tokens - suffix_tokens
    if not prefix_only:
        return True
    for line in result.steps:
        if _label_tokens(line) & prefix_only:
            return False
    return True


def _check_situation_changes_output(
    graph: TopologyGraph,
    backend: LLMBackend,
    case: DescriberSafetyCase,
) -> bool | None:
    """When ``situation`` is set, re-run without it and assert the
    rewritten text or the backend prompt differs.

    Returns ``None`` when the case carries no ``situation`` — there's
    no invariant to check. For EchoBackend (or any other deterministic
    stub) we fall back to comparing the prompts that the backend
    received, so the assertion still catches a missing prompt-side
    injection even when the stub returns canned text identically.
    """
    if case.situation is None:
        return None
    backend_no = _clone_backend(backend)
    backend_yes = _clone_backend(backend)
    without = llm_describe_path(
        graph, case.path, backend_no,
        start_index=case.start_index,
        style=case.style,
    )
    with_situation = llm_describe_path(
        graph, case.path, backend_yes,
        start_index=case.start_index,
        style=case.style,
        situation=case.situation,
    )
    if without.steps != with_situation.steps:
        return True
    prompt_no = _last_prompt(backend_no)
    prompt_yes = _last_prompt(backend_yes)
    if prompt_no is None or prompt_yes is None:
        # No prompt visibility (real cloud backend, etc.). With
        # identical rewritten text we can't claim the situation
        # changed anything — flag as failure.
        return False
    return prompt_no != prompt_yes


def _clone_backend(backend: LLMBackend) -> LLMBackend:
    """For EchoBackend, hand out a fresh script-aligned copy so the
    with/without runs see the same scripted reply order. Other backends
    are already side-effect-free per call so we return the same one."""
    if isinstance(backend, EchoBackend):
        remaining = list(backend._script[backend._index:])  # noqa: SLF001
        return EchoBackend(script=remaining)
    return backend


def _last_prompt(backend: LLMBackend) -> str | None:
    if isinstance(backend, EchoBackend) and backend.calls:
        prompt = backend.calls[-1]["prompt"]
        return prompt if isinstance(prompt, str) else None
    return None


def evaluate_describer_safety(
    graph: TopologyGraph,
    backend: LLMBackend,
    cases: Iterable[DescriberSafetyCase],
    *,
    backend_name: str = "echo",
) -> DescriberSafetyEvaluation:
    """Run :func:`llm_describe_path` across ``cases`` and check invariants.

    The four invariants:

    1. **references preserved** — each rewritten step still surfaces
       at least one token from its deterministic-floor node label.
    2. **step indices preserved** — the rewritten line count matches
       ``base_steps`` (fallback passes trivially).
    3. **prior steps untouched** — for ``start_index > 0`` runs, the
       rewritten slice does not introduce tokens from labels that
       only exist in ``path[:start_index]``.
    4. **situation changes output** — when ``situation`` is set,
       re-running without it must produce either a different
       rewritten slice or a different backend prompt.

    Per-case all four are pass/fail; the aggregate rates are
    proportion-of-passes.
    """
    cases_list = list(cases)
    outcomes: list[DescriberSafetyOutcome] = []
    fallbacks = 0
    for case in cases_list:
        result = llm_describe_path(
            graph, case.path, backend,
            start_index=case.start_index,
            situation=case.situation,
            style=case.style,
        )
        if result.used_fallback:
            fallbacks += 1
        outcomes.append(
            DescriberSafetyOutcome(
                case=case,
                references_preserved=_check_references_preserved(result, graph),
                step_indices_preserved=_check_step_indices_preserved(result),
                prior_steps_untouched=_check_prior_steps_untouched(
                    result, graph, case.path, case.start_index
                ),
                situation_changes_output=_check_situation_changes_output(
                    graph, backend, case
                ),
                used_fallback=result.used_fallback,
            )
        )

    n = len(outcomes)

    def _rate(predicate) -> float:
        if n == 0:
            return 0.0
        return sum(1 for o in outcomes if predicate(o)) / n

    sit_outcomes = [o for o in outcomes if o.situation_changes_output is not None]
    sit_rate = (
        sum(1 for o in sit_outcomes if o.situation_changes_output) / len(sit_outcomes)
        if sit_outcomes
        else 0.0
    )

    metrics = DescriberSafetyMetrics(
        n_total=n,
        references_preserved_rate=_rate(lambda o: o.references_preserved),
        step_indices_preserved_rate=_rate(lambda o: o.step_indices_preserved),
        prior_steps_untouched_rate=_rate(lambda o: o.prior_steps_untouched),
        situation_change_rate=sit_rate,
        fallback_rate=fallbacks / n if n else 0.0,
        all_invariants_rate=_rate(lambda o: o.all_invariants_hold),
    )
    return DescriberSafetyEvaluation(
        backend_name=backend_name,
        metrics=metrics,
        outcomes=outcomes,
    )


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def grounding_report_markdown(
    resolver_evals: list[ResolverEvaluation],
    safety_eval: DescriberSafetyEvaluation | None = None,
) -> str:
    """Render a grounding eval as markdown — resolver comparison + describer safety."""
    parts: list[str] = ["## Resolver grounding", ""]
    if not resolver_evals:
        parts.append("_(no resolver evaluations)_")
    else:
        parts.append(
            "| resolver | n | precise | ambiguous | unresolvable | "
            "precision@1 | recall@3 | recall@5 | clarify | fp_resolve | abstain |"
        )
        parts.append("|" + "---|" * 11)
        for ev in resolver_evals:
            m = ev.metrics
            parts.append(
                f"| {ev.resolver_name} | {m.n_total} | {m.n_precise} | "
                f"{m.n_ambiguous} | {m.n_unresolvable} | "
                f"{m.precision_at_1:.2f} | {m.recall_at_3:.2f} | "
                f"{m.recall_at_5:.2f} | {m.clarification_rate:.2f} | "
                f"{m.false_positive_resolve_rate:.2f} | "
                f"{m.abstention_rate:.2f} |"
            )
        parts.append("")

    parts.extend(["## Describer rewrite safety", ""])
    if safety_eval is None:
        parts.append("_(skipped — no backend supplied for describer safety)_")
    else:
        m = safety_eval.metrics
        parts.append(f"backend: `{safety_eval.backend_name}`, n={m.n_total}")
        parts.append("")
        parts.append("| invariant | pass rate |")
        parts.append("|---|---|")
        parts.append(f"| references_preserved | {m.references_preserved_rate:.2f} |")
        parts.append(f"| step_indices_preserved | {m.step_indices_preserved_rate:.2f} |")
        parts.append(f"| prior_steps_untouched | {m.prior_steps_untouched_rate:.2f} |")
        parts.append(f"| situation_changes_output | {m.situation_change_rate:.2f} |")
        parts.append(f"| all_invariants | {m.all_invariants_rate:.2f} |")
        parts.append(f"| fallback_rate | {m.fallback_rate:.2f} |")

    return "\n".join(parts) + "\n"


__all__ = [
    "CaseKind",
    "CaseOutcome",
    "DescriberSafetyCase",
    "DescriberSafetyEvaluation",
    "DescriberSafetyMetrics",
    "DescriberSafetyOutcome",
    "GroundingCase",
    "GroundingCorpus",
    "GroundingMetrics",
    "ResolverEvaluation",
    "evaluate_describer_safety",
    "evaluate_resolver",
    "grounding_report_markdown",
    "load_grounding_corpus",
]
