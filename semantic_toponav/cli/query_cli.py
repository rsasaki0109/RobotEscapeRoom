"""CLI subcommands for semantic node queries (`find`, `nearest`)."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from semantic_toponav.cli.editor import _parse_props
from semantic_toponav.cli.llm_cli import add_llm_args, build_llm_backend_from_args
from semantic_toponav.graph.serialization import GraphLoadError, load_graph
from semantic_toponav.graph.types import GraphValidationError, TopologyNode
from semantic_toponav.query import (
    ClarificationAnswer,
    NoMatchError,
    find_nodes,
    llm_resolve_goal,
    nearest_node_by_graph_distance,
    nearest_node_by_pose,
    resolve_goal,
)


def _filters_from_args(args: argparse.Namespace) -> dict[str, Any]:
    props: dict[str, Any] | None = None
    if getattr(args, "prop", None):
        try:
            props = _parse_props(args.prop)
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from exc
        if not props:
            props = None
    return {
        "type": getattr(args, "type", None),
        "label_contains": getattr(args, "label_contains", None),
        "label_equals": getattr(args, "label_equals", None),
        "properties": props,
    }


def _node_summary(n: TopologyNode) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": n.id,
        "label": n.label,
        "type": n.type,
        "properties": dict(n.properties),
    }
    if n.pose is not None:
        out["pose"] = n.pose.to_dict()
    return out


def cmd_find(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        filters = _filters_from_args(args)
    except SystemExit as exc:
        print(str(exc.code), file=sys.stderr)
        return 2

    matches = find_nodes(graph, **filters)
    if args.format == "json":
        print(json.dumps([_node_summary(n) for n in matches], ensure_ascii=False, indent=2))
    else:
        if not matches:
            print("(no matches)")
        else:
            print(f"Matches ({len(matches)}):")
            for n in matches:
                pose_part = ""
                if n.pose is not None:
                    pose_part = f"  pose=({n.pose.x:.2f}, {n.pose.y:.2f})"
                print(
                    f"  {n.id:25s} type={n.type:14s} label={n.label!r}{pose_part}"
                )
    return 0


def cmd_nearest(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if (args.from_pose is None) == (args.from_node is None):
        print(
            "error: pass exactly one of --from-pose X Y or --from-node ID",
            file=sys.stderr,
        )
        return 2

    try:
        filters = _filters_from_args(args)
    except SystemExit as exc:
        print(str(exc.code), file=sys.stderr)
        return 2

    payload: dict[str, Any]
    try:
        if args.from_pose is not None:
            x, y = args.from_pose
            node = nearest_node_by_pose(graph, (x, y), **filters)
            payload = {"mode": "euclidean", "node": _node_summary(node)}
        else:
            node, path = nearest_node_by_graph_distance(
                graph, args.from_node, **filters
            )
            payload = {
                "mode": "graph_distance",
                "node": _node_summary(node),
                "path": path,
            }
    except NoMatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Nearest ({payload['mode']}):")
        n = payload["node"]
        print(f"  id    : {n['id']}")
        print(f"  type  : {n['type']}")
        print(f"  label : {n['label']!r}")
        if "pose" in n:
            print(f"  pose  : ({n['pose']['x']:.2f}, {n['pose']['y']:.2f})")
        if "path" in payload:
            print("  path  : " + " -> ".join(payload["path"]))
    return 0


def _build_query_encoder(args: argparse.Namespace):
    """Construct a query-encoder backend from --vlm-backend / --vlm-dim.

    Returns ``None`` when no backend was requested. Raises with a
    user-facing message when the requested backend can't be loaded
    (e.g. ``clip`` without the ``[vlm]`` extra installed).
    """
    name = getattr(args, "vlm_backend", None)
    if not name:
        return None
    try:
        from semantic_toponav.encoders.backends import CLIPBackend, HashingBackend
    except ImportError as exc:  # pragma: no cover - core has zero deps
        raise SystemExit(
            f"error: --vlm-backend requires the encoders module ({exc})"
        ) from exc
    if name == "hashing":
        return HashingBackend(dim=getattr(args, "vlm_dim", 32))
    if name == "clip":
        try:
            return CLIPBackend(
                model_name=getattr(args, "vlm_clip_model", "openai/clip-vit-base-patch32"),
                device=getattr(args, "vlm_clip_device", None),
            )
        except ImportError as exc:
            raise SystemExit(
                f"error: --vlm-backend clip requires the [vlm] extra ({exc})"
            ) from exc
    raise SystemExit(f"error: unknown --vlm-backend {name!r}")


def cmd_resolve(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    text = " ".join(args.text) if isinstance(args.text, list) else args.text

    try:
        backend = build_llm_backend_from_args(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        query_encoder = _build_query_encoder(args)
    except SystemExit as exc:
        print(exc.code, file=sys.stderr)
        return 2

    clarification: ClarificationAnswer | None = None
    if getattr(args, "clarify_with", None) or getattr(args, "clarify_free", None):
        clarification = ClarificationAnswer(
            chosen_id=getattr(args, "clarify_with", None),
            free_text=getattr(args, "clarify_free", None),
        )

    llm_result = None
    if backend is None:
        # Without an LLM backend, --vlm-backend has nothing to attach to.
        # Fall back to the deterministic resolver and tell the user.
        if query_encoder is not None:
            print(
                "warning: --vlm-backend is ignored without --llm-backend "
                "(the embedding scores are an LLM-prompt augmentation).",
                file=sys.stderr,
            )
        if clarification is not None:
            print(
                "warning: --clarify-with / --clarify-free are ignored "
                "without --llm-backend (clarification dialog is an "
                "LLM-rerank feature).",
                file=sys.stderr,
            )
        candidates = resolve_goal(graph, text, top_k=args.top_k)
    else:
        try:
            llm_result = llm_resolve_goal(
                graph, text, backend,
                top_k=args.top_k,
                query_encoder=query_encoder,
                clarification=clarification,
            )
        except ImportError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        candidates = llm_result.candidates

    if args.format == "json":
        payload: dict[str, object] = {
            "query": llm_result.query if llm_result is not None else text,
            "candidates": [
                {
                    "node_id": c.node_id,
                    "score": c.score,
                    "reasons": list(c.reasons),
                    "node": _node_summary(c.node),
                }
                for c in candidates
            ],
        }
        if llm_result is not None:
            payload["llm"] = {
                "pick": llm_result.llm_pick,
                "reason": llm_result.llm_reason,
                "used_fallback": llm_result.used_fallback,
                "raw_response": llm_result.raw_response,
                "embedding_scores": dict(llm_result.embedding_scores),
            }
            if llm_result.clarification is not None:
                q = llm_result.clarification
                payload["llm"]["clarification"] = {
                    "question": q.question,
                    "candidate_ids": [c.node_id for c in q.candidates],
                }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if not candidates:
            print("(no matches)")
        else:
            print(f"Candidates ({len(candidates)}):")
            for c in candidates:
                print(
                    f"  {c.node_id:25s} score={c.score:<5g} "
                    f"label={c.node.label!r} type={c.node.type}"
                )
                for reason in c.reasons:
                    print(f"      - {reason}")
            if llm_result is not None:
                tag = "fallback" if llm_result.used_fallback else "applied"
                print(
                    f"LLM rerank: {tag} "
                    f"(pick={llm_result.llm_pick!r})"
                )
                if llm_result.clarification is not None:
                    q = llm_result.clarification
                    print(f"Ambiguous: {q.question}")
                    candidate_ids = " ".join(c.node_id for c in q.candidates)
                    print(
                        f"  re-run with: --clarify-with <one of: "
                        f"{candidate_ids}>"
                    )
    return 0


def _add_filter_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--type", help="filter by node type")
    p.add_argument("--label-contains", help="case-insensitive substring match on label")
    p.add_argument("--label-equals", help="exact label match")
    p.add_argument(
        "--prop",
        action="append",
        metavar="KEY=VALUE",
        help="filter by property (repeatable; int/float/bool inferred)",
    )
    p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="output format (default: text)",
    )


def register_subcommands(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("find", help="list nodes matching semantic filters")
    p.add_argument("graph")
    _add_filter_args(p)
    p.set_defaults(func=cmd_find)

    p = sub.add_parser(
        "nearest",
        help="find the nearest matching node (Euclidean from --from-pose or "
        "graph-distance from --from-node)",
    )
    p.add_argument("graph")
    p.add_argument(
        "--from-pose",
        type=float,
        nargs=2,
        metavar=("X", "Y"),
        help="Euclidean reference pose",
    )
    p.add_argument(
        "--from-node",
        metavar="NODE_ID",
        help="graph-distance reference node",
    )
    _add_filter_args(p)
    p.set_defaults(func=cmd_nearest)

    p = sub.add_parser(
        "resolve",
        help="resolve a free-text goal (e.g. 'the second floor lab') to "
        "ranked candidate nodes",
    )
    p.add_argument("graph")
    p.add_argument(
        "text",
        nargs="+",
        help="natural-language description of the goal "
        "(multiple words are joined with spaces)",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="return at most this many candidates (default: 5)",
    )
    p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="output format (default: text)",
    )
    add_llm_args(p)
    p.add_argument(
        "--vlm-backend",
        choices=["hashing", "clip"],
        help=(
            "use a visual encoder to compute query-vs-node embedding "
            "similarity scores; the LLM prompt grows an "
            "`embedding_score=` column. Requires --llm-backend to be "
            "set too (the scores augment the LLM rerank, not the "
            "deterministic resolver)."
        ),
    )
    p.add_argument(
        "--vlm-dim", type=int, default=32,
        help="dimension for --vlm-backend hashing (default: 32)",
    )
    p.add_argument(
        "--vlm-clip-model",
        default="openai/clip-vit-base-patch32",
        help="HuggingFace model name for --vlm-backend clip",
    )
    p.add_argument(
        "--vlm-clip-device",
        help="device override for --vlm-backend clip (e.g. cuda, cpu)",
    )
    p.add_argument(
        "--clarify-with",
        metavar="NODE_ID",
        help=(
            "thread a previous turn's clarification answer (a specific "
            "node id from the prior clarification.candidate_ids list) "
            "back into the resolver. Narrows the candidate pool to the "
            "named node. Out-of-pool ids are ignored."
        ),
    )
    p.add_argument(
        "--clarify-free",
        metavar="TEXT",
        help=(
            "thread a free-text clarification ('the one on the second "
            "floor') back into the resolver. Appended to the original "
            "query before re-running."
        ),
    )
    p.set_defaults(func=cmd_resolve)
