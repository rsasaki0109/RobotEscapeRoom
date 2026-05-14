"""Planner-related exceptions."""


class PlanningError(Exception):
    """Raised when planning fails for a non-graph reason."""


class NoPathError(PlanningError):
    """Raised when no path exists between start and goal."""
