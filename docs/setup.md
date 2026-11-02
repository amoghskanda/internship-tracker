# Local setup

Run these commands from the repository root unless a step changes directories. The dashboard example and offline ranking command in the root README need no private runtime.

## Dashboard

```sh
cd dashboard
npm ci
npm run dev
```

The dev server prints its URL. It loads the fictional fixture if no live feed is present. To build static files for the Python service:

```sh
npm run build
```

The static build writes `dashboard/dist/client/`. `npm start` uses Wrangler to run a built worker and is intended for a hosted build, not the static Python service.

## Collector and local configuration

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ./collector
cp runner/config.example.json runner/config.json
mkdir -p runner/private
cp runner/examples/resume-profile.example.json runner/private/resume_profile.json
```

Edit the private profile to describe your own evidence. Edit `runner/config.json` to set the recipient, paths, and commands. The command arrays run with `runner/` as their working directory. For scheduled runs, replace `python3` and `node` with absolute executable paths. Point Python at the virtual environment where you installed the collector.

The example uses the sibling `dashboard/` and `excel/` directories. `runner/config.json`, `runner/private/`, and `runner/data/` are ignored by Git.

## Spreadsheet runtime

The Excel CLI imports `@oai/artifact-tool`. It must be resolvable in the Node environment that runs the CLI. The package is an external runtime dependency and is not bundled here. `npm install` in `excel/` alone does not supply it.

Once that runtime is available, collect, rank, and synchronize:

```sh
python -m internship_collector --output runner/data/collected.json
python3 runner/scheduler/ranker.py \
  --jobs runner/data/collected.json \
  --resume-profile runner/private/resume_profile.json \
  --in-place
node excel/src/sync.mjs \
  --jobs runner/data/collected.json \
  --output runner/data/Summer-2027-Internships.xlsx \
  --json-output runner/data/merged_jobs.json
```

Build the dashboard, then start the local service:

```sh
cd runner
python3 -m scheduler --config config.json config-check
python3 -m scheduler --config config.json serve
```

Open `http://127.0.0.1:8765`. The service reads the merged JSON and handles application edits through the configured Excel command. Close Excel before making changes through the dashboard.

## Scheduling and reminders

From `runner/`, validate a tick before installing a launch agent:

```sh
python3 -m scheduler --config config.json tick
sh launchd/install_launchd.sh print
sh launchd/install_launchd.sh install
```

A tick may run collection or send reminders if they are due and SMTP is configured. The default schedule collects at 07:00 in `America/Los_Angeles` and checks for reminders every 12 hours. Configure both values in `config.json`.

For Gmail reminders, set your recipient first, then run:

```sh
python3 -m scheduler --config config.json setup-email
```

The setup reads the app password through hidden input, stores SMTP values in the local `.env` file with owner-only permissions, and sends a test message to the configured recipient. You can also supply SMTP values through the environment. The Python CLI loads `runner/.env`; Node does not need these credentials.

`sh launchd/install_launchd.sh uninstall` removes the timer. The separate `launchd/install_dashboard.py` script installs or removes a persistent local dashboard service.

## Hosted application storage

Hosted deployment is optional. It uses the `DB` Cloudflare D1 binding defined in `dashboard/vite.config.ts`. Set `CLOUDFLARE_D1_DATABASE_ID` and optionally `CLOUDFLARE_D1_DATABASE_NAME` in the build environment, apply the SQL migrations under `dashboard/drizzle/`, and use `npm run build:hosted`.

The API has no built-in authentication. Configure deployment access controls before adding personal data. Do not put private resume profiles, application records, credentials, or real workbooks in `dashboard/public/`.
