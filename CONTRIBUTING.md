# Contributing to semantic-toponav

Thanks for your interest in `semantic-toponav`! This document is a quick
orientation for landing changes — what the project values, how to get a
dev environment running, and the conventions PRs are expected to follow.

## Project scope

A short reminder of what this project *is* and *isn't*, so feature
proposals can be assessed against a stable target:

- **In scope:** the global, semantic, graph-level planning layer — graph
  definition / I/O, A* and Dijkstra over semantic edges, semantic cost
  functions, semantic waypoint generation, occupancy / trajectory / bag
  ingestion, and the thin ROS2 adapter package.
- **Out of scope:** low-level motion control, obstacle avoidance, SLAM,
  dense occupancy planning, behavior trees. These belong in Nav2 /
  Autoware / your own local planner.

When in doubt about whether something fits, open a discussion or draft
issue *before* writing code — it's much cheaper to align early.

## Development setup

```bash
git clone https://github.com/rsasaki0109/semantic-toponav.git
cd semantic-toponav

# Editable install with all dev/optional extras.
pip install -e '.[dev,viz,viz_web,map]'
```

The `[map]` extra pulls `numpy` + `scikit-image` (occupancy grids); the
`[viz_web]` extra pulls `pyvis` (interactive HTML viewer). They are
optional — tests gated on them will skip cleanly when absent.

ROS2 / `rosbag2_py` are *never* a build dependency. The relevant tests
gate themselves on `pytest.importorskip("rosbag2_py")` and skip when no
ROS2 environment is sourced.

## Running tests and linters

```bash
# Full test suite (skipped tests come from absent optional deps).
pytest

# Lint.
ruff check .

# Run a single test file.
pytest tests/test_planner_astar.py -v
```

Both `pytest` and `ruff` must pass on PRs. CI runs the same commands
under Python 3.10 / 3.11 / 3.12.

## Branch & commit conventions

- **Branch name:** `feat/<topic>`, `fix/<topic>`, `chore/<topic>`,
  `docs/<topic>`. Keep it short and lowercase-kebab.
- **Commit message:** first line is an imperative sentence under ~70
  chars (`Add foo to bar`, not `Added foo` or `fixing bar`). Use the
  body to explain *why* the change is needed when it isn't obvious from
  the diff.
- **One logical change per PR.** Refactors, formatting passes, and
  feature work should land separately so reviewers can reason about
  them in isolation.

## Pull request checklist

Before opening a PR:

- [ ] `pytest` passes locally (note any tests that skipped due to
      optional deps, so reviewers know what wasn't exercised).
- [ ] `ruff check .` passes.
- [ ] New public APIs are documented in `docs/interfaces.md`.
- [ ] User-visible changes are mentioned in `README.md` if they belong
      on the top-level tour.
- [ ] No new mandatory dependencies. If you need a third-party package,
      put it behind a new `[extra]` in `pyproject.toml` and gate
      imports/tests on its presence.
- [ ] No generated artifacts in the diff (HTML viewer output, build
      directories, `__pycache__`, virtual envs, ...).

The PR template at `.github/PULL_REQUEST_TEMPLATE.md` mirrors this
checklist — fill it out rather than deleting it.

## Code style

- Python 3.10+ syntax (PEP 604 unions, `match`, etc.).
- Type hints on public functions and dataclasses.
- Prefer pure functions and dataclasses over classes-with-state.
- One module per concern; keep files small and self-explanatory.
- Reach for the standard library before adding a dependency.
- Match the style of the file you're editing; the codebase is small
  enough that consistency matters more than personal preference.

## Adding tests

Tests live in `tests/` and use plain `pytest` — no fixtures factories,
no class-based setup unless there's a real reason. Each test file
mirrors the module it tests (`test_planner_astar.py` covers
`semantic_toponav/planner/astar.py`, etc.).

For tests that need an optional dependency, gate the import at the top
of the file:

```python
import pytest
pytest.importorskip("pyvis")     # or rosbag2_py, matplotlib, ...

from semantic_toponav.visualization import save_interactive_html  # noqa: E402
```

Add the test file to the `per-file-ignores` list in `pyproject.toml`
under `[tool.ruff.lint.per-file-ignores]` so `E402` (module-level
imports below code) is silenced just for that file.

## Reporting bugs / requesting features

- Bugs: open an issue using the **Bug report** template. Please include
  the failing command/snippet, the actual output, and the expected
  output. A minimal reproducer that runs against the bundled examples
  is ideal.
- Features: open an issue using the **Feature request** template. State
  what you want to do *and* why the current API doesn't already let you
  do it — concrete use cases turn into better designs.

## License

By contributing you agree that your contributions are licensed under
the Apache License 2.0, the same as the rest of the project.
