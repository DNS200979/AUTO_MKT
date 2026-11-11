# syntax=docker/dockerfile:1

FROM python:3.15-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip wheel --wheel-dir /wheels .


FROM python:3.15-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 market \
    && useradd --uid 10001 --gid market --home-dir /app --no-create-home --shell /usr/sbin/nologin market

WORKDIR /app
COPY --from=builder /wheels /wheels
RUN python -m pip install /wheels/*.whl && rm -rf /wheels
COPY alembic.ini ./
COPY migrations ./migrations

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

CMD ["uvicorn", "market_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
