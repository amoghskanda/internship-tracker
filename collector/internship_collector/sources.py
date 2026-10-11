"""Public source adapters for the internship collector."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from html.parser import HTMLParser
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import parse_qsl, urlsplit
from urllib.request import Request, urlopen

from .filters import has_summer_2027, is_internship_title, location_allowed, matches_role_keywords
from .models import InternshipRecord, SourceHealth
from .normalization import canonicalize_url, job_id_from_url, stable_job_id, utc_now
from .text import detect_visa_sponsorship, extract_job_description, extract_skills, summarize_jd

SIMPLIFY_README_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md"
GREENHOUSE_API_ROOT = "https://boards-api.greenhouse.io/v1/boards"
ASHBY_API_ROOT = "https://api.ashbyhq.com/posting-api/job-board"
LEVER_API_ROOT = "https://api.lever.co/v0/postings"
JOBRIGHT_URLS = (
    "https://jobright.ai/jobs/summer-2027-internship-jobs-in-united-states",
    "https://jobright.ai/jobs/summer-2027-software-development-internship-jobs-in-united-states",
    "https://jobright.ai/jobs/summer-2027-machine-learning-internship-jobs-in-united-states",
    "https://jobright.ai/jobs/summer-2027-data-science-internship-jobs-in-united-states",
    "https://jobright.ai/jobs/summer-2027-computer-vision-internship-jobs-in-united-states",
)

DEFAULT_GREENHOUSE_BOARDS: dict[str, str] = {
    "scaleai": "Scale AI",
    "freeformfuturecorp": "Freeform",
}
DEFAULT_ASHBY_BOARDS: dict[str, str] = {
    "notion": "Notion",
    "zip": "Zip",
}


class HttpClient:
    """Minimal public HTTP client with a descriptive user agent."""

    def __init__(self, *, timeout: float = 30.0, user_agent: str = "internship-collector/0.1") -> None:
        self.timeout = timeout
        self.user_agent = user_agent

    def get_text(self, url: str) -> str:
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "text/plain, text/html, application/json"})
        with urlopen(request, timeout=self.timeout) as response:
            data = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="replace")

    def get_json(self, url: str) -> dict[str, Any]:
        return json.loads(self.get_text(url))


@dataclass
class AdapterResult:
    records: list[InternshipRecord]
    health: list[SourceHealth]


class BrowserJobsAdapter:
    """Read jobs verified by a signed-in T3 browser task."""

    name = "browser"

    def __init__(self, path: str | Path, *, season: str = "Summer 2027", country_filter: str | None = "US", include_remote_unknown: bool = False, role_keywords: tuple[str, ...] = ()) -> None:
        self.path = Path(path)
        self.season = season
        self.country_filter = country_filter
        self.include_remote_unknown = include_remote_unknown
        self.role_keywords = role_keywords

    def run(self, *, now: str | None = None) -> AdapterResult:
        fetched_at = now or utc_now()
        if not self.path.exists():
            return AdapterResult([], [SourceHealth(self.name, str(self.path), fetched_at, "ok", 0)])
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        items = payload if isinstance(payload, list) else payload.get("jobs", payload.get("records", []))
        if not isinstance(items, list):
            raise ValueError("browser jobs file must be an array or object with jobs")
        records: list[InternshipRecord] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            role = str(item.get("role") or item.get("title") or "").strip()
            location = str(item.get("location") or "").strip()
            if not is_internship_title(role) or not has_summer_2027(" ".join((role, str(item.get("season") or ""), str(item.get("jd") or "")))):
                continue
            if not matches_role_keywords(role, self.role_keywords) or not location_allowed(location, self.country_filter, include_remote_unknown=self.include_remote_unknown):
                continue
            url = canonicalize_url(str(item.get("url") or item.get("apply_url") or ""))
            source = str(item.get("source") or "browser").strip().lower()
            jd = str(item.get("jd") or "").strip()
            visa = str(item.get("visa_sponsorship") or "not stated").strip().lower()
            if visa not in {"provided", "not provided", "not stated"}:
                visa = "not stated"
            skills_value = item.get("skills") or []
            skills = [str(value) for value in skills_value] if isinstance(skills_value, list) else extract_skills(str(skills_value))
            records.append(InternshipRecord(
                company=str(item.get("company") or "Unknown company").strip(), role=role, url=url,
                job_id=_job_id(url, item.get("job_id")), location=location, jd=summarize_jd(jd),
                skills=skills or extract_skills(jd), visa_sponsorship=visa,
                visa_evidence=str(item.get("visa_evidence") or "").strip(),
                source_url=str(item.get("source_url") or "").strip(),
                discovered_at=str(item.get("discovered_at") or fetched_at), last_seen=fetched_at,
                date_posted=str(item.get("date_posted") or "").strip(), season=self.season, source=source,
            ))
        return AdapterResult(records, [SourceHealth(self.name, str(self.path), fetched_at, "ok", len(records))])


def parse_jobright_page(page: str) -> list[Mapping[str, Any]]:
    """Read the public server-rendered Jobright result payload."""

    match = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', page, re.DOTALL | re.IGNORECASE)
    if not match:
        raise ValueError("Jobright page did not contain its public result payload")
    payload = json.loads(match.group(1))
    jobs = payload.get("props", {}).get("pageProps", {}).get("jobList", [])
    if not isinstance(jobs, list):
        raise ValueError("Jobright result payload has an invalid job list")
    return [item for item in jobs if isinstance(item, Mapping)]


class JobrightAdapter:
    """Collect the newest public Summer 2027 results from Jobright category pages."""

    name = "jobright"

    def __init__(self, urls: Sequence[str] = JOBRIGHT_URLS, *, client: Any | None = None, season: str = "Summer 2027", country_filter: str | None = "US", include_remote_unknown: bool = False, role_keywords: tuple[str, ...] = ()) -> None:
        self.urls = tuple(urls)
        self.client = client or HttpClient(user_agent="Mozilla/5.0 internship-collector/0.1")
        self.season = season
        self.country_filter = country_filter
        self.include_remote_unknown = include_remote_unknown
        self.role_keywords = role_keywords

    def run(self, *, now: str | None = None) -> AdapterResult:
        fetched_at = now or utc_now()
        records: list[InternshipRecord] = []
        health: list[SourceHealth] = []
        for url in self.urls:
            try:
                page_records: list[InternshipRecord] = []
                for item in parse_jobright_page(self.client.get_text(url)):
                    job = item.get("jobResult") if isinstance(item.get("jobResult"), Mapping) else {}
                    company = item.get("companyResult") if isinstance(item.get("companyResult"), Mapping) else {}
                    title = str(job.get("jobTitle") or "").strip()
                    location = str(job.get("jobLocation") or "").strip()
                    season_text = " ".join((title, str(job.get("internHireDate") or ""), str(job.get("jobSummary") or "")))
                    if not is_internship_title(title) or not has_summer_2027(season_text):
                        continue
                    if not matches_role_keywords(title, self.role_keywords):
                        continue
                    if not location_allowed(location, self.country_filter, include_remote_unknown=self.include_remote_unknown):
                        continue
                    details = "\n".join(
                        [str(job.get("jobSummary") or ""), *map(str, job.get("coreResponsibilities") or []), *map(str, job.get("requirements") or [])]
                    )
                    tags = {str(value).strip().casefold() for value in (job.get("recommendationTags") or [])}
                    if "no h1b" in tags:
                        visa, evidence = "not provided", "Jobright marks the listing No H1B."
                    elif "h1b sponsored" in tags:
                        visa, evidence = "provided", "Jobright marks the listing H1B Sponsored."
                    else:
                        visa, evidence = "not stated", ""
                    role_url = canonicalize_url(str(job.get("url") or job.get("applyLink") or url))
                    page_records.append(InternshipRecord(
                        company=str(company.get("companyName") or "Unknown company").strip(),
                        role=title,
                        url=role_url,
                        job_id=_job_id(role_url, job.get("jobId")),
                        location=location,
                        jd=summarize_jd(details),
                        skills=extract_skills(details),
                        visa_sponsorship=visa,
                        visa_evidence=evidence,
                        source_url=role_url,
                        discovered_at=fetched_at,
                        last_seen=fetched_at,
                        date_posted=_date_posted(job),
                        season=self.season,
                        source=self.name,
                    ))
                records.extend(page_records)
                health.append(SourceHealth(self.name, url, fetched_at, "ok", len(page_records)))
            except Exception as exc:
                health.append(SourceHealth(self.name, url, fetched_at, "error", 0, f"{type(exc).__name__}: {exc}"))
        return AdapterResult(records, health)


def _job_id(url: str, explicit: Any = None) -> str:
    value = str(explicit or "").strip()
    return value or job_id_from_url(url) or stable_job_id(url)


def _clean_text(value: str) -> str:
    value = re.sub(r"[ \t\r\f\v]+", " ", value or "")
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _parse_timestamp(value: Any, fallback: str) -> str:
    if not value:
        return fallback
    text = str(value).strip()
    return text or fallback


def _date_posted(item: Mapping[str, Any]) -> str:
    """Return an explicit source posting timestamp when one is available."""

    # Keep this separate from updated_at/last_seen. A posting's modification
    # time is not its publication date, and several ATS feeds expose both.
    for key in (
        "date_posted",
        "datePosted",
        "first_published",
        "firstPublished",
        "published_at",
        "publishedAt",
        "posting_date",
        "postingDate",
        "posted_at",
        "postedAt",
        "publishTime",
        "created_at",
        "createdAt",
    ):
        value = item.get(key)
        if value:
            return _parse_timestamp(value, "")
    return ""


class _TableParser(HTMLParser):
    """Capture HTML table cells and links from the Simplify README."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, Any]] = []
        self._row: dict[str, Any] | None = None
        self._cell: dict[str, Any] | None = None
        self._cell_tag_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = {"cells": []}
        elif tag == "td" and self._row is not None:
            self._cell = {"parts": [], "links": []}
            self._cell_tag_depth = 1
        elif self._cell is not None:
            self._cell_tag_depth += 1
            if tag == "br":
                self._cell["parts"].append("\n")
            if tag == "a":
                href = dict(attrs).get("href")
                if href:
                    self._cell["links"].append(href)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._cell is not None and tag.lower() == "br":
            self._cell["parts"].append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "td" and self._row is not None and self._cell is not None:
            self._row["cells"].append(self._cell)
            self._cell = None
            self._cell_tag_depth = 0
        elif self._cell is not None and self._cell_tag_depth > 0:
            self._cell_tag_depth -= 1
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["parts"].append(data)


def _cell_text(cell: Mapping[str, Any]) -> str:
    return _clean_text("".join(str(part) for part in cell.get("parts", [])))


def _choose_application_url(urls: Sequence[str]) -> str:
    cleaned = [url.strip() for url in urls if url and url.strip()]
    non_simplify = [url for url in cleaned if "simplify.jobs" not in url.lower()]
    # Image links and tracking pixels should never become the application URL.
    non_images = [url for url in non_simplify if not re.search(r"\.(?:png|jpe?g|gif|svg)(?:[?#]|$)", url, re.IGNORECASE)]
    return (non_images or [url for url in cleaned if "simplify.jobs/p/" in url.lower()] or cleaned or [""])[0]


def parse_simplify_readme(markdown: str) -> list[dict[str, Any]]:
    """Parse active internship rows from the repository's HTML tables."""

    parser = _TableParser()
    parser.feed(markdown)
    previous_company = ""
    parsed: list[dict[str, Any]] = []
    for row in parser.rows:
        cells = row.get("cells", [])
        if len(cells) < 4:
            continue
        values = [_cell_text(cell) for cell in cells]
        if values[0].casefold() == "company" or values[1].casefold() == "role":
            continue
        company = re.sub(r"^[^A-Za-z0-9]+", "", values[0]).strip()
        if company in {"", "↳"} or company.startswith("↳"):
            company = previous_company
        else:
            company = re.sub(r"^[🔥🎓🛂🔒\s]+", "", company).strip()
            previous_company = company
        if not company:
            continue
        role = re.sub(r"^[🔥🎓🛂🔒\s]+", "", values[1]).strip()
        location = values[2].replace("\n", "; ")
        urls = cells[3].get("links", [])
        parsed.append(
            {
                "company": company,
                "role": role,
                "location": _clean_text(location),
                "url": _choose_application_url(urls),
                "visa_marker": "🛂" in " ".join(values),
                "closed_marker": "🔒" in " ".join(values),
                "raw": "\n".join(values),
            }
        )
    return parsed


def _json_ld_job_posting(page: str) -> dict[str, Any] | None:
    """Extract a JobPosting JSON-LD object from an employer page."""

    blocks = re.findall(r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", page, re.IGNORECASE | re.DOTALL)
    for block in blocks:
        try:
            parsed = json.loads(block.strip())
        except (TypeError, ValueError):
            continue
        candidates: list[Any] = []
        if isinstance(parsed, list):
            candidates.extend(parsed)
        elif isinstance(parsed, Mapping) and isinstance(parsed.get("@graph"), list):
            candidates.extend(parsed["@graph"])
            candidates.append(parsed)
        else:
            candidates.append(parsed)
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            kind = candidate.get("@type")
            types = kind if isinstance(kind, list) else [kind]
            if any(str(item).casefold() == "jobposting" for item in types):
                return dict(candidate)
    return None


def _greenhouse_detail_endpoint(url: str) -> str | None:
    parts = urlsplit(url)
    hostname = (parts.hostname or "").casefold()
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    pieces = [piece for piece in parts.path.split("/") if piece]
    if "greenhouse" in hostname and any(piece.casefold() == "job_app" for piece in pieces):
        board = query.get("for") or query.get("board")
        token = query.get("token") or query.get("gh_jid")
        if board and token:
            return f"{GREENHOUSE_API_ROOT}/{board}/jobs/{token}?content=true"
    greenhouse_board_by_host = {
        "careers.withwaymo.com": "waymo",
        "epicgames.com": "epicgames",
        "www.epicgames.com": "epicgames",
    }
    if "gh_jid" in query and hostname in greenhouse_board_by_host:
        return f"{GREENHOUSE_API_ROOT}/{greenhouse_board_by_host[hostname]}/jobs/{query['gh_jid']}?content=true"
    if "greenhouse" not in hostname:
        return None
    if "jobs" not in [piece.casefold() for piece in pieces]:
        return None
    index = next((index for index, piece in enumerate(pieces) if piece.casefold() == "jobs"), -1)
    if index <= 0 or index + 1 >= len(pieces):
        return None
    return f"{GREENHOUSE_API_ROOT}/{pieces[index - 1]}/jobs/{pieces[index + 1]}?content=true"


def _ashby_board_endpoint(url: str) -> tuple[str, str] | None:
    parts = urlsplit(url)
    if (parts.hostname or "").casefold() not in {"jobs.ashbyhq.com", "jobs.ashby.com"}:
        return None
    pieces = [piece for piece in parts.path.split("/") if piece]
    if len(pieces) < 2:
        return None
    board, job_id = pieces[0], pieces[1]
    if job_id.casefold() in {"application", "apply"}:
        return None
    return f"{ASHBY_API_ROOT}/{board}", job_id


def _lever_detail_endpoint(url: str) -> str | None:
    parts = urlsplit(url)
    if (parts.hostname or "").casefold() not in {"jobs.lever.co", "jobs.lever.com"}:
        return None
    pieces = [piece for piece in parts.path.split("/") if piece]
    if len(pieces) < 2:
        return None
    return f"{LEVER_API_ROOT}/{pieces[0]}/{pieces[1]}"


def _workday_detail_endpoint(url: str) -> str | None:
    parts = urlsplit(url)
    hostname = (parts.hostname or "").casefold()
    if not hostname.endswith(".myworkdayjobs.com"):
        return None
    pieces = [piece for piece in parts.path.split("/") if piece]
    job_index = next((index for index, piece in enumerate(pieces) if piece.casefold() == "job"), -1)
    if job_index <= 0 or job_index + 1 >= len(pieces):
        return None
    tenant = hostname.split(".wd", 1)[0]
    site = pieces[job_index - 1]
    slug = pieces[-1]
    if not tenant or not site or not slug:
        return None
    return f"https://{hostname}/wday/cxs/{tenant}/{site}/job/{slug}"


def _generic_page_summary(page: str) -> tuple[str, str]:
    posting = _json_ld_job_posting(page)
    if posting:
        description = str(posting.get("description") or "")
        if len(description.split()) < 8:
            raise ValueError("JobPosting JSON-LD did not contain a usable description")
        return description, summarize_jd(description)
    description = extract_job_description(page)
    if len(description.split()) < 8:
        raise ValueError("no structured job description found")
    return description, summarize_jd(description)


def _fetch_enrichment(endpoint: str, client: Any, *, ashby_job_id: str = "") -> dict[str, Any]:
    if endpoint.startswith(GREENHOUSE_API_ROOT):
        payload = client.get_json(endpoint)
        return payload if isinstance(payload, Mapping) else {}
    if endpoint.startswith(ASHBY_API_ROOT):
        payload = client.get_json(endpoint)
        return payload if isinstance(payload, Mapping) else {}
    if endpoint.startswith(LEVER_API_ROOT):
        payload = client.get_json(endpoint)
        return payload if isinstance(payload, Mapping) else {}
    if "/wday/cxs/" in endpoint:
        payload = client.get_json(endpoint)
        if not isinstance(payload, Mapping):
            return {}
        info = payload.get("jobPostingInfo")
        return dict(info) if isinstance(info, Mapping) else {}
    page = client.get_text(endpoint)
    description, summary = _generic_page_summary(page)
    return {"content": description, "descriptionHtml": description, "_summary": summary}


def _enrich_records(
    records: list[InternshipRecord],
    *,
    client: Any,
    workers: int,
    max_requests: int,
    fetched_at: str,
) -> SourceHealth:
    """Fetch employer descriptions with a bounded worker pool.

    Direct Greenhouse and Ashby URLs use their public APIs. Other employer URLs
    use the public page and JobPosting JSON-LD when available. One request is
    made per unique endpoint and every failed row keeps an explicit error.
    """

    tasks: dict[str, list[tuple[int, str]]] = {}
    for index, record in enumerate(records):
        if not record.url:
            record.enrichment_error = "no employer URL"
            continue
        gh_endpoint = _greenhouse_detail_endpoint(record.url)
        if gh_endpoint:
            tasks.setdefault(gh_endpoint, []).append((index, ""))
            continue
        ashby = _ashby_board_endpoint(record.url)
        if ashby:
            endpoint, ashby_job_id = ashby
            tasks.setdefault(endpoint, []).append((index, ashby_job_id))
            continue
        lever_endpoint = _lever_detail_endpoint(record.url)
        if lever_endpoint:
            tasks.setdefault(lever_endpoint, []).append((index, ""))
            continue
        workday_endpoint = _workday_detail_endpoint(record.url)
        if workday_endpoint:
            tasks.setdefault(workday_endpoint, []).append((index, ""))
            continue
        tasks.setdefault(record.url, []).append((index, ""))
    endpoints = list(tasks)[:max_requests]
    for endpoint in list(tasks)[max_requests:]:
        for index, _ in tasks[endpoint]:
            records[index].enrichment_error = "enrichment request limit reached"
    succeeded = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_fetch_enrichment, endpoint, client, ashby_job_id=tasks[endpoint][0][1]): endpoint
            for endpoint in endpoints
        }
        for future in as_completed(futures):
            endpoint = futures[future]
            try:
                payload = future.result()
                payloads: list[tuple[int, Mapping[str, Any]]] = []
                if endpoint.startswith(ASHBY_API_ROOT):
                    jobs_by_id = {
                        str(item.get("id")): item
                        for item in payload.get("jobs", [])
                        if isinstance(item, Mapping)
                    }
                    for index, job_id in tasks[endpoint]:
                        item = jobs_by_id.get(job_id)
                        if item is not None:
                            payloads.append((index, item))
                        else:
                            records[index].enrichment_error = f"LookupError: Ashby posting {job_id} was not present in the board feed"
                            failed += 1
                else:
                    payloads = [(index, payload) for index, _ in tasks[endpoint]]
                for index, item in payloads:
                    content = str(item.get("content") or item.get("descriptionHtml") or item.get("description") or item.get("jobDescription") or item.get("descriptionPlain") or "")
                    if not content:
                        raise ValueError("employer page did not expose a description")
                    summary = str(item.get("_summary") or summarize_jd(content))
                    if not summary.strip():
                        raise ValueError("employer description had no usable role details")
                    skills = extract_skills(content)
                    visa, evidence = detect_visa_sponsorship(content)
                    record = records[index]
                    record.jd = summary
                    record.skills = list(dict.fromkeys([*record.skills, *skills]))
                    if visa != "not stated":
                        record.visa_sponsorship = visa
                        record.visa_evidence = evidence
                    record.source_url = record.url
                    record.enrichment_error = ""
                succeeded += len(payloads)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                for index, _ in tasks[endpoint]:
                    records[index].enrichment_error = error
                failed += len(tasks[endpoint])
    status = "ok" if failed == 0 else "error"
    message = "" if failed == 0 else f"{failed} posting description fetches failed"
    return SourceHealth("simplify-enrichment", "employer URLs listed in Simplify", fetched_at, status, succeeded, message)


class SimplifyAdapter:
    """Adapter for the public Pitt CSC and Simplify Summer 2027 README."""

    name = "simplify"

    def __init__(
        self,
        *,
        client: Any | None = None,
        readme_url: str = SIMPLIFY_README_URL,
        season: str = "Summer 2027",
        country_filter: str | None = "US",
        include_remote_unknown: bool = False,
        role_keywords: tuple[str, ...] = (),
        enrich: bool = True,
        enrichment_workers: int = 8,
        max_enrichment_requests: int = 400,
    ) -> None:
        self.client = client or HttpClient()
        self.readme_url = readme_url
        self.season = season
        self.country_filter = country_filter
        self.include_remote_unknown = include_remote_unknown
        self.role_keywords = role_keywords
        self.enrich = enrich
        self.enrichment_workers = max(1, enrichment_workers)
        self.max_enrichment_requests = max(0, max_enrichment_requests)

    def run(self, *, now: str | None = None) -> AdapterResult:
        fetched_at = now or utc_now()
        try:
            readme = self.client.get_text(self.readme_url)
            if not has_summer_2027(readme[:12000]):
                raise ValueError("README did not declare Summer 2027")
            records: list[InternshipRecord] = []
            for row in parse_simplify_readme(readme):
                if row["closed_marker"] or not row["url"]:
                    continue
                if not is_internship_title(row["role"]):
                    continue
                if not matches_role_keywords(row["role"], self.role_keywords):
                    continue
                if not location_allowed(row["location"], self.country_filter, include_remote_unknown=self.include_remote_unknown):
                    continue
                url = row["url"]
                visa = "not provided" if row["visa_marker"] else "not stated"
                evidence = "Source marks sponsorship as unavailable." if row["visa_marker"] else ""
                records.append(
                    InternshipRecord(
                        company=row["company"],
                        role=row["role"],
                        url=canonicalize_url(url),
                        job_id=_job_id(url),
                        location=row["location"],
                        jd="",
                        skills=[],
                        visa_sponsorship=visa,
                        visa_evidence=evidence,
                        source_url=self.readme_url,
                        discovered_at=fetched_at,
                        last_seen=fetched_at,
                        date_posted="",
                        season=self.season,
                        source=self.name,
                    )
                )
            health = [SourceHealth(self.name, self.readme_url, fetched_at, "ok", len(records))]
            if self.enrich and records and self.max_enrichment_requests:
                enrichment_health = _enrich_records(
                    records,
                    client=self.client,
                    workers=self.enrichment_workers,
                    max_requests=self.max_enrichment_requests,
                    fetched_at=fetched_at,
                )
                health.append(enrichment_health)
            return AdapterResult(records, health)
        except Exception as exc:
            health = SourceHealth(self.name, self.readme_url, fetched_at, "error", 0, f"{type(exc).__name__}: {exc}")
            return AdapterResult([], [health])


class GreenhouseAdapter:
    """Adapter for Greenhouse's public job-board API."""

    name = "greenhouse"

    def __init__(
        self,
        boards: Mapping[str, str] | Sequence[str],
        *,
        client: Any | None = None,
        season: str = "Summer 2027",
        country_filter: str | None = "US",
        include_remote_unknown: bool = False,
        role_keywords: tuple[str, ...] = (),
    ) -> None:
        self.boards = dict(boards) if isinstance(boards, Mapping) else {slug: slug for slug in boards}
        self.client = client or HttpClient()
        self.season = season
        self.country_filter = country_filter
        self.include_remote_unknown = include_remote_unknown
        self.role_keywords = role_keywords

    def run(self, *, now: str | None = None) -> AdapterResult:
        fetched_at = now or utc_now()
        records: list[InternshipRecord] = []
        health: list[SourceHealth] = []
        for slug, configured_company in self.boards.items():
            endpoint = f"{GREENHOUSE_API_ROOT}/{slug}/jobs?content=true"
            try:
                payload = self.client.get_json(endpoint)
                jobs = payload.get("jobs", [])
                board_records: list[InternshipRecord] = []
                for job in jobs:
                    title = str(job.get("title") or "").strip()
                    content = str(job.get("content") or "")
                    if not is_internship_title(title) or not has_summer_2027(f"{title}\n{content}"):
                        continue
                    if not matches_role_keywords(title, self.role_keywords):
                        continue
                    location = str((job.get("location") or {}).get("name") or "").strip()
                    if not location_allowed(location, self.country_filter, include_remote_unknown=self.include_remote_unknown):
                        continue
                    url = str(job.get("absolute_url") or f"https://job-boards.greenhouse.io/{slug}/jobs/{job.get('id', '')}")
                    visa, evidence = detect_visa_sponsorship(content)
                    board_records.append(
                        InternshipRecord(
                            company=str(job.get("company_name") or configured_company or slug).strip(),
                            role=title,
                            url=canonicalize_url(url),
                            job_id=_job_id(url, job.get("id")),
                            location=location,
                            jd=summarize_jd(content),
                            skills=extract_skills(content),
                            visa_sponsorship=visa,
                            visa_evidence=evidence,
                            source_url=canonicalize_url(url),
                            discovered_at=fetched_at,
                            last_seen=fetched_at,
                            date_posted=_date_posted(job),
                            season=self.season,
                            source=f"greenhouse:{slug}",
                        )
                    )
                records.extend(board_records)
                health.append(SourceHealth(f"greenhouse:{slug}", endpoint, fetched_at, "ok", len(board_records)))
            except Exception as exc:
                health.append(SourceHealth(f"greenhouse:{slug}", endpoint, fetched_at, "error", 0, f"{type(exc).__name__}: {exc}"))
        return AdapterResult(records, health)


class AshbyAdapter:
    """Adapter for Ashby's public posting API."""

    name = "ashby"

    def __init__(
        self,
        boards: Mapping[str, str] | Sequence[str],
        *,
        client: Any | None = None,
        season: str = "Summer 2027",
        country_filter: str | None = "US",
        include_remote_unknown: bool = False,
        role_keywords: tuple[str, ...] = (),
    ) -> None:
        self.boards = dict(boards) if isinstance(boards, Mapping) else {slug: slug for slug in boards}
        self.client = client or HttpClient()
        self.season = season
        self.country_filter = country_filter
        self.include_remote_unknown = include_remote_unknown
        self.role_keywords = role_keywords

    def run(self, *, now: str | None = None) -> AdapterResult:
        fetched_at = now or utc_now()
        records: list[InternshipRecord] = []
        health: list[SourceHealth] = []
        for slug, configured_company in self.boards.items():
            endpoint = f"{ASHBY_API_ROOT}/{slug}"
            try:
                payload = self.client.get_json(endpoint)
                jobs = payload.get("jobs", [])
                board_records: list[InternshipRecord] = []
                for job in jobs:
                    title = str(job.get("title") or "").strip()
                    description = str(job.get("descriptionHtml") or job.get("descriptionPlain") or "")
                    if not is_internship_title(title) or not has_summer_2027(f"{title}\n{description}"):
                        continue
                    if not matches_role_keywords(title, self.role_keywords):
                        continue
                    locations = [str(job.get("location") or "").strip()]
                    locations.extend(str(item.get("location") or "").strip() for item in (job.get("secondaryLocations") or []) if isinstance(item, Mapping))
                    location = "; ".join(dict.fromkeys(item for item in locations if item))
                    if not location_allowed(location, self.country_filter, include_remote_unknown=self.include_remote_unknown):
                        continue
                    url = str(job.get("jobUrl") or job.get("applyUrl") or f"https://jobs.ashbyhq.com/{slug}/{job.get('id', '')}")
                    visa, evidence = detect_visa_sponsorship(description)
                    board_records.append(
                        InternshipRecord(
                            company=str(job.get("companyName") or configured_company or slug).strip(),
                            role=title,
                            url=canonicalize_url(url),
                            job_id=_job_id(url, job.get("id")),
                            location=location,
                            jd=summarize_jd(description),
                            skills=extract_skills(description),
                            visa_sponsorship=visa,
                            visa_evidence=evidence,
                            source_url=canonicalize_url(url),
                            discovered_at=fetched_at,
                            last_seen=fetched_at,
                            date_posted=_date_posted(job),
                            season=self.season,
                            source=f"ashby:{slug}",
                        )
                    )
                records.extend(board_records)
                health.append(SourceHealth(f"ashby:{slug}", endpoint, fetched_at, "ok", len(board_records)))
            except Exception as exc:
                health.append(SourceHealth(f"ashby:{slug}", endpoint, fetched_at, "error", 0, f"{type(exc).__name__}: {exc}"))
        return AdapterResult(records, health)
