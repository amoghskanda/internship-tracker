"""URL normalization, stable identifiers, and cross-source deduplication."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from .models import InternshipRecord

_TRACKING_QUERY_NAMES = {
    "campaign",
    "fbclid",
    "gh_src",
    "jobsource",
    "lever-source",
    "lever-via",
    "ref",
    "referrer",
    "source",
    "src",
    "trk",
    "tracking",
}


def utc_now() -> str:
    """Return a compact, timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonicalize_url(url: str) -> str:
    """Normalize a public job URL while retaining identity-bearing query values.

    Employer application links commonly carry ``utm_*``, ``ref``, and ``embed``
    parameters. Those values do not identify a posting, so they are removed. A
    Greenhouse ``token`` query value is retained because it is the job ID.
    """

    raw = (url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    scheme = (parts.scheme or "https").lower()
    hostname = (parts.hostname or "").lower()
    if not hostname:
        return raw
    port = parts.port
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        hostname = f"{hostname}:{port}"
    netloc = hostname
    if parts.username or parts.password:
        # Job URLs should not contain credentials. Preserve the authority if a
        # source ever supplies one, but avoid silently dropping it.
        userinfo = parts.username or ""
        if parts.password is not None:
            userinfo += f":{parts.password}"
        netloc = f"{userinfo}@{netloc}"
    path = unquote(parts.path or "/")
    path = re.sub(r"/{2,}", "/", path)
    path = path.rstrip("/") or "/"
    query: list[tuple[str, str]] = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        key_lower = key.lower()
        if key_lower.startswith("utm_") or key_lower in _TRACKING_QUERY_NAMES or key_lower == "embed":
            continue
        query.append((key, value))
    query.sort()
    return urlunsplit((scheme, netloc, quote(path, safe="/%:@-._~"), urlencode(query), ""))


def job_id_from_url(url: str) -> str:
    """Extract an ATS job ID where the URL exposes one."""

    if not url:
        return ""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    token = query.get("token")
    if token:
        return token.strip()
    gh_jid = query.get("gh_jid")
    if gh_jid:
        return gh_jid.strip()
    path_parts = [unquote(piece) for piece in parts.path.split("/") if piece]
    for index, piece in enumerate(path_parts[:-1]):
        if piece.lower() in {"job", "jobs", "posting", "postings", "p"}:
            candidate = path_parts[index + 1].strip()
            if candidate and candidate.lower() not in {"application", "apply"}:
                return candidate
    if path_parts and path_parts[-1].lower() not in {"application", "apply", "job_app"}:
        candidate = path_parts[-1].strip()
        # Ashby uses a UUID as the last path segment. Greenhouse and Lever may
        # use numeric IDs. Avoid returning a generic company slug as an ID.
        if re.fullmatch(r"(?:\d+|[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,}|[0-9A-Za-z]{10,})", candidate):
            return candidate
    return ""


def stable_job_id(url: str) -> str:
    """Create a stable local ID when a source does not expose one."""

    canonical = canonicalize_url(url)
    return f"url-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}" if canonical else ""


def normalized_company(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (company or "").casefold())


def _dedup_key(record: InternshipRecord) -> tuple[str, ...]:
    company = normalized_company(record.company)
    job_id = (record.job_id or "").strip().casefold()
    if company and job_id:
        return ("job", company, job_id)
    return ("url", canonicalize_url(record.url))


def _role_signature(record: InternshipRecord) -> tuple[str, str, str]:
    role = re.sub(r"[^a-z0-9]+", " ", (record.role or "").casefold()).strip()
    location = re.sub(r"[^a-z0-9]+", " ", (record.location or "").casefold()).strip()
    return normalized_company(record.company), role, location


def _source_score(record: InternshipRecord) -> tuple[int, int, int]:
    """Prefer direct employer URLs and records with employer descriptions."""

    aggregate = record.url.lower().startswith(("https://simplify.jobs/", "https://jobright.ai/"))
    direct = 0 if aggregate else 1
    jd = 1 if record.jd and "description was not fetched" not in record.jd.lower() else 0
    source = 1 if record.source and record.source not in {"simplify", "jobright"} else 0
    return direct, jd, source


def _merge_records(existing: InternshipRecord, incoming: InternshipRecord) -> InternshipRecord:
    # Source means the discovery channel, so it follows the earliest observation
    # even when a later direct-employer record supplies richer job details.
    first_source = existing.source
    if incoming.discovered_at < existing.discovered_at:
        first_source = incoming.source or existing.source
    elif not first_source:
        first_source = incoming.source
    primary, secondary = (incoming, existing) if _source_score(incoming) > _source_score(existing) else (existing, incoming)
    primary.skills = list(dict.fromkeys([*primary.skills, *secondary.skills]))
    if not primary.visa_evidence and secondary.visa_evidence:
        primary.visa_evidence = secondary.visa_evidence
        primary.visa_sponsorship = secondary.visa_sponsorship
    elif primary.visa_sponsorship == "not stated" and secondary.visa_sponsorship != "not stated":
        primary.visa_sponsorship = secondary.visa_sponsorship
        primary.visa_evidence = secondary.visa_evidence
    if not primary.location and secondary.location:
        primary.location = secondary.location
    if len(secondary.jd) > len(primary.jd) and "description was not fetched" in primary.jd.lower():
        primary.jd = secondary.jd
    primary.discovered_at = min(primary.discovered_at, secondary.discovered_at)
    primary.last_seen = max(primary.last_seen, secondary.last_seen)
    primary.source = first_source
    return primary


def deduplicate_records(records: Iterable[InternshipRecord]) -> list[InternshipRecord]:
    """Deduplicate the same posting without collapsing sibling job IDs.

    A duplicate is the same normalized company plus the same employer job ID,
    or the same canonical URL when no job ID exists. Two roles at one company
    remain separate when their job IDs differ.
    """

    by_key: dict[tuple[str, ...], InternshipRecord] = {}
    by_signature: dict[tuple[str, str, str], tuple[str, ...]] = {}
    order: list[tuple[str, ...]] = []
    for record in records:
        key = _dedup_key(record)
        signature = _role_signature(record)
        matching_key = by_signature.get(signature) if all(signature) else None
        if key in by_key:
            by_key[key] = _merge_records(by_key[key], record)
        elif matching_key is not None:
            by_key[matching_key] = _merge_records(by_key[matching_key], record)
        else:
            by_key[key] = record
            order.append(key)
            if all(signature):
                by_signature[signature] = key
    return [by_key[key] for key in order]
