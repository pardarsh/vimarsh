"""Vimarsh: attributed AI analysis of Indian parliamentary bills."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("vimarsh")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0"
