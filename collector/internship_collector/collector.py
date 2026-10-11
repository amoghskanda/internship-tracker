"""Collection orchestration and JSON-ready output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .models import CollectionResult, InternshipRecord, SourceHealth
from .normalization import deduplicate_records, utc_now
from .text import classify_domain
from .sources import (
    DEFAULT_ASHBY_BOARDS,
    DEFAULT_GREENHOUSE_BOARDS,
    AshbyAdapter,
    BrowserJobsAdapter,
    GreenhouseAdapter,
    HttpClient,
    JobrightAdapter,
    SimplifyAdapter,
)


@dataclass
class CollectorConfig:
    """Runtime filters and source settings."""

    season: str = "Summer 2027"
    country_filter: str | None = "US"
    include_remote_unknown: bool = False
    role_keywords: tuple[str, ...] = ()
    simplify_url: str = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md"
    greenhouse_boards: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_GREENHOUSE_BOARDS))
    ashby_boards: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_ASHBY_BOARDS))
    enrich_simplify: bool = True
    enrichment_workers: int = 8
    max_enrichment_requests: int = 400
    browser_jobs_path: str | None = None


class Collector:
    """Run configured adapters and return records plus per-source health."""

    def __init__(self, adapters: Sequence[Any], *, config: CollectorConfig | None = None) -> None:
        self.adapters = list(adapters)
        self.config = config or CollectorConfig()

    def run(self, *, now: str | None = None) -> CollectionResult:
        records: list[InternshipRecord] = []
        health: list[SourceHealth] = []
        run_now = now or utc_now()
        for adapter in self.adapters:
            try:
                result = adapter.run(now=run_now)
                records.extend(result.records)
                health.extend(result.health)
            except Exception as exc:
                source_name = getattr(adapter, "name", adapter.__class__.__name__.casefold())
                source_url = getattr(adapter, "readme_url", "")
                health.append(SourceHealth(source_name, source_url, run_now, "error", 0, f"{type(exc).__name__}: {exc}"))
        deduplicated = deduplicate_records(records)
        for record in deduplicated:
            record.domain = classify_domain(record.role, record.jd, record.skills)
        return CollectionResult(deduplicated, health, run_now)


def build_default_collector(config: CollectorConfig | None = None, *, client: Any | None = None) -> Collector:
    cfg = config or CollectorConfig()
    http = client or HttpClient()
    shared = {
        "season": cfg.season,
        "country_filter": cfg.country_filter,
        "include_remote_unknown": cfg.include_remote_unknown,
        "role_keywords": cfg.role_keywords,
    }
    adapters = [
        SimplifyAdapter(
            client=http,
            readme_url=cfg.simplify_url,
            enrich=cfg.enrich_simplify,
            enrichment_workers=cfg.enrichment_workers,
            max_enrichment_requests=cfg.max_enrichment_requests,
            **shared,
        ),
        GreenhouseAdapter(cfg.greenhouse_boards, client=http, **shared),
        AshbyAdapter(cfg.ashby_boards, client=http, **shared),
        JobrightAdapter(client=http, **shared),
    ]
    if cfg.browser_jobs_path:
        adapters.append(BrowserJobsAdapter(cfg.browser_jobs_path, **shared))
    return Collector(adapters, config=cfg)


def collect_default(config: CollectorConfig | None = None, *, client: Any | None = None, now: str | None = None) -> CollectionResult:
    return build_default_collector(config, client=client).run(now=now)
