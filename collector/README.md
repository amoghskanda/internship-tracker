# Internship collector

This Python package collects Summer 2027 internship listings into JSON. It reads public feeds from SimplifyJobs and Jobright, plus configurable Greenhouse and Ashby boards. It normalizes records, classifies a broad job domain, enriches public job descriptions where available, and deduplicates by employer job identity or exact company, role, and location.

The default location filter is the United States. Use `--all-countries` to include other countries, `--include-remote` to allow remote listings without a country, and repeat `--role-keyword` to narrow the title filter.

Install the package from the repository root and run it with:

```sh
python -m pip install -e ./collector
python -m internship_collector --output runner/data/collected.json
```

The collector never treats missing visa language as a denial. It records sponsorship as `provided` or `not provided` only when the source explicitly states the policy. Export-control and citizenship requirements remain `not stated`.

Date posted stays blank when a source does not expose a publication timestamp. `discovered_at` and `last_seen` describe observations by the collector. Employer descriptions use public ATS data when available and JobPosting structured data on other pages when present.

Browser-verified job records can be imported with the `--browser-jobs` option. The collector itself does not sign in to LinkedIn or Instagram.
