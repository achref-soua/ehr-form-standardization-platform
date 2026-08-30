# syntax=docker/dockerfile:1.12
FROM ghcr.io/astral-sh/uv:0.12.7@sha256:95f2aa1fe59274951cfe9b0cbc7972e879ff1004bc8945d130a32eb0dbd85945 AS uv
FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}" \
    PADDLE_OCR_BASE_DIR=/models \
    PADDLE_PDX_CACHE_HOME=/models

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10002 ocr \
    && useradd --system --uid 10002 --gid ocr --home-dir /app ocr \
    && mkdir -p /models /app/.cache /app/.modelscope \
    && chown -R ocr:ocr /models /app/.cache /app/.modelscope

WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY services/ocr/pyproject.toml services/ocr/uv.lock ./
RUN uv sync --frozen --no-dev --no-editable \
    && rm -rf /root/.cache/uv
COPY services/ocr/app.py ./app.py

USER 10002:10002
EXPOSE 8081
HEALTHCHECK --interval=20s --timeout=3s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/readyz', timeout=2)"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8081", "--no-access-log"]
