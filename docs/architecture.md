# Architecture

The project has four independently readable modules. JSON is the boundary between collection, ranking, workbook synchronization, and the dashboard. Resume profiles are inputs to ranking, not part of the public job feed.

## Collection and identity

`collector/internship_collector/sources.py` implements public feed and employer board adapters. `collector.py` runs each adapter, records source health, enriches descriptions, applies season and location filters, and deduplicates the results.

URL normalization removes tracking parameters while retaining employer job identifiers. Employer-scoped job identity and exact company, role, and location matches prevent duplicate aggregator rows. Two roles at the same employer with different job IDs remain separate. Source and source URL record how the role was discovered; the role URL remains the application destination.

Descriptions and explicit source statements drive skill and sponsorship extraction. Missing fields remain unknown. Discovery timestamps describe when the collector saw a listing and do not substitute for the employer's publication date.

## Ranking

`runner/scheduler/ranker.py` evaluates every job against the variants in a structured local profile. It extracts requirement terms from descriptions and skills, compares them with resume skills and evidence, applies confidence calibration and conservative caps, and selects a supported variant. The output adds ranking fields to the job record.

Titles affect title and domain fit but do not count as requirement evidence. Sparse listings cannot achieve Tier 1. Eligibility rules and manual priority overrides remain separate from the numeric match score. [The ranking documentation](../runner/docs/ranking-algorithm.md) lists weights and thresholds.

This is deterministic text scoring. It has no embedding model, model API, or learned calibration against hiring outcomes. Abbreviated listings, unusual terminology, and incomplete profiles can produce poor matches, so the dashboard exposes the evidence for review.

## Workbook ownership and synchronization

`excel/src/sync.mjs` defines `SOURCE_FIELDS` and `MANUAL_FIELDS`. Collection and ranking refresh the former. Status, application dates, notes, contacts, removal state, and manual overrides belong to the user and survive future merges.

The writer reads the existing workbook, matches stable IDs, checks for an Excel lock, verifies that the file has not changed, creates a backup, and renames a temporary workbook over the destination. It publishes a JSON sidecar for the dashboard. A read-only export path picks up manual Excel changes without rewriting the workbook.

The workbook and JSON sidecar are separate files. Each replacement is atomic, but the two replacements are not one transaction. A failure between them can leave the JSON behind the workbook; a later export reconciles it. Keep Excel closed during writes.

The spreadsheet API comes from `@oai/artifact-tool`. Its implementation and runtime are external to this repository.

## Dashboard data modes

`dashboard/lib/tracker.ts` chooses the data source at runtime:

| Mode | Read path | Write path |
| --- | --- | --- |
| Local service | `/api/jobs` from the Python server | `/api/applications` updates the workbook through the Excel CLI |
| Hosted feed | `/tracker-data.json`, overlaid with application records by stable ID | `/api/applications` stores fields in Cloudflare D1 |
| Static snapshot | `/tracker-data.json` without available application storage | Read-only |
| Example | `/tracker-data.example.json` | Read-only |

A standalone dev server falls back to the fictional example when the local API and real feed are absent. The example never requests or overlays hosted application records. Malformed live data reports an error rather than silently replacing it with an example.

The hosted API validates IDs, statuses, real calendar dates, notes, priority overrides, and removal flags before executing parameterized SQL. Database errors return a storage-unavailable response. Authentication must be provided by the deployment; the API does not implement accounts or authorization.

## Scheduler and reminders

The scheduler stores run results and reminder timestamps in SQLite. A process lock prevents overlapping ticks. The daily path runs collection, ranking, and sync in order. A ranking failure prevents downstream workbook writes. Command arguments are arrays and execute without a shell.

Reminder selection uses current application state. Failed delivery leaves the reminder timestamp unchanged. Failed operations use retry backoff, and daily timing uses the configured IANA timezone. The default launch agent checks once per minute; the Mac must be running for it to do work.

The local HTTP server binds to `127.0.0.1` by default, restricts Host headers, and serves dashboard files only from the configured build directory. SMTP secrets and resume profiles remain in ignored local files.
