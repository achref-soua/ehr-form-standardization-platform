# syntax=docker/dockerfile:1.12
FROM ghcr.io/astral-sh/uv:0.12.7@sha256:95f2aa1fe59274951cfe9b0cbc7972e879ff1004bc8945d130a32eb0dbd85945 AS uv
FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

RUN groupadd --system --gid 10001 ehrfs \
    && useradd --system --uid 10001 --gid ehrfs --home-dir /app ehrfs
WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY apps/api ./apps/api
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations
COPY infra/postgres/omop54 ./infra/postgres/omop54
RUN uv sync --frozen --no-dev --no-editable \
    && rm -rf /root/.cache/uv

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready', timeout=2)"]
CMD ["uvicorn", "ehrfs_api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
