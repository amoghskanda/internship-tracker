from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from internship_collector.collector import Collector
from internship_collector.models import InternshipRecord
from internship_collector.normalization import canonicalize_url, deduplicate_records, job_id_from_url
from internship_collector.sources import AshbyAdapter, BrowserJobsAdapter, GreenhouseAdapter, JobrightAdapter, SimplifyAdapter, _lever_detail_endpoint, _workday_detail_endpoint, parse_simplify_readme
from internship_collector.text import classify_domain, detect_visa_sponsorship, extract_job_description, extract_skills, summarize_jd
from internship_collector.filters import has_summer_2027, is_us_location


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value))
    return suite


class FakeClient:
    def __init__(self, *, text: dict[str, str] | None = None, payloads: dict[str, dict] | None = None):
        self.text = text or {}
        self.payloads = payloads or {}

    def get_text(self, url: str) -> str:
        if url not in self.text:
            raise KeyError(url)
        return self.text[url]

    def get_json(self, url: str) -> dict:
        if url not in self.payloads:
            raise KeyError(url)
        return self.payloads[url]


def record(company: str, role: str, url: str, job_id: str) -> InternshipRecord:
    return InternshipRecord(
        company=company,
        role=role,
        url=url,
        job_id=job_id,
        location="San Francisco, CA",
        jd="",
        skills=[],
        visa_sponsorship="not stated",
        visa_evidence="",
        source_url="https://source.example/jobs",
        discovered_at="2026-09-09T00:00:00Z",
        last_seen="2026-09-09T00:00:00Z",
    )


def test_url_canonicalization_strips_tracking_and_keeps_job_identity():
    url = "https://JOB-BOARDS.Greenhouse.io/acme/jobs/123/?utm_source=Simplify&ref=Simplify&gh_jid=123"
    assert canonicalize_url(url) == "https://job-boards.greenhouse.io/acme/jobs/123?gh_jid=123"
    assert job_id_from_url(url) == "123"


def test_season_and_us_filters_are_explicit():
    assert has_summer_2027("Software internship, 2027 Summer")
    assert has_summer_2027("Summer-2027 internship")
    assert not has_summer_2027("Summer 2026 internship")
    assert is_us_location("San Francisco, CA")
    assert is_us_location("Remote in USA")
    assert not is_us_location("Milan, Italy")
    assert not is_us_location("Bangalore, IN")


def test_simplify_parser_carries_company_and_skips_closed_or_non_us_rows():
    readme = """
    # Summer 2027 internships
    <table>
      <tr><th>Company</th><th>Role</th><th>Location</th><th>Application</th></tr>
      <tr><td>🔥 <strong><a href="https://simplify.jobs/c/Acme">Acme</a></strong></td><td>Software Engineering Intern</td><td>San Francisco, CA</td><td><a href="https://job-boards.greenhouse.io/acme/jobs/123?utm_source=x">Apply</a><a href="https://simplify.jobs/p/abc">S</a></td></tr>
      <tr><td>↳</td><td>Data Science Intern - 2027 Summer</td><td>NYC</td><td><a href="https://jobs.ashbyhq.com/acme/uuid/application?embed=true">Apply</a></td></tr>
      <tr><td>Acme</td><td>Software Engineer</td><td>Boston, MA</td><td><a href="https://example.com/job">Apply</a></td></tr>
      <tr><td>Other</td><td>Software Intern</td><td>London, UK</td><td><a href="https://example.com/uk">Apply</a></td></tr>
      <tr><td>🔒 Closed</td><td>Closed Intern</td><td>Seattle, WA</td><td><a href="https://example.com/closed">Apply</a></td></tr>
    </table>
    """
    rows = parse_simplify_readme(readme)
    assert rows[0]["company"] == "Acme"
    assert rows[1]["company"] == "Acme"
    assert rows[1]["url"].startswith("https://jobs.ashbyhq.com/acme/")
    adapter = SimplifyAdapter(client=FakeClient(text={"fixture": readme}), readme_url="fixture", enrich=False)
    result = adapter.run(now="2026-09-09T00:00:00Z")
    assert [(item.company, item.role) for item in result.records] == [
        ("Acme", "Software Engineering Intern"),
        ("Acme", "Data Science Intern - 2027 Summer"),
    ]
    assert result.records[0].url == "https://job-boards.greenhouse.io/acme/jobs/123"
    assert result.records[0].date_posted == ""


def test_greenhouse_adapter_requires_summer_2027_and_internship_title():
    endpoint = "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
    payload = {
        "jobs": [
            {
                "id": 123,
                "company_name": "Acme",
                "title": "ML Engineering Intern (Summer 2027)",
                "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/123",
                "location": {"name": "New York, NY"},
                "first_published": "2026-07-16T14:33:31-04:00",
                "content": "<h2>Responsibilities</h2><p>Build models with Python and PyTorch.</p><p>We will sponsor US visas.</p>",
            },
            {
                "id": 124,
                "company_name": "Acme",
                "title": "Software Engineer (New Grad Summer 2027)",
                "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/124",
                "location": {"name": "New York, NY"},
                "content": "<p>Summer 2027 role.</p>",
            },
        ]
    }
    result = GreenhouseAdapter({"acme": "Acme"}, client=FakeClient(payloads={endpoint: payload})).run(now="2026-09-09T00:00:00Z")
    assert len(result.records) == 1
    item = result.records[0]
    assert item.job_id == "123"
    assert item.skills == ["Python", "PyTorch"]
    assert item.visa_sponsorship == "provided"
    assert item.date_posted == "2026-07-16T14:33:31-04:00"
    assert len(item.visa_evidence.split()) <= 25
    assert item.discovered_at == "2026-09-09T00:00:00Z"


def test_ashby_adapter_uses_board_feed_and_secondary_locations():
    endpoint = "https://api.ashbyhq.com/posting-api/job-board/notion"
    payload = {
        "jobs": [
            {
                "id": "abc-123",
                "title": "Software Engineer Intern (Summer 2027)",
                "location": "San Francisco, California",
                "secondaryLocations": [{"location": "New York, New York"}],
                "jobUrl": "https://jobs.ashbyhq.com/notion/abc-123",
                "publishedAt": "2026-08-24T14:44:49.699+00:00",
                "descriptionHtml": "<h1>What you'll do</h1><p>Build React and TypeScript features.</p>",
            }
        ]
    }
    result = AshbyAdapter({"notion": "Notion"}, client=FakeClient(payloads={endpoint: payload})).run(now="2026-09-09T00:00:00Z")
    assert len(result.records) == 1
    assert result.records[0].job_id == "abc-123"
    assert "New York" in result.records[0].location
    assert result.records[0].skills == ["TypeScript", "React"]
    assert result.records[0].date_posted == "2026-08-24T14:44:49.699+00:00"


def test_workday_and_lever_public_detail_endpoints_are_stable():
    workday = "https://globalhr.wd5.myworkdayjobs.com/rec_rtx_ext_gateway/job/US-IA-CEDAR-RAPIDS/Software-Engineer-Intern---Summer-2027-_01870613"
    assert _workday_detail_endpoint(workday) == "https://globalhr.wd5.myworkdayjobs.com/wday/cxs/globalhr/rec_rtx_ext_gateway/job/Software-Engineer-Intern---Summer-2027-_01870613"
    lever = "https://jobs.lever.co/acme/abc-123/apply"
    assert _lever_detail_endpoint(lever) == "https://api.lever.co/v0/postings/acme/abc-123"


def test_visa_detection_does_not_infer_from_export_control():
    assert detect_visa_sponsorship("Applicants must be US persons under ITAR.") == ("not stated", "")
    assert detect_visa_sponsorship("Visa sponsorship is not available for this role.")[0] == "not provided"
    assert detect_visa_sponsorship("We sponsor US visas.")[0] == "provided"
    assert detect_visa_sponsorship("We do not sponsor visas, but we sponsor US visas for this role.")[0] == "not stated"


def test_domain_classifier_prioritizes_specific_ai_domains():
    assert classify_domain("Computer Vision Software Intern", skills=["OpenCV"]) == "Computer Vision"
    assert classify_domain("MLOps Intern", "Build model serving infrastructure") == "MLOps / AI Infrastructure"
    assert classify_domain("Applied AI Intern", skills=["PyTorch"]) == "Machine Learning / AI"
    assert classify_domain("Software Developer Intern") == "Software Engineering"
    assert classify_domain("Data Analytics Intern") == "Data"


def test_jobright_adapter_reads_public_next_payload_and_explicit_h1b_tag():
    url = "https://jobright.example/summer-2027"
    next_data = {
        "props": {"pageProps": {"jobList": [{
            "jobResult": {
                "jobId": "jr-1",
                "jobTitle": "Computer Vision Intern - Summer 2027",
                "jobLocation": "San Jose, CA",
                "internHireDate": "Start in 2027 Summer",
                "publishTime": "2026-09-09 17:29:01",
                "jobSummary": "Build image processing systems with Python and OpenCV.",
                "recommendationTags": ["H1B Sponsored"],
                "url": "https://jobright.ai/jobs/info/jr-1?utm_source=test",
            },
            "companyResult": {"companyName": "Vision Co"},
        }]}}
    }
    page = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>'
    result = JobrightAdapter([url], client=FakeClient(text={url: page})).run(now="2026-09-09T00:00:00Z")
    assert len(result.records) == 1
    assert result.records[0].company == "Vision Co"
    assert result.records[0].visa_sponsorship == "provided"
    assert result.records[0].skills == ["Python", "OpenCV"]
    assert result.records[0].date_posted == "2026-09-09 17:29:01"


def test_summary_is_structured_and_short():
    summary = summarize_jd("<h2>Responsibilities</h2><p>Build distributed systems and work with Python and AWS.</p>")
    assert summary.startswith("JD excerpt: Build distributed systems")
    assert "Skills named in the posting" in summary
    assert len(summary.split()) < 25
    gallup = summarize_jd("<p><em>Apply early for priority consideration.</em></p><p><strong>What You'll Do</strong></p><p>During your internship, you will:</p><ul><li>Build customer-facing applications with Python and SQL.</li></ul>")
    assert "Build customer-facing applications" in gallup
    assert "Apply early" not in gallup


def test_generic_page_requires_a_description_container_and_ignores_forms():
    page = "<html><body><nav>Apply</nav><form id='application-form'><input name='description' /></form></body></html>"
    assert extract_job_description(page) == ""
    page = "<html><body><div class='job__description'><img src='logo.png'><p><strong>What you'll do</strong><br></p><ul><li>Build APIs and test services.</li></ul></div><form id='application-form'>Apply</form></body></html>"
    assert "Build APIs" in extract_job_description(page)


def test_skill_extraction_rejects_ambiguous_cv_and_c_mentions():
    skills = extract_skills("Please upload your CV. Candidates may have C++ experience and C programming skills.")
    assert "Computer vision" not in skills
    assert "C++" in skills
    assert "C" in skills


def test_dedup_preserves_same_company_different_job_ids():
    first = record("Acme", "Data Intern", "https://jobs.example/acme/123?utm_source=x", "123")
    duplicate = record("ACME", "Data Intern", "https://jobs.example/acme/123?ref=board", "123")
    sibling = record("Acme", "ML Intern", "https://jobs.example/acme/124", "124")
    result = deduplicate_records([first, duplicate, sibling])
    assert len(result) == 2
    assert {item.job_id for item in result} == {"123", "124"}


def test_dedup_collapses_exact_role_and_location_across_aggregators():
    direct = record("Acme", "ML Intern", "https://jobs.example/acme/123", "123")
    aggregate = record("ACME", "ML Intern", "https://jobright.ai/jobs/info/xyz", "xyz")
    other_location = record("Acme", "ML Intern", "https://jobs.example/acme/124", "124")
    other_location.location = "New York, NY"
    result = deduplicate_records([aggregate, direct, other_location])
    assert len(result) == 2
    assert result[0].url == direct.url


def test_dedup_keeps_the_first_discovery_source_when_later_feed_is_richer():
    first = record("Acme", "ML Intern", "https://simplify.jobs/p/acme", "123")
    first.source = "simplify"
    first.discovered_at = "2026-09-01T00:00:00Z"
    richer = record("Acme", "ML Intern", "https://boards.greenhouse.io/acme/jobs/123", "123")
    richer.source = "greenhouse:acme"
    richer.discovered_at = "2026-09-02T00:00:00Z"
    result = deduplicate_records([first, richer])
    assert len(result) == 1
    assert result[0].source == "simplify"
    assert "greenhouse.io" in result[0].url


def test_browser_jobs_adapter_preserves_linkedin_discovery_url_and_apply_url():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "browser_jobs.json"
        path.write_text(json.dumps({"jobs": [{"company": "Acme", "role": "Software Engineer Intern - Summer 2027", "location": "New York, NY", "url": "https://jobs.acme.com/123", "job_id": "123", "source": "linkedin", "source_url": "https://www.linkedin.com/jobs/view/123", "discovered_at": "2026-09-10T00:00:00Z"}]}))
        result = BrowserJobsAdapter(path).run(now="2026-09-10T01:00:00Z")
        assert len(result.records) == 1
        assert result.records[0].source == "linkedin"
        assert result.records[0].source_url == "https://www.linkedin.com/jobs/view/123"
        assert result.records[0].url == "https://jobs.acme.com/123"


def test_collector_keeps_source_health_when_an_adapter_fails():
    class Broken:
        name = "broken"

        def run(self, *, now: str):
            raise RuntimeError("offline")

    result = Collector([Broken()]).run(now="2026-09-09T00:00:00Z")
    assert result.records == []
    assert result.source_health[0].status == "error"
    assert "offline" in result.source_health[0].error


def test_collection_result_exposes_jobs_and_records_aliases():
    class One:
        name = "one"

        def run(self, *, now: str):
            from internship_collector.models import SourceHealth
            from internship_collector.sources import AdapterResult

            return AdapterResult([record("Acme", "Data Intern", "https://example.com/job/1", "1")], [SourceHealth("one", "https://example.com", now, "ok", 1)])

    payload = Collector([One()]).run(now="2026-09-09T00:00:00Z").to_dict()
    assert payload["jobs"] == payload["records"]
    assert payload["updated_at"] == "2026-09-09T00:00:00Z"
