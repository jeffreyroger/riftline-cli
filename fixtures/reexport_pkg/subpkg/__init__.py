# reexport_pkg/subpkg/__init__.py
#
# Second hop of the two-level re-export chain:
#   reexport_pkg/__init__.py  -> reexport_pkg.subpkg  -> reexport_pkg.subpkg.utils
#
# helper is defined in utils.py; we surface it here so reexport_pkg itself
# can re-export it from its own __init__.py.

from .utils import helper   # two-level: helper defined in reexport_pkg.subpkg.utils
