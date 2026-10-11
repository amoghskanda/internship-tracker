"""Data models returned by the collector."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

VisaSponsorship = Literal["provided", "not provided", "not stated"]


@dataclass
class InternshipRecord:
    """One internship posting in the tracker output."""

    company: str
    role: str
    url: str
    job_id: str
    location: str
    jd: str
    skills: list[str]
    visa_sponsorship: VisaSponsorship
    visa_evidence: str
    source_url: str
    discovered_at: str
    last_seen: str
    date_posted: str = ""
    season: str = "Summer 2027"
    domain: str = "Other"
    source: str = ""
    enrichment_error: str = ""

    def __post_init__(self) -> None:
        if self.visa_sponsorship not in {"provided", "not provided", "not stated"}:
            raise ValueError(f"Unsupported visa sponsorship value: {self.visa_sponsorship}")
        self.skills = list(dict.fromkeys(skill.strip() for skill in self.skills if skill.strip()))

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class SourceHealth:
    """Fetch status for a configured source or employer board."""

    source: str
    source_url: str
    fetched_at: str
    status: Literal["ok", "error"]
    records: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class CollectionResult:
    """JSON-ready collector response."""

    records: list[InternshipRecord] = field(default_factory=list)
    source_health: list[SourceHealth] = field(default_factory=list)
    collected_at: str = ""

    def to_dict(self) -> dict[str, object]:
        records = [record.to_dict() for record in self.records]
        return {
            # Keep both names so the feed can be consumed by the scheduler and
            # by the Excel sync's records-compatible input path.
            "jobs": records,
            "records": records,
            "source_health": [health.to_dict() for health in self.source_health],
            "updated_at": self.collected_at,
            "collected_at": self.collected_at,
        }
