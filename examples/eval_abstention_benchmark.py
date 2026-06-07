"""Abstention benchmark for NL→node grounding, broken out by category.

Most navigation benchmarks measure *reaching* a goal; none (per the
landscape survey in ``docs/related_work.md``) measure whether a resolver
correctly **abstains** on a query it cannot ground. This script does, with
a taxonomy — answerable / unresolvable / false_premise / out_of_map — so
the report shows *where* the deterministic floor wrongly resolves instead
of abstaining.

The headline: the bag-of-words floor leaks on `out_of_map` /
`false_premise` exactly where a stray token (`room`, `kitchen`) pulls a
real label up ("the server *room*" → the meeting room) — and the
LLM-augmented path, once allowed to decline, closes those leaks
(`false_premise` fp 0.17 → 0.00, `out_of_map` fp 0.33 → 0.00).

Run from the repository root. By default it prints the deterministic
report *and* a deterministic-vs-LLM comparison, where the "LLM" path is a
recorded reference transcript replayed for reproducibility (no API key, no
network):

    python examples/eval_abstention_benchmark.py

To run the LLM path against a *real* model instead of the transcript:

    python examples/eval_abstention_benchmark.py --llm-backend ollama
    python examples/eval_abstention_benchmark.py --llm-backend anthropic
"""

from __future__ import annotations

import argparse
from pathlib import Path

from semantic_toponav.eval.abstention import (
    abstention_comparison_markdown,
    abstention_report_markdown,
    load_abstention_corpus,
    load_abstention_transcript,
    run_abstention_benchmark,
)
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.llm.backends import LLMBackend

ROOT = Path(__file__).parent.parent
GRAPH = ROOT / "examples" / "multi_floor_office.yaml"
CORPUS = ROOT / "tests" / "fixtures" / "grounding" / "abstention_taxonomy.yaml"
TRANSCRIPT = ROOT / "tests" / "fixtures" / "grounding" / "abstention_llm_transcript.yaml"


def _build_backend(kind: str, model: str | None) -> LLMBackend:
    if kind == "transcript":
        return load_abstention_transcript(TRANSCRIPT)
    if kind == "ollama":
        from semantic_toponav.llm.backends import OllamaBackend

        return OllamaBackend(model) if model else OllamaBackend()
    if kind == "anthropic":
        from semantic_toponav.llm.backends import AnthropicBackend

        return AnthropicBackend(model) if model else AnthropicBackend()
    raise ValueError(f"unknown backend {kind!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--llm-backend",
        choices=("transcript", "ollama", "anthropic"),
        default="transcript",
        help="LLM backend for the augmented path (default: recorded transcript).",
    )
    parser.add_argument(
        "--llm-model",
        default=None,
        help="Model id for the live backends (ollama / anthropic).",
    )
    args = parser.parse_args()

    graph = load_graph(str(GRAPH))
    cases = load_abstention_corpus(CORPUS)

    deterministic = run_abstention_benchmark(graph, cases)
    print(abstention_report_markdown(deterministic))
    print()

    backend = _build_backend(args.llm_backend, args.llm_model)
    llm = run_abstention_benchmark(graph, cases, backend=backend)
    print(abstention_comparison_markdown(deterministic, llm))


if __name__ == "__main__":
    main()
