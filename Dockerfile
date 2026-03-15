FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml .
RUN uv sync --no-dev --no-install-project

COPY src/ src/
COPY entrypoint.sh /entrypoint.sh

RUN useradd -m -s /bin/sh engine && chown -R engine:engine /app && \
    mkdir -p /data && chown engine:engine /data && \
    mkdir -p /home/engine/.claude && \
    echo '{"hasCompletedOnboarding":true,"installMethod":"native"}' > /home/engine/.claude/.claude.json && \
    chown -R engine:engine /home/engine/.claude && \
    chmod +x /entrypoint.sh

ENV PYTHONPATH=/app/src
EXPOSE 5000

ENTRYPOINT ["/entrypoint.sh"]
