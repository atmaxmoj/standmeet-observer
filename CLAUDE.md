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
- **复用已有基础设施，不要重新发明。** 调 LLM 用 `app.state.llm`，不要自己 `import anthropic` 新建 client。调 DB 用 `app.state.db`。新功能接入前先看现有接口能不能满足，不能就扩展接口，而不是绕过。
- **大改动先说方案。** 涉及新模块、新依赖、架构变更时，先用 2-3 句话解释设计选择和替代方案，等用户确认再动手。不要直接写完一大坨再发现方向错了。
- **新 UI feature 必须有 Playwright 关键路径测试。** 不只是"panel 渲染了"，要测核心交互（发消息能收到回复、按钮能点、错误能展示）。
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
