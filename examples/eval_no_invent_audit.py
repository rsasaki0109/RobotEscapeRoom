"""Adversarial *no-invent* audit of the LLM-augmented resolver.

`llm_resolve_goal` lets an LLM re-rank the deterministic candidate pool
but never invent a node id. This script *proves* that as a runnable
regression: it replays a catalog of adversarial LLM replies (hallucinated
ids, real-but-out-of-pool ids, prompt-injection, payloads, substring /
case near-misses, multi-pick confusers) plus an out-of-pool clarification
pin, and reports the leak rate — the fraction of attacks that smuggled an
out-of-pool id into the output. A correct resolver scores 0.00.

It needs no model or API key (each attack reply is scripted through an
`EchoBackend`). Run from the repository root:

    python examples/eval_no_invent_audit.py
"""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.eval.no_invent import (
    no_invent_audit_markdown,
    run_no_invent_audit,
)
from semantic_toponav.graph.serialization import load_graph

ROOT = Path(__file__).parent.parent
GRAPH = ROOT / "examples" / "multi_floor_office.yaml"
QUERY = "executive office on 3F"


def main() -> None:
    graph = load_graph(str(GRAPH))
    report = run_no_invent_audit(graph, QUERY)
    print(no_invent_audit_markdown(report))
    print()
    status = "SAFE — no attack invented a destination" if report.all_safe else "LEAK DETECTED"
    print(f"{status}  (leak_rate = {report.leak_rate:.2f}, {report.n_attacks} attacks)")


if __name__ == "__main__":
    main()
