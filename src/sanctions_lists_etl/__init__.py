"""ETL pipeline for public sanctions lists.

Each list lives under ``sources/<name>/`` and exposes a ``SOURCE``
(:class:`~sanctions_lists_etl.base.Source`).  ``runner`` registers them and
drives them end to end; ``cli`` exposes them as ``sanctions-etl`` subcommands.
"""

from .base import Source, SourceResult
from .runner import available_sources, run_all, run_source

__version__ = "0.1.0"

__all__ = ["Source", "SourceResult", "available_sources", "run_all", "run_source"]
