"""Defines helper() -- the real home of the two-level re-export target.

Chain:
  reexport_pkg/__init__.py  (from .subpkg import helper)
    -> reexport_pkg/subpkg/__init__.py  (from .utils import helper)
      -> reexport_pkg/subpkg/utils.py   <-- defined here
"""


def helper(x):
    """Double x.  Two-level re-export target."""
    return x * 2
