# Summer 2027 internship tracker

A local-first application that collects internship listings, ranks them against private resume profiles, keeps application details in Excel, and presents the results in a browser dashboard.

## How it works

```text
Public job feeds -> Python collector -> local resume ranker -> Excel and JSON sync
                                                               -> React dashboard
macOS launchd -> daily collection and ranking, plus 12-hour email reminders
```

The collector reads public Summer 2027 listings from SimplifyJobs, Jobright, Greenhouse, and Ashby. It normalizes the records and removes duplicate employer listings. A browser-job adapter can import listings supplied as JSON.

The Python ranker compares each listing with structured resume profiles stored on the user's machine. It uses local text and evidence scoring, applies confidence and eligibility gates, and records the best matching profile, tier, score, supporting evidence, gaps, and tailoring suggestions. It does not send resume text to a model or network service. See [the ranking method](runner/docs/ranking-algorithm.md).

The Excel sync keeps source and ranking fields current while preserving application status, dates, notes, contact names, removal state, and manual tier overrides. It writes a JSON feed for the dashboard. The dashboard filters by tier, domain, source, application status, and sponsorship, and shows job details and the application pipeline.

On macOS, `launchd` runs the scheduler after the configured daily time and checks every 12 hours for pending-application reminders. The dashboard server binds to `127.0.0.1` by default. A Cloudflare D1 binding is required for hosted application-state writes.

This repository does not include LinkedIn mutual scraping or an Instagram Stories monitor. Those sources require separate signed-in browser workflows. The collector can accept browser-verified job listings through its JSON adapter.

## Repository layout

- `dashboard/` contains the React/Vinext tracker UI and Cloudflare application API.
- `collector/` contains the Python source adapters, normalization, enrichment, and deduplication.
- `runner/scheduler/` contains the macOS scheduler, local server, email reminders, and ranking engine.
- `excel/` contains the Node workbook and JSON synchronization CLI.
- `runner/docs/ranking-algorithm.md` describes tier thresholds and ranking evidence.

## Run the collector

Requirements: Python 3.10 or newer.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ./collector
python -m internship_collector --output runner/data/collected.json
```

The collector writes only to the path you provide. `runner/data/` is ignored by Git.

## Configure ranking and reminders

Copy `runner/config.example.json` to `runner/config.json` and set the command paths, reminder recipient, and dashboard directory for your machine. Create `runner/private/resume_profile.json` from the example at `runner/examples/resume-profile.example.json`, then replace the sample content with your own structured profile. Both `config.json` and `private/` are ignored.

Rank a collected feed with:

```sh
python3 runner/scheduler/ranker.py \
  --jobs runner/data/collected.json \
  --resume-profile runner/private/resume_profile.json \
  --output runner/data/ranked.json
```

Email reminders stay off until you configure SMTP locally. Run the scheduler setup command only after editing your recipient and SMTP settings in the local config.

## Dashboard and Excel sync

Requirements: Node.js 22 or newer.

```sh
cd dashboard
npm ci
npm run build
```

The generated tracker feed and workbook belong in local runtime data. The repository includes an empty JSON fixture and a blank workbook schema so a public clone contains no application records.

The Excel CLI source is in `excel/src/sync.mjs`. It imports `@oai/artifact-tool`, which this workspace supplies through the T3 Code runtime. That package is not vendored in this repository. The dashboard uses Vinext, React, and the Cloudflare Vite plugin. For hosted application-state writes, configure Cloudflare D1 with the `DB` binding and set `CLOUDFLARE_D1_DATABASE_ID`.

## Privacy

The public repository contains no resume files or resume profile, job feed, workbook history, application records, contact names, browser session, SMTP credential, or machine-specific deployment configuration. The empty fixture at `dashboard/public/tracker-data.example.json` is safe sample data. Keep your own profile in `runner/private/`, generated data in `runner/data/`, and secrets in ignored `.env` files.
