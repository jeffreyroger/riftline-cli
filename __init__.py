"""Riftline: know what breaks before you break it."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("riftline-cli")
except PackageNotFoundError:
    # Not installed (e.g. running from a raw checkout with no `pip install`).
    __version__ = "0+unknown"
