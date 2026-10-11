# Scheduler and ranking engine

The scheduler coordinates collection, ranking, workbook sync, and reminder email on macOS. A launchd timer checks once a minute. The Python service runs the daily workflow at the configured local time and sends a digest when a pending opening has waited 12 hours since discovery or its last reminder.

The ranker is deterministic and runs locally. It evaluates each job against every resume variant in a private JSON profile, selects the strongest supported match, and writes tier, confidence, eligibility, evidence, gaps, and tailoring suggestions into the job feed. Tier 1 requires detailed listing evidence and strong skill coverage. Sparse or title-only listings cannot reach Tier 1. See [the ranking algorithm](docs/ranking-algorithm.md).

Copy `config.example.json` to `config.json` and edit the command arrays and local paths. Keep the resume profile in `private/`, SMTP values in `.env`, and generated files in `data/`. These paths are ignored by Git.

Run a scheduler tick or start the local dashboard server from this directory:

```sh
python3 -m scheduler --config config.json tick
python3 -m scheduler --config config.json serve
```

The service binds to `127.0.0.1` by default. The macOS installer is in `launchd/install_launchd.sh`; use its `install`, `print`, or `uninstall` subcommand. Email setup reads the Gmail app password with hidden input and stores it only in the local `.env` file.
