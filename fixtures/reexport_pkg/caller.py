"""Caller that imports both symbols from the package's public surface.

This is the file the resolver must handle:
  - `from reexport_pkg import compute` --> single-level re-export
  - `from reexport_pkg import helper`  --> two-level re-export

Riftline should resolve both calls to their true defining modules, not to
the __init__.py that re-exports them.
"""
from reexport_pkg import compute
from reexport_pkg import helper


def use_compute(x):
    """Calls compute() via the package's public surface (single-level re-export)."""
    return compute(x)


def use_helper(x):
    """Calls helper() via the package's public surface (two-level re-export)."""
    return helper(x)
