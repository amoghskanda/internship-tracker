# Excel and JSON sync

`src/sync.mjs` merges the collector feed into an Excel workbook and writes a JSON sidecar for the dashboard. It uses stable job IDs when available, falls back to employer-scoped job IDs or URL hashes, and preserves application-owned fields such as status, dates, notes, contacts, removal state, and manual priority overrides.

Before replacing a workbook, the writer checks for an Excel lock, verifies that the source workbook has not changed during the operation, creates a backup, and replaces the file atomically. The JSON export mode reads manual workbook changes without rewriting the workbook.

Example commands:

```sh
node src/sync.mjs \
  --jobs ../runner/data/collected.json \
  --output ../runner/data/Summer-2027-Internships.xlsx \
  --json-output ../runner/data/merged_jobs.json

node src/sync.mjs \
  --export-json \
  --input ../runner/data/Summer-2027-Internships.xlsx \
  --json-output ../runner/data/merged_jobs.json
```

The CLI imports `@oai/artifact-tool`. The personal workflow supplies that package through a separate spreadsheet runtime. It is not included or vendored here, and installing this directory alone does not provide it. The dashboard example and Python ranker run independently of this dependency.
