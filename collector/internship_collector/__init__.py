"""Public interface for the Summer 2027 internship collector."""

from .collector import Collector, CollectorConfig, collect_default
from .models import CollectionResult, InternshipRecord, SourceHealth
from .normalization import canonicalize_url, deduplicate_records
from .sources import AshbyAdapter, GreenhouseAdapter, SimplifyAdapter

__all__ = [
    "CollectionResult",
    "Collector",
    "CollectorConfig",
    "InternshipRecord",
    "SourceHealth",
    "AshbyAdapter",
    "canonicalize_url",
    "collect_default",
    "deduplicate_records",
    "GreenhouseAdapter",
    "SimplifyAdapter",
]
