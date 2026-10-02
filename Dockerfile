# RelayPay voice support backend: one container runs the public FastAPI app (voice page, Vapi endpoint,
# console) and the private MCP server on localhost inside it. Secrets come from the environment at runtime
# (Cloud Run: Secret Manager), never from the image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_NO_INTERACTION=1

WORKDIR /app

# Dependencies first, so code changes don't reinstall them. The Agent SDK's Linux wheel bundles Claude Code.
RUN pip install "poetry==2.4.1"
COPY pyproject.toml poetry.lock poetry.toml ./
RUN poetry install --only main --no-root --no-ansi

COPY src ./src
COPY data ./data
RUN poetry install --only main --no-ansi

# Non-root, with a writable home; the agent's working folders live in /tmp.
RUN useradd --create-home --uid 10001 relaypay
USER relaypay

ENV PATH="/app/.venv/bin:$PATH" \
    HOME=/home/relaypay \
    HOST=0.0.0.0 \
    PORT=8080 \
    LOG_FORMAT=json \
    RETRIEVAL_LOG_PATH=/tmp/retrieval.jsonl

EXPOSE 8080
CMD ["relaypay-backend"]
