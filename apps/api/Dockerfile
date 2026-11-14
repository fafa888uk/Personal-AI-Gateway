# Personal AI Gateway — API image
# python:3.12-slim + requirements + alembic upgrade + uvicorn.
# No secrets are baked in: OPENAI_API_KEY etc. come from the server-side
# env file at runtime only (see infra/docker-compose.yml).
# APP_VERSION is a build arg so /api/health and /api/v1/app/version report
# the release version; APP_RELEASE_INFO_JSON stays runtime-only.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG APP_VERSION=""
ENV APP_VERSION=${APP_VERSION}

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway ./gateway
COPY alembic ./alembic
COPY alembic.ini .

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
