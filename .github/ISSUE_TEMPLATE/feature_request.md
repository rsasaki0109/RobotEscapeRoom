---
name: Feature request
about: Propose a new capability or API for `semantic-toponav`
title: "[FEATURE] "
labels: enhancement
assignees: ''
---

## Use case

<!--
What are you trying to do? Describe the real-world scenario, not just
the API you want. ("I'm building a guide robot that needs to revisit
rooms; the current planner has no way to express revisit preferences.")
-->

## What's missing today

<!--
What does the current API/CLI let you do, and where does it fall
short? Link to the relevant module/function if you can.
-->

## Proposed solution

<!--
Sketch the API or CLI shape you'd like. Pseudocode is fine.
If a downstream Nav2 / Autoware / behaviour-tree consumer is involved,
say how the new piece is supposed to interact with it.
-->

```python
# Example of what you'd like to write.
```

## Alternatives considered

<!--
Other approaches you thought about and why they don't fit (workarounds,
existing flags, separate package, ...).
-->

## Scope check

This project keeps a deliberate boundary: graph-level semantic planning
*only*. The local-execution side (Nav2, MPPI, controllers) is out of
scope. Does your proposal fit on the planning side?

- [ ] Yes, this is a graph/planner/waypoint feature.
- [ ] I'm not sure — happy to discuss.
