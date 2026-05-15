"""Tests for preference_aware (soft per-edge preference scores)."""

from __future__ import annotations

import json

import pytest

from semantic_toponav.cli.main import main as cli_main
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.planner import (
    avoid_restricted,
    compose_costs,
    plan_astar,
    preference_aware,
)


def _diamond_with_preferences() -> TopologyGraph:
    """a -- b -- d (cost 1+1, "scenic" route); a -- c -- d (cost 5+5).

    The fast route is plain. The slow route is tagged scenic on its
    edges so a strong scenic preference can flip the planner over.
    """
    g = TopologyGraph()
    for nid in "abcd":
        g.add_node(TopologyNode(id=nid, label=nid.upper(), type="room", pose=Pose2D(0, 0)))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="bd", source="b", target="d", type="traversable", cost=1.0))
    g.add_edge(
        TopologyEdge(
            id="ac",
            source="a",
            target="c",
            type="traversable",
            cost=5.0,
            properties={"preferences": {"scenic": 1.0}},
        )
    )
    g.add_edge(
        TopologyEdge(
            id="cd",
            source="c",
            target="d",
            type="traversable",
            cost=5.0,
            properties={"preferences": {"scenic": 1.0}},
        )
    )
    return g


def test_positive_weight_reduces_cost_for_tagged_edge() -> None:
    g = _diamond_with_preferences()
    # Without preferences the fast route a-b-d (cost 2) beats a-c-d (10).
    base = plan_astar(g, "a", "d")
    assert base == ["a", "b", "d"]

    # A strong scenic preference brings ac/cd down enough to win.
    cost = preference_aware(g, preferences={"scenic": 0.95})
    # Tagged edges drop to 5.0 * max(0.1, 1.0 - 0.95) = 5.0 * 0.1 = 0.5
    assert cost(g.get_edge("ac")) == pytest.approx(0.25, abs=1e-9) or cost(g.get_edge("ac")) <= 1.0
    path = plan_astar(g, "a", "d", cost_fn=cost)
    assert path == ["a", "c", "d"]


def test_negative_weight_penalizes_tagged_edges() -> None:
    g = _diamond_with_preferences()
    cost = preference_aware(g, preferences={"scenic": -0.5})
    # Tagged edges: 5.0 * (1.0 - (-0.5 * 1.0)) = 5.0 * 1.5 = 7.5; untagged unchanged.
    assert cost(g.get_edge("ac")) == pytest.approx(7.5, abs=1e-9)
    assert cost(g.get_edge("ab")) == 1.0


def test_zero_weight_is_identity() -> None:
    g = _diamond_with_preferences()
    cost = preference_aware(g, preferences={"scenic": 0.0})
    for eid in ("ab", "bd", "ac", "cd"):
        assert cost(g.get_edge(eid)) == g.get_edge(eid).cost


def test_missing_edge_preferences_defaults_to_zero() -> None:
    g = _diamond_with_preferences()
    # ab/bd have no preferences property at all; should not error.
    cost = preference_aware(g, preferences={"scenic": 0.5})
    assert cost(g.get_edge("ab")) == 1.0
    assert cost(g.get_edge("bd")) == 1.0


def test_missing_key_on_edge_contributes_zero() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="A", type="room", pose=Pose2D(0, 0)))
    g.add_node(TopologyNode(id="b", label="B", type="room", pose=Pose2D(0, 0)))
    g.add_edge(
        TopologyEdge(
            id="e",
            source="a",
            target="b",
            type="traversable",
            cost=2.0,
            properties={"preferences": {"scenic": 1.0}},  # no "crowded" key
        )
    )
    # Caller asks for crowded too; the missing key just doesn't contribute.
    cost = preference_aware(g, preferences={"scenic": 0.5, "crowded": -0.5})
    # score = 0.5 * 1.0 + (-0.5) * 0 = 0.5 -> multiplier 0.5
    assert cost(g.get_edge("e")) == pytest.approx(1.0, abs=1e-9)


def test_multi_dimensional_preferences_compose() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="A", type="room", pose=Pose2D(0, 0)))
    g.add_node(TopologyNode(id="b", label="B", type="room", pose=Pose2D(0, 0)))
    g.add_edge(
        TopologyEdge(
            id="e",
            source="a",
            target="b",
            type="traversable",
            cost=10.0,
            properties={"preferences": {"scenic": 0.8, "crowded": 0.6}},
        )
    )
    # score = 1.0 * 0.8 + (-1.0) * 0.6 = 0.2 -> multiplier 0.8 -> cost 8.0
    cost = preference_aware(g, preferences={"scenic": 1.0, "crowded": -1.0})
    assert cost(g.get_edge("e")) == pytest.approx(8.0, abs=1e-9)


def test_multiplier_clamps_at_min_and_max() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="A", type="room", pose=Pose2D(0, 0)))
    g.add_node(TopologyNode(id="b", label="B", type="room", pose=Pose2D(0, 0)))
    g.add_edge(
        TopologyEdge(
            id="e",
            source="a",
            target="b",
            type="traversable",
            cost=10.0,
            properties={"preferences": {"scenic": 1.0}},
        )
    )
    # Score = 100 -> raw multiplier -99 -> clamped to min 0.1 -> cost 1.0
    cost_hi = preference_aware(g, preferences={"scenic": 100.0})
    assert cost_hi(g.get_edge("e")) == pytest.approx(1.0, abs=1e-9)
    # Score = -100 -> raw multiplier 101 -> clamped to max 10.0 -> cost 100.0
    cost_lo = preference_aware(g, preferences={"scenic": -100.0})
    assert cost_lo(g.get_edge("e")) == pytest.approx(100.0, abs=1e-9)


def test_custom_clamp_overrides() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="A", type="room", pose=Pose2D(0, 0)))
    g.add_node(TopologyNode(id="b", label="B", type="room", pose=Pose2D(0, 0)))
    g.add_edge(
        TopologyEdge(
            id="e",
            source="a",
            target="b",
            type="traversable",
            cost=10.0,
            properties={"preferences": {"scenic": 1.0}},
        )
    )
    # Larger floor: multiplier capped at 0.5, so cost stays at 5.0 not 1.0.
    cost = preference_aware(g, preferences={"scenic": 1.0}, min_multiplier=0.5)
    assert cost(g.get_edge("e")) == pytest.approx(5.0, abs=1e-9)


def test_composes_with_avoid_restricted() -> None:
    g = _diamond_with_preferences()
    g.get_edge("ac").type = "restricted"
    g.get_edge("cd").type = "restricted"
    # Even with strong scenic pref, avoid_restricted should still block ac/cd.
    cost = compose_costs(
        avoid_restricted,
        preference_aware(g, preferences={"scenic": 1.0}),
    )
    path = plan_astar(g, "a", "d", cost_fn=cost)
    assert path == ["a", "b", "d"]


def test_custom_property_key() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="A", type="room", pose=Pose2D(0, 0)))
    g.add_node(TopologyNode(id="b", label="B", type="room", pose=Pose2D(0, 0)))
    g.add_edge(
        TopologyEdge(
            id="e",
            source="a",
            target="b",
            type="traversable",
            cost=2.0,
            properties={"user_tags": {"liked": 1.0}},
        )
    )
    cost = preference_aware(
        g, preferences={"liked": 0.5}, preference_property="user_tags"
    )
    assert cost(g.get_edge("e")) == pytest.approx(1.0, abs=1e-9)


def test_invalid_weight_type_raises() -> None:
    g = _diamond_with_preferences()
    with pytest.raises(TypeError, match="weight"):
        preference_aware(g, preferences={"scenic": "loud"})  # type: ignore[dict-item]


def test_invalid_key_type_raises() -> None:
    g = _diamond_with_preferences()
    with pytest.raises(TypeError, match="key"):
        preference_aware(g, preferences={123: 1.0})  # type: ignore[dict-item]


def test_invalid_clamp_raises() -> None:
    g = _diamond_with_preferences()
    with pytest.raises(ValueError, match="min_multiplier"):
        preference_aware(g, preferences={"scenic": 1.0}, min_multiplier=0)
    with pytest.raises(ValueError, match="max_multiplier"):
        preference_aware(
            g, preferences={"scenic": 1.0}, min_multiplier=2.0, max_multiplier=1.0
        )


def test_malformed_edge_preferences_raises() -> None:
    g = _diamond_with_preferences()
    g.get_edge("ac").properties["preferences"] = "not-a-dict"
    cost = preference_aware(g, preferences={"scenic": 0.5})
    with pytest.raises(ValueError, match="must be a mapping"):
        cost(g.get_edge("ac"))


def test_non_numeric_edge_pref_value_raises() -> None:
    g = _diamond_with_preferences()
    g.get_edge("ac").properties["preferences"] = {"scenic": "very"}
    cost = preference_aware(g, preferences={"scenic": 0.5})
    with pytest.raises(ValueError, match="must be numeric"):
        cost(g.get_edge("ac"))


def _diamond_with_node_preferences() -> TopologyGraph:
    """a -- b -- d (cost 1+1); a -- c -- d (cost 5+5). Node c is "scenic".

    No edge carries a preferences property — only the c node does.
    """
    g = TopologyGraph()
    for nid in "abd":
        g.add_node(TopologyNode(id=nid, label=nid.upper(), type="room", pose=Pose2D(0, 0)))
    g.add_node(
        TopologyNode(
            id="c",
            label="C",
            type="room",
            pose=Pose2D(0, 0),
            properties={"preferences": {"scenic": 1.0}},
        )
    )
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="bd", source="b", target="d", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="ac", source="a", target="c", type="traversable", cost=5.0))
    g.add_edge(TopologyEdge(id="cd", source="c", target="d", type="traversable", cost=5.0))
    return g


def test_node_default_applies_to_incident_edges() -> None:
    g = _diamond_with_node_preferences()
    # Edge ac touches c (scenic=1.0); a has no pref -> skipped from avg.
    # avg over [1.0] = 1.0; score = 1.0; raw mult = 0.0 -> clamped to 0.1
    # -> cost 5.0 * 0.1 = 0.5
    cost = preference_aware(g, preferences={"scenic": 1.0})
    assert cost(g.get_edge("ac")) == pytest.approx(0.5, abs=1e-9)
    assert cost(g.get_edge("cd")) == pytest.approx(0.5, abs=1e-9)
    # ab/bd touch no scenic node -> unchanged.
    assert cost(g.get_edge("ab")) == 1.0
    assert cost(g.get_edge("bd")) == 1.0


def test_node_default_with_explicit_zero_neighbor_dilutes() -> None:
    """Explicit scenic=0.0 on the neighbor counts toward the average."""
    g = _diamond_with_node_preferences()
    g.get_node("a").properties["preferences"] = {"scenic": 0.0}
    # avg(1.0 from c, 0.0 from a) = 0.5; score = 0.5; mult = 0.5 -> cost 2.5
    cost = preference_aware(g, preferences={"scenic": 1.0})
    assert cost(g.get_edge("ac")) == pytest.approx(2.5, abs=1e-9)


def test_node_default_averages_both_endpoints() -> None:
    g = TopologyGraph()
    g.add_node(
        TopologyNode(
            id="a", label="A", type="room", pose=Pose2D(0, 0),
            properties={"preferences": {"scenic": 1.0}},
        )
    )
    g.add_node(
        TopologyNode(
            id="b", label="B", type="room", pose=Pose2D(0, 0),
            properties={"preferences": {"scenic": 0.4}},
        )
    )
    g.add_edge(TopologyEdge(id="e", source="a", target="b", type="traversable", cost=10.0))
    cost = preference_aware(g, preferences={"scenic": 1.0})
    # average = (1.0 + 0.4) / 2 = 0.7 -> multiplier 0.3 -> cost 3.0
    assert cost(g.get_edge("e")) == pytest.approx(3.0, abs=1e-9)


def test_edge_preferences_override_node_defaults_per_key() -> None:
    g = _diamond_with_node_preferences()
    # Override on the ac edge: scenic explicitly 0.0 — node default ignored.
    g.get_edge("ac").properties["preferences"] = {"scenic": 0.0}
    cost = preference_aware(g, preferences={"scenic": 1.0})
    assert cost(g.get_edge("ac")) == 5.0  # unchanged
    # cd still inherits scenic=1.0 from c -> clamped to 0.1 multiplier.
    assert cost(g.get_edge("cd")) == pytest.approx(0.5, abs=1e-9)


def test_edge_and_node_defaults_are_per_key_independent() -> None:
    """Edge can specify one key while another falls back to node default."""
    g = TopologyGraph()
    g.add_node(
        TopologyNode(
            id="a", label="A", type="room", pose=Pose2D(0, 0),
            properties={"preferences": {"crowded": 1.0}},
        )
    )
    g.add_node(TopologyNode(id="b", label="B", type="room", pose=Pose2D(0, 0)))
    g.add_edge(
        TopologyEdge(
            id="e", source="a", target="b", type="traversable", cost=10.0,
            properties={"preferences": {"scenic": 1.0}},  # crowded not set
        )
    )
    cost = preference_aware(g, preferences={"scenic": 1.0, "crowded": -1.0})
    # scenic: edge 1.0 (edge wins); crowded: avg over [a's 1.0] = 1.0
    # score = 1.0 * 1.0 + (-1.0) * 1.0 = 0.0 -> multiplier 1.0 -> cost 10.0
    assert cost(g.get_edge("e")) == pytest.approx(10.0, abs=1e-9)


def test_use_node_defaults_false_ignores_node_preferences() -> None:
    g = _diamond_with_node_preferences()
    cost = preference_aware(g, preferences={"scenic": 1.0}, use_node_defaults=False)
    # ac/cd have no edge prefs -> contribute 0, no discount.
    assert cost(g.get_edge("ac")) == 5.0
    assert cost(g.get_edge("cd")) == 5.0


def test_node_defaults_flip_route_under_strong_pref() -> None:
    g = _diamond_with_node_preferences()
    # node default for ac/cd is scenic=1.0 (only c has the key) -> raw
    # multiplier 0.0 -> clamped to floor 0.1 -> ac/cd cost 0.5 each ->
    # total 1.0 < 2.0 (ab-bd). Route flips to the scenic side.
    cost = preference_aware(g, preferences={"scenic": 1.0})
    path = plan_astar(g, "a", "d", cost_fn=cost)
    assert path == ["a", "c", "d"]


def test_malformed_node_preferences_raises_at_construction() -> None:
    g = _diamond_with_node_preferences()
    g.get_node("c").properties["preferences"] = "not-a-dict"
    with pytest.raises(ValueError, match="must be a mapping"):
        preference_aware(g, preferences={"scenic": 1.0})


def test_non_numeric_node_preference_value_raises() -> None:
    g = _diamond_with_node_preferences()
    g.get_node("c").properties["preferences"] = {"scenic": "very"}
    with pytest.raises(ValueError, match="must be numeric"):
        preference_aware(g, preferences={"scenic": 1.0})


def test_node_default_with_custom_property_key() -> None:
    g = TopologyGraph()
    g.add_node(
        TopologyNode(
            id="a", label="A", type="room", pose=Pose2D(0, 0),
            properties={"user_tags": {"liked": 1.0}},
        )
    )
    g.add_node(TopologyNode(id="b", label="B", type="room", pose=Pose2D(0, 0)))
    g.add_edge(TopologyEdge(id="e", source="a", target="b", type="traversable", cost=4.0))
    cost = preference_aware(
        g, preferences={"liked": 1.0}, preference_property="user_tags"
    )
    # Only a carries the key -> avg over [1.0] = 1.0; score 1.0;
    # raw mult 0.0 -> clamped to 0.1 -> cost 4.0 * 0.1 = 0.4
    assert cost(g.get_edge("e")) == pytest.approx(0.4, abs=1e-9)


def test_cli_prefer_flips_route_to_scenic(tmp_path, capsys) -> None:
    yaml = tmp_path / "g.yaml"
    yaml.write_text(
        """version: 1
metadata: {name: t}
nodes:
  - {id: a, label: A, type: room, pose: {x: 0, y: 0, yaw: 0, frame_id: map}}
  - {id: b, label: B, type: room, pose: {x: 1, y: 0, yaw: 0, frame_id: map}}
  - {id: c, label: C, type: room, pose: {x: 1, y: 1, yaw: 0, frame_id: map}}
  - {id: d, label: D, type: room, pose: {x: 2, y: 0, yaw: 0, frame_id: map}}
edges:
  - {id: ab, source: a, target: b, type: traversable, cost: 1.0}
  - {id: bd, source: b, target: d, type: traversable, cost: 1.0}
  - {id: ac, source: a, target: c, type: traversable, cost: 5.0, properties: {preferences: {scenic: 1.0}}}
  - {id: cd, source: c, target: d, type: traversable, cost: 5.0, properties: {preferences: {scenic: 1.0}}}
""",
        encoding="utf-8",
    )

    rc = cli_main(["plan", str(yaml), "a", "d", "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert json.loads(out)["path"] == ["a", "b", "d"]

    rc = cli_main([
        "plan", str(yaml), "a", "d",
        "--prefer", "scenic:0.95",
        "--format", "json",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert json.loads(out)["path"] == ["a", "c", "d"]


def test_cli_prefer_default_weight_is_one(tmp_path, capsys) -> None:
    yaml = tmp_path / "g.yaml"
    yaml.write_text(
        """version: 1
metadata: {name: t}
nodes:
  - {id: a, label: A, type: room, pose: {x: 0, y: 0, yaw: 0, frame_id: map}}
  - {id: b, label: B, type: room, pose: {x: 1, y: 0, yaw: 0, frame_id: map}}
  - {id: c, label: C, type: room, pose: {x: 1, y: 1, yaw: 0, frame_id: map}}
  - {id: d, label: D, type: room, pose: {x: 2, y: 0, yaw: 0, frame_id: map}}
edges:
  - {id: ab, source: a, target: b, type: traversable, cost: 1.0}
  - {id: bd, source: b, target: d, type: traversable, cost: 1.0}
  - {id: ac, source: a, target: c, type: traversable, cost: 5.0, properties: {preferences: {scenic: 1.0}}}
  - {id: cd, source: c, target: d, type: traversable, cost: 5.0, properties: {preferences: {scenic: 1.0}}}
""",
        encoding="utf-8",
    )
    # Weight defaults to 1.0 -> multiplier clamps to 0.1 -> ac/cd cost 0.5 each.
    rc = cli_main(["plan", str(yaml), "a", "d", "--prefer", "scenic", "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert json.loads(out)["path"] == ["a", "c", "d"]


def test_cli_prefer_malformed_weight_errors(tmp_path, capsys) -> None:
    yaml = tmp_path / "g.yaml"
    yaml.write_text(
        """version: 1
metadata: {name: t}
nodes:
  - {id: a, label: A, type: room, pose: {x: 0, y: 0, yaw: 0, frame_id: map}}
  - {id: b, label: B, type: room, pose: {x: 1, y: 0, yaw: 0, frame_id: map}}
edges:
  - {id: ab, source: a, target: b, type: traversable, cost: 1.0}
""",
        encoding="utf-8",
    )
    rc = cli_main(["plan", str(yaml), "a", "b", "--prefer", "scenic:loud"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "weight" in err and "loud" in err
