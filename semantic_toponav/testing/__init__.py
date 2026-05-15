"""Test helpers and shared fixtures for semantic-toponav adapters.

This subpackage is shipped as part of the installed wheel (unlike the
top-level ``tests/`` directory, which is excluded). Adapter authors —
e.g. the out-of-tree ``semantic-toponav-mast3r`` package implementing
:class:`~semantic_toponav.encoders.AlignedRgbSource` — can import the
conformance suites from :mod:`semantic_toponav.testing.conformance` to
check that their implementations honor the documented Protocol
contracts.
"""
