<!--
Thanks for the PR! A couple of pointers:
- One logical change per PR. Refactors, formatting passes, and feature
  work should land separately so reviewers can reason about them in
  isolation.
- New mandatory dependencies are not accepted. Put third-party packages
  behind a new `[extra]` in `pyproject.toml` and gate imports/tests on
  their presence.
- See `CONTRIBUTING.md` for the full conventions.
-->

## Summary

<!-- One or two sentences: what this PR does and why. -->

## Changes

<!-- Bulleted list of the user-visible changes. Skip implementation
detail unless it affects the public surface. -->

-
-

## Test plan

- [ ] `pytest` passes locally (note any tests that skipped due to optional deps)
- [ ] `ruff check .` passes
- [ ] New public API documented in `docs/interfaces.md`
- [ ] User-visible feature mentioned in `README.md` if it belongs on the tour
- [ ] No new mandatory dependencies (use `[extra]` + lazy import + `pytest.importorskip`)

## Related issues

<!-- e.g. Closes #123, Fixes #456 -->
