# reexport_pkg/__init__.py
#
# Exposes two symbols via re-exports so callers can write:
#   from reexport_pkg import compute   # single-level re-export (compute lives in .core)
#   from reexport_pkg import helper    # two-level re-export  (helper lives in .subpkg.utils,
#                                      #   re-exported first by .subpkg/__init__.py)
#
# Neither symbol is *defined* here -- this file only shapes the public surface.

from .core import compute    # single-level: compute defined in reexport_pkg.core
from .subpkg import helper   # two-level:   helper re-exported by reexport_pkg.subpkg
