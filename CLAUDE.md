# Bisimulator

Behavioral distillation engine. Observes screen activity (via Screenpipe), identifies tasks, and distills behavioral patterns into Playbook entries.

## Architecture

3-layer pipeline:
1. **Rules filter** ($0) — drop noise apps, short text
2. **Haiku task-level** (~$0.01/episode) — identify tasks within time windows
3. **Opus weekly** (~$1-2/week) — distill patterns into Playbook entries

## Running

```bash
# First time: installs screenpipe + starts everything (macOS & Linux)
make setup

# Daily use
make start          # start screenpipe + docker
make stop           # stop everything
make status         # check health
make logs           # bisimulator logs
```

Only env var needed: `ANTHROPIC_API_KEY` in `.env`.

Set `LOG_LEVEL=DEBUG` (default) for verbose logging, `LOG_LEVEL=INFO` for production.

## Key Rules

- **Logging must be abundant.** Every significant step needs a debug log. When something goes wrong, logs are the first thing to check. If logs are insufficient to diagnose an issue, add more logs before guessing.
- Commit messages in English only, no Chinese.
- Models are hardcoded in `config.py`. DO NOT swap them — Haiku on task-level keeps costs ~$0, Opus on task-level would cost ~$50/day.

## Structure

```
src/engine/
├── config.py              # Settings + model constants
├── db.py                  # SQLite (episodes, playbook_entries, state)
├── main.py                # FastAPI app + pipeline loop
├── api/routes.py          # REST endpoints
└── pipeline/
    ├── collector.py       # Signal collectors (screenpipe first)
    ├── filter.py          # Rules-based noise filter + WindowAccumulator
    ├── episode.py         # Haiku: time window -> episodes
    └── distill.py         # Opus: episodes -> playbook entries
```
