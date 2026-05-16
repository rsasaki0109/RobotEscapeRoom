"""Verify each v1-locked schema is valid JSONSchema and round-trips
through its dataclass.

See ``docs/schema_v1.md`` for the freeze policy. Any drift between
the dataclass `to_dict()` shape and the schema file fails this test;
intentional changes must update both in the same PR.
"""

from __future__ import annotations

import json
from datetime import time
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

from semantic_toponav.coordination.branch_and_bound import ConflictExplanation
from semantic_toponav.coordination.fleet import (
    FleetPlanResult,
    PlanWithSchedulerResult,
)
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.planner.reservations import Reservation
from semantic_toponav.query.clarification import ClarificationQuestion
from semantic_toponav.query.llm_resolve import LLMResolveResult
from semantic_toponav.query.resolve import GoalCandidate

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def _load(name: str) -> dict:
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Every shipped schema parses as valid JSON Schema Draft 2020-12.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "schema_file",
    [
        "semantic_waypoint_array.schema.json",
        "plan_with_scheduler_result_v1.schema.json",
        "fleet_plan_result_v1.schema.json",
        "conflict_explanation_v1.schema.json",
        "resolve_trace_v1.schema.json",
    ],
)
def test_schema_file_is_valid_jsonschema(schema_file: str) -> None:
    schema = _load(schema_file)
    jsonschema.Draft202012Validator.check_schema(schema)


# ---------------------------------------------------------------------------
# PlanWithSchedulerResult
# ---------------------------------------------------------------------------


def _granted_pwsr() -> PlanWithSchedulerResult:
    return PlanWithSchedulerResult(
        agent_id="robotA",
        path=["lobby", "corridor", "office"],
        claims=[
            Reservation(
                resource_id="corridor",
                start=time(10, 0),
                end=time(10, 5),
                agent_id="robotA",
            )
        ],
        granted=True,
        failure_reason=None,
        conflicts=[],
        reason_code="ok",
    )


def _denied_pwsr() -> PlanWithSchedulerResult:
    return PlanWithSchedulerResult(
        agent_id="robotB",
        path=[],
        claims=[],
        granted=False,
        failure_reason="corridor already booked",
        conflicts=[
            Reservation(
                resource_id="corridor",
                start=time(10, 0),
                end=time(10, 5),
                agent_id="robotA",
            )
        ],
        reason_code="reservation_conflict",
    )


def test_pwsr_to_dict_validates() -> None:
    schema = _load("plan_with_scheduler_result_v1.schema.json")
    for sample in (_granted_pwsr(), _denied_pwsr()):
        payload = sample.to_dict()
        jsonschema.validate(instance=payload, schema=schema)
        # JSON round-trip preserves shape (no datetime / set leaks).
        assert json.loads(json.dumps(payload)) == payload


def test_pwsr_unknown_field_rejected() -> None:
    schema = _load("plan_with_scheduler_result_v1.schema.json")
    payload = _granted_pwsr().to_dict()
    payload["bogus"] = "extra"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=payload, schema=schema)


def test_pwsr_reason_code_is_a_closed_enum() -> None:
    schema = _load("plan_with_scheduler_result_v1.schema.json")
    payload = _granted_pwsr().to_dict()
    payload["reason_code"] = "newly_invented"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=payload, schema=schema)


# ---------------------------------------------------------------------------
# FleetPlanResult
# ---------------------------------------------------------------------------


def test_fleet_plan_result_to_dict_validates(tmp_path: Path) -> None:
    schema = _load("fleet_plan_result_v1.schema.json")
    pwsr_schema = _load("plan_with_scheduler_result_v1.schema.json")
    # Inline the per-agent schema so the $ref resolves against the test fixture.
    schema = dict(schema)
    schema["properties"] = dict(schema["properties"])
    schema["properties"]["results"] = {
        "type": "array",
        "items": pwsr_schema,
    }

    fpr = FleetPlanResult(results=[_granted_pwsr(), _denied_pwsr()])
    payload = fpr.to_dict()
    jsonschema.validate(instance=payload, schema=schema)
    assert payload["all_granted"] is False

    fpr_all = FleetPlanResult(results=[_granted_pwsr()])
    assert fpr_all.to_dict()["all_granted"] is True


def test_fleet_plan_result_empty_is_not_all_granted() -> None:
    fpr = FleetPlanResult(results=[])
    # Matches the dataclass property's documented behavior: an empty
    # fleet is not "all_granted" because there's nothing to be granted.
    assert fpr.to_dict()["all_granted"] is False


# ---------------------------------------------------------------------------
# ConflictExplanation
# ---------------------------------------------------------------------------


def test_conflict_explanation_to_dict_validates() -> None:
    schema = _load("conflict_explanation_v1.schema.json")
    ce = ConflictExplanation(
        blocked_agent_id="robotB",
        reason_code="reservation_conflict",
        blocking_agents=("robotA", "robotC"),
        blocking_resources=("corridor", "elevator"),
        detail="elevator overlap 10:02-10:05",
    )
    payload = ce.to_dict()
    jsonschema.validate(instance=payload, schema=schema)
    # Tuples become lists for JSON.
    assert isinstance(payload["blocking_agents"], list)
    assert payload["blocking_agents"] == ["robotA", "robotC"]


# ---------------------------------------------------------------------------
# ResolveTrace
# ---------------------------------------------------------------------------


def _tiny_graph() -> TopologyGraph:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="Alpha", type="room", pose=Pose2D(0.0, 0.0)))
    g.add_node(TopologyNode(id="b", label="Beta", type="room", pose=Pose2D(1.0, 0.0)))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable"))
    return g


def _trace_no_clarification() -> LLMResolveResult:
    g = _tiny_graph()
    a = g.get_node("a")
    b = g.get_node("b")
    cands = [
        GoalCandidate(node_id="a", node=a, score=2.0, reasons=["label token: alpha"]),
        GoalCandidate(node_id="b", node=b, score=0.5, reasons=[]),
    ]
    return LLMResolveResult(
        query="alpha",
        candidates=cands,
        base_candidates=cands,
        llm_pick="a",
        llm_reason="alpha label is an exact match",
        raw_response="Top match: a\nReason: alpha label is an exact match",
        used_fallback=False,
        embedding_scores={"a": 0.91, "b": 0.42},
        clarification=None,
    )


def _trace_with_clarification() -> LLMResolveResult:
    g = _tiny_graph()
    a = g.get_node("a")
    b = g.get_node("b")
    cands = [
        GoalCandidate(node_id="a", node=a, score=1.0, reasons=[]),
        GoalCandidate(node_id="b", node=b, score=0.9, reasons=[]),
    ]
    return LLMResolveResult(
        query="the room",
        candidates=cands,
        base_candidates=cands,
        llm_pick=None,
        llm_reason=None,
        raw_response="Clarify: which room?",
        used_fallback=True,
        embedding_scores={},
        clarification=ClarificationQuestion(
            question="The query matched 2 candidates with near-equal scores: a, b. Which one did you mean?",
            candidates=tuple(cands),
        ),
    )


def test_resolve_trace_to_dict_validates_no_clarification() -> None:
    schema = _load("resolve_trace_v1.schema.json")
    payload = _trace_no_clarification().to_dict()
    jsonschema.validate(instance=payload, schema=schema)
    assert payload["clarification"] is None
    assert payload["embedding_scores"] == {"a": 0.91, "b": 0.42}


def test_resolve_trace_to_dict_validates_with_clarification() -> None:
    schema = _load("resolve_trace_v1.schema.json")
    payload = _trace_with_clarification().to_dict()
    jsonschema.validate(instance=payload, schema=schema)
    assert payload["clarification"] is not None
    assert payload["clarification"]["candidates"][0]["node_id"] == "a"


def test_resolve_trace_unknown_field_rejected() -> None:
    schema = _load("resolve_trace_v1.schema.json")
    payload = _trace_no_clarification().to_dict()
    payload["secret"] = "leaked"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=payload, schema=schema)


# ---------------------------------------------------------------------------
# Cross-schema consistency: reason_code enum stays a single closed set
# ---------------------------------------------------------------------------


def test_reason_code_enum_matches_across_schemas() -> None:
    """PlanWithSchedulerResult and ConflictExplanation must dispatch on
    the same closed set of reason codes — the docs are explicit about
    this and the BnB explanation mirrors the admission code 1:1."""
    pwsr = _load("plan_with_scheduler_result_v1.schema.json")
    ce = _load("conflict_explanation_v1.schema.json")
    pwsr_enum = pwsr["properties"]["reason_code"]["enum"]
    ce_enum = ce["properties"]["reason_code"]["enum"]
    assert pwsr_enum == ce_enum, (
        f"reason_code enum drift: PlanWithSchedulerResult={pwsr_enum} vs "
        f"ConflictExplanation={ce_enum}"
    )
