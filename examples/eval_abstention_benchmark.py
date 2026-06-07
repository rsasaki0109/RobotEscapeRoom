"""Abstention benchmark for NL→node grounding, broken out by category.

Most navigation benchmarks measure *reaching* a goal; none (per the
landscape survey in ``docs/related_work.md``) measure whether a resolver
correctly **abstains** on a query it cannot ground. This script does, with
a taxonomy — answerable / unresolvable / false_premise / out_of_map — so
the report shows *where* the deterministic floor wrongly resolves instead
of abstaining.

The headline: the bag-of-words floor leaks on `out_of_map` /
`false_premise` exactly where a stray token (`room`, `kitchen`) pulls a
real label up ("the server *room*" → the meeting room) — the abstention
axis the LLM-augmented path is meant to harden.

Deterministic and backend-free. Run from the repository root:

    python examples/eval_abstention_benchmark.py
"""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.eval.abstention import (
    abstention_report_markdown,
    load_abstention_corpus,
    run_abstention_benchmark,
)
from semantic_toponav.graph.serialization import load_graph

ROOT = Path(__file__).parent.parent
GRAPH = ROOT / "examples" / "multi_floor_office.yaml"
CORPUS = ROOT / "tests" / "fixtures" / "grounding" / "abstention_taxonomy.yaml"


def main() -> None:
    graph = load_graph(str(GRAPH))
    cases = load_abstention_corpus(CORPUS)
    report = run_abstention_benchmark(graph, cases)
    print(abstention_report_markdown(report))


if __name__ == "__main__":
    main()
